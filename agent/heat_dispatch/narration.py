"""Plain-language wording for model attributions. Deterministic, so a number is never reworded wrongly."""
from __future__ import annotations

from typing import Any

# BQML reports attributions per TRANSFORM output (the *_band / log_ names) or per raw input column,
# depending on version: handle both.
FEATURE_LABELS = {
    "lake_distance_band": "distance from Lake Michigan",
    "dist_to_lake_km": "distance from Lake Michigan",
    "downtown_distance_band": "distance from downtown (the Loop)",
    "dist_to_loop_km": "distance from downtown (the Loop)",
    "log_pop_density": "how densely built and populated the area is",
    "pop_density_km2": "how densely built and populated the area is",
    "building_era": "age of the housing stock",
    "median_year_structure_built": "age of the housing stock",
    "building_share": "share of the ground covered by buildings",
    "green_share": "parks, grass and trees nearby",
    "paved_use_share": "industrial, commercial and parking land",
    "paved_use": "industrial, commercial and parking land",
    "log_road_density": "how much of the area is street",
    "road_km_per_km2": "how much of the area is street",
}


def label_for(feature: str) -> str:
    return FEATURE_LABELS.get(feature, feature.replace("_", " "))


def describe_why(why: Any, top: int = 3) -> str:
    """[{feature, contribution_f}] or [[feature, value]] -> 'distance from the lake +2.1°F; dense development +0.8°F'.

    contribution_f is degrees F versus the average Chicago grid cell (positive = hotter).
    """
    if isinstance(why, str):
        import json
        try:
            why = json.loads(why)
        except ValueError:
            return ""
    parts = []
    for item in (why or [])[:top]:
        # BigQuery structs reach us as {feature, contribution_f} objects directly, but as [feature, value] pairs
        # when they travel through MCP Toolbox (verified live): accept both.
        try:
            if isinstance(item, dict):
                feature, value = item["feature"], item["contribution_f"]
            else:
                feature, value = item[0], item[1]
            parts.append(f"{label_for(str(feature))} {float(value):+.1f}°F")
        except (KeyError, IndexError, TypeError, ValueError):
            continue
    return "; ".join(parts)
