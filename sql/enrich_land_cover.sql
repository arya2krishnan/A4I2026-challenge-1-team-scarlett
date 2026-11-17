-- Enrichment (not part of the 01..06 pipeline): per-grid-cell land cover from NLCD 2021 via Earth Engine.
--
-- Builds `cell_land_cover`, one row per `grid_cells` row, with two things a city can change:
--   impervious_pct   mean NLCD 2021 percent developed imperviousness (30 m pixels, 0-100)
--   tree_canopy_pct  mean NLCD/USFS Tree Canopy Cover 2021 (TCC v2021-4, NLCD product, 30 m pixels, 0-100)
-- each measured twice: over the cell rectangle itself, and over a disc of OSM_RADIUS_M around the cell centre
-- (the same radius the OSM features in 01 use), because air temperature responds to the surroundings.
--
-- Cell geometry matches 01_grid_cells.sql: lat_i = FLOOR(lat / LAT_STEP), so the cell spans
-- [lat_i, lat_i+1) * LAT_STEP by [lon_i, lon_i+1) * LON_STEP, and latitude/longitude are the centre.
--
-- ST_REGIONSTATS reads the raster in Earth Engine (the API must be enabled on the project). Masked pixels would be
-- excluded from the mean; *_px (area-weighted pixel counts) show how much of the area was usable. On the
-- 2026-11-17 run no Chicago cell had masked pixels: open water reads 0 for both layers.
-- Runs in ~20 s for 5,053 cells. Read-only on grid_cells; writes only cell_land_cover.

CREATE OR REPLACE TABLE `{{PROJECT}}.{{DATASET}}.cell_land_cover` AS
WITH cells AS (
  SELECT
    cell_id, lat_i, lon_i,
    ST_GEOGFROMTEXT(FORMAT('POLYGON((%f %f, %f %f, %f %f, %f %f, %f %f))',
      lon_i * {{LON_STEP}},       lat_i * {{LAT_STEP}},
      (lon_i + 1) * {{LON_STEP}}, lat_i * {{LAT_STEP}},
      (lon_i + 1) * {{LON_STEP}}, (lat_i + 1) * {{LAT_STEP}},
      lon_i * {{LON_STEP}},       (lat_i + 1) * {{LAT_STEP}},
      lon_i * {{LON_STEP}},       lat_i * {{LAT_STEP}})) AS cell_poly,
    ST_BUFFER(ST_GEOGPOINT(longitude, latitude), {{OSM_RADIUS_M}}) AS buf_poly
  FROM `{{PROJECT}}.{{DATASET}}.grid_cells`
),
stats AS (
  SELECT
    cell_id, lat_i, lon_i,
    ST_REGIONSTATS(cell_poly, 'ee://USGS/NLCD_RELEASES/2021_REL/NLCD/2021', 'impervious') AS imp,
    ST_REGIONSTATS(cell_poly, 'ee://USGS/NLCD_RELEASES/2021_REL/TCC/v2021-4/TCC_v2021-4_CONUS_2021',
                   'NLCD_Percent_Tree_Canopy_Cover') AS tcc,
    ST_REGIONSTATS(buf_poly, 'ee://USGS/NLCD_RELEASES/2021_REL/NLCD/2021', 'impervious') AS imp_b,
    ST_REGIONSTATS(buf_poly, 'ee://USGS/NLCD_RELEASES/2021_REL/TCC/v2021-4/TCC_v2021-4_CONUS_2021',
                   'NLCD_Percent_Tree_Canopy_Cover') AS tcc_b
  FROM cells
)
SELECT
  cell_id, lat_i, lon_i,
  ROUND(imp.mean, 2)   AS impervious_pct,
  ROUND(tcc.mean, 2)   AS tree_canopy_pct,
  ROUND(imp_b.mean, 2) AS impervious_pct_300m,
  ROUND(tcc_b.mean, 2) AS tree_canopy_pct_300m,
  CAST(imp.count AS INT64)   AS impervious_px,
  CAST(tcc.count AS INT64)   AS tree_canopy_px,
  CAST(imp_b.count AS INT64) AS impervious_px_300m,
  CAST(tcc_b.count AS INT64) AS tree_canopy_px_300m,
  'USGS NLCD 2021 (2021_REL) percent developed imperviousness; ee://USGS/NLCD_RELEASES/2021_REL/NLCD/2021 band impervious' AS source_impervious,
  'USFS/NLCD Tree Canopy Cover v2021-4, NLCD product; ee://USGS/NLCD_RELEASES/2021_REL/TCC/v2021-4/TCC_v2021-4_CONUS_2021 band NLCD_Percent_Tree_Canopy_Cover' AS source_canopy,
  2021 AS vintage,
  {{OSM_RADIUS_M}} AS buffer_radius_m,
  CURRENT_TIMESTAMP() AS computed_at
FROM stats;
