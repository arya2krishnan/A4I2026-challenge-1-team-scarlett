-- 03  Everything the agent needs about a grid cell, in one table.
--
-- grid_cells (physical features + measured offset) + tract_vulnerability (who lives there)
-- + the nearest INDOOR cooling facility and nearest library (City of Chicago "Cooling Centers"
-- dataset, loaded by scripts/load_chicago_facilities.py). Spray features and park facilities
-- are outdoors or not guaranteed air-conditioned, so they do not count as indoor cooling.
--
-- "km_to_cooling" is the access gap: how far a resident of a hot cell must go to get indoors.

CREATE OR REPLACE TABLE `{{PROJECT}}.{{DATASET}}.site_context` AS
WITH
fac AS (
  SELECT *, ST_GEOGPOINT(longitude, latitude) AS fpt
  FROM `{{PROJECT}}.{{DATASET}}.cooling_facilities`
),
cells AS (
  SELECT g.*, ST_GEOGPOINT(g.longitude, g.latitude) AS pt
  FROM `{{PROJECT}}.{{DATASET}}.grid_cells` AS g
),
nearest_cool AS (
  SELECT c.cell_id,
    ARRAY_AGG(STRUCT(f.site_name, f.facility_type, f.address, f.hours_of_operation,
                     ST_DISTANCE(c.pt, f.fpt) / 1000 AS km)
              ORDER BY ST_DISTANCE(c.pt, f.fpt) LIMIT 1)[OFFSET(0)] AS best
  FROM cells AS c CROSS JOIN fac AS f
  WHERE f.is_indoor
  GROUP BY c.cell_id
),
nearest_lib AS (
  SELECT c.cell_id,
    ARRAY_AGG(STRUCT(f.site_name, f.address, f.hours_of_operation,
                     ST_DISTANCE(c.pt, f.fpt) / 1000 AS km)
              ORDER BY ST_DISTANCE(c.pt, f.fpt) LIMIT 1)[OFFSET(0)] AS best
  FROM cells AS c CROSS JOIN fac AS f
  WHERE f.facility_type = 'Library'
  GROUP BY c.cell_id
)
SELECT
  g.cell_id, g.lat_i, g.lon_i, g.latitude, g.longitude, g.community_area, g.tract_geo_id,
  g.dist_to_lake_km, g.dist_to_loop_km, g.pop_density_km2, g.median_year_structure_built,
  g.building_share, g.green_share, g.paved_use_share, g.road_km_per_km2,
  g.offset_f, g.n_obs, g.is_holdout,
  v.total_pop AS tract_pop, v.pop_65_plus, v.pct_65_plus, v.households, v.no_car_households,
  v.no_vehicle_rate, v.poverty_rate, v.median_income, v.median_age, v.vulnerability_index,
  nc.best.site_name AS nearest_cooling_name, nc.best.facility_type AS nearest_cooling_type,
  nc.best.address AS nearest_cooling_address, nc.best.hours_of_operation AS nearest_cooling_hours,
  nc.best.km AS km_to_cooling,
  nl.best.site_name AS nearest_library_name, nl.best.address AS nearest_library_address,
  nl.best.hours_of_operation AS nearest_library_hours, nl.best.km AS km_to_library
FROM `{{PROJECT}}.{{DATASET}}.grid_cells` AS g
JOIN `{{PROJECT}}.{{DATASET}}.tract_vulnerability` AS v ON v.geo_id = g.tract_geo_id
LEFT JOIN nearest_cool AS nc USING (cell_id)
LEFT JOIN nearest_lib  AS nl USING (cell_id);
