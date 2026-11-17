"""Offline guards for the v2 heat-model candidate (docs/specs/2026-11-17-heat-layers-design.md, REQ-001/005/013)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import sqlglot

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_sql  # noqa: E402

V2 = sorted((ROOT / "sql" / "v2").glob("*.sql"))
V2_FEATURES = {"trend_lat_km", "trend_lon_km", "trend_lat2", "trend_lon2", "trend_latlon",
               "surface_heat_f", "impervious_pct_300m", "tree_canopy_pct_300m"}
VARS = run_sql.load_vars("PROJECT", "DATASET")


def test_v2_files_exist_outside_the_numbered_pipeline():
    assert [f.name for f in V2] == ["10_site_context_lst.sql", "11_train_lst.sql", "12_evaluate_lst.sql"]
    assert not any(f.parent.name == "v2" for f in run_sql.sql_files([]))


@pytest.mark.parametrize("f", V2, ids=lambda f: f.name)
def test_v2_templates_render_and_parse(f):
    sql = run_sql.render(f.read_text(), VARS)
    assert "{{" not in sql
    sqlglot.parse(re.sub(r"\bMODEL\s+(?=`)", "", sql), read="bigquery")


def test_v2_model_uses_trend_surface_heat_and_land_cover():
    train = (ROOT / "sql/v2/11_train_lst.sql").read_text()
    v2 = train[train.index("heat_offset_lst`"):]
    for feat in V2_FEATURES:
        assert feat in v2
    assert v2.count("n_obs >= {{MIN_OBS}} AND NOT is_holdout AND offset_f IS NOT NULL") == 1


def test_v2_has_no_demographic_features():
    train = (ROOT / "sql/v2/11_train_lst.sql").read_text().lower()
    for word in ("poverty", "vulnerab", "race", "pop_65", "no_vehicle", "income", "no_car"):
        assert word not in train


def test_live_model_and_table_are_never_overwritten():
    """REQ-013: only sql/04 may create heat_offset_model; nothing in v2 recreates the live objects."""
    for f in sorted((ROOT / "sql").rglob("*.sql")):
        text = f.read_text()
        creates_live = re.search(r"CREATE\s+OR\s+REPLACE\s+MODEL\s+`[^`]*\.heat_offset_model`", text)
        if f.name != "04_train_model.sql":
            assert not creates_live, f"{f} must not create the live heat_offset_model"
        if f.parent.name == "v2":
            assert not re.search(r"CREATE\s+OR\s+REPLACE\s+(TABLE|VIEW)\s+`[^`]*\.site_context`", text)
    live = (ROOT / "sql/04_train_model.sql").read_text()
    assert not any(feat in live for feat in V2_FEATURES)


def _transform_outputs(path: str) -> set[str]:
    body = re.search(r"TRANSFORM\s*\((.*?)\)\s*OPTIONS", (ROOT / path).read_text(), re.S | re.I).group(1)
    parts, depth, cur = [], 0, ""
    for ch in body:  # split on commas outside (...) and [...]
        depth += ch in "([" and 1 or ch in ")]" and -1 or 0
        if ch == "," and depth == 0:
            parts.append(cur); cur = ""
        else:
            cur += ch
    parts.append(cur)
    names = set()
    for part in parts:
        part = part.strip()
        m = re.search(r"\bAS\s+(\w+)\s*$", part, re.I)
        names.add(m.group(1) if m else part)
    return names - {"offset_f"}


def test_every_model_feature_has_a_label_in_agent_and_console():
    """REQ-004: no 'why' reason may reach a dispatcher as a raw column name."""
    sys.path.insert(0, str(ROOT / "agent"))
    from heat_dispatch import narration
    train = (ROOT / "sql/v2/11_train_lst.sql").read_text()
    v2_sql = train[train.index("heat_offset_lst`"):]
    feats = _transform_outputs("sql/04_train_model.sql")
    feats |= {n for n in V2_FEATURES | {"lake_distance_band"} if n in v2_sql}
    ts = (ROOT / "web/frontend/src/format.ts").read_text()
    for f in sorted(feats):
        assert f in narration.FEATURE_LABELS, f"agent label missing: {f}"
        assert re.search(rf"\b{f}\s*:", ts), f"console label missing: {f}"


def test_surface_heat_is_labelled_surface_not_air():
    """REQ-005."""
    sys.path.insert(0, str(ROOT / "agent"))
    from heat_dispatch import narration
    label = narration.label_for("surface_heat_f")
    assert "surface" in label and "air" not in label
