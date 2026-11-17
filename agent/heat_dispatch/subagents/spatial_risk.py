"""Spatial Risk & Microclimate Agent: analyzes weather, physical offsets, and heat corridors."""
from __future__ import annotations

from typing import Any
from google.adk.agents import Agent
from ..forecast import get_forecast_high, heat_risk_for_forecast
from ..places import locate_place

SPATIAL_RISK_INSTRUCTION = """You are the Heat & Spatial Risk Specialist for Chicago Emergency Heat Dispatch.
Your job is to analyze ambient weather forecasts, run BigQuery ML physical microclimate offset models,
and identify urban heat island corridors across Chicago's 77 official community areas.

Key Guidelines:
- You have direct access to BigQuery ML tools including `predict_site_heat`, `get_forecast_high`, `heat_risk_for_forecast`, and `locate_place`.
- When asked why a location or neighborhood is hot, you MUST call `predict_site_heat(latitude=..., longitude=...)` to retrieve the modelled offset and physical feature contributions (`why` list).
- Use `get_forecast_high` to fetch official NWS Chicago forecast high temperature.
- Use `heat_risk_for_forecast` to assess NWS HeatRisk tiers and health warnings.
- Explain physical heat drivers clearly for non-technical public health operators: quote the exact offset contributions (e.g. "distance from the lake +2.1°F, impervious deficit +1.2°F").
- Distinguish between measured ground truth (Heat Watch street campaign) and modelled offsets.
- Always provide your operational findings directly in plain language; do not transfer to another agent.
"""


def build_spatial_risk_agent(model: Any, toolbox_tools: Any = None, before_callback: Any = None, after_callback: Any = None) -> Agent:
    tools: list[Any] = [get_forecast_high, heat_risk_for_forecast, locate_place]
    if toolbox_tools:
        tools.append(toolbox_tools)
    return Agent(
        name="spatial_risk_agent",
        model=model,
        description="Heat & Spatial Risk specialist: analyzes weather forecasts, runs BQML microclimate offset models, and explains physical heat island drivers.",
        instruction=SPATIAL_RISK_INSTRUCTION,
        tools=tools,
        before_tool_callback=before_callback,
        after_tool_callback=after_callback,
    )
