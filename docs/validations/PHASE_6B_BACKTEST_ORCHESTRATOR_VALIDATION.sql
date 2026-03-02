-- Phase 6B deterministic backtest orchestrator validation.

SELECT
    'phase6b_backtest_fold_window_order_violation' AS check_name,
    COUNT(*) AS violations
FROM backtest_fold_result
WHERE NOT (
    train_start_utc < train_end_utc
    AND train_end_utc < valid_start_utc
    AND valid_start_utc < valid_end_utc
);

SELECT
    'phase6b_backtest_fold_negative_trade_count' AS check_name,
    COUNT(*) AS violations
FROM backtest_fold_result
WHERE trades_count < 0;

SELECT
    'phase6b_backtest_fold_win_rate_range_violation' AS check_name,
    COUNT(*) AS violations
FROM backtest_fold_result
WHERE win_rate < 0
   OR win_rate > 1;

SELECT
    'phase6b_backtest_fold_drawdown_range_violation' AS check_name,
    COUNT(*) AS violations
FROM backtest_fold_result
WHERE max_drawdown_pct < 0
   OR max_drawdown_pct > 1;

SELECT
    'phase6b_model_training_window_order_violation' AS check_name,
    COUNT(*) AS violations
FROM model_training_window
WHERE NOT (
    train_start_utc < train_end_utc
    AND train_end_utc < valid_start_utc
    AND valid_start_utc < valid_end_utc
);

SELECT
    'phase6b_training_window_orphan_backtest_fold' AS check_name,
    COUNT(*) AS violations
FROM model_training_window w
LEFT JOIN backtest_fold_result f
  ON f.backtest_run_id = w.backtest_run_id
 AND f.fold_index = w.fold_index
WHERE f.backtest_run_id IS NULL;

SELECT
    'phase6b_prediction_lineage_fold_missing' AS check_name,
    COUNT(*) AS violations
FROM model_prediction p
LEFT JOIN model_training_window w
  ON w.training_window_id = p.training_window_id
WHERE p.run_mode = 'BACKTEST'
  AND p.training_window_id IS NOT NULL
  AND w.training_window_id IS NULL;

SELECT
    'phase6b_regime_lineage_fold_missing' AS check_name,
    COUNT(*) AS violations
FROM regime_output r
LEFT JOIN model_training_window w
  ON w.training_window_id = r.training_window_id
WHERE r.run_mode = 'BACKTEST'
  AND r.training_window_id IS NOT NULL
  AND w.training_window_id IS NULL;

SELECT
    'phase6b_backtest_run_initial_capital_nonpositive' AS check_name,
    COUNT(*) AS violations
FROM backtest_run
WHERE initial_capital <= 0;
