-- v2 held-out evaluation: the same 442 held-out cells as sql/05, scored by every candidate.
-- Statement 1: one row per model (r2, RMSE, MAE). Statement 2: unmeasured cells whose v2 prediction falls
-- outside the measured offset range (where a quadratic trend could run away), plus the most extreme ones.

WITH holdout AS (
  SELECT * FROM `{{PROJECT}}.{{DATASET}}.site_context_lst`
  WHERE n_obs >= {{MIN_OBS}} AND is_holdout AND offset_f IS NOT NULL
)
SELECT 'baseline_predict_zero' AS model, 0.0 AS r2_score,
       SQRT(AVG(POW(offset_f, 2))) AS rmse_f, AVG(ABS(offset_f)) AS mae_f, COUNT(*) AS n
FROM holdout
UNION ALL
SELECT 'trend_only', r2_score, SQRT(mean_squared_error), mean_absolute_error, NULL
FROM ML.EVALUATE(MODEL `{{PROJECT}}.{{DATASET}}.heat_offset_trend_only`, (SELECT * FROM holdout))
UNION ALL
SELECT 'previous_model', r2_score, SQRT(mean_squared_error), mean_absolute_error, NULL
FROM ML.EVALUATE(MODEL `{{PROJECT}}.{{DATASET}}.heat_offset_model`, (SELECT * FROM holdout))
UNION ALL
SELECT 'model_v2_lst', r2_score, SQRT(mean_squared_error), mean_absolute_error, NULL
FROM ML.EVALUATE(MODEL `{{PROJECT}}.{{DATASET}}.heat_offset_lst`, (SELECT * FROM holdout))
ORDER BY r2_score;

WITH pred AS (
  SELECT community_area, n_obs, predicted_offset_f
  FROM ML.PREDICT(MODEL `{{PROJECT}}.{{DATASET}}.heat_offset_lst`,
                  (SELECT * FROM `{{PROJECT}}.{{DATASET}}.site_context_lst`))
),
measured AS (
  SELECT MIN(offset_f) AS lo, MAX(offset_f) AS hi
  FROM `{{PROJECT}}.{{DATASET}}.site_context_lst` WHERE n_obs >= {{MIN_OBS}}
)
SELECT
  COUNTIF(IFNULL(p.n_obs, 0) < {{MIN_OBS}} AND (p.predicted_offset_f < m.lo OR p.predicted_offset_f > m.hi)) AS unmeasured_outside_range,
  ROUND(MIN(p.predicted_offset_f), 2) AS min_pred_f, ROUND(MAX(p.predicted_offset_f), 2) AS max_pred_f,
  ANY_VALUE(m.lo) AS measured_lo_f, ANY_VALUE(m.hi) AS measured_hi_f,
  ARRAY_AGG(STRUCT(p.community_area, ROUND(p.predicted_offset_f, 2) AS pred_f)
            ORDER BY ABS(p.predicted_offset_f) DESC LIMIT 5) AS most_extreme
FROM pred AS p CROSS JOIN measured AS m;
