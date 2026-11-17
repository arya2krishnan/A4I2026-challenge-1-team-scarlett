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
- Use `get_forecast_high` to fetch official NWS Chicago forecast high temperature.
- Use `heat_risk_for_forecast` to assess NWS HeatRisk tiers and health warnings.
- Use `predict_site_heat` to obtain modelled heat offsets (°F) and physical feature attributions
  (distance to Lake Michigan, net impervious deficit, building density, Loop proximity).
- Explain physical heat drivers clearly for non-technical public health operators.
- Distinguish between measured ground truth (Heat Watch street campaign) and modelled offsets.
- Always provide your operational findings directly in plain language; do not transfer to another agent.
"""


def build_spatial_risk_agent(model: Any, toolbox_tools: Any = None) -> Agent:
    tools: list[Any] = [get_forecast_high, heat_risk_for_forecast, locate_place]
    if toolbox_tools:
        tools.append(toolbox_tools)
    return Agent(
        name="spatial_risk_agent",
        model=model,
        description="Heat & Spatial Risk specialist: analyzes weather forecasts, runs BQML microclimate offset models, and explains physical heat island drivers.",
        instruction=SPATIAL_RISK_INSTRUCTION,
        tools=tools,
    )
