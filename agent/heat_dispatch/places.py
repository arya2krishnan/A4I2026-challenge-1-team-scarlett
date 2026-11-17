"""locate_place: 'Englewood' / '63rd and Halsted' -> coordinates the Toolbox tools can use.

Order: (1) a small built-in table of well-known Chicago neighbourhoods (approximate centres, offline, instant),
(2) Google Geocoding when MAPS_API_KEY is set (any address or intersection). Anything outside Chicago is refused.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

from .config import get_settings

# Approximate neighbourhood centres (lat, lon). Good to ~1 km: enough to pick a grid cell, not to find a door.
NEIGHBORHOODS: dict[str, tuple[float, float]] = {
    "the loop": (41.8781, -87.6298), "loop": (41.8781, -87.6298), "downtown": (41.8781, -87.6298),
    "englewood": (41.7796, -87.6444), "west englewood": (41.7790, -87.6720),
    "austin": (41.8940, -87.7650), "north lawndale": (41.8600, -87.7200),
    "little village": (41.8430, -87.7140), "south lawndale": (41.8430, -87.7140),
    "back of the yards": (41.8100, -87.6600), "pilsen": (41.8560, -87.6600),
    "chinatown": (41.8520, -87.6322), "bridgeport": (41.8380, -87.6500),
    "bronzeville": (41.8330, -87.6150), "hyde park": (41.7943, -87.5907),
    "woodlawn": (41.7790, -87.5970), "south shore": (41.7600, -87.5760),
    "chatham": (41.7400, -87.6150), "auburn gresham": (41.7450, -87.6560),
    "roseland": (41.6930, -87.6200), "pullman": (41.6930, -87.6080),
    "chicago lawn": (41.7790, -87.6950), "gage park": (41.7950, -87.6960),
    "brighton park": (41.8170, -87.6990), "garfield park": (41.8810, -87.7160),
    "east garfield park": (41.8810, -87.7040), "west garfield park": (41.8800, -87.7300),
    "humboldt park": (41.9020, -87.7230), "logan square": (41.9230, -87.7080),
    "belmont cragin": (41.9300, -87.7600), "albany park": (41.9690, -87.7230),
    "uptown": (41.9660, -87.6550), "edgewater": (41.9890, -87.6600),
    "rogers park": (42.0080, -87.6680), "west ridge": (42.0000, -87.6930),
    "lincoln park": (41.9210, -87.6490), "near west side": (41.8750, -87.6640),
    "west town": (41.9000, -87.6750), "ohare": (41.9786, -87.9048), "o'hare": (41.9786, -87.9048),
}
CHICAGO_BOX = (41.60, 42.10, -87.95, -87.50)   # lat_min, lat_max, lon_min, lon_max


def in_chicago(lat: float, lon: float) -> bool:
    return CHICAGO_BOX[0] <= lat <= CHICAGO_BOX[1] and CHICAGO_BOX[2] <= lon <= CHICAGO_BOX[3]


def _norm(text: str) -> str:
    return re.sub(r"[^a-z' ]", " ", text.lower().replace(",", " ")).strip()


def _geocode(address: str, key: str) -> dict | None:
    q = urllib.parse.urlencode({"address": f"{address}, Chicago, IL", "key": key, "region": "us",
                                "components": "administrative_area:IL|country:US"})
    with urllib.request.urlopen(f"https://maps.googleapis.com/maps/api/geocode/json?{q}", timeout=15) as r:
        data = json.load(r)
    if data.get("status") != "OK" or not data.get("results"):
        return None
    res = data["results"][0]
    loc = res["geometry"]["location"]
    return {"latitude": loc["lat"], "longitude": loc["lng"], "formatted_address": res.get("formatted_address", "")}


def locate_place(place: str) -> dict:
    """Turn a Chicago neighbourhood, address or intersection into latitude/longitude for the heat tools.

    Args:
        place: e.g. 'Englewood', '63rd and Halsted', '3401 W Foster Ave'.
    """
    text = _norm(place or "")
    if not text:
        return {"status": "not_found", "message": "No place given. Ask the planner for a neighbourhood or intersection."}
    # 'south side' style regions are too broad to be one point
    if text in {"south side", "west side", "north side", "far south side", "southwest side", "northwest side"}:
        return {"status": "too_broad", "message": f"'{place}' covers many neighbourhoods. Ask for a neighbourhood "
                "(e.g. Englewood, Austin, Little Village) or run rank_priority_sites for the whole city and filter."}
    if text in NEIGHBORHOODS:
        lat, lon = NEIGHBORHOODS[text]
        return {"status": "ok", "source": "built-in neighbourhood centre (approximate, ~1 km)", "query": place,
                "latitude": lat, "longitude": lon}
    key = get_settings().maps_api_key
    if key:
        try:
            hit = _geocode(place, key)
        except Exception as exc:  # network or quota: fall through to a clear message
            return {"status": "error", "message": f"Geocoding failed ({exc.__class__.__name__}). Try a neighbourhood name."}
        if hit and in_chicago(hit["latitude"], hit["longitude"]):
            return {"status": "ok", "source": "Google Geocoding", "query": place, **hit}
        if hit:
            return {"status": "outside_area", "message": f"'{place}' resolves outside Chicago "
                    f"({hit['formatted_address']}). This assistant only covers the City of Chicago."}
    return {"status": "not_found", "message": f"Could not place '{place}'. Try a Chicago neighbourhood name"
            + ("" if key else " (street addresses need a Maps API key, which is not configured)") + "."}
