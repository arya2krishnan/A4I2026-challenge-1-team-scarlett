-- 05  Honest evaluation: held-out superblocks the model never saw, against a naive baseline.
--
-- If r2 here looks spectacular (>0.9) suspect leakage. If it is near zero the features do not
-- explain heat and the agent must say so. Either way, put these numbers in the deck.

WITH holdout AS (
  SELECT * FROM `{{PROJECT}}.{{DATASET}}.site_context`
  WHERE n_obs >= {{MIN_OBS}} AND is_holdout AND offset_f IS NOT NULL
),
model_metrics AS (
  SELECT 'model_on_heldout_blocks' AS what, mean_absolute_error AS mae_f,
         SQRT(mean_squared_error) AS rmse_f, r2_score
  FROM ML.EVALUATE(MODEL `{{PROJECT}}.{{DATASET}}.heat_offset_model`, (SELECT * FROM holdout))
),
baseline AS (
  -- "always predict the city average" (offset 0)
  SELECT 'baseline_predict_zero' AS what, AVG(ABS(offset_f)) AS mae_f,
         SQRT(AVG(POW(offset_f, 2))) AS rmse_f, 0.0 AS r2_score
  FROM holdout
)
SELECT * FROM model_metrics
UNION ALL SELECT * FROM baseline
UNION ALL SELECT 'heldout_cells', COUNT(*), NULL, NULL FROM holdout;
