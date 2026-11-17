"""Forecast + heat-risk tools (pure Python, no GCP needed).

get_forecast_high      keyless api.weather.gov: the coming daytime highs for a point.
heat_risk_for_forecast forecast high + a site's predicted OFFSET -> expected air temperature there, and the
                       NWS heat-index category when humidity is known.
"""
from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from typing import Any

from .config import get_settings

NWS = "https://api.weather.gov"

# NWS heat index chart categories (degrees F, heat index not air temperature).
_CATEGORIES = [
    (125, "Extreme danger: heat stroke highly likely"),
    (103, "Danger: heat cramps/exhaustion likely, heat stroke possible with prolonged exposure"),
    (90, "Extreme caution: heat cramps/exhaustion possible, heat stroke possible"),
    (80, "Caution: fatigue possible with prolonged exposure"),
]


def heat_index_f(temp_f: float, rh_pct: float) -> float:
    """NWS Rothfusz regression with its published adjustments. Valid for about 80F and up."""
    t, rh = float(temp_f), float(rh_pct)
    simple = 0.5 * (t + 61.0 + (t - 68.0) * 1.2 + rh * 0.094)
    if (simple + t) / 2 < 80:
        return simple
    hi = (-42.379 + 2.04901523 * t + 10.14333127 * rh - 0.22475541 * t * rh - 0.00683783 * t * t
          - 0.05481717 * rh * rh + 0.00122874 * t * t * rh + 0.00085282 * t * rh * rh
          - 0.00000199 * t * t * rh * rh)
    if rh < 13 and 80 <= t <= 112:
        hi -= ((13 - rh) / 4) * math.sqrt((17 - abs(t - 95.0)) / 17)
    elif rh > 85 and 80 <= t <= 87:
        hi += ((rh - 85) / 10) * ((87 - t) / 5)
    return hi


def category_for(hi_f: float) -> str:
    for floor, text in _CATEGORIES:
        if hi_f >= floor:
            return text
    return "Below the NWS heat-index caution range"


def heat_risk_for_forecast(forecast_high_f: float, predicted_offset_f: float,
                           relative_humidity_pct: float | None = None) -> dict:
    """Expected conditions at a site: forecast high plus the site's predicted offset.

    Args:
        forecast_high_f: the city forecast high in degrees F (e.g. 102).
        predicted_offset_f: the site's predicted offset from a heat tool (degrees F hotter than the average spot).
        relative_humidity_pct: afternoon relative humidity, 0-100, if known. Without it only the air temperature
            is returned (a heat index needs humidity).
    """
    air = float(forecast_high_f) + float(predicted_offset_f)
    out: dict[str, Any] = {
        "forecast_high_f": round(float(forecast_high_f), 1),
        "predicted_offset_f": round(float(predicted_offset_f), 1),
        "expected_air_temp_f": round(air, 1),
        "note": ("Air temperature = forecast high + the site's offset. The offset comes from one volunteer-driven "
                 "afternoon and is spatial only: treat it as a ranking signal, not a thermometer reading."),
    }
    if relative_humidity_pct is not None:
        rh = max(0.0, min(100.0, float(relative_humidity_pct)))
        hi = heat_index_f(air, rh)
        out.update({"relative_humidity_pct": rh, "expected_heat_index_f": round(hi, 1),
                    "nws_heat_index_category": category_for(hi)})
        if air > 112:
            out["heat_index_caveat"] = ("Air temperature is above ~112F, past the range the NWS heat-index regression was "
                                        "fitted on (the NWS chart stops at 110F). Treat the heat index as 'extreme', not exact.")
    else:
        out["nws_heat_index_category"] = "unknown without humidity (pass relative_humidity_pct for a heat index)"
    return out


def _get_json(url: str, user_agent: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "application/geo+json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def get_forecast_high(latitude: float = 41.8781, longitude: float = -87.6298) -> dict:
    """Coming daytime highs from the National Weather Service for a point (defaults to downtown Chicago).

    Use when the planner has not given a forecast, or to confirm 'tomorrow is 102'. US only, keyless.

    Args:
        latitude: decimal degrees.
        longitude: decimal degrees.
    """
    ua = get_settings().contact_agent
    try:
        point = _get_json(f"{NWS}/points/{latitude:.4f},{longitude:.4f}", ua)
        forecast = _get_json(point["properties"]["forecast"], ua)
    except (urllib.error.URLError, KeyError, ValueError, TimeoutError) as exc:
        return {"status": "unavailable", "message": f"Could not reach the NWS forecast service ({exc.__class__.__name__}). "
                "Ask the planner for the forecast high instead."}
    days = []
    for p in forecast.get("properties", {}).get("periods", []):
        if not p.get("isDaytime"):
            continue
        rh = (p.get("relativeHumidity") or {}).get("value")
        days.append({"period": p.get("name"), "starts": p.get("startTime"), "high_f": p.get("temperature"),
                     "relative_humidity_pct": rh, "short_forecast": p.get("shortForecast")})
        if len(days) == 4:
            break
    return {"status": "ok", "source": "api.weather.gov", "updated": forecast.get("properties", {}).get("updateTime"),
            "daytime_highs": days}
