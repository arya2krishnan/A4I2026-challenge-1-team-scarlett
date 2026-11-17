-- v2 candidate models, trained beside the live heat_offset_model (which this file never touches).
-- Same label, training rows and options as sql/04: measured cells outside the held-out superblocks.
--   heat_offset_trend_only  baseline: location trend alone (the bar v2 must beat by >= 0.02 held-out r2)
--   heat_offset_lst         v2 "how hot it feels": trend + satellite surface heat + NLCD land cover + lake band
-- No demographic column is a feature.

CREATE OR REPLACE MODEL `{{PROJECT}}.{{DATASET}}.heat_offset_trend_only`
TRANSFORM (trend_lat_km, trend_lon_km, trend_lat2, trend_lon2, trend_latlon, offset_f)
OPTIONS (model_type = 'LINEAR_REG', input_label_cols = ['offset_f'], data_split_method = 'NO_SPLIT',
         l2_reg = 1.0, enable_global_explain = TRUE) AS
SELECT trend_lat_km, trend_lon_km, trend_lat2, trend_lon2, trend_latlon, offset_f
FROM `{{PROJECT}}.{{DATASET}}.site_context_lst`
WHERE n_obs >= {{MIN_OBS}} AND NOT is_holdout AND offset_f IS NOT NULL;

CREATE OR REPLACE MODEL `{{PROJECT}}.{{DATASET}}.heat_offset_lst`
TRANSFORM (
  trend_lat_km, trend_lon_km, trend_lat2, trend_lon2, trend_latlon,
  surface_heat_f, impervious_pct_300m, tree_canopy_pct_300m,
  ML.BUCKETIZE(dist_to_lake_km, [0.5, 1.0, 2.0, 4.0, 8.0, 14.0]) AS lake_distance_band,
  offset_f
)
OPTIONS (model_type = 'LINEAR_REG', input_label_cols = ['offset_f'], data_split_method = 'NO_SPLIT',
         l2_reg = 1.0, enable_global_explain = TRUE) AS
SELECT trend_lat_km, trend_lon_km, trend_lat2, trend_lon2, trend_latlon,
       surface_heat_f, impervious_pct_300m, tree_canopy_pct_300m, dist_to_lake_km, offset_f
FROM `{{PROJECT}}.{{DATASET}}.site_context_lst`
WHERE n_obs >= {{MIN_OBS}} AND NOT is_holdout AND offset_f IS NOT NULL;
