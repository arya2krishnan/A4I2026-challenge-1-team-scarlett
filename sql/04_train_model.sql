-- 04  Train the heat-offset model in BigQuery ML.
--
-- Features: lake / downtown distance, density, housing age, plus OpenStreetMap roof, green, paved-use and road mix.
-- LINEAR_REG: trains inside BigQuery (free-tier eligible), supports ML.EXPLAIN_PREDICT, and its
-- attributions are easy to say out loud. Distances are bucketized (the lake effect is a step
-- near the shore, then flat) and density is log-scaled; TRANSFORM bakes this in, so ML.PREDICT
-- and ML.EXPLAIN_PREDICT take the raw columns.
--
-- Trained ONLY on measured cells (n_obs >= MIN_OBS) outside the held-out superblocks. The
-- held-out superblocks are scored by 05_evaluate.sql, never seen here.
--
-- Label: offset_f = degrees F hotter than the campaign mean. Not a temperature.

CREATE OR REPLACE MODEL `{{PROJECT}}.{{DATASET}}.heat_offset_model`
TRANSFORM (
  ML.BUCKETIZE(dist_to_lake_km, [0.5, 1.0, 2.0, 4.0, 8.0, 14.0]) AS lake_distance_band,
  ML.BUCKETIZE(dist_to_loop_km, [2.0, 4.0, 7.0, 11.0, 16.0])    AS downtown_distance_band,
  LOG(1 + pop_density_km2)                                      AS log_pop_density,
  ML.BUCKETIZE(median_year_structure_built, [1940, 1955, 1970, 1985]) AS building_era,
  building_share, green_share, paved_use_share,
  LOG(1 + road_km_per_km2) AS log_road_density,
  offset_f
)
OPTIONS (
  model_type = 'LINEAR_REG',
  input_label_cols = ['offset_f'],
  data_split_method = 'NO_SPLIT',
  l2_reg = 1.0,
  enable_global_explain = TRUE
) AS
SELECT
  dist_to_lake_km, dist_to_loop_km, pop_density_km2, median_year_structure_built,
  building_share, green_share, paved_use_share, road_km_per_km2, offset_f
FROM `{{PROJECT}}.{{DATASET}}.site_context`
WHERE n_obs >= {{MIN_OBS}}
  AND NOT is_holdout
  AND offset_f IS NOT NULL;
