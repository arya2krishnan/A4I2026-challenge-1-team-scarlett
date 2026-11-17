-- Enriched context + the v2 model's extra inputs, so heat_offset_lst can score the corrected data.
--
-- site_context_enriched (a4i_climate_work_v2, built by sql/enrichment/03_site_context.sql) already carries the
-- grid, label, NLCD land cover (impervious_pct_300m, tree_canopy_pct_300m) and per-cell Landsat lst_offset_f, plus
-- corrected ACS 2024 vulnerability and event-verified cooling sites. It lacks only the two derived v2 inputs, added
-- here exactly as in sql/v2/10_site_context_lst.sql:
--   trend_*         location trend (km from the city-centre reference, squares, product)
--   surface_heat_f  Landsat surface offset averaged over the cell and its 8 neighbours (0 if none)
-- Land-cover nulls become 0 as in site_context_lst. Written to the work dataset; the live site_context_lst is untouched.

CREATE OR REPLACE VIEW `{{PROJECT}}.a4i_climate_work_v2.site_context_enriched_lst` AS
WITH lst3 AS (
  SELECT c.cell_id, AVG(n.lst_offset_f) AS lst_offset_3x3_f
  FROM `{{PROJECT}}.a4i_climate_work_v2.site_context_enriched` AS c
  JOIN `{{PROJECT}}.{{DATASET}}.cell_surface_temp` AS n
    ON n.lat_i BETWEEN c.lat_i - 1 AND c.lat_i + 1
   AND n.lon_i BETWEEN c.lon_i - 1 AND c.lon_i + 1
  WHERE n.lst_offset_f IS NOT NULL
  GROUP BY c.cell_id
),
base AS (
  SELECT e.* REPLACE (IFNULL(e.impervious_pct_300m, 0) AS impervious_pct_300m,
                      IFNULL(e.tree_canopy_pct_300m, 0) AS tree_canopy_pct_300m),
    (e.latitude - ({{TREND_LAT0}})) * {{KM_PER_DEG_LAT}} AS trend_lat_km,
    (e.longitude - ({{TREND_LON0}})) * {{KM_PER_DEG_LON}} AS trend_lon_km
  FROM `{{PROJECT}}.a4i_climate_work_v2.site_context_enriched` AS e
)
SELECT
  b.*,
  POW(b.trend_lat_km, 2) AS trend_lat2,
  POW(b.trend_lon_km, 2) AS trend_lon2,
  b.trend_lat_km * b.trend_lon_km AS trend_latlon,
  IFNULL(l.lst_offset_3x3_f, 0) AS surface_heat_f
FROM base AS b
LEFT JOIN lst3 AS l USING (cell_id);
