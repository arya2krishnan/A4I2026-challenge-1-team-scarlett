"""Social Media & 311 Heat Emergency Agent: ADK agent for public alerts, dispatch updates, and resident support."""
from __future__ import annotations

from typing import Any

from google.adk.agents import Agent
from google.adk.models import Gemini
from google.genai.types import HttpRetryOptions

from heat_dispatch.config import get_settings
from heat_dispatch.forecast import get_forecast_high, heat_risk_for_forecast
from heat_dispatch.places import locate_place

from .alerts import broadcast_critical_alert
from .call_311 import check_heat_illness_urgency, find_cooling_for_caller, intake_wellness_check, log_311_heat_call
from .config import get_social_settings
from .dispatch_updates import broadcast_dispatch_actions
from .prompts import SOCIAL_MEDIA_INSTRUCTION
from .vulnerability import identify_top_vulnerabilities

S = get_settings()
SOC_S = get_social_settings()


def _model() -> Gemini:
    return Gemini(
        model=S.model,
        retry_options=HttpRetryOptions(initial_delay=1, max_delay=4, attempts=6),
        client_kwargs={"enterprise": True, "location": S.model_location},
    )


social_media_agent = Agent(
    name="heat_social_agent",
    model=_model(),
    description=(
        "Chicago emergency-heat public communications & 311 desk assistant: "
        "broadcasts critical Twitter alerts, publishes operational dispatch updates, "
        "and answers resident 311 calls for cooling centers and wellness checks."
    ),
    instruction=SOCIAL_MEDIA_INSTRUCTION,
    tools=[
        broadcast_critical_alert,
        broadcast_dispatch_actions,
        identify_top_vulnerabilities,
        log_311_heat_call,
        find_cooling_for_caller,
        intake_wellness_check,
        check_heat_illness_urgency,
        locate_place,
        get_forecast_high,
        heat_risk_for_forecast,
    ],
)

# Export root_agent alias for standard ADK discovery
root_agent = social_media_agent
