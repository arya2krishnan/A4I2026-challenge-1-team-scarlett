#!/usr/bin/env python3
"""Generate toolbox/tools.yaml: the MCP Toolbox tool definitions (parameterized BigQuery SQL).

Why a generator: four tools share the same "score every grid cell with ML.EXPLAIN_PREDICT, add
vulnerability and cooling-access, keep the best cell per superblock" logic. Writing that once here keeps
the tools consistent. The generated tools.yaml is committed so reviewers can read it; a test fails if it
drifts from this file.

    python toolbox/build_tools_yaml.py            # rewrite toolbox/tools.yaml
    python toolbox/build_tools_yaml.py --check    # exit 1 if tools.yaml is out of date

${VAR} / ${VAR:default} placeholders are resolved by scripts/render_toolbox.py at deploy time
(Toolbox also expands them itself, but we render first so a missing value fails before upload).
"""
from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
OUT = HERE / "tools.yaml"
MIN_OBS = json.loads((HERE.parent / "sql" / "chicago.json").read_text())["MIN_OBS"]

T = "`${GOOGLE_CLOUD_PROJECT}.${BQ_DATASET:a4i_climate}"   # table prefix; close the backtick after the name
MODEL = f"{T}.heat_offset_model`"


def tbl(name: str) -> str:
    return f"{T}.{name}`"


# ----------------------------------------------------------------------------------------------
# Shared parameter definitions
# ----------------------------------------------------------------------------------------------
def p_limit(default: int = 8, mx: int = 25) -> dict:
    return {"name": "limit", "type": "integer", "default": default, "minValue": 1, "maxValue": mx,
            "description": f"How many rows to return (default {default}, max {mx})."}


P_HEAT_WEIGHT = {
    "name": "heat_weight", "type": "float", "default": 0.5, "minValue": 0, "maxValue": 1,
    "description": ("Weight on predicted heat versus resident vulnerability in the priority score. 0.5 = equal. "
                    "1.0 = pure heat ranking, 0.0 = pure vulnerability ranking."),
}
P_MIN_DENSITY = {
    "name": "min_density", "type": "float", "default": 3000, "minValue": 0,
    "description": ("Ignore grid cells with fewer than this many people per km2 nearby (parks, rail yards, industrial "
                    "land are hot but empty). Default 3000 (keeps out airports, rail yards, industrial land and parks)."),
}
P_SPACING = {
    "name": "spacing_cells", "type": "integer", "default": 5, "minValue": 1, "maxValue": 20,
    "description": ("Keep only the best cell per square block of this many grid cells (1 cell = ~330 m), so stops are "
                    "spread across the city instead of clustered. Default 5 = ~1.7 km apart."),
}
P_LAT = {"name": "latitude", "type": "float", "minValue": 41.0, "maxValue": 43.0,
         "description": "Latitude in decimal degrees (Chicago is about 41.6 to 42.1)."}
P_LON = {"name": "longitude", "type": "float", "minValue": -89.0, "maxValue": -87.0,
         "description": "Longitude in decimal degrees (Chicago is about -87.95 to -87.5)."}

# ----------------------------------------------------------------------------------------------
# Shared SQL: score every candidate cell with the model, then rank + space
# ----------------------------------------------------------------------------------------------
SCORED_SITES = f"""
WITH pred AS (
  -- LIVE model call over every candidate cell, measured or not. EXPLAIN_PREDICT returns the prediction
  -- AND per-feature attributions (degrees F contributed by each feature versus the average cell).
  SELECT *
  FROM ML.EXPLAIN_PREDICT(
    MODEL {MODEL},
    (SELECT * FROM {tbl('site_context')} WHERE pop_density_km2 >= @min_density),
    STRUCT(3 AS top_k_features))
),
scored AS (
  SELECT
    p.*,
    PERCENT_RANK() OVER (ORDER BY p.predicted_offset_f) AS heat_percentile,
    LEAST(IFNULL(p.km_to_cooling, 3), 3) / 3 AS access_gap
  FROM pred AS p
),
ranked AS (
  SELECT
    s.*,
    -- priority = (heat and vulnerability, blended by heat_weight) x (0.6 .. 1.0 by distance from indoor cooling)
    (@heat_weight * s.heat_percentile + (1 - @heat_weight) * s.vulnerability_index)
      * (0.6 + 0.4 * s.access_gap) AS priority_score
  FROM scored AS s
),
spaced AS (
  SELECT r.*
  FROM ranked AS r
  WHERE TRUE
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY CAST(FLOOR(r.lat_i / @spacing_cells) AS INT64), CAST(FLOOR(r.lon_i / @spacing_cells) AS INT64)
    ORDER BY r.priority_score DESC) = 1
)
"""

