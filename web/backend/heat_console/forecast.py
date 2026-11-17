"""Planning days from the National Weather Service (keyless). Falls back to 7 dated days with no high, which the
operator fills in as a scenario."""
from __future__ import annotations

import datetime as dt
from typing import Any

import httpx

CHICAGO = (41.8781, -87.6298)
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


async def planning_days(user_agent: str, today: dt.date | None = None) -> dict[str, Any]:
    today = today or dt.date.today()
    scenario_day = {
        "date": today.isoformat(),
        "weekday": WEEKDAYS[today.weekday()],
        "label": "Heat Advisory (102°F Scenario)",
        "high_f": 102,
        "short_forecast": "Excessive Heat Warning",
    }
    days = [scenario_day]
    try:
        async with httpx.AsyncClient(timeout=10, headers={"User-Agent": user_agent, "Accept": "application/geo+json"}) as c:
            point = (await c.get(f"https://api.weather.gov/points/{CHICAGO[0]:.4f},{CHICAGO[1]:.4f}")).json()
            fc = (await c.get(point["properties"]["forecast"])).json()
        for p in fc["properties"]["periods"]:
            if not p.get("isDaytime"):
                continue
            d = dt.date.fromisoformat(p["startTime"][:10])
            days.append({"date": d.isoformat(), "weekday": WEEKDAYS[d.weekday()], "label": p.get("name"),
                         "high_f": p.get("temperature"), "short_forecast": p.get("shortForecast")})
        if len(days) > 1:
            return {"source": "api.weather.gov + scenario", "days": days[:8]}
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        pass
    for i in range(1, 7):
        d = today + dt.timedelta(days=i)
        days.append({"date": d.isoformat(), "weekday": WEEKDAYS[d.weekday()],
                     "label": d.strftime("%A"), "high_f": 95 if i == 1 else None, "short_forecast": None})
    return {"source": "scenario", "days": days}

