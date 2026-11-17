"""Reactive Triage & Disruption Agent: handles midday outages and 311 distress calls."""
from __future__ import annotations

from typing import Any
from google.adk.agents import Agent
from ..places import locate_place

TRIAGE_INSTRUCTION = """You are the Reactive Triage & Disruption Specialist for Chicago Emergency Heat Dispatch.
Your job is to respond in real-time to midday emergency incidents such as cooling center HVAC breakdowns,
power outages, or clusters of 311 heat distress calls.

Key Guidelines:
- When a facility fails (e.g. Legler Regional Library AC breakdown):
  1. Use `nearest_cooling_facilities` to find the nearest backup indoor cooling facility (such as a nearby High School gym or senior center).
  2. Direct emergency hydration assets or shade canopies to the affected site's exterior/parking lot.
- When a 311 heat distress cluster occurs (e.g. 79th & Halsted):
  1. Use `locate_place` and `predict_site_heat` to evaluate conditions at the intersection.
  2. Recommend immediate rerouting of the nearest wellness check canvass team or mobile hydration truck.
- Keep recommendations fast, actionable, and calm under emergency pressure.
"""


def build_triage_agent(model: Any, toolbox_tools: Any = None) -> Agent:
    tools: list[Any] = [locate_place]
    if toolbox_tools:
        tools.append(toolbox_tools)
    return Agent(
        name="triage_agent",
        model=model,
        description="Reactive Triage & Disruption specialist: handles midday cooling center outages, 311 distress calls, and emergency rerouting.",
        instruction=TRIAGE_INSTRUCTION,
        tools=tools,
    )
