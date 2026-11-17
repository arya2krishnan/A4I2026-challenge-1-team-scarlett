-- 06  Sanity checks on what the agent will read. Every row should say PASS.

WITH s AS (SELECT * FROM `{{PROJECT}}.{{DATASET}}.site_context`),
checks AS (
  SELECT 'site_context has cells' AS chk, COUNT(*) > 1000 AS ok, CAST(COUNT(*) AS STRING) AS detail FROM s
  UNION ALL SELECT 'measured cells exist', COUNTIF(n_obs >= {{MIN_OBS}}) > 200, CAST(COUNTIF(n_obs >= {{MIN_OBS}}) AS STRING) FROM s
  UNION ALL SELECT 'unmeasured cells exist (the point of the model)', COUNTIF(n_obs = 0) > 0, CAST(COUNTIF(n_obs = 0) AS STRING) FROM s
  UNION ALL SELECT 'no null model features',
    COUNTIF(dist_to_lake_km IS NULL OR dist_to_loop_km IS NULL OR pop_density_km2 IS NULL OR median_year_structure_built IS NULL OR building_share IS NULL OR green_share IS NULL) = 0,
    CAST(COUNTIF(dist_to_lake_km IS NULL OR dist_to_loop_km IS NULL OR pop_density_km2 IS NULL OR median_year_structure_built IS NULL OR building_share IS NULL OR green_share IS NULL) AS STRING) FROM s
  UNION ALL SELECT 'vulnerability in 0..1', COUNTIF(vulnerability_index < 0 OR vulnerability_index > 1) = 0, CAST(COUNTIF(vulnerability_index IS NULL) AS STRING) || ' null' FROM s
  UNION ALL SELECT 'cooling facility found for every cell', COUNTIF(km_to_cooling IS NULL) = 0, CAST(COUNTIF(km_to_cooling IS NULL) AS STRING) || ' missing' FROM s
  UNION ALL SELECT 'measured offset averages ~0 (campaign mean removed)', ABS(AVG(IF(n_obs > 0, offset_f, NULL))) < 1.0, CAST(ROUND(AVG(IF(n_obs > 0, offset_f, NULL)), 2) AS STRING) FROM s
  UNION ALL SELECT 'intra-city spread > 3F', MAX(offset_f) - MIN(offset_f) > 3, CAST(ROUND(MAX(offset_f) - MIN(offset_f), 1) AS STRING) FROM s
  UNION ALL SELECT 'holdout is 10-35% of cells', COUNTIF(is_holdout) / COUNT(*) BETWEEN 0.10 AND 0.35, CAST(ROUND(COUNTIF(is_holdout) / COUNT(*), 2) AS STRING) FROM s
  UNION ALL SELECT 'every cell is inside the city (has a community area)', COUNTIF(community_area IS NULL) = 0, CAST(COUNTIF(community_area IS NULL) AS STRING) || ' outside' FROM s
  UNION ALL SELECT 'OSM land cover is populated', AVG(building_share) > 0.02 AND AVG(green_share) > 0.01, FORMAT('bldg %.3f green %.3f paved %.3f', AVG(building_share), AVG(green_share), AVG(paved_use_share)) FROM s
  UNION ALL SELECT 'facilities loaded', (SELECT COUNT(*) FROM `{{PROJECT}}.{{DATASET}}.cooling_facilities`) > 50, CAST((SELECT COUNT(*) FROM `{{PROJECT}}.{{DATASET}}.cooling_facilities`) AS STRING)
)
SELECT chk AS `check`, IF(ok, 'PASS', 'FAIL') AS result, detail FROM checks;
