-- 01  Grid cells: the unit the model learns from AND the unit it predicts for.
--
-- Chicago's Heat Watch campaign is ~49k readings driven along fixed routes. We snap them to a
-- ~330 m grid (LAT_STEP x LON_STEP degrees). A cell that was driven has a MEASURED offset
-- (cell mean minus campaign mean). A cell nobody drove through is still a candidate: that is
-- the whole point, the agent must answer for places that were never measured.
--
-- The target is the OFFSET (degrees F hotter than the campaign average), not a temperature.
-- Features are PHYSICAL ONLY (lake, downtown, density, building age, and OpenStreetMap land cover within OSM_RADIUS_M:
-- roof area, parks/trees, industrial/parking land, street length). Demographics are kept out
-- of the model on purpose: they are layered on afterwards (02/03) and audited at the end, so the
-- audit is not circular ("it found poor tracts because we fed it income").
--
-- Spatial hold-out: cells are grouped into BLOCK x BLOCK superblocks (~2.7 km); ~20% of
-- superblocks (by hash) are held out whole. A random row split would leak, because neighbouring
-- cells share a temperature.

CREATE OR REPLACE TABLE `{{PROJECT}}.{{DATASET}}.grid_cells` AS
WITH
obs AS (
  SELECT
    CAST(FLOOR(latitude  / {{LAT_STEP}}) AS INT64) AS lat_i,
    CAST(FLOOR(longitude / {{LON_STEP}}) AS INT64) AS lon_i,
    temp_f - AVG(temp_f) OVER () AS offset_f
  FROM `{{PROJECT}}.{{DATASET}}.heat_observations`
  WHERE temp_f IS NOT NULL AND latitude IS NOT NULL AND longitude IS NOT NULL
),
measured AS (
  SELECT lat_i, lon_i, AVG(offset_f) AS offset_f, COUNT(*) AS n_obs
  FROM obs
  GROUP BY lat_i, lon_i
),
bounds AS (
  SELECT
    MIN(lat_i) - {{CAND_RADIUS_CELLS}} AS lat_lo, MAX(lat_i) + {{CAND_RADIUS_CELLS}} AS lat_hi,
    MIN(lon_i) - {{CAND_RADIUS_CELLS}} AS lon_lo, MAX(lon_i) + {{CAND_RADIUS_CELLS}} AS lon_hi
  FROM measured
),
all_cells AS (
  SELECT lat_i, lon_i
  FROM bounds,
       UNNEST(GENERATE_ARRAY(lat_lo, lat_hi)) AS lat_i,
       UNNEST(GENERATE_ARRAY(lon_lo, lon_hi)) AS lon_i
),
-- candidates: driven cells plus anything within CAND_RADIUS_CELLS of a driven cell
near_driven AS (
  SELECT DISTINCT a.lat_i, a.lon_i
  FROM all_cells AS a
  JOIN measured AS m
    ON ABS(m.lat_i - a.lat_i) <= {{CAND_RADIUS_CELLS}}
   AND ABS(m.lon_i - a.lon_i) <= {{CAND_RADIUS_CELLS}}
),
lake AS (
  SELECT ST_GEOGFROMTEXT('{{LAKE_POLY_WKT}}') AS water,
         ST_GEOGFROMTEXT('{{LAKE_LINE_WKT}}') AS shore
),
cand_all AS (
  SELECT
    n.lat_i, n.lon_i,
    (n.lat_i + 0.5) * {{LAT_STEP}} AS latitude,
    (n.lon_i + 0.5) * {{LON_STEP}} AS longitude,
    ST_GEOGPOINT((n.lon_i + 0.5) * {{LON_STEP}}, (n.lat_i + 0.5) * {{LAT_STEP}}) AS pt
  FROM near_driven AS n
  CROSS JOIN lake
  WHERE NOT ST_INTERSECTS(lake.water, ST_GEOGPOINT((n.lon_i + 0.5) * {{LON_STEP}}, (n.lat_i + 0.5) * {{LAT_STEP}}))
),
-- clip to the City of Chicago: the driven footprint also covers inner suburbs (Berwyn, Cicero...) where a
-- Chicago dispatcher cannot send a truck. Each cell also gets its community-area (neighbourhood) name.
cand AS (
  SELECT c.*, a.community AS community_area
  FROM cand_all AS c
  JOIN `{{PROJECT}}.{{DATASET}}.community_areas` AS a ON ST_INTERSECTS(a.geom, c.pt)
  WHERE TRUE
  QUALIFY ROW_NUMBER() OVER (PARTITION BY c.lat_i, c.lon_i ORDER BY a.area_number) = 1
),
tracts AS (
  SELECT
    geo_id, total_pop, median_year_structure_built,
    ST_GEOGPOINT(tract_lon, tract_lat) AS tpt
  FROM `{{PROJECT}}.{{DATASET}}.tract_demographics`
  WHERE tract_lat IS NOT NULL AND tract_lon IS NOT NULL AND total_pop > 0
),
nearest_tract AS (
  SELECT
    c.lat_i, c.lon_i,
    ARRAY_AGG(STRUCT(t.geo_id AS tract_geo_id,
                     ST_DISTANCE(c.pt, t.tpt) AS d_m,
                     t.median_year_structure_built AS yr_built)
              ORDER BY ST_DISTANCE(c.pt, t.tpt) LIMIT 1)[OFFSET(0)] AS best
  FROM cand AS c
  CROSS JOIN tracts AS t
  GROUP BY c.lat_i, c.lon_i
),
density AS (
  -- people per km2 around the cell: population of tracts whose centroid lies within the radius.
  -- Coarse (a tract's people are placed at its centroid) but it needs no extra data.
  SELECT
    c.lat_i, c.lon_i,
    SUM(t.total_pop) / (ACOS(-1) * POW({{DENSITY_RADIUS_KM}}, 2)) AS pop_density_km2
  FROM cand AS c
  JOIN tracts AS t ON ST_DWITHIN(c.pt, t.tpt, {{DENSITY_RADIUS_KM}} * 1000)
  GROUP BY c.lat_i, c.lon_i
),
osm AS (
  -- built-environment mix around each cell. A feature counts toward a cell if its centroid is within OSM_RADIUS_M
  -- (an approximation: no polygon clipping, which would be far slower and barely more accurate at this scale).
  SELECT
    c.lat_i, c.lon_i,
    LEAST(1.0, SAFE_DIVIDE(SUM(IF(o.kind = 'building',  o.size_m, 0)), ACOS(-1) * POW({{OSM_RADIUS_M}}, 2))) AS building_share,
    LEAST(1.0, SAFE_DIVIDE(SUM(IF(o.kind = 'green',     o.size_m, 0)), ACOS(-1) * POW({{OSM_RADIUS_M}}, 2))) AS green_share,
    LEAST(1.0, SAFE_DIVIDE(SUM(IF(o.kind = 'paved_use', o.size_m, 0)), ACOS(-1) * POW({{OSM_RADIUS_M}}, 2))) AS paved_use_share,
    SAFE_DIVIDE(SUM(IF(o.kind = 'road', o.size_m, 0)) / 1000, ACOS(-1) * POW({{OSM_RADIUS_M}} / 1000, 2)) AS road_km_per_km2
  FROM cand AS c
  JOIN `{{PROJECT}}.{{DATASET}}.osm_chicago` AS o ON ST_DWITHIN(c.pt, o.centroid, {{OSM_RADIUS_M}})
  GROUP BY c.lat_i, c.lon_i
),
median_year AS (
  SELECT APPROX_QUANTILES(median_year_structure_built, 2)[OFFSET(1)] AS yr FROM tracts
)
SELECT
  FORMAT('%d_%d', c.lat_i, c.lon_i) AS cell_id,
  c.lat_i, c.lon_i, c.latitude, c.longitude, c.community_area,
  nt.best.tract_geo_id AS tract_geo_id,
  nt.best.d_m AS tract_dist_m,
  ST_DISTANCE(c.pt, lake.shore) / 1000 AS dist_to_lake_km,
  ST_DISTANCE(c.pt, ST_GEOGPOINT({{LOOP_LON}}, {{LOOP_LAT}})) / 1000 AS dist_to_loop_km,
  COALESCE(d.pop_density_km2, 0) AS pop_density_km2,
  COALESCE(nt.best.yr_built, my.yr) AS median_year_structure_built,
  COALESCE(o.building_share, 0) AS building_share,
  COALESCE(o.green_share, 0) AS green_share,
  COALESCE(o.paved_use_share, 0) AS paved_use_share,
  COALESCE(o.road_km_per_km2, 0) AS road_km_per_km2,
  m.offset_f,
  COALESCE(m.n_obs, 0) AS n_obs,
  MOD(ABS(FARM_FINGERPRINT(CONCAT(
        CAST(CAST(FLOOR(c.lat_i / {{BLOCK}}) AS INT64) AS STRING), '_',
        CAST(CAST(FLOOR(c.lon_i / {{BLOCK}}) AS INT64) AS STRING)))), 5) = 0 AS is_holdout
FROM cand AS c
CROSS JOIN lake
CROSS JOIN median_year AS my
JOIN nearest_tract AS nt USING (lat_i, lon_i)
LEFT JOIN density AS d USING (lat_i, lon_i)
LEFT JOIN osm AS o USING (lat_i, lon_i)
LEFT JOIN measured AS m USING (lat_i, lon_i)
WHERE nt.best.d_m <= {{MAX_TRACT_DIST_M}};