SITE_COLUMNS = """
  ROW_NUMBER() OVER (ORDER BY priority_score DESC) AS rank,
  cell_id,
  community_area AS neighborhood,
  ROUND(latitude, 5) AS latitude,
  ROUND(longitude, 5) AS longitude,
  tract_geo_id,
  ROUND(predicted_offset_f, 2) AS predicted_offset_f,
  ROUND(baseline_prediction_value, 2) AS average_cell_offset_f,
  ARRAY(SELECT AS STRUCT a.feature, ROUND(a.attribution, 2) AS contribution_f
        FROM UNNEST(top_feature_attributions) AS a ORDER BY ABS(a.attribution) DESC) AS why,
  ROUND(heat_percentile, 3) AS heat_percentile,
  ROUND(vulnerability_index, 3) AS vulnerability_index,
  ROUND(priority_score, 3) AS priority_score,
  CAST(ROUND(tract_pop) AS INT64) AS tract_population,
  CAST(ROUND(pop_65_plus) AS INT64) AS residents_65_plus,
  CAST(ROUND(no_car_households) AS INT64) AS households_without_car,
  ROUND(poverty_rate, 3) AS poverty_rate,
  ROUND(km_to_cooling, 2) AS km_to_indoor_cooling,
  nearest_cooling_name, nearest_cooling_type, nearest_cooling_address,
  nearest_library_name, nearest_library_address, nearest_library_hours,
  ROUND(km_to_library, 2) AS km_to_library,
  n_obs AS measured_readings,
  ROUND(offset_f, 2) AS measured_offset_f
"""


def clean(text: str) -> str:
    """Dedent and strip trailing spaces so PyYAML can emit a readable literal block (|)."""
    lines = [ln.rstrip() for ln in textwrap.dedent(text).strip().splitlines()]
    return "\n".join(lines) + "\n"


def tool(name: str, description: str, statement: str, parameters: list[dict]) -> dict:
    return {"kind": "tool", "name": name, "type": "bigquery-sql", "source": "heat-bq",
            "description": clean(description), "statement": clean(statement),
            "parameters": parameters}


def agg_block(label: str, src: str) -> str:
    """Population-weighted summary of a set of tracts (src has the tract_vulnerability columns)."""
    return f"""
  SELECT '{label}' AS group_name,
    COUNT(*) AS tracts,
    CAST(SUM(total_pop) AS INT64) AS population,
    ROUND(SAFE_DIVIDE(SUM(poverty_rate * total_pop), SUM(total_pop)), 3) AS poverty_rate,
    ROUND(SAFE_DIVIDE(SUM(no_vehicle_rate * total_pop), SUM(total_pop)), 3) AS households_without_car_rate,
    ROUND(SAFE_DIVIDE(SUM(pct_65_plus * total_pop), SUM(total_pop)), 3) AS share_65_plus,
    ROUND(SAFE_DIVIDE(SUM(median_income * total_pop), SUM(total_pop)), 0) AS median_income_pop_weighted,
    ROUND(AVG(vulnerability_index), 3) AS mean_vulnerability_index,
    ROUND(COUNTIF(vulnerability_index >= 0.75) / COUNT(*), 3) AS share_in_top_vulnerability_quartile
  FROM {src}"""


