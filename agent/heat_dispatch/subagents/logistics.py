"""Logistics & Facilities Agent: sites water trucks and pairs with libraries and high school gyms."""
from __future__ import annotations

from typing import Any
from google.adk.agents import Agent
from ..places import locate_place

LOGISTICS_INSTRUCTION = """You are the Logistics & Facilities Specialist for Chicago Emergency Heat Dispatch.
Your job is to site mobile hydration trucks at high-priority street intersections and identify indoor cooling facilities
(Chicago Public Libraries for hours extension, and CPS High School gymnasiums for mass emergency cooling).

Key Guidelines:
- Use `rank_priority_sites` to find the highest-priority heat/vulnerability intersections for water trucks.
- Use `nearest_cooling_facilities` with `facility_type='Library'` to find the closest CPL library branches to extend hours.
- Use `nearest_cooling_facilities` with `facility_type='High School'` to identify CPS High School gymnasiums with large-capacity indoor air conditioning.
- Provide practical operational context: specify exact cross streets, parking/staging feasibility, and nearest indoor cooling distance.
"""


def build_logistics_agent(model: Any, toolbox_tools: Any = None) -> Agent:
    tools: list[Any] = [locate_place]
    if toolbox_tools:
        tools.append(toolbox_tools)
    return Agent(
        name="logistics_agent",
        model=model,
        description="Logistics & Facilities specialist: sites hydration trucks and identifies libraries and high school gyms for cooling shelter.",
        instruction=LOGISTICS_INSTRUCTION,
        tools=tools,
    )
