-- Phase 3 runtime validation gates.
-- Each query returns: check_name|violations

-- 1) Every decision hour with emitted signals has exactly one active risk profile assignment.
WITH signal_hours AS (
    SELECT DISTINCT ts.account_id, ts.hour_ts_utc
    FROM trade_signal ts
), active_profiles AS (
    SELECT
        sh.account_id,
        sh.hour_ts_utc,
        COUNT(*) AS active_count
    FROM signal_hours sh
    LEFT JOIN account_risk_profile_assignment a
      ON a.account_id = sh.account_id
     AND a.effective_from_utc <= sh.hour_ts_utc
     AND (a.effective_to_utc IS NULL OR a.effective_to_utc > sh.hour_ts_utc)
    GROUP BY sh.account_id, sh.hour_ts_utc
)
SELECT
    'phase3_active_profile_uniqueness' AS check_name,
    COUNT(*) AS violations
FROM active_profiles
WHERE active_count <> 1;

-- 2) Risk profile mode/value consistency must remain valid.
SELECT
    'phase3_risk_profile_mode_value_consistency' AS check_name,
    COUNT(*) AS violations
FROM risk_profile p
WHERE NOT (
    (
        p.total_exposure_mode = 'PERCENT_OF_PV'
        AND p.max_total_exposure_pct IS NOT NULL
        AND p.max_total_exposure_amount IS NULL
    ) OR (
        p.total_exposure_mode = 'ABSOLUTE_AMOUNT'
        AND p.max_total_exposure_amount IS NOT NULL
        AND p.max_total_exposure_pct IS NULL
    )
)
OR NOT (
    (
        p.cluster_exposure_mode = 'PERCENT_OF_PV'
        AND p.max_cluster_exposure_pct IS NOT NULL
        AND p.max_cluster_exposure_amount IS NULL
    ) OR (
        p.cluster_exposure_mode = 'ABSOLUTE_AMOUNT'
        AND p.max_cluster_exposure_amount IS NOT NULL
        AND p.max_cluster_exposure_pct IS NULL
    )
);

-- 3) Decision-trace events must be emitted for every signal.
WITH signal_counts AS (
    SELECT run_id, account_id, hour_ts_utc, COUNT(*) AS n_signals
    FROM trade_signal
    GROUP BY run_id, account_id, hour_ts_utc
), trace_counts AS (
    SELECT run_id, account_id, origin_hour_ts_utc AS hour_ts_utc, COUNT(*) AS n_traces
    FROM risk_event
    WHERE event_type = 'DECISION_TRACE'
    GROUP BY run_id, account_id, origin_hour_ts_utc
)
SELECT
    'phase3_decision_trace_coverage' AS check_name,
    COUNT(*) AS violations
FROM signal_counts s
LEFT JOIN trace_counts t
  ON t.run_id = s.run_id
 AND t.account_id = s.account_id
 AND t.hour_ts_utc = s.hour_ts_utc
WHERE COALESCE(t.n_traces, 0) < s.n_signals;

-- 4) Severe-loss mode must produce recovery-mode trace reason codes.
WITH severe_hours AS (
    SELECT
        ts.run_id,
        ts.account_id,
        ts.hour_ts_utc,
        rp.severe_loss_drawdown_trigger,
        r.drawdown_pct
    FROM trade_signal ts
    JOIN risk_hourly_state r
      ON r.run_mode = ts.run_mode
     AND r.account_id = ts.account_id
     AND r.hour_ts_utc = ts.hour_ts_utc
     AND r.source_run_id = ts.risk_state_run_id
    JOIN account_risk_profile_assignment a
      ON a.account_id = ts.account_id
     AND a.effective_from_utc <= ts.hour_ts_utc
     AND (a.effective_to_utc IS NULL OR a.effective_to_utc > ts.hour_ts_utc)
    JOIN risk_profile rp
      ON rp.profile_version = a.profile_version
    WHERE r.drawdown_pct >= rp.severe_loss_drawdown_trigger
)
SELECT
    'phase3_severe_loss_trace_coverage' AS check_name,
    COUNT(*) AS violations
FROM severe_hours sh
WHERE NOT EXISTS (
    SELECT 1
    FROM risk_event e
    WHERE e.run_id = sh.run_id
      AND e.account_id = sh.account_id
      AND e.origin_hour_ts_utc = sh.hour_ts_utc
      AND e.event_type = 'DECISION_TRACE'
      AND e.reason_code IN (
          'SEVERE_RECOVERY_ENTRY_PENDING_GATE',
          'SEVERE_RECOVERY_HOLD',
          'SEVERE_RECOVERY_DERISK_INTENT',
          'SEVERE_RECOVERY_EXIT',
          'SEVERE_LOSS_RECOVERY_ENTRY_BLOCKED'
      )
);

-- 5) Existing runtime risk gate regression check (must still hold).
SELECT
    'phase3_runtime_risk_gate_regression' AS check_name,
    COUNT(*) AS violations
FROM order_request o
JOIN risk_hourly_state r
  ON r.run_mode = o.run_mode
 AND r.account_id = o.account_id
 AND r.hour_ts_utc = o.hour_ts_utc
 AND r.source_run_id = o.risk_state_run_id
WHERE o.status <> 'REJECTED'
  AND (r.halt_new_entries OR r.kill_switch_active);

-- 6) Existing cluster-cap regression check (must still hold).
SELECT
    'phase3_cluster_cap_regression' AS check_name,
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
WHERE o.status <> 'REJECTED'
  AND ce.exposure_pct > ce.max_cluster_exposure_pct;
