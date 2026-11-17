"""Unit tests for the 1 Orchestrator + 5 Specialist Agents hierarchy."""
import pytest
from heat_dispatch.agent import (
    root_agent,
    spatial_risk_agent,
    logistics_agent,
    outreach_agent,
    triage_agent,
    equity_agent,
)
from heat_dispatch.dispatch import (
    pick_high_schools,
    render_sheet,
    build_dispatch_plan,
)


def test_subagents_registered_under_root():
    assert len(root_agent.sub_agents) == 5
    names = {a.name for a in root_agent.sub_agents}
    assert names == {
        "spatial_risk_agent",
        "logistics_agent",
        "outreach_agent",
        "triage_agent",
        "equity_agent",
    }


def test_each_subagent_has_role_and_instruction():
    agents = [spatial_risk_agent, logistics_agent, outreach_agent, triage_agent, equity_agent]
    for a in agents:
        assert a.name is not None and len(a.name) > 0
        assert a.description is not None and len(a.description) > 10
        assert a.instruction is not None and len(a.instruction) > 20


def test_pick_high_schools():
    sample_sites = [
        {
            "rank": 1,
            "nearest_high_school_name": "Marshall Metropolitan High School",
            "nearest_high_school_address": "3250 W Adams St",
            "nearest_cooling_type": "High School",
            "km_to_indoor_cooling": 1.2,
        },
        {
            "rank": 2,
            "nearest_high_school_name": "Marshall Metropolitan High School",  # Duplicate, should deduplicate
            "nearest_cooling_type": "High School",
            "km_to_indoor_cooling": 1.4,
        },
        {
            "rank": 3,
            "nearest_high_school_name": "Crane Medical Preparatory High School",
            "nearest_high_school_address": "2245 W Jackson Blvd",
            "nearest_cooling_type": "High School",
            "km_to_indoor_cooling": 2.1,
        },
    ]
    picked = pick_high_schools(sample_sites, n=2)
    assert len(picked) == 2
    assert picked[0]["high_school"] == "Marshall Metropolitan High School"
    assert picked[1]["high_school"] == "Crane Medical Preparatory High School"
    assert picked[0]["km_from_site"] == 1.2


def test_render_sheet_includes_high_schools():
    high_schools = [
        {
            "high_school": "Dunbar Vocational Career Academy High School",
            "address": "3000 S King Dr",
            "current_hours": "Mon-Fri 7AM-7PM (Emergency AC Gymnasium Cooling)",
            "km_from_site": 1.1,
            "serves_site_rank": 1,
        }
    ]
    sheet = render_sheet(
        forecast_high_f=102.0,
        stops=[],
        teams=[],
        libraries=[],
        audit=[],
        params={},
        high_schools=high_schools,
    )
    assert "## 4. Emergency high school cooling gymnasiums" in sheet
    assert "Dunbar Vocational Career Academy High School" in sheet
    assert "3000 S King Dr" in sheet


def test_every_specialist_has_the_guard_and_stash_callbacks():
    """Callbacks are per agent: a specialist without them silently loses its ranking and skips the Chicago guard."""
    from heat_dispatch.agent import guard_point_tools, root_agent, stash_tool_results
    assert root_agent.sub_agents
    for a in (root_agent, *root_agent.sub_agents):
        assert a.before_tool_callback is guard_point_tools, a.name
        assert a.after_tool_callback is stash_tool_results, a.name
