"""Equity & Verification Agent: audits allocations against citywide ACS demographic baselines."""
from __future__ import annotations

from typing import Any
from google.adk.agents import Agent

EQUITY_INSTRUCTION = """You are the Equity Audit Specialist for Chicago Emergency Heat Dispatch.
Your job is to evaluate proposed resource allocations against citywide ACS demographic baselines to prevent
algorithmic bias and ensure historically disinvested communities receive priority.

Key Guidelines:
- Use `equity_audit` to compare the demographics of recommended sites/tracts against the citywide median.
- Verify that poverty rate, senior population share, and zero-vehicle household share exceed citywide averages.
- Flag any risk of resource hoarding in affluent, cooler lakefront tourist corridors.
- Provide a clear, objective fairness verdict with demographic multiplier ratios (e.g., 2.1x poverty vs citywide).
- Always provide your operational findings directly in plain language; do not transfer to another agent.
"""


def build_equity_agent(model: Any, toolbox_tools: Any = None, before_callback: Any = None, after_callback: Any = None) -> Agent:
    tools: list[Any] = []
    if toolbox_tools:
        tools.append(toolbox_tools)
    return Agent(
        name="equity_agent",
        model=model,
        description="Equity Audit specialist: validates resource fairness against ACS demographic baselines to prevent algorithmic bias.",
        instruction=EQUITY_INSTRUCTION,
        tools=tools,
        before_tool_callback=before_callback,
        after_tool_callback=after_callback,
    )
