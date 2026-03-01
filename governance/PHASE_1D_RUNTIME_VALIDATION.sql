-- PHASE 1D runtime validation gate
-- All SELECT statements must return violations = 0.

-- 1) Append-only enforcement on economic tables (no UPDATE/DELETE path).
WITH economic_tables AS (
    SELECT 'trade_signal' AS table_name
    UNION ALL SELECT 'order_request'
    UNION ALL SELECT 'order_fill'
    UNION ALL SELECT 'position_lot'
    UNION ALL SELECT 'executed_trade'
    UNION ALL SELECT 'cash_ledger'
    UNION ALL SELECT 'risk_event'
),
append_only_trigger_tables AS (
    SELECT c.relname AS table_name
    FROM pg_trigger t
    JOIN pg_class c ON c.oid = t.tgrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND NOT t.tgisinternal
      AND t.tgfoid = 'fn_enforce_append_only()'::regprocedure
      AND (t.tgtype & 2) = 2   -- BEFORE
      AND (t.tgtype & 8) = 8   -- DELETE
      AND (t.tgtype & 16) = 16 -- UPDATE
)
SELECT
    'append_only_trigger_gaps' AS check_name,
    COUNT(*) AS violations
FROM economic_tables e
LEFT JOIN append_only_trigger_tables a
  ON a.table_name = e.table_name
WHERE a.table_name IS NULL;

-- 2) Replay sample-hour readiness gate.
-- Empty-runtime bootstrap (0 rows) is accepted; otherwise require >= 3 hours.
WITH run_hours AS (
    SELECT COUNT(*)::bigint AS total_hours
    FROM run_context
)
SELECT
    'replay_sample_hour_shortfall' AS check_name,
    CASE
        WHEN total_hours = 0 THEN 0
        WHEN total_hours >= 3 THEN 0
        ELSE 3 - total_hours
    END AS violations
FROM run_hours;

-- 3) Replay manifest parity against run_context roots for sample hours.
WITH sample_hours AS (
    SELECT run_id, account_id, run_mode, origin_hour_ts_utc
    FROM run_context
    ORDER BY origin_hour_ts_utc DESC, run_id ASC
    LIMIT 3
)
SELECT
    'replay_manifest_root_mismatch' AS check_name,
    COUNT(*) AS violations
FROM sample_hours s
JOIN run_context rc
  ON rc.run_id = s.run_id
 AND rc.account_id = s.account_id
 AND rc.run_mode = s.run_mode
 AND rc.origin_hour_ts_utc = s.origin_hour_ts_utc
LEFT JOIN replay_manifest rm
  ON rm.run_id = s.run_id
 AND rm.account_id = s.account_id
 AND rm.run_mode = s.run_mode
 AND rm.origin_hour_ts_utc = s.origin_hour_ts_utc
WHERE rm.run_id IS NULL
   OR rm.replay_root_hash <> rc.replay_root_hash
   OR rm.run_seed_hash <> rc.run_seed_hash;

-- 4) Cross-account contamination exclusion.
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

-- 5) Ledger arithmetic continuity invariant.
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

-- 6) Walk-forward contamination exclusion on both prediction surfaces.
SELECT
    'walk_forward_contamination_exclusion' AS check_name,
    COUNT(*) AS violations
FROM (
    SELECT mp.run_id
    FROM model_prediction mp
    JOIN model_training_window tw
      ON tw.training_window_id = mp.training_window_id
    WHERE mp.run_mode = 'BACKTEST'
      AND (
          mp.hour_ts_utc < tw.valid_start_utc
          OR mp.hour_ts_utc >= tw.valid_end_utc
          OR mp.hour_ts_utc <= tw.train_end_utc
      )
    UNION ALL
    SELECT ro.run_id
    FROM regime_output ro
    JOIN model_training_window tw
      ON tw.training_window_id = ro.training_window_id
    WHERE ro.run_mode = 'BACKTEST'
      AND (
          ro.hour_ts_utc < tw.valid_start_utc
          OR ro.hour_ts_utc >= tw.valid_end_utc
          OR ro.hour_ts_utc <= tw.train_end_utc
      )
) q;

-- 7) Activation gate enforcement on prediction surfaces.
SELECT
    'activation_gate_enforcement' AS check_name,
    COUNT(*) AS violations
