-- Preserve existing cell IDs, measured labels and spatial hold-out. Full county
-- polygons cover a community/Census city-boundary disagreement near West Lawn.
CREATE OR REPLACE TABLE `{{PROJECT}}.{{WORK}}.cell_tract_map` AS
WITH tracts AS (
  SELECT geo_id, ST_GEOGFROMGEOJSON(geojson, make_valid => TRUE) AS geom
  FROM `{{PROJECT}}.{{WORK}}.tract_boundaries_2024`
), matches AS (
  SELECT g.cell_id, t.geo_id
  FROM `{{PROJECT}}.{{SOURCE}}.grid_cells` g
  JOIN tracts t ON ST_COVERS(t.geom, ST_GEOGPOINT(g.longitude, g.latitude))
), grouped AS (
  SELECT cell_id, COUNT(*) match_count, MIN(geo_id) tract_geo_id
  FROM matches GROUP BY cell_id
)
SELECT g.cell_id, g.latitude, g.longitude, g.tract_geo_id AS original_tract_geo_id,
  m.tract_geo_id, COALESCE(m.match_count, 0) AS polygon_match_count,
  CASE WHEN m.match_count = 1 THEN 'polygon_containment'
       WHEN m.match_count > 1 THEN 'ambiguous_boundary' ELSE 'unmatched' END AS mapping_status,
  g.tract_geo_id IS DISTINCT FROM m.tract_geo_id AS tract_changed,
  ST_COVERS(ST_GEOGFROMGEOJSON(c.geojson, make_valid => TRUE),
            ST_GEOGPOINT(g.longitude, g.latitude)) AS inside_census_chicago_place,
  g.offset_f, g.n_obs, g.is_holdout, 2024 AS boundary_year,
  'Census TIGERweb ACS2024 Cook County tract containment' AS mapping_source
FROM `{{PROJECT}}.{{SOURCE}}.grid_cells` g
LEFT JOIN grouped m USING (cell_id)
CROSS JOIN `{{PROJECT}}.{{WORK}}.chicago_boundary_2024` c;

ASSERT (SELECT COUNT(*) FROM `{{PROJECT}}.{{WORK}}.cell_tract_map`) =
       (SELECT COUNT(*) FROM `{{PROJECT}}.{{SOURCE}}.grid_cells`) AS 'All source cells must be retained';
ASSERT (SELECT COUNT(*) = COUNT(DISTINCT cell_id) FROM `{{PROJECT}}.{{WORK}}.cell_tract_map`)
       AS 'Cell mapping must be unique';
ASSERT (SELECT COUNTIF(polygon_match_count != 1) = 0 FROM `{{PROJECT}}.{{WORK}}.cell_tract_map`)
       AS 'Every cell must have exactly one containing county tract';
ASSERT (SELECT COUNT(*) = 0 FROM `{{PROJECT}}.{{SOURCE}}.grid_cells` g
  JOIN `{{PROJECT}}.{{WORK}}.cell_tract_map` m USING (cell_id)
  WHERE g.offset_f IS DISTINCT FROM m.offset_f OR g.n_obs IS DISTINCT FROM m.n_obs
    OR g.is_holdout IS DISTINCT FROM m.is_holdout) AS 'Labels and hold-out membership must be unchanged';

SELECT COUNT(*) AS cells, COUNT(DISTINCT tract_geo_id) AS mapped_tracts,
  COUNTIF(tract_changed) AS changed_assignments,
  COUNTIF(NOT inside_census_chicago_place) AS census_city_boundary_disagreements,
  COUNTIF(n_obs >= 8) AS measured_cells,
  COUNTIF(n_obs >= 8 AND is_holdout) AS held_out_measured_cells
FROM `{{PROJECT}}.{{WORK}}.cell_tract_map`;
