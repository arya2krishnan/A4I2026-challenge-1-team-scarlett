"""Request bodies. Stops and teams accept the exact dicts build_dispatch_plan returns (extra fields are kept)."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Same box as agent/heat_dispatch/places.py (a test keeps them equal). Duplicated so the API does not import the agent.
CHICAGO_BOX = (41.60, 42.10, -87.95, -87.50)   # lat_min, lat_max, lon_min, lon_max


def in_chicago(lat: float, lon: float) -> bool:
    return CHICAGO_BOX[0] <= lat <= CHICAGO_BOX[1] and CHICAGO_BOX[2] <= lon <= CHICAGO_BOX[3]


class _Point(BaseModel):
    latitude: float
    longitude: float

    @model_validator(mode="after")
    def _inside_chicago(self):
        if not in_chicago(self.latitude, self.longitude):
            raise ValueError(f"({self.latitude}, {self.longitude}) is outside the City of Chicago")
        return self


class Stop(_Point):
    """One hydration-truck stop (build_dispatch_plan -> hydration_stops[i])."""
    model_config = ConfigDict(extra="allow")
    stop: int = Field(ge=1)


class Team(_Point):
    """One wellness-check team (build_dispatch_plan -> wellness_teams[i])."""
    model_config = ConfigDict(extra="allow")
    team: int = Field(ge=1)


class ProposalIn(BaseModel):
    """The agent's recommendation sheet. Unknown top-level keys (e.g. `map`) are ignored."""
    model_config = ConfigDict(extra="ignore")
    forecast_high_f: float
    hydration_stops: list[Stop] = Field(min_length=1)
    wellness_teams: list[Team] = Field(default_factory=list)
    library_extensions: list[dict] = Field(default_factory=list)
    high_school_gyms: list[dict] = Field(default_factory=list)
    dispatch_sheet_markdown: str = ""
    equity_audit_ran: bool = False
    submitted_by: str = "heat_dispatch_agent"

    @model_validator(mode="after")
    def _unique_numbers(self):
        for label, nums in (("stop", [s.stop for s in self.hydration_stops]),
                            ("team", [t.team for t in self.wellness_teams])):
            if len(nums) != len(set(nums)):
                raise ValueError(f"duplicate {label} numbers: {nums}")
        return self


class StopOverride(_Point):
    reason: str = Field(min_length=1)


class ApproveIn(BaseModel):
    proposal_id: str
    approved_by: str = Field(min_length=1)
    approved_stops: list[int] = Field(min_length=1)
    approved_teams: list[int] | None = None          # None = every wellness team in the proposal
    overrides: dict[int, StopOverride] = Field(default_factory=dict)   # stop number -> new point + reason


class OverrideIn(StopOverride):
    """Midday triage: move one stop of an approved dispatch."""
    stop: int = Field(ge=1)
    requested_by: str = Field(min_length=1)


class CloseIn(BaseModel):
    """Stand a dispatch down (end of the heat day, or cancelled): it leaves the active list."""
    closed_by: str = Field(min_length=1)
    reason: str = Field(min_length=1)