FROM (
    SELECT mp.run_id
    FROM model_prediction mp
    LEFT JOIN model_activation_gate mag
      ON mag.activation_id = mp.activation_id
     AND mag.model_version_id = mp.model_version_id
     AND mag.run_mode = mp.run_mode
    WHERE (
        mp.run_mode IN ('PAPER', 'LIVE')
        AND (mp.activation_id IS NULL OR mag.status <> 'APPROVED')
    )
       OR (
        mp.run_mode = 'BACKTEST'
        AND mp.activation_id IS NOT NULL
    )
    UNION ALL
    SELECT ro.run_id
    FROM regime_output ro
    LEFT JOIN model_activation_gate mag
      ON mag.activation_id = ro.activation_id
     AND mag.model_version_id = ro.model_version_id
     AND mag.run_mode = ro.run_mode
    WHERE (
        ro.run_mode IN ('PAPER', 'LIVE')
        AND (ro.activation_id IS NULL OR mag.status <> 'APPROVED')
    )
       OR (
        ro.run_mode = 'BACKTEST'
        AND ro.activation_id IS NOT NULL
    )
) q;

-- 8) Runtime risk gate enforcement + deterministic risk-event logging surface.
SELECT
    'runtime_risk_gate_violation' AS check_name,
    COUNT(*) AS violations
FROM order_request o
JOIN risk_hourly_state r
  ON r.run_mode = o.run_mode
 AND r.account_id = o.account_id
 AND r.hour_ts_utc = o.hour_ts_utc
 AND r.source_run_id = o.risk_state_run_id
WHERE o.status <> 'REJECTED'
  AND (r.halt_new_entries OR r.kill_switch_active);

SELECT
    'runtime_risk_gate_logging_gap' AS check_name,
    COUNT(*) AS violations
FROM order_request o
JOIN risk_hourly_state r
  ON r.run_mode = o.run_mode
 AND r.account_id = o.account_id
 AND r.hour_ts_utc = o.hour_ts_utc
 AND r.source_run_id = o.risk_state_run_id
WHERE o.status = 'REJECTED'
  AND (r.halt_new_entries OR r.kill_switch_active)
  AND NOT EXISTS (
      SELECT 1
      FROM risk_event e
      WHERE e.run_id = o.run_id
        AND e.account_id = o.account_id
        AND e.origin_hour_ts_utc = o.origin_hour_ts_utc
        AND e.reason_code IN ('HALT_NEW_ENTRIES_ACTIVE', 'KILL_SWITCH_ACTIVE')
  );

-- 9) Cluster-cap enforcement active and logged.
SELECT
    'cluster_cap_violation' AS check_name,
    COUNT(*) AS violations
FROM order_request o
JOIN trade_signal ts
  ON ts.signal_id = o.signal_id
JOIN asset_cluster_membership acm
  ON acm.membership_id = o.cluster_membership_id
JOIN cluster_exposure_hourly_state ce
  ON ce.run_mode = o.run_mode
 AND ce.account_id = o.account_id
 AND ce.hour_ts_utc = o.hour_ts_utc
 AND ce.source_run_id = o.risk_state_run_id
 AND ce.cluster_id = acm.cluster_id
WHERE o.status <> 'REJECTED'
  AND ce.exposure_pct > ce.max_cluster_exposure_pct;

SELECT
    'cluster_cap_logging_gap' AS check_name,
    COUNT(*) AS violations
FROM order_request o
JOIN asset_cluster_membership acm
  ON acm.membership_id = o.cluster_membership_id
JOIN cluster_exposure_hourly_state ce
  ON ce.run_mode = o.run_mode
 AND ce.account_id = o.account_id
 AND ce.hour_ts_utc = o.hour_ts_utc
 AND ce.source_run_id = o.risk_state_run_id
 AND ce.cluster_id = acm.cluster_id
WHERE o.status = 'REJECTED'
  AND ce.exposure_pct > ce.max_cluster_exposure_pct
  AND NOT EXISTS (
      SELECT 1
      FROM risk_event e
      WHERE e.run_id = o.run_id
        AND e.account_id = o.account_id
        AND e.origin_hour_ts_utc = o.origin_hour_ts_utc
        AND e.reason_code = 'CLUSTER_CAP_EXCEEDED'
  );

-- 10) Deterministic replay parity mismatch pairs must be zero.
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