def build() -> list[dict]:
    docs: list[dict] = []
    docs.append({
        "kind": "source", "name": "heat-bq", "type": "bigquery",
        "project": "${GOOGLE_CLOUD_PROJECT}", "location": "${BQ_LOCATION:US}",
        "maxQueryResultRows": 200, "maximumBytesBilled": 10737418240,
    })

    docs.append(tool(
        "rank_priority_sites",
        """
        Ranks places across Chicago for emergency heat response TODAY (hydration trucks, cooling stops). Runs the BigQuery ML
        heat model (ML.EXPLAIN_PREDICT) live over every ~330 m grid cell, INCLUDING cells nobody ever measured, then combines
        predicted heat, who lives there (65+, no car, poverty) and distance from the nearest indoor cooling site.
        Returns the best cell per block so results are spread out. For each site: predicted_offset_f (degrees F hotter than
        the average Chicago spot on a hot day; add it to the forecast high, it is NOT a temperature), `why` (the model's
        per-feature contributions in degrees F), residents, and the nearest cooling site and library with hours.
        measured_readings = 0 means no Heat Watch car ever drove there: the number is a pure model prediction.
        """,
        f"{SCORED_SITES}\nSELECT {SITE_COLUMNS}\nFROM spaced\nORDER BY priority_score DESC\nLIMIT @limit",
        [p_limit(8), P_HEAT_WEIGHT, P_MIN_DENSITY, P_SPACING],
    ))

    docs.append(tool(
        "rank_wellness_check_tracts",
        """
        Ranks census tracts for door-to-door wellness checks. Averages the live ML.PREDICT heat prediction over each tract's
        grid cells and blends it with a vulnerability index (share 65+, households without a car, poverty). Returns people
        counts to size the visit list: residents_65_plus and households_without_car. Tract centroid coordinates are
        returned for mapping. Use for "who do we check on", not "where does the truck park" (use rank_priority_sites).
        """,
        f"""
WITH pred AS (
  SELECT * FROM ML.PREDICT(
    MODEL {MODEL},
    (SELECT * FROM {tbl('site_context')} WHERE pop_density_km2 >= @min_density))
),
tract AS (
  SELECT
    tract_geo_id,
    APPROX_TOP_COUNT(community_area, 1)[OFFSET(0)].value AS neighborhood,
    AVG(predicted_offset_f) AS predicted_offset_f,
    AVG(latitude) AS latitude, AVG(longitude) AS longitude,
    AVG(km_to_cooling) AS km_to_indoor_cooling,
    ANY_VALUE(tract_pop) AS tract_pop, ANY_VALUE(pop_65_plus) AS pop_65_plus,
    ANY_VALUE(households) AS households, ANY_VALUE(no_car_households) AS no_car_households,
    ANY_VALUE(poverty_rate) AS poverty_rate, ANY_VALUE(median_income) AS median_income,
    ANY_VALUE(vulnerability_index) AS vulnerability_index, COUNT(*) AS cells
  FROM pred
  GROUP BY tract_geo_id
),
ranked AS (
  SELECT t.*, PERCENT_RANK() OVER (ORDER BY t.predicted_offset_f) AS heat_percentile
  FROM tract AS t
)
SELECT
  ROW_NUMBER() OVER (ORDER BY priority_score DESC) AS rank,
  tract_geo_id, neighborhood,
  ROUND(latitude, 5) AS latitude, ROUND(longitude, 5) AS longitude,
  ROUND(predicted_offset_f, 2) AS predicted_offset_f,
  ROUND(heat_percentile, 3) AS heat_percentile,
  ROUND(vulnerability_index, 3) AS vulnerability_index,
  ROUND(priority_score, 3) AS priority_score,
  CAST(ROUND(tract_pop) AS INT64) AS tract_population,
  CAST(ROUND(pop_65_plus) AS INT64) AS residents_65_plus,
  CAST(ROUND(households) AS INT64) AS households,
  CAST(ROUND(no_car_households) AS INT64) AS households_without_car,
  ROUND(poverty_rate, 3) AS poverty_rate,
  ROUND(median_income, 0) AS median_income,
  ROUND(km_to_indoor_cooling, 2) AS avg_km_to_indoor_cooling
FROM (
  SELECT *, (@heat_weight * heat_percentile + (1 - @heat_weight) * vulnerability_index) AS priority_score
  FROM ranked
)
ORDER BY priority_score DESC
LIMIT @limit""",
        [p_limit(10), P_HEAT_WEIGHT, P_MIN_DENSITY],
    ))

    docs.append(tool(
        "predict_site_heat",
        """
        Explains the heat at ONE location: snaps the coordinates to the nearest ~330 m grid cell and runs ML.EXPLAIN_PREDICT.
        Returns predicted_offset_f (degrees F hotter than the average Chicago spot on a hot day) and `why`, the model's
        per-feature contributions in degrees F (lake and downtown distance, population density, housing age, share of buildings / green space / paved land / street), plus the
        raw feature values and who lives there. Use for "why is X so hot" or "how hot is this address". Works for places nobody
        measured. If snap_distance_m is over 600, the point is outside the modelled area: say so, do not report the number.
        measured_readings > 0 means Heat Watch drove there and measured_offset_f is the real reading to compare against.
        """,
        f"""
WITH target AS (
  SELECT *, ST_DISTANCE(ST_GEOGPOINT(longitude, latitude), ST_GEOGPOINT(@longitude, @latitude)) AS snap_distance_m
  FROM {tbl('site_context')}
  ORDER BY snap_distance_m
  LIMIT 1
)
SELECT
  cell_id, community_area AS neighborhood, ROUND(latitude, 5) AS cell_latitude, ROUND(longitude, 5) AS cell_longitude,
  ROUND(snap_distance_m, 0) AS snap_distance_m,
  ROUND(predicted_offset_f, 2) AS predicted_offset_f,
  ROUND(baseline_prediction_value, 2) AS average_cell_offset_f,
  ARRAY(SELECT AS STRUCT a.feature, ROUND(a.attribution, 2) AS contribution_f
        FROM UNNEST(top_feature_attributions) AS a ORDER BY ABS(a.attribution) DESC) AS why,
  ROUND(dist_to_lake_km, 2) AS km_to_lake, ROUND(dist_to_loop_km, 1) AS km_to_the_loop,
  ROUND(pop_density_km2, 0) AS people_per_km2, CAST(median_year_structure_built AS INT64) AS median_year_homes_built,
  ROUND(building_share, 3) AS building_share_300m, ROUND(green_share, 3) AS green_share_300m,
  ROUND(paved_use_share, 3) AS paved_use_share_300m, ROUND(road_km_per_km2, 1) AS road_km_per_km2,
  tract_geo_id, CAST(ROUND(tract_pop) AS INT64) AS tract_population,
  CAST(ROUND(pop_65_plus) AS INT64) AS residents_65_plus,
  CAST(ROUND(no_car_households) AS INT64) AS households_without_car,
  ROUND(poverty_rate, 3) AS poverty_rate, ROUND(vulnerability_index, 3) AS vulnerability_index,
  nearest_cooling_name, nearest_cooling_type, nearest_cooling_address, nearest_cooling_hours,
  ROUND(km_to_cooling, 2) AS km_to_indoor_cooling,
  nearest_library_name, nearest_library_address, nearest_library_hours, ROUND(km_to_library, 2) AS km_to_library,
  n_obs AS measured_readings, ROUND(offset_f, 2) AS measured_offset_f
FROM ML.EXPLAIN_PREDICT(MODEL {MODEL}, (SELECT * FROM target), STRUCT(4 AS top_k_features))""",
        [P_LAT, P_LON],
    ))

    docs.append(tool(
        "who_lives_near",
        """
        Who lives around a point: total residents, residents 65+, households without a car, poverty rate and median income,
        summed over census tracts whose centre lies within radius_m. ACS 5-year estimates, tract level: a tract is counted
        whole, so treat the totals as the neighbourhood, not an exact circle.
        """,
        f"""
SELECT
  COUNT(*) AS tracts_counted,
  CAST(SUM(total_pop) AS INT64) AS residents,
  CAST(SUM(pop_65_plus) AS INT64) AS residents_65_plus,
  CAST(SUM(no_car_households) AS INT64) AS households_without_car,
  CAST(SUM(households) AS INT64) AS households,
  ROUND(SAFE_DIVIDE(SUM(poverty_rate * total_pop), SUM(total_pop)), 3) AS poverty_rate,
  ROUND(SAFE_DIVIDE(SUM(median_income * total_pop), SUM(total_pop)), 0) AS median_income_pop_weighted,
  ROUND(AVG(vulnerability_index), 3) AS mean_vulnerability_index
FROM {tbl('tract_vulnerability')}
WHERE ST_DWITHIN(ST_GEOGPOINT(tract_lon, tract_lat), ST_GEOGPOINT(@longitude, @latitude), @radius_m)""",
        [P_LAT, P_LON, {"name": "radius_m", "type": "integer", "default": 800, "minValue": 200, "maxValue": 5000,
                        "description": "Search radius in metres around the point (default 800)."}],
    ))

    docs.append(tool(
        "nearest_cooling_facilities",
        """
        City of Chicago cooling sites nearest a point, with address and hours (City of Chicago Cooling Centers dataset, a
        point-in-time snapshot: always tell the user to confirm hours). facility_type 'any' returns indoor sites only
        (libraries, senior centers, community colleges, community service centers, police districts). Other values:
        'Library', 'Satellite Senior Center', 'Regional Senior Center', 'Chicago Community College',
        'Community Service Center', 'Police District', 'Park District Facility', 'Park District Spray Feature'.
        Use this for extended library hours: facility_type = 'Library'.
        """,
        f"""
SELECT
  facility_type, site_name, address, zip, phone, hours_of_operation, is_indoor,
  ROUND(latitude, 5) AS latitude, ROUND(longitude, 5) AS longitude,
  ROUND(ST_DISTANCE(ST_GEOGPOINT(longitude, latitude), ST_GEOGPOINT(@longitude, @latitude)) / 1000, 2) AS km_away
FROM {tbl('cooling_facilities')}
WHERE (@facility_type = 'any' AND is_indoor) OR facility_type = @facility_type
ORDER BY km_away
LIMIT @limit""",
        [P_LAT, P_LON,
         {"name": "facility_type", "type": "string", "default": "any",
          "description": "'any' (indoor sites only) or one exact facility type, e.g. 'Library'."},
         p_limit(5, 15)],
    ))

    docs.append(tool(
        "heat_frequency",
        """
        How often Chicago-area weather stations reached a temperature, by year, May-September, from NOAA GHCN-Daily
        (daily station maxima, about seven years). The daily value is the average TMAX of the reporting stations. Use it to
        say how unusual a forecast is ("102F or hotter happened N days in 7 summers") and whether it is getting more common.
        The street-level Heat Watch data is ONE day and cannot answer frequency questions; this can.
        """,
        f"""
WITH daily AS (
  SELECT observation_date, AVG(max_temp_f) AS city_high_f
  FROM {tbl('station_daily_temps')}
  WHERE max_temp_f IS NOT NULL
  GROUP BY observation_date
)
SELECT
  EXTRACT(YEAR FROM observation_date) AS year,
  COUNT(*) AS summer_days_reported,
  COUNTIF(city_high_f >= @threshold_f) AS days_at_or_above_threshold,
  ROUND(MAX(city_high_f), 1) AS hottest_day_f,
  ROUND(AVG(city_high_f), 1) AS mean_summer_high_f,
  SUM(COUNTIF(city_high_f >= @threshold_f)) OVER () AS total_days_all_years,
  COUNT(*) OVER () AS years_covered
FROM daily
WHERE EXTRACT(MONTH FROM observation_date) BETWEEN 5 AND 9
GROUP BY year
ORDER BY year""",
        [{"name": "threshold_f", "type": "float", "default": 95, "minValue": 70, "maxValue": 120,
          "description": "Temperature in degrees F to count days at or above (default 95)."}],
    ))

    docs.append(tool(
        "equity_audit",
        f"""
        Audits the OUTPUT of rank_priority_sites. Takes the same top-N recommended sites (same parameters, so pass the same
        values you used for the ranking) and compares the people living in those tracts with the whole modelled city:
        poverty rate, households without a car, share 65+, income, mean vulnerability index, and the share of tracts in the
        top vulnerability quartile. Returns two rows, 'recommended_sites' and 'citywide'. Race is NOT in the model and NOT in
        this table; the audit compares the vulnerabilities the Today track cares about. Report the result whether or not it
        flatters the recommendations.
        """,
        f"""{SCORED_SITES.rstrip()},
top AS (
  SELECT * FROM spaced ORDER BY priority_score DESC LIMIT @limit
),
modelled AS (
  SELECT v.* FROM {tbl('tract_vulnerability')} AS v
  WHERE v.geo_id IN (SELECT DISTINCT tract_geo_id FROM {tbl('site_context')})
),
picked AS (
  SELECT m.* FROM modelled AS m WHERE m.geo_id IN (SELECT tract_geo_id FROM top)
)
{agg_block('recommended_sites', 'picked')}
UNION ALL
{agg_block('citywide', 'modelled')}""",
        [p_limit(8), P_HEAT_WEIGHT, P_MIN_DENSITY, P_SPACING],
    ))

    docs.append(tool(
        "model_card",
        f"""
        How good the heat model really is: ML.EVALUATE on spatially held-out city blocks the model never saw, next to a naive
        'always predict the city average' baseline. Use it to answer "how much should I trust this" and to state limits. If
        the model's r2 is low, say so plainly; the training data is a single volunteer-driven afternoon.
        """,
        f"""
WITH holdout AS (
  SELECT * FROM {tbl('site_context')} WHERE n_obs >= {MIN_OBS} AND is_holdout AND offset_f IS NOT NULL
)
SELECT 'model on held-out blocks' AS what, ROUND(mean_absolute_error, 2) AS mean_abs_error_f,
       ROUND(SQRT(mean_squared_error), 2) AS rmse_f, ROUND(r2_score, 3) AS r2_score,
       (SELECT COUNT(*) FROM holdout) AS cells_evaluated
FROM ML.EVALUATE(MODEL {MODEL}, (SELECT * FROM holdout))
UNION ALL
SELECT 'baseline: always predict the city average', ROUND(AVG(ABS(offset_f)), 2),
       ROUND(SQRT(AVG(POW(offset_f, 2))), 2), 0.0, COUNT(*)
FROM holdout""",
        [],
    ))

    docs.append(tool(
        "model_global_importance",
        """
        Which features the heat model leans on overall (ML.GLOBAL_EXPLAIN), as mean absolute contribution in degrees F.
        Use to explain what drives heat across Chicago, as opposed to one site.
        """,
        f"SELECT feature, ROUND(attribution, 3) AS mean_abs_contribution_f\nFROM ML.GLOBAL_EXPLAIN(MODEL {MODEL})\nORDER BY attribution DESC",
        [],
    ))

    names = [d["name"] for d in docs if d["kind"] == "tool"]
    docs.append({"kind": "toolset", "name": "heat_dispatch", "tools": names})
    return docs


class _Dumper(yaml.SafeDumper):
    pass


def _str(dumper: yaml.SafeDumper, data: str):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|" if "\n" in data else None)


_Dumper.add_representer(str, _str)
HEADER = ("# GENERATED by toolbox/build_tools_yaml.py. Edit that file, then re-run it. Do not edit by hand.\n"
          "# Dollar-brace placeholders (project, dataset, location) are resolved by scripts/render_toolbox.py before deploy.\n")


def render() -> str:
    body = "---\n".join(yaml.dump(d, Dumper=_Dumper, sort_keys=False, width=120, allow_unicode=True) for d in build())
    return HEADER + body


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    text = render()
    if args.check:
        if not OUT.exists() or OUT.read_text() != text:
            print("toolbox/tools.yaml is out of date: run python toolbox/build_tools_yaml.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text)
    print(f"wrote {OUT.relative_to(HERE.parent)} ({len(build()) - 2} tools)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
