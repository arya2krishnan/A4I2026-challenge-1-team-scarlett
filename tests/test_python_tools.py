"""Offline tests for the agent's Python layer (no GCP, no network)."""
import asyncio
import json
import types

import pytest

from heat_dispatch import dispatch, forecast, narration, places, results
from heat_dispatch.agent import guard_point_tools, stash_tool_results


# ---- results.parse_rows --------------------------------------------------------------------------
@pytest.mark.parametrize("resp,n", [
    (None, 0), ("null", 0), ("", 0), ('{"a": 1}', 1), ('[{"a": 1},{"a": 2}]', 2),
    ('{"a": 1}{"a": 2}', 2), ([{"a": 1}], 1), ({"rows": [{"a": 1}, {"a": 2}]}, 2), ("not json", 0),
])
def test_parse_rows(resp, n):
    assert len(results.parse_rows(resp)) == n


# ---- narration -----------------------------------------------------------------------------------
def test_describe_why_orders_and_signs():
    why = [{"feature": "lake_distance_band", "contribution_f": 2.14}, {"feature": "building_era", "contribution_f": -0.31}]
    assert narration.describe_why(why) == "distance from Lake Michigan +2.1°F; age of the housing stock -0.3°F"
    assert narration.describe_why(json.dumps(why)).startswith("distance from Lake Michigan")
    # live MCP Toolbox returns structs as [feature, value] pairs
    assert narration.describe_why([["lake_distance_band", 1.68], ["building_era", 0.37]]) == \
        "distance from Lake Michigan +1.7°F; age of the housing stock +0.4°F"
    assert narration.describe_why(None) == ""
    assert narration.describe_why([{"feature": "x"}]) == ""          # malformed entries are skipped, not raised


# ---- forecast / heat index -----------------------------------------------------------------------
@pytest.mark.parametrize("t,rh,expected", [(90, 70, 106), (96, 40, 101), (95, 55, 109), (92, 60, 105), (100, 50, 118), (80, 40, 80)])
def test_heat_index_matches_nws_chart(t, rh, expected):
    assert forecast.heat_index_f(t, rh) == pytest.approx(expected, abs=2.0)


def test_heat_risk_is_forecast_plus_offset():
    r = forecast.heat_risk_for_forecast(102, 6.1)
    assert r["expected_air_temp_f"] == 108.1
    assert "unknown" in r["nws_heat_index_category"]
    r = forecast.heat_risk_for_forecast(98, 2.0, 50)            # 100F air at 50% RH -> heat index ~118
    assert r["expected_heat_index_f"] == pytest.approx(118, abs=2) and r["nws_heat_index_category"].startswith("Danger")
    assert "heat_index_caveat" not in r
    assert "heat_index_caveat" in forecast.heat_risk_for_forecast(106, 8, 45)   # 114F air: past the regression's range


def test_forecast_tool_degrades_gracefully(monkeypatch):
    def boom(*a, **k):
        raise TimeoutError("down")
    monkeypatch.setattr(forecast, "_get_json", boom)
    out = forecast.get_forecast_high()
    assert out["status"] == "unavailable" and "Ask the planner" in out["message"]


def test_forecast_tool_parses_periods(monkeypatch):
    calls = []

    def fake(url, ua):
        calls.append(url)
        if "/points/" in url:
            return {"properties": {"forecast": "https://api.weather.gov/gridpoints/LOT/1,1/forecast"}}
        return {"properties": {"updateTime": "t", "periods": [
            {"name": "Thursday", "isDaytime": True, "temperature": 102, "startTime": "s",
             "relativeHumidity": {"value": 48}, "shortForecast": "Sunny"},
            {"name": "Thursday Night", "isDaytime": False, "temperature": 80}]}}
    monkeypatch.setattr(forecast, "_get_json", fake)
    out = forecast.get_forecast_high()
    assert out["status"] == "ok" and out["daytime_highs"] == [
        {"period": "Thursday", "starts": "s", "high_f": 102, "relative_humidity_pct": 48, "short_forecast": "Sunny"}]


# ---- places --------------------------------------------------------------------------------------
def test_locate_known_neighborhood():
    r = places.locate_place("Englewood")
    assert r["status"] == "ok" and places.in_chicago(r["latitude"], r["longitude"])
    assert places.locate_place("  the LOOP, ")["status"] == "ok"


def test_locate_refuses_regions_and_unknowns(monkeypatch):
    monkeypatch.setattr(places, "get_settings", lambda: types.SimpleNamespace(maps_api_key=""))
    assert places.locate_place("south side")["status"] == "too_broad"
    r = places.locate_place("63rd and Halsted")
    assert r["status"] == "not_found" and "Maps API key" in r["message"]
    assert places.locate_place("")["status"] == "not_found"


def test_locate_rejects_geocode_outside_chicago(monkeypatch):
    monkeypatch.setattr(places, "get_settings", lambda: types.SimpleNamespace(maps_api_key="k"))
    monkeypatch.setattr(places, "_geocode", lambda a, k: {"latitude": 31.0, "longitude": -97.0, "formatted_address": "Waco, TX"})
    assert places.locate_place("Chicago Ave")["status"] == "outside_area"


