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
    try:
        async with httpx.AsyncClient(timeout=10, headers={"User-Agent": user_agent, "Accept": "application/geo+json"}) as c:
            point = (await c.get(f"https://api.weather.gov/points/{CHICAGO[0]:.4f},{CHICAGO[1]:.4f}")).json()
            fc = (await c.get(point["properties"]["forecast"])).json()
        days = []
        for p in fc["properties"]["periods"]:
            if not p.get("isDaytime"):
                continue
            d = dt.date.fromisoformat(p["startTime"][:10])
            days.append({"date": d.isoformat(), "weekday": WEEKDAYS[d.weekday()], "label": p.get("name"),
                         "high_f": p.get("temperature"), "short_forecast": p.get("shortForecast")})
        if days:
            return {"source": "api.weather.gov", "days": days[:7]}
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        pass
    days = []
    for i in range(7):
        d = today + dt.timedelta(days=i)
        days.append({"date": d.isoformat(), "weekday": WEEKDAYS[d.weekday()],
                     "label": "Today" if i == 0 else d.strftime("%A"), "high_f": None, "short_forecast": None})
    return {"source": "unavailable", "days": days}
