-- PHASE 1C Revision C validation gate (authoritative readiness checks).
-- All result rows must return violations = 0.

SELECT
    'triggers_with_v2_refs_action_statement' AS check_name,
    COUNT(*) AS violations
FROM information_schema.triggers
WHERE trigger_schema = 'public'
  AND strpos(lower(action_statement), '_v2') > 0;

SELECT
    'functions_with_v2_refs_blueprint_scope' AS check_name,
    COUNT(*) AS violations
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public'
  AND (
      p.prosrc ILIKE '%cash_ledger_v2%'
   OR p.prosrc ILIKE '%order_request_v2%'
   OR p.prosrc ILIKE '%executed_trade_v2%'
  );

SELECT
    'functions_named_with_v2_suffix' AS check_name,
    COUNT(*) AS violations
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public'
  AND right(p.proname, 3) = '_v2';

SELECT
    'residual_v2_relations' AS check_name,
    COUNT(*) AS violations
FROM pg_class
WHERE relnamespace = 'public'::regnamespace
  AND relkind IN ('r', 'p', 'v', 'm', 'f')
  AND right(relname, 3) = '_v2';

SELECT
    'no_fk_targets_on_hypertables' AS check_name,
    COUNT(*) AS violations
FROM (
    SELECT 1
    FROM pg_constraint c
    JOIN pg_class child_tbl ON child_tbl.oid = c.conrelid
    JOIN pg_namespace child_ns ON child_ns.oid = child_tbl.relnamespace
    JOIN pg_class parent_tbl ON parent_tbl.oid = c.confrelid
    JOIN pg_namespace parent_ns ON parent_ns.oid = parent_tbl.relnamespace
    JOIN timescaledb_information.hypertables h
      ON h.hypertable_schema = parent_ns.nspname
     AND h.hypertable_name = parent_tbl.relname
    WHERE c.contype = 'f'
      AND child_ns.nspname = 'public'
) q;

SELECT
    'nullable_replay_critical_hash_columns' AS check_name,
    COUNT(*) AS violations
FROM information_schema.columns
WHERE table_schema = 'public'
  AND (table_name, column_name) IN (
    ('run_context','run_seed_hash'),
    ('run_context','context_hash'),
    ('run_context','replay_root_hash'),
    ('backtest_run','row_hash'),
    ('model_training_window','training_window_hash'),
    ('model_training_window','row_hash'),
    ('backtest_fold_result','row_hash'),
    ('market_ohlcv_hourly','row_hash'),
    ('order_book_snapshot','row_hash'),
    ('feature_snapshot','row_hash'),
    ('regime_output','upstream_hash'),
    ('regime_output','row_hash'),
    ('model_prediction','upstream_hash'),
    ('model_prediction','row_hash'),
    ('meta_learner_component','row_hash'),
    ('trade_signal','upstream_hash'),
    ('trade_signal','row_hash'),
    ('order_request','parent_signal_hash'),
    ('order_request','row_hash'),
    ('order_fill','parent_order_hash'),
    ('order_fill','row_hash'),
    ('position_lot','parent_fill_hash'),
    ('position_lot','row_hash'),
    ('executed_trade','parent_lot_hash'),
    ('executed_trade','row_hash'),
    ('cash_ledger','row_hash'),
    ('position_hourly_state','row_hash'),
    ('portfolio_hourly_state','row_hash'),
    ('risk_hourly_state','row_hash'),
    ('risk_event','parent_state_hash'),
    ('risk_event','row_hash'),
    ('cluster_exposure_hourly_state','parent_risk_hash'),
    ('cluster_exposure_hourly_state','row_hash')
  )
  AND is_nullable = 'YES';

SELECT
    'walk_forward_contamination_exclusion' AS check_name,
    COUNT(*) AS violations
FROM model_prediction mp
JOIN model_training_window tw
  ON tw.training_window_id = mp.training_window_id
WHERE mp.run_mode = 'BACKTEST'
  AND (
      mp.hour_ts_utc < tw.valid_start_utc
      OR mp.hour_ts_utc >= tw.valid_end_utc
      OR mp.hour_ts_utc <= tw.train_end_utc
  );

SELECT
    'cross_account_isolation' AS check_name,
    COUNT(*) AS violations
FROM (
    SELECT ts.signal_id
    FROM trade_signal ts
    JOIN run_context rc
      ON rc.run_id = ts.run_id
     AND rc.run_mode = ts.run_mode
     AND rc.origin_hour_ts_utc = ts.hour_ts_utc
    WHERE ts.account_id <> rc.account_id
    UNION ALL
    SELECT orq.order_id
    FROM order_request orq
    JOIN run_context rc
      ON rc.run_id = orq.run_id
     AND rc.run_mode = orq.run_mode
     AND rc.origin_hour_ts_utc = orq.origin_hour_ts_utc
    WHERE orq.account_id <> rc.account_id
) q;

WITH ordered AS (
    SELECT
        account_id,
        run_mode,
        ledger_seq,
        balance_before,
        balance_after,
        delta_cash,
        prev_ledger_hash,
        ledger_hash,
        LAG(balance_after) OVER (
            PARTITION BY account_id, run_mode
            ORDER BY ledger_seq
        ) AS expected_before,
        LAG(ledger_hash) OVER (
            PARTITION BY account_id, run_mode
            ORDER BY ledger_seq
        ) AS expected_prev_hash
    FROM cash_ledger
)
SELECT
    'ledger_arithmetic_continuity' AS check_name,
    COUNT(*) AS violations
FROM ordered
WHERE balance_after <> balance_before + delta_cash
   OR (ledger_seq > 1 AND balance_before <> expected_before)
   OR (ledger_seq > 1 AND prev_ledger_hash <> expected_prev_hash);

SELECT
    'cluster_cap_enforcement' AS check_name,
    COUNT(*) AS violations
FROM cluster_exposure_hourly_state
WHERE exposure_pct > max_cluster_exposure_pct;

WITH parity_pairs AS (
    SELECT
        a.run_id AS run_id_a,
        b.run_id AS run_id_b,
        (a.replay_root_hash = b.replay_root_hash) AS root_hash_match,
        (a.authoritative_row_count = b.authoritative_row_count) AS row_count_match
    FROM replay_manifest a
    JOIN replay_manifest b
      ON a.account_id = b.account_id
     AND a.run_mode = b.run_mode
     AND a.origin_hour_ts_utc = b.origin_hour_ts_utc
    WHERE a.run_id <> b.run_id
      AND a.run_seed_hash = b.run_seed_hash
)
SELECT
    'deterministic_replay_parity_mismatch_pairs' AS check_name,
    COUNT(*) AS violations
FROM parity_pairs
WHERE NOT (root_hash_match AND row_count_match);
