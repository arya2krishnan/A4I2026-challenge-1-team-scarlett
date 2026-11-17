"""Fake Toolbox rows shared by the planner, console-tool and web-backend tests (shapes match tools.yaml output)."""
from __future__ import annotations

import json

HOURS_A = "Mon. & Wed., 10-6; Tues. & Thurs., Noon-8; Fri. & Sat., 9-5; Sun., 1-5"


def sites(n: int = 12) -> list[dict]:
    return [{
        "rank": i + 1, "cell_id": f"c{i:03d}", "neighborhood": f"Hood{i}", "latitude": 41.75 + i * 0.01,
        "longitude": -87.65, "tract_geo_id": f"17031{i:06d}", "predicted_offset_f": round(1.5 - i * 0.1, 2),
        "why": [["lake_distance_band", 0.8], ["building_era", 0.2]], "priority_score": round(0.9 - i * 0.03, 3),
        "residents_65_plus": 300 + i, "households_without_car": 100, "poverty_rate": 0.3, "tract_population": 3000,
        "km_to_indoor_cooling": 1.2, "nearest_cooling_name": "Somewhere", "measured_readings": i % 2,
        "measured_offset_f": 1.0, "vulnerability_index": 0.7,
    } for i in range(n)]


def tracts(n: int = 20) -> list[dict]:
    return [{
        "rank": i + 1, "tract_geo_id": f"17031{100 + i:06d}", "neighborhood": f"Tract{i}",
        "latitude": 41.80 + (i % 5) * 0.004, "longitude": -87.62 + (i // 5) * 0.004,
        "predicted_offset_f": round(1.2 - i * 0.05, 2), "priority_score": round(0.95 - i * 0.02, 3),
        "residents_65_plus": 500 - i, "households_without_car": 120, "poverty_rate": 0.25,
        "tract_population": 2500, "avg_km_to_indoor_cooling": 0.9, "vulnerability_index": 0.6,
    } for i in range(n)]


def libraries() -> list[dict]:
    return [
        {"site_name": "Near", "site_category": "Library", "address": "1 Near St", "latitude": 41.805,
         "longitude": -87.615, "service_hours": HOURS_A},
        {"site_name": "Legler Regional", "site_category": "Library", "address": "115 S Pulaski", "latitude": 41.81,
         "longitude": -87.61, "service_hours": HOURS_A},
        {"site_name": "Far Away", "site_category": "Library", "address": "9 Far", "latitude": 42.0,
         "longitude": -87.8, "service_hours": HOURS_A},
        {"site_name": "Galewood-Mont Clare", "site_category": "Library", "address": "x", "latitude": 41.806,
         "longitude": -87.616, "service_hours": "Closed until further notice"},
    ]


def tract_layer() -> list[dict]:
    rows = []
    for t in tracts(20):
        rows.append({"tract_geo_id": t["tract_geo_id"], "neighborhood": t["neighborhood"],
                     "latitude": t["latitude"], "longitude": t["longitude"],
                     "predicted_offset_f": t["predicted_offset_f"], "measured_readings": 3, "measured_offset_f": 1.0,
                     "total_pop": 2500, "pop_65_plus": t["residents_65_plus"], "pct_65_plus": 0.2,
                     "poverty_rate": 0.25, "no_vehicle_rate": 0.3, "median_income": 40000,
                     "vulnerability_index": t["vulnerability_index"], "area_km2": 0.5,
                     "nearest_ac_name": "Near", "nearest_ac_category": "Library", "km_to_ac": 0.4,
                     "geometry": json.dumps({"type": "Polygon", "coordinates": [[
                         [t["longitude"], t["latitude"]], [t["longitude"] + 0.003, t["latitude"]],
                         [t["longitude"] + 0.003, t["latitude"] + 0.003], [t["longitude"], t["latitude"]]]]})})
    return rows


def all_sites() -> list[dict]:
    return libraries() + [
        {"site_name": "District 7", "site_category": "Police District", "latitude": 41.77, "longitude": -87.65,
         "is_current_cooling_site": True, "indoor_air_conditioned": True, "open_24_7": True},
        {"site_name": "NOBLE - COMER", "site_category": "CPS High School (candidate)", "latitude": 41.76,
         "longitude": -87.60, "is_current_cooling_site": False, "indoor_air_conditioned": None, "open_24_7": False},
    ]


async def fake_invoke(name: str, params: dict) -> list[dict]:
    """Fake Toolbox: honours limit and min_offset like the SQL does."""
    lo = params.get("min_offset", -99)
    if name == "rank_priority_sites":
        return [s for s in sites(50) if s["predicted_offset_f"] >= lo][: params.get("limit", 8)]
    if name == "rank_wellness_check_tracts":
        return [t for t in tracts(40) if t["predicted_offset_f"] >= lo][: params.get("limit", 10)]
    if name == "list_sites":
        cat = params.get("category", "any")
        return [s for s in all_sites() if cat == "any" or s["site_category"] == cat]
    if name == "tract_map_layer":
        return tract_layer()
    raise KeyError(name)
