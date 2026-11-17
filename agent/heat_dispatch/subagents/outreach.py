"""Community Outreach Agent: prioritizes wellness check canvassing for isolated seniors."""
from __future__ import annotations

from typing import Any
from google.adk.agents import Agent
from ..places import locate_place

OUTREACH_INSTRUCTION = """You are the Community Outreach Specialist for Chicago Emergency Heat Dispatch.
Your job is to prioritize census tracts for frontline door-to-door senior wellness checks and heat vulnerability canvassing.

Key Guidelines:
- Use `rank_wellness_check_tracts` to find tracts with the highest concentration of residents aged 65+,
  households without a car, and elevated poverty rates.
- Use `who_lives_near` to inspect demographic vulnerability within walking distance of any specific site.
- Estimate senior populations and mobility constraints for each canvassing zone.
- Recommend practical canvassing team sizes and prioritize areas with isolated seniors.
- Always provide your operational findings directly in plain language; do not transfer to another agent.
"""


def build_outreach_agent(model: Any, toolbox_tools: Any = None, before_callback: Any = None, after_callback: Any = None) -> Agent:
    tools: list[Any] = [locate_place]
    if toolbox_tools:
        tools.append(toolbox_tools)
    return Agent(
        name="outreach_agent",
        model=model,
        description="Community Outreach specialist: prioritizes census tracts with isolated seniors and zero-vehicle households for wellness checks.",
        instruction=OUTREACH_INSTRUCTION,
        tools=tools,
        before_tool_callback=before_callback,
        after_tool_callback=after_callback,
    )
