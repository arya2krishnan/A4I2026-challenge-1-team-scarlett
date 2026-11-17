-- Enrichment: multi-summer Landsat land surface temperature (LST) per grid cell.
--
-- Rendered and run by scripts/enrich_surface_temp.py (not part of the 01..06 model pipeline).
-- {{SCENE_IDS}} is a SQL array of Earth Engine asset ids chosen by that script's --probe step, e.g.
--   ['LANDSAT/LC08/C02/T1_L2/LC08_023031_20200705', ...]
--
-- For each grid cell x scene, BigQuery's ST_REGIONSTATS reads the Earth Engine image over the cell polygon
-- (cell bounds = lat_i*LAT_STEP .. (lat_i+1)*LAT_STEP, same FLOOR mapping as sql/01_grid_cells.sql):
--   ST_B10   raw DN; Kelvin = DN * 0.00341802 + 149.0 (USGS Collection 2 Level-2 scale/offset), then °F.
--   QA_PIXEL per-cell min/max decide "clear": every pixel must be 21824 (clear land) .. 21952 (clear water)
--            with low cloud/shadow/cirrus confidence. Any cloud, dilated cloud, shadow, or medium/high cloud
--            confidence bit pushes min below 21824 or max above 21956, so the cell is dropped for that scene.
--            Water fraction = (mean QA - 21824) / 128 on clear cells (bit 7 = water).
-- Offset = cell LST minus the mean over that scene's clear, mostly-land cells (water_frac < 0.5), so
-- day-to-day weather cancels and only the spatial pattern is kept.

CREATE OR REPLACE TABLE `{{PROJECT}}.{{DATASET}}.cell_surface_temp_scenes`
OPTIONS (description = "Landsat 8/9 C2 L2 surface temperature (ST_B10) per grid cell per clear summer scene; see docs/sources/surface_temperature.md")
AS
WITH
scenes AS (
  SELECT
    asset,
    REGEXP_EXTRACT(asset, r'[^/]+$') AS scene_id,
    PARSE_DATE('%Y%m%d', REGEXP_EXTRACT(asset, r'_(\d{8})$')) AS acquired_date,
    CONCAT('ee://', asset) AS ee_id
  FROM UNNEST({{SCENE_IDS}}) AS asset
),
cells AS (
  SELECT
    cell_id, lat_i, lon_i,
    ST_GEOGFROMTEXT(FORMAT('POLYGON((%f %f, %f %f, %f %f, %f %f, %f %f))',
      lon_i * {{LON_STEP}},       lat_i * {{LAT_STEP}},
      (lon_i + 1) * {{LON_STEP}}, lat_i * {{LAT_STEP}},
      (lon_i + 1) * {{LON_STEP}}, (lat_i + 1) * {{LAT_STEP}},
      lon_i * {{LON_STEP}},       (lat_i + 1) * {{LAT_STEP}},
      lon_i * {{LON_STEP}},       lat_i * {{LAT_STEP}})) AS cell_geom
  FROM `{{PROJECT}}.{{DATASET}}.grid_cells`
),
raw AS (
  SELECT
    c.cell_id, c.lat_i, c.lon_i, s.scene_id, s.acquired_date,
    ST_REGIONSTATS(c.cell_geom, s.ee_id, 'ST_B10')   AS st,
    ST_REGIONSTATS(c.cell_geom, s.ee_id, 'QA_PIXEL') AS qa
  FROM cells AS c CROSS JOIN scenes AS s
),
cell_scene AS (
  SELECT
    cell_id, lat_i, lon_i, scene_id, acquired_date,
    CAST(st.count AS INT64) AS n_pixels,
    (qa.min >= 21824 AND qa.max <= 21956 AND st.min > 0) AS is_clear,
    IF(qa.min >= 21824 AND qa.max <= 21956, LEAST(GREATEST((qa.mean - 21824) / 128, 0), 1), NULL) AS water_frac,
    IF(qa.min >= 21824 AND qa.max <= 21956 AND st.min > 0,
       ((st.mean * 0.00341802 + 149.0) - 273.15) * 9 / 5 + 32, NULL) AS lst_f,
    IF(qa.min >= 21824 AND qa.max <= 21956 AND st.min > 0, st.stdDev * 0.00341802 * 9 / 5, NULL) AS lst_within_cell_sd_f
  FROM raw
),
scene_mean AS (
  SELECT scene_id,
         AVG(lst_f) AS city_mean_lst_f,
         COUNTIF(is_clear) / COUNT(*) AS scene_clear_frac
  FROM cell_scene
  GROUP BY scene_id
),
scene_land_mean AS (
  SELECT scene_id, AVG(lst_f) AS city_land_mean_lst_f
  FROM cell_scene
  WHERE is_clear AND water_frac < 0.5
  GROUP BY scene_id
)
SELECT
  cs.cell_id, cs.lat_i, cs.lon_i, cs.scene_id, cs.acquired_date,
  cs.is_clear, cs.n_pixels, cs.water_frac,
  cs.lst_f, cs.lst_within_cell_sd_f,
  l.city_land_mean_lst_f AS city_mean_lst_f,   -- mean of clear cells with water_frac < 0.5 in this scene
  m.scene_clear_frac,
  cs.lst_f - l.city_land_mean_lst_f AS lst_offset_f
FROM cell_scene AS cs
JOIN scene_mean AS m USING (scene_id)
JOIN scene_land_mean AS l USING (scene_id);

CREATE OR REPLACE TABLE `{{PROJECT}}.{{DATASET}}.cell_surface_temp`
OPTIONS (description = "Per-cell multi-summer Landsat LST offset (median over clear scenes); see docs/sources/surface_temperature.md")
AS
SELECT
  g.cell_id, g.lat_i, g.lon_i,
  COUNTIF(s.is_clear) AS n_scenes,
  p.med AS lst_offset_f,
  p.q25 AS lst_offset_q25_f,
  p.q75 AS lst_offset_q75_f,
  p.q75 - p.q25 AS lst_offset_iqr_f,
  STDDEV(s.lst_offset_f) AS lst_offset_sd_f,
  AVG(s.lst_offset_f) AS lst_offset_mean_f,
  AVG(s.lst_f) AS lst_mean_f,
  AVG(s.water_frac) AS water_frac,
  MIN(IF(s.is_clear, EXTRACT(YEAR FROM s.acquired_date), NULL)) AS first_year,
  MAX(IF(s.is_clear, EXTRACT(YEAR FROM s.acquired_date), NULL)) AS last_year
FROM `{{PROJECT}}.{{DATASET}}.grid_cells` AS g
LEFT JOIN `{{PROJECT}}.{{DATASET}}.cell_surface_temp_scenes` AS s USING (cell_id)
LEFT JOIN (
  SELECT DISTINCT cell_id,
    PERCENTILE_CONT(lst_offset_f, 0.5)  OVER (PARTITION BY cell_id) AS med,
    PERCENTILE_CONT(lst_offset_f, 0.25) OVER (PARTITION BY cell_id) AS q25,
    PERCENTILE_CONT(lst_offset_f, 0.75) OVER (PARTITION BY cell_id) AS q75
  FROM `{{PROJECT}}.{{DATASET}}.cell_surface_temp_scenes`
  WHERE is_clear
) AS p USING (cell_id)
GROUP BY g.cell_id, g.lat_i, g.lon_i, p.med, p.q25, p.q75;
