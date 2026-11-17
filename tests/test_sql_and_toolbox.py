"""Structural checks on the SQL and the MCP Toolbox config. These catch typos and drift; they do NOT run BigQuery."""
import re
from pathlib import Path

import pytest
import sqlglot
import yaml

import build_tools_yaml
import render_toolbox
import run_sql

ROOT = Path(__file__).resolve().parents[1]
VARS = run_sql.load_vars("proj", "a4i_climate", {"ACS_TABLE": "censustract_2022_5yr"})
TOOLS = [d for d in yaml.safe_load_all((ROOT / "toolbox" / "tools.yaml").read_text()) if d["kind"] == "tool"]


def parseable(sql: str) -> None:
    # sqlglot does not know BigQuery ML's `MODEL` keyword inside ML.* functions; everything else it checks.
    sqlglot.parse(re.sub(r"\bMODEL\s+(?=`)", "", sql), read="bigquery")


@pytest.mark.parametrize("f", run_sql.sql_files([]), ids=lambda f: f.name)
def test_pipeline_sql_renders_and_parses(f):
    sql = run_sql.render(f.read_text(), VARS)
    assert "{{" not in sql
    parseable(sql)


def test_unresolved_token_is_an_error():
    with pytest.raises(KeyError):
        run_sql.render("SELECT {{NOPE}}", VARS)


def test_pipeline_files_are_numbered_in_order():
    assert [f.name[:2] for f in run_sql.sql_files([])] == ["00", "01", "02", "03", "04", "05", "06"]


def test_tools_yaml_is_up_to_date():
    assert (ROOT / "toolbox" / "tools.yaml").read_text() == build_tools_yaml.render()


@pytest.mark.parametrize("t", TOOLS, ids=lambda t: t["name"])
def test_tool_sql_parses_and_params_match(t):
    stmt = t["statement"]
    declared = {p["name"] for p in t["parameters"]}
    used = set(re.findall(r"@(\w+)", stmt))
    assert used == declared, f"{t['name']}: used {used} vs declared {declared}"
    parseable(re.sub(r"@\w+", "1", re.sub(r"\$\{[A-Za-z_]+(:[^}]*)?\}", "x", stmt)))
    assert t["description"].strip()
    for p in t["parameters"]:
        assert p["description"] and p["type"] in {"string", "integer", "float", "boolean", "array"}


def test_every_ml_tool_calls_the_model_live():
    ml = {t["name"] for t in TOOLS if "ML.EXPLAIN_PREDICT" in t["statement"] or "ML.PREDICT" in t["statement"]}
    assert {"rank_priority_sites", "predict_site_heat", "rank_wellness_check_tracts", "equity_audit"} <= ml
    assert "ML.EXPLAIN_PREDICT" in next(t for t in TOOLS if t["name"] == "rank_priority_sites")["statement"]


def test_no_tool_can_write():
    for t in TOOLS:
        assert not re.search(r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|MERGE|TRUNCATE)\b", t["statement"], re.I), t["name"]


def test_toolset_lists_exactly_the_tools():
    docs = list(yaml.safe_load_all((ROOT / "toolbox" / "tools.yaml").read_text()))
    ts = next(d for d in docs if d["kind"] == "toolset")
    assert set(ts["tools"]) == {t["name"] for t in TOOLS}


def test_instruction_only_names_real_tools():
    from heat_dispatch.prompts import INSTRUCTION
    real = {t["name"] for t in TOOLS} | {"locate_place", "get_forecast_high", "heat_risk_for_forecast", "build_dispatch_plan",
                                         "get_dispatch_status", "set_operator_constraints", "replan_dispatch"}
    prefixes = ("rank_", "predict_", "build_", "locate_", "get_forecast", "heat_", "model_", "nearest_", "who_", "equity_",
                "tract_", "list_", "get_dispatch", "set_operator", "replan_")
    params = {p["name"] for t in TOOLS for p in t["parameters"]}          # e.g. heat_weight is a parameter, not a tool
    mentioned = {w for w in re.findall(r"\b[a-z]+(?:_[a-z]+)+\b", INSTRUCTION) if w.startswith(prefixes)} - params
    assert mentioned and mentioned <= real, f"instruction names unknown tools: {mentioned - real}"
    assert {t["name"] for t in TOOLS} <= mentioned | {"model_global_importance"}, "a Toolbox tool the prompt never mentions"


def test_render_toolbox_resolves_env_and_defaults():
    out = render_toolbox.resolve("a ${P}.${D:a4i_climate} ${L:US}", {"P": "proj"})
    assert out == "a proj.a4i_climate US"
    with pytest.raises(KeyError):
        render_toolbox.resolve("${P}", {})
    full = render_toolbox.resolve((ROOT / "toolbox" / "tools.yaml").read_text(), {"GOOGLE_CLOUD_PROJECT": "proj"})
    assert "${" not in full and "proj.a4i_climate.heat_offset_lst" in full
