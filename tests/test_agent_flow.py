"""Run the REAL ADK Runner with a scripted model and fake data tools.

Proves the wiring that matters and that unit tests cannot: an after-tool callback stores a tool's rows in session state,
and a later tool (build_dispatch_plan) reads them back, so the dispatch sheet carries the exact tool output.
"""
import asyncio
import json

from google.adk.agents import Agent
from google.adk.models import BaseLlm, LlmResponse
from google.adk.runners import InMemoryRunner
from google.genai import types

from heat_dispatch.agent import guard_point_tools, stash_tool_results
from heat_dispatch.dispatch import build_dispatch_plan

SITE = {"rank": 1, "latitude": 41.77961, "longitude": -87.64439, "predicted_offset_f": 6.1,
        "why": [{"feature": "log_pop_density", "contribution_f": 1.9}], "residents_65_plus": 612,
        "households_without_car": 455, "poverty_rate": 0.34, "km_to_indoor_cooling": 2.8,
        "nearest_cooling_name": "Kennedy-King College", "nearest_cooling_address": "740 W. 63rd Street",
        "nearest_library_name": "Sherman", "nearest_library_address": "5440 S Racine Ave",
        "nearest_library_hours": "Mon-Fri 9-6", "km_to_library": 1.1, "measured_readings": 0, "tract_geo_id": "17031680900"}


def rank_priority_sites(limit: int = 8, heat_weight: float = 0.5) -> str:
    """Fake of the Toolbox tool: returns a JSON string exactly like toolbox-core does."""
    return json.dumps([SITE])


def predict_site_heat(latitude: float, longitude: float) -> str:
    """Fake point tool (must be blocked by the guard when outside Chicago)."""
    return json.dumps([{"predicted_offset_f": 1.0}])


class ScriptedLlm(BaseLlm):
    model: str = "scripted"
    script: list = []
    calls: int = 0

    async def generate_content_async(self, llm_request, stream=False):
        step = self.script[min(self.calls, len(self.script) - 1)]
        object.__setattr__(self, "calls", self.calls + 1)
        part = types.Part(function_call=types.FunctionCall(name=step[0], args=step[1])) if step[0] else types.Part(text=step[1])
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


def run(script, user="plan it"):
    agent = Agent(name="t", model=ScriptedLlm(script=script),
                  tools=[rank_priority_sites, predict_site_heat, build_dispatch_plan],
                  before_tool_callback=guard_point_tools, after_tool_callback=stash_tool_results)
    runner = InMemoryRunner(agent=agent, app_name="t")

    async def go():
        s = await runner.session_service.create_session(app_name="t", user_id="u")
        events = [e async for e in runner.run_async(user_id="u", session_id=s.id,
                  new_message=types.Content(role="user", parts=[types.Part(text=user)]))]
        return events, await runner.session_service.get_session(app_name="t", user_id="u", session_id=s.id)

    return asyncio.run(go())


def test_callback_state_reaches_the_dispatch_tool():
    events, session = run([("rank_priority_sites", {"limit": 1, "heat_weight": 0.7}),
                           ("build_dispatch_plan", {"forecast_high_f": 102, "hydration_trucks": 1, "wellness_teams": 0,
                                                    "library_extensions": 1}),
                           (None, "done")])
    assert session.state["ranked_sites"][0]["latitude"] == 41.77961
    assert session.state["ranking_params"] == {"heat_weight": 0.7, "limit": 1}
    plan = next(p.function_response.response for e in events for p in (e.content.parts if e.content else [])
                if p.function_response and p.function_response.name == "build_dispatch_plan")
    assert plan["status"] == "ok"
    assert plan["hydration_stops"][0]["expected_air_temp_f"] == 108.1
    assert "41.77961, -87.64439" in plan["dispatch_sheet_markdown"]
    assert plan["library_extensions"][0]["library"] == "Sherman"


def test_out_of_area_point_is_refused_without_calling_the_tool():
    events, _ = run([("predict_site_heat", {"latitude": 32.78, "longitude": -96.8}), (None, "sorry")])
    resp = next(p.function_response.response for e in events for p in (e.content.parts if e.content else [])
                if p.function_response)
    assert resp["status"] == "outside_area"


# ---- the race that broke the canned "Plan tomorrow" click --------------------------------------------------------
class ParallelLlm(BaseLlm):
    """First response issues the ranking AND the dispatch tool in the SAME step (what Gemini did live)."""
    model: str = "scripted-parallel"
    calls: int = 0

    async def generate_content_async(self, llm_request, stream=False):
        object.__setattr__(self, "calls", self.calls + 1)
        if self.calls == 1:
            parts = [types.Part(function_call=types.FunctionCall(name="slow_rank_priority_sites", args={"limit": 1})),
                     types.Part(function_call=types.FunctionCall(name="build_dispatch_plan", args={
                         "forecast_high_f": 102, "hydration_trucks": 1, "wellness_teams": 0, "library_extensions": 0}))]
        else:
            parts = [types.Part(text="done")]
        yield LlmResponse(content=types.Content(role="model", parts=parts))


async def slow_rank_priority_sites(limit: int = 1) -> str:
    """Fake ranking tool that takes a moment, like BigQuery does."""
    await asyncio.sleep(0.6)
    return json.dumps([SITE])


slow_rank_priority_sites.__name__ = "slow_rank_priority_sites"


def test_dispatch_waits_for_a_ranking_issued_in_the_same_step(monkeypatch):
    import heat_dispatch.agent as ag
    from heat_dispatch import dispatch
    monkeypatch.setattr(dispatch, "SITES_WAIT_S", 10.0)      # the race test needs the real waiting behaviour
    monkeypatch.setitem(ag._STASH, "slow_rank_priority_sites", "ranked_sites")   # treat the fake like the real tool
    agent = Agent(name="t", model=ParallelLlm(), tools=[slow_rank_priority_sites, build_dispatch_plan],
                  after_tool_callback=stash_tool_results)
    runner = InMemoryRunner(agent=agent, app_name="t")

    async def go():
        s = await runner.session_service.create_session(app_name="t", user_id="u")
        return [e async for e in runner.run_async(user_id="u", session_id=s.id,
                new_message=types.Content(role="user", parts=[types.Part(text="plan")]))]

    events = asyncio.run(go())
    plans = [p.function_response.response for e in events for p in (e.content.parts if e.content else [])
             if p.function_response and p.function_response.name == "build_dispatch_plan"]
    assert plans and plans[0]["status"] == "ok", plans
