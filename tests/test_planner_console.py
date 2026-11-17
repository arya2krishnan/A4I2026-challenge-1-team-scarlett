"""Offline tests for the deterministic planner and the agent's console tools (no GCP, no model)."""
import asyncio
import types

import pytest

import console_fixtures as fx
from heat_dispatch import console, planner


# ---- hours ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,day,expected", [
    (fx.HOURS_A, "mon", "10 am-6 pm"), (fx.HOURS_A, "thu", "12 pm-8 pm"), (fx.HOURS_A, "sun", "1 pm-5 pm"),
    ("Mon. - Thurs., 9-8; Fri. & Sat., 9-5; Sun., 1-5", "wed", "9 am-8 pm"),
    ("Mon.- Thurs., 10-6 Fri. & Sat., 9-5; Sun., 1-5", "fri", "9 am-5 pm"),
    ("Closed until further notice", "mon", None), (None, "mon", None),
])
def test_library_hours(text, day, expected):
    assert planner.hours_today(text, day) == expected


def test_resolve_site_names():
    names = ["Legler Regional", "Near", "North Austin", "Austin"]
    assert planner.resolve_site_names(["legler library", "near"], names) == (["Legler Regional", "Near"], [])
    assert planner.resolve_site_names(["austin"], names) == (["Austin"], [])       # exact beats substring
    assert planner.resolve_site_names(["nowhere"], names) == ([], ["nowhere"])


def test_normalize_constraints_clamps_and_defaults():
    c = planner.normalize_constraints({"trucks": 999, "cutoff_f": 9, "ranking": "nope", "closed_sites": ["b", "a", "a"]})
    assert c["trucks"] == planner.LIMITS["trucks"] and c["cutoff_f"] == 3.0 and c["ranking"] == "balanced"
    assert c["closed_sites"] == ["a", "b"] and c["wellness_teams"] == planner.DEFAULT_CONSTRAINTS["wellness_teams"]


def test_ranking_calls_pass_cutoff_and_weight():
    calls = planner.ranking_calls({"ranking": "heat", "cutoff_f": 0.5})
    assert calls["rank_priority_sites"]["heat_weight"] == 1.0
    assert calls["rank_wellness_check_tracts"]["min_offset"] == 0.5


# ---- build_plan ----------------------------------------------------------------------------------
def plan(**kw):
    c = {"trucks": 3, "wellness_teams": 2, "libraries": 2, **kw.pop("c", {})}
    return planner.build_plan(c, fx.sites(), fx.tracts(), fx.libraries(), weekday="mon", **kw)


def test_plan_counts_and_numbers_are_copied_from_rows():
    p = plan()
    kinds = [i["kind"] for i in p["items"]]
    assert kinds.count("well") == 2 and kinds.count("truck") == 3 and kinds.count("lib") == 2
    t1 = next(i for i in p["items"] if i["kind"] == "truck")
    row = fx.sites()[0]
    assert (t1["latitude"], t1["predicted_offset_f"], t1["key"]) == (row["latitude"], row["predicted_offset_f"], "truck:c000")
    assert t1["why"][0] == {"feature": "lake_distance_band", "contribution_f": 0.8}


def test_libraries_skip_closed_far_and_shut_branches():
    p = plan(c={"libraries": 5, "closed_sites": ["Legler Regional"]})
    libs = [i for i in p["items"] if i["kind"] == "lib"]
    assert [b["name"] for b in libs] == ["Near"]            # Legler closed, Far Away serves nothing, Galewood shut
    assert libs[0]["hours_today"] == "10 am-6 pm" and libs[0]["extend_to"] == "10 pm"
    wells = {i["tract_geo_id"] for i in p["items"] if i["kind"] == "well"}
    assert not wells & set(libs[0]["served_tracts"])        # a tract with a team is not double-counted


def test_skip_pulls_in_next_best():
    p = plan(skipped=["truck:c000"])
    trucks = [i["key"] for i in p["items"] if i["kind"] == "truck"]
    assert "truck:c000" not in trucks and trucks[-1] == "truck:c003"


def test_approved_items_stay_pinned_and_capacity_unapproves_lowest():
    approved = {"truck:c000": {}, "truck:c001": {}, "truck:c002": {}}
    p = plan(c={"trucks": 1}, approved=approved)
    assert list(p["approved"]) == ["truck:c000"]
    w = p["warnings"][0]
    assert w["reason"] == "capacity" and w["unapproved"] == ["truck:c001", "truck:c002"]
    assert [i["key"] for i in p["items"] if i["kind"] == "truck"] == ["truck:c000"]


def test_approved_closed_library_is_unapproved():
    p = plan(c={"closed_sites": ["Near"]}, approved={"lib:Near": {}})
    assert "lib:Near" not in p["approved"] and p["warnings"][0]["reason"] == "ineligible"