# ---- dispatch plan -------------------------------------------------------------------------------
def site(rank, lat, lon, offset, lib=None, lib_km=1.0):
    return {"rank": rank, "latitude": lat, "longitude": lon, "predicted_offset_f": offset,
            "why": [{"feature": "log_pop_density", "contribution_f": 1.2}], "residents_65_plus": 500 + rank,
            "households_without_car": 300, "poverty_rate": 0.31, "km_to_indoor_cooling": 2.4,
            "nearest_cooling_name": "Test Library", "nearest_cooling_address": "1 Main St",
            "nearest_library_name": lib, "nearest_library_address": "1 Main St", "nearest_library_hours": "M-F 9-6",
            "km_to_library": lib_km, "measured_readings": 0 if rank == 1 else 20, "tract_geo_id": f"1703100{rank}"}


def ctx(**state):
    return types.SimpleNamespace(state=dict(state))


def test_plan_needs_data_first():
    assert asyncio.run(dispatch.build_dispatch_plan(102, tool_context=ctx()))["status"] == "need_data"


def test_plan_uses_stored_rows_verbatim(monkeypatch):
    monkeypatch.setattr(dispatch, "reverse_geocode", lambda lat, lon: None)
    sites = [site(1, 41.7796, -87.6444, 6.1, "Library A"), site(2, 41.89, -87.76, 5.0, "Library A"),
             site(3, 41.85, -87.72, 4.0, "Library B", lib_km=4.0), site(4, 41.80, -87.60, 3.0, "Library C")]
    tracts = [{"tract_geo_id": "17031000100", "latitude": 41.8, "longitude": -87.7, "residents_65_plus": 700,
               "households_without_car": 400}]
    out = asyncio.run(dispatch.build_dispatch_plan(102, hydration_trucks=3, wellness_teams=2, library_extensions=3,
                                                   tool_context=ctx(ranked_sites=sites, wellness_tracts=tracts)))
    assert out["status"] == "ok"
    stops = out["hydration_stops"]
    assert [s["latitude"] for s in stops] == [41.7796, 41.89, 41.85]          # model coordinates untouched
    assert stops[0]["expected_air_temp_f"] == 108.1 and stops[0]["measured"] is False
    libs = [l["library"] for l in out["library_extensions"]]
    assert libs == ["Library A", "Library C"]                                  # distinct, B is >2.5 km away
    assert len(out["wellness_teams"]) == 1
    md = out["dispatch_sheet_markdown"]
    assert "41.77960, -87.64440" in md and "never measured" in md and "Not yet run" in md  # audit flagged as not run
    assert out["equity_audit_ran"] is False
    assert len(out["map"]["markers"]) == 4 and {m["kind"] for m in out["map"]["markers"]} == {"hydration", "wellness"}


def test_plan_includes_audit_when_present(monkeypatch):
    monkeypatch.setattr(dispatch, "reverse_geocode", lambda lat, lon: "123 W Test St, Chicago")
    audit = [{"group_name": "recommended_sites", "poverty_rate": 0.30, "households_without_car_rate": 0.40,
              "share_65_plus": 0.12, "mean_vulnerability_index": 0.8},
             {"group_name": "citywide", "poverty_rate": 0.20, "households_without_car_rate": 0.25,
              "share_65_plus": 0.13, "mean_vulnerability_index": 0.5}]
    out = asyncio.run(dispatch.build_dispatch_plan(100, 1, 0, 0, ctx(ranked_sites=[site(1, 41.8, -87.7, 5)], equity_audit=audit)))
    assert out["equity_audit_ran"] and "1.50x" in out["dispatch_sheet_markdown"]
    assert "123 W Test St" in out["dispatch_sheet_markdown"]


# ---- callbacks -----------------------------------------------------------------------------------
def test_stash_stores_rows_and_params():
    c = ctx()
    t = types.SimpleNamespace(name="rank_priority_sites")
    stash_tool_results(t, {"heat_weight": 0.7, "limit": 5, "junk": 1}, c, json.dumps([{"a": 1}, {"a": 2}]))
    assert c.state["ranked_sites"] == [{"a": 1}, {"a": 2}]
    assert c.state["ranking_params"] == {"heat_weight": 0.7, "limit": 5}


def test_stash_ignores_other_tools_and_empty_results():
    c = ctx(ranked_sites=[{"keep": 1}])
    stash_tool_results(types.SimpleNamespace(name="heat_frequency"), {}, c, '[{"a": 1}]')
    stash_tool_results(types.SimpleNamespace(name="rank_priority_sites"), {}, c, "null")
    assert c.state["ranked_sites"] == [{"keep": 1}] and "heat_frequency" not in c.state


def test_guard_blocks_points_outside_chicago():
    t = types.SimpleNamespace(name="predict_site_heat")
    assert guard_point_tools(t, {"latitude": 41.78, "longitude": -87.64}, None) is None
    assert guard_point_tools(t, {"latitude": 32.78, "longitude": -96.8}, None)["status"] == "outside_area"
    assert guard_point_tools(t, {}, None)["status"] == "error"
    assert guard_point_tools(types.SimpleNamespace(name="heat_frequency"), {}, None) is None
