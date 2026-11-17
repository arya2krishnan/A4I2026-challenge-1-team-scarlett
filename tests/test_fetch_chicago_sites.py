"""Offline tests for tools/fetch_chicago_sites.py (no network)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import fetch_chicago_sites as fs  # noqa: E402

T = "2026-11-17T00:00:00+00:00"


def test_point_handles_every_geometry_shape():
    assert fs.point({"latitude": "41.8", "longitude": "-87.6"}) == (41.8, -87.6)
    assert fs.point({"lat": "41.7", "long": "-87.5"}) == (41.7, -87.5)
    assert fs.point({"location": {"type": "Point", "coordinates": [-87.64, 41.78]}}) == (41.78, -87.64)
    assert fs.point({"location": {"latitude": "41.85", "longitude": "-87.65"}}) == (41.85, -87.65)
    assert fs.point({"location": None}) == (None, None)


def test_cooling_flags_spray_features_outdoor_and_keeps_new_columns():
    recs = [{"site_type": "Park District Facility", "site_name": "A", "brand_new_field": "x",
             "location": {"coordinates": [-87.7, 41.8]}, ":@computed_region_x": "1"},
            {"site_type": "Park District Spray Feature", "site_name": "B", "location": {"coordinates": [-87.7, 41.8]}}]
    cols, rows, stats = fs.normalize("cooling_centers", recs, T)
    assert [r["indoor_air_conditioned"] for r in rows] == ["true", "false"]
    assert "brand_new_field" in cols and not any(c.startswith(":") for c in cols)
    assert stats == {"fetched": 2, "no_point": 0, "outside_chicago": 0, "kept": 2}


def test_candidates_mark_cps_high_schools_as_not_current():
    _, cool, _ = fs.normalize("cooling_centers", [{"site_type": "Police District", "site_name": "1st",
                                                   "location": {"coordinates": [-87.62, 41.85]}}], T)
    _, cps, _ = fs.normalize("cps_schools", [
        {"school_id": "1", "short_name": "HS", "grade_cat": "HS", "lat": "41.7", "long": "-87.6"},
        {"school_id": "2", "short_name": "ES", "grade_cat": "ES", "lat": "41.7", "long": "-87.6"}], T)
    c = fs.candidates(cool, cps)
    assert [(r["site_key"], r["is_current_cooling_site"], r["open_24_7"]) for r in c] == [
        ("cool-0001", "true", "true"), ("cps-1", "false", "false")]


def test_schema_types():
    s = {f["name"]: f["type"] for f in fs.bq_schema(fs.CANDIDATE_COLS)}
    assert s["latitude"] == "FLOAT64" and s["zip"] == "STRING" and s["open_24_7"] == "BOOL"
    assert s["retrieved_at"] == "TIMESTAMP"
