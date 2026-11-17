-- v2 candidate inputs (NOT part of the 01..06 pipeline; the live site_context / heat_offset_model are untouched).
--
-- site_context_lst = site_context + three new kinds of input for the "how hot it feels" layer
-- (docs/specs/2026-11-17-heat-layers-design.md, Layer 1):
--   trend_*               coarse location trend: km north/east of a city-centre reference, their squares and product
--   surface_heat_f        Landsat surface-temperature offset (°F, SURFACE not air), mean over the cell and its 8
--                         neighbours (cell_surface_temp; held-out Pearson 0.48 vs 0.42 for the cell alone); 0 if none
--   impervious_pct_300m   NLCD 2021 imperviousness within 300 m (cell_land_cover)
--   tree_canopy_pct_300m  NLCD 2021 tree canopy within 300 m (cell_land_cover)
-- A VIEW, so it always reflects the current site_context. Additive only: every site_context column is kept.

CREATE OR REPLACE VIEW `{{PROJECT}}.{{DATASET}}.site_context_lst` AS
WITH lst3 AS (
  SELECT c.cell_id, AVG(n.lst_offset_f) AS lst_offset_3x3_f
  FROM `{{PROJECT}}.{{DATASET}}.site_context` AS c
  JOIN `{{PROJECT}}.{{DATASET}}.cell_surface_temp` AS n
    ON n.lat_i BETWEEN c.lat_i - 1 AND c.lat_i + 1
   AND n.lon_i BETWEEN c.lon_i - 1 AND c.lon_i + 1
  WHERE n.lst_offset_f IS NOT NULL
  GROUP BY c.cell_id
),
base AS (
  SELECT s.*,
    (s.latitude - ({{TREND_LAT0}})) * {{KM_PER_DEG_LAT}} AS trend_lat_km,
    (s.longitude - ({{TREND_LON0}})) * {{KM_PER_DEG_LON}} AS trend_lon_km
  FROM `{{PROJECT}}.{{DATASET}}.site_context` AS s
)
SELECT
  b.*,
  POW(b.trend_lat_km, 2) AS trend_lat2,
  POW(b.trend_lon_km, 2) AS trend_lon2,
  b.trend_lat_km * b.trend_lon_km AS trend_latlon,
  IFNULL(l.lst_offset_3x3_f, 0) AS surface_heat_f,
  IFNULL(lc.impervious_pct_300m, 0) AS impervious_pct_300m,
  IFNULL(lc.tree_canopy_pct_300m, 0) AS tree_canopy_pct_300m
FROM base AS b
LEFT JOIN lst3 AS l USING (cell_id)
LEFT JOIN `{{PROJECT}}.{{DATASET}}.cell_land_cover` AS lc USING (cell_id);
