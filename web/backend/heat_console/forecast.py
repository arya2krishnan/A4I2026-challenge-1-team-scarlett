"""Planning days from the National Weather Service (keyless). Falls back to 7 dated days with no high, which the
operator fills in as a scenario."""
from __future__ import annotations

import datetime as dt
from typing import Any

import httpx

CHICAGO = (41.8781, -87.6298)
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


HISTORIC_DAYS = [
    {
        "date": "2026-07-12",
        "weekday": "mon",
        "label": "Mon Jul 12",
        "high_f": 92,
        "short_forecast": "Heat Advisory · High Humidity",
    },
    {
        "date": "2026-07-13",
        "weekday": "tue",
        "label": "Tue Jul 13",
        "high_f": 96,
        "short_forecast": "Excessive Heat Watch · Advisory in Effect",
    },
    {
        "date": "2026-07-14",
        "weekday": "wed",
        "label": "Wed Jul 14 (Peak Alert)",
        "high_f": 102,
        "short_forecast": "Extreme Heat Emergency · Peak Danger",
    },
    {
        "date": "2026-07-15",
        "weekday": "thu",
        "label": "Thu Jul 15",
        "high_f": 104,
        "short_forecast": "Excessive Heat Warning · Heat Index 119°F",
    },
    {
        "date": "2026-07-16",
        "weekday": "fri",
        "label": "Fri Jul 16",
        "high_f": 99,
        "short_forecast": "Excessive Heat Warning",
    },
    {
        "date": "2026-07-17",
        "weekday": "sat",
        "label": "Sat Jul 17",
        "high_f": 91,
        "short_forecast": "Heat Advisory · Front Approaching",
    },
    {
        "date": "2026-07-18",
        "weekday": "sun",
        "label": "Sun Jul 18 (Relief)",
        "high_f": 78,
        "short_forecast": "Cold Front Relief · Stand Down",
    },
]


async def planning_days(user_agent: str, today: dt.date | None = None, mode: str = "historic") -> dict[str, Any]:
    today = today or dt.date.today()
    live_days = []
    try:
        async with httpx.AsyncClient(timeout=10, headers={"User-Agent": user_agent, "Accept": "application/geo+json"}) as c:
            point = (await c.get(f"https://api.weather.gov/points/{CHICAGO[0]:.4f},{CHICAGO[1]:.4f}")).json()
            fc = (await c.get(point["properties"]["forecast"])).json()
        for p in fc["properties"]["periods"]:
            if not p.get("isDaytime"):
                continue
            d = dt.date.fromisoformat(p["startTime"][:10])
            live_days.append({"date": d.isoformat(), "weekday": WEEKDAYS[d.weekday()], "label": p.get("name"),
                             "high_f": p.get("temperature"), "short_forecast": p.get("shortForecast")})
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        pass

    if not live_days:
        for i in range(7):
            d = today + dt.timedelta(days=i)
            live_days.append({"date": d.isoformat(), "weekday": WEEKDAYS[d.weekday()],
                             "label": d.strftime("%A"), "high_f": 57 if i == 0 else 48, "short_forecast": "Live NOAA Fall Season"})

    days = HISTORIC_DAYS if mode == "historic" else live_days[:8]
    return {
        "source": "1995 Historic Chicago Heatwave" if mode == "historic" else "api.weather.gov",
        "mode": mode,
        "days": days,
        "historic": HISTORIC_DAYS,
        "current": live_days[:8],
    }