def test_approved_truck_survives_when_its_tract_gets_a_wellness_team():
    sites = fx.sites()
    sites[0] = {**sites[0], "tract_geo_id": fx.tracts()[0]["tract_geo_id"]}     # same tract as the top wellness pick
    p = planner.build_plan({"trucks": 2, "wellness_teams": 1, "libraries": 0}, sites, fx.tracts(), [],
                           approved={"truck:c000": {}}, weekday="mon")
    assert "truck:c000" in {i["key"] for i in p["items"]} and "truck:c000" in p["approved"]


def test_diff_and_summary():
    a, b = plan(), plan(c={"trucks": 1})
    d = planner.diff_plans(a["items"], b["items"])
    assert set(d) == {"truck"} and [x["key"] for x in d["truck"]["removed"]] == ["truck:c001", "truck:c002"]
    s = planner.summarize(b["items"], fx.tract_layer(), cutoff_f=0.5)
    assert s["hot_tracts"] == sum(1 for t in fx.tract_layer() if t["predicted_offset_f"] >= 0.5)
    assert 0 < s["share_of_hot_65_plus_reached"] <= 1 and s["counts"]["truck"] == 1


# ---- console tools -------------------------------------------------------------------------------
def tctx(**state):
    return types.SimpleNamespace(state=dict(state))


@pytest.fixture(autouse=True)
def fake_toolbox(monkeypatch):
    monkeypatch.setattr(console, "_invoke", fx.fake_invoke)


def seeded(**kw):
    base = planner.build_plan({"trucks": 4, "wellness_teams": 2, "libraries": 2}, fx.sites(50), fx.tracts(40),
                              fx.libraries(), weekday="mon")
    ctx = {"turn_id": "t1", "plan_version": 3, "weekday": "mon", "forecast_high_f": 96,
           "constraints": base["constraints"], "approved": {}, "skipped": [],
           "plan_items": [{"key": i["key"], "kind": i["kind"], "name": i["name"]} for i in base["items"]], **kw}
    return tctx(console_context=ctx)


def test_set_constraints_then_replan_writes_plan_and_diff_to_state():
    c = seeded(approved={"truck:c000": {}, "truck:c001": {}, "truck:c002": {}})
    r = asyncio.run(console.set_operator_constraints(trucks=2, close_sites=["legler"], tool_context=c))
    assert r["constraints"]["trucks"] == 2 and r["constraints"]["closed_sites"] == ["Legler Regional"]
    out = asyncio.run(console.replan_dispatch(tool_context=c))
    assert out["status"] == "ok" and out["planned"]["truck"] == 2
    saved = c.state[console.STATE_PLAN]
    assert saved["turn_id"] == "t1" and saved["base_version"] == 3
    assert {x["key"] for x in saved["diff"]["truck"]["removed"]} == {"truck:c002", "truck:c003"}
    assert "trucks: 4 -> 2" in saved["changes"] and "Legler Regional: closed" in saved["changes"]
    assert out["warnings"] and "only 2 are available" in out["warnings"][0]
    assert c.state["ranked_sites"]                                   # build_dispatch_plan sees the same rows


def test_unknown_site_is_reported_not_guessed():
    c = seeded()
    r = asyncio.run(console.set_operator_constraints(close_sites=["Hogwarts"], tool_context=c))
    assert r["unknown_sites"] == ["Hogwarts"] and r["constraints"]["closed_sites"] == []


def test_bad_ranking_rejected_and_status_reports_counts():
    c = seeded()
    assert asyncio.run(console.set_operator_constraints(ranking="vibes", tool_context=c))["status"] == "error"
    s = console.get_dispatch_status(tool_context=c)
    assert s["plan_version"] == 3 and s["planned"]["truck"] == 4
    assert "coverage" in s
    assert "total_estimated_residents_served" in s["coverage"]
    assert "total_seniors_65_plus_served" in s["coverage"]
    assert "share_of_hot_65_plus_reached_pct" in s["coverage"]



def test_replan_reports_toolbox_failure(monkeypatch):
    async def boom(name, params):
        raise ConnectionError("down")
    monkeypatch.setattr(console, "_invoke", boom)
    c = seeded()
    out = asyncio.run(console.replan_dispatch(tool_context=c))
    assert out["status"] == "error" and console.STATE_PLAN not in c.state


def test_sub_80_stand_down():
    from heat_dispatch.planner import build_plan
    plan = build_plan({}, [], [], [], day={"high_f": 72, "weekday": "sun"})
    assert plan["stand_down"] is True
    assert plan["items"] == []
    assert "72°F < 80°F" in plan["stand_down_reason"]

