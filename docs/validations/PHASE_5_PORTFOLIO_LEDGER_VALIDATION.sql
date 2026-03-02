-- Phase 5 portfolio/ledger validation gates.
-- Each query returns: check_name|violations

-- 1) Every order_fill must map to exactly one cash_ledger row.
WITH fill_coverage AS (
    SELECT
        f.fill_id,
        COUNT(l.ledger_id) AS ledger_rows
    FROM order_fill f
    LEFT JOIN cash_ledger l
      ON l.run_id = f.run_id
     AND l.account_id = f.account_id
     AND l.origin_hour_ts_utc = f.origin_hour_ts_utc
     AND l.ref_type = 'ORDER_FILL'
     AND l.ref_id = f.fill_id
    GROUP BY f.fill_id
)
SELECT
    'phase5_cash_ledger_fill_coverage' AS check_name,
    COUNT(*) AS violations
FROM fill_coverage
WHERE ledger_rows <> 1;

-- 2) Cash delta formula by side must include fee + slippage cash effects.
SELECT
    'phase5_cash_delta_formula' AS check_name,
    COUNT(*) AS violations
FROM cash_ledger l
JOIN order_fill f
  ON f.fill_id = l.ref_id
 AND l.ref_type = 'ORDER_FILL'
JOIN order_request o
  ON o.order_id = f.order_id
 AND o.run_id = f.run_id
 AND o.run_mode = f.run_mode
 AND o.account_id = f.account_id
WHERE l.delta_cash <> (
    CASE
        WHEN o.side = 'BUY' THEN -(f.fill_notional + f.fee_paid + f.slippage_cost)
        ELSE (f.fill_notional - f.fee_paid - f.slippage_cost)
    END
);

-- 3) Ledger sequence, arithmetic, and hash-chain continuity.
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
        LAG(ledger_seq) OVER (
            PARTITION BY account_id, run_mode
            ORDER BY ledger_seq
        ) AS prev_seq,
        LAG(balance_after) OVER (
            PARTITION BY account_id, run_mode
            ORDER BY ledger_seq
        ) AS prev_balance_after,
        LAG(ledger_hash) OVER (
            PARTITION BY account_id, run_mode
            ORDER BY ledger_seq
        ) AS prev_hash
    FROM cash_ledger
)
SELECT
    'phase5_ledger_chain_continuity' AS check_name,
    COUNT(*) AS violations
FROM ordered
WHERE balance_after <> balance_before + delta_cash
   OR (prev_seq IS NULL AND ledger_seq <> 1)
   OR (prev_seq IS NOT NULL AND ledger_seq <> prev_seq + 1)
   OR (prev_seq IS NOT NULL AND balance_before <> prev_balance_after)
   OR (prev_seq IS NULL AND prev_ledger_hash IS NOT NULL)
   OR (prev_seq IS NOT NULL AND prev_ledger_hash <> prev_hash);

-- 4) Each run-hour must have one portfolio row, one risk row, and required cluster rows.
WITH run_hours AS (
    SELECT run_id, account_id, run_mode, origin_hour_ts_utc
    FROM run_context
),
required_assets AS (
    SELECT DISTINCT
        rc.run_id,
        rc.account_id,
        rc.run_mode,
        rc.origin_hour_ts_utc,
        mp.asset_id
    FROM run_hours rc
    JOIN model_prediction mp
      ON mp.run_id = rc.run_id
     AND mp.account_id = rc.account_id
     AND mp.run_mode = rc.run_mode
     AND mp.hour_ts_utc = rc.origin_hour_ts_utc
    UNION
    SELECT DISTINCT
        rc.run_id,
        rc.account_id,
        rc.run_mode,
        rc.origin_hour_ts_utc,
        ps.asset_id
    FROM run_hours rc
    JOIN position_hourly_state ps
      ON ps.source_run_id = rc.run_id
     AND ps.account_id = rc.account_id
     AND ps.run_mode = rc.run_mode
     AND ps.hour_ts_utc = rc.origin_hour_ts_utc
    WHERE ps.quantity > 0
),
active_membership AS (
    SELECT DISTINCT ON (ra.run_id, ra.account_id, ra.run_mode, ra.origin_hour_ts_utc, ra.asset_id)
        ra.run_id,
        ra.account_id,
        ra.run_mode,
        ra.origin_hour_ts_utc,
        ra.asset_id,
        m.cluster_id
    FROM required_assets ra
    JOIN asset_cluster_membership m
      ON m.asset_id = ra.asset_id
     AND m.effective_from_utc <= ra.origin_hour_ts_utc
     AND (m.effective_to_utc IS NULL OR m.effective_to_utc > ra.origin_hour_ts_utc)
    ORDER BY
        ra.run_id,
        ra.account_id,
        ra.run_mode,
        ra.origin_hour_ts_utc,
        ra.asset_id,
        m.effective_from_utc DESC,
        m.membership_id DESC
),
required_clusters AS (
    SELECT
        run_id,
        account_id,
        run_mode,
        origin_hour_ts_utc,
        COUNT(DISTINCT cluster_id) AS required_cluster_count
    FROM active_membership
    GROUP BY run_id, account_id, run_mode, origin_hour_ts_utc
),
portfolio_counts AS (
    SELECT
        rc.run_id,
        rc.account_id,
        rc.run_mode,
        rc.origin_hour_ts_utc,
        COUNT(p.*) AS portfolio_count
    FROM run_hours rc
    LEFT JOIN portfolio_hourly_state p
      ON p.source_run_id = rc.run_id
     AND p.account_id = rc.account_id
     AND p.run_mode = rc.run_mode
     AND p.hour_ts_utc = rc.origin_hour_ts_utc
    GROUP BY rc.run_id, rc.account_id, rc.run_mode, rc.origin_hour_ts_utc
),
risk_counts AS (
    SELECT
        rc.run_id,
        rc.account_id,
        rc.run_mode,
        rc.origin_hour_ts_utc,
        COUNT(r.*) AS risk_count
    FROM run_hours rc
    LEFT JOIN risk_hourly_state r
      ON r.source_run_id = rc.run_id
     AND r.account_id = rc.account_id
     AND r.run_mode = rc.run_mode
     AND r.hour_ts_utc = rc.origin_hour_ts_utc
    GROUP BY rc.run_id, rc.account_id, rc.run_mode, rc.origin_hour_ts_utc
),
cluster_counts AS (
    SELECT
        rc.run_id,
        rc.account_id,
        rc.run_mode,
        rc.origin_hour_ts_utc,
        COUNT(c.*) AS cluster_count
    FROM run_hours rc
    LEFT JOIN cluster_exposure_hourly_state c
      ON c.source_run_id = rc.run_id
     AND c.account_id = rc.account_id
     AND c.run_mode = rc.run_mode
     AND c.hour_ts_utc = rc.origin_hour_ts_utc
    GROUP BY rc.run_id, rc.account_id, rc.run_mode, rc.origin_hour_ts_utc
)
SELECT
    'phase5_hourly_state_presence' AS check_name,
    COUNT(*) AS violations
FROM run_hours rc
JOIN portfolio_counts pc
  ON pc.run_id = rc.run_id
 AND pc.account_id = rc.account_id
 AND pc.run_mode = rc.run_mode
 AND pc.origin_hour_ts_utc = rc.origin_hour_ts_utc
JOIN risk_counts rcnt
  ON rcnt.run_id = rc.run_id
 AND rcnt.account_id = rc.account_id
 AND rcnt.run_mode = rc.run_mode
 AND rcnt.origin_hour_ts_utc = rc.origin_hour_ts_utc
JOIN cluster_counts cc
  ON cc.run_id = rc.run_id
 AND cc.account_id = rc.account_id
 AND cc.run_mode = rc.run_mode
 AND cc.origin_hour_ts_utc = rc.origin_hour_ts_utc
LEFT JOIN required_clusters req
  ON req.run_id = rc.run_id
 AND req.account_id = rc.account_id
 AND req.run_mode = rc.run_mode
 AND req.origin_hour_ts_utc = rc.origin_hour_ts_utc
WHERE pc.portfolio_count <> 1
   OR rcnt.risk_count <> 1
   OR cc.cluster_count <> COALESCE(req.required_cluster_count, 0);

-- 5) Portfolio reconciliation and bounded ratio ranges.
SELECT
    'phase5_portfolio_reconciliation_formula' AS check_name,
    COUNT(*) AS violations
FROM portfolio_hourly_state p
WHERE p.portfolio_value <> p.cash_balance + p.market_value
   OR p.cash_balance < 0
   OR p.market_value < 0
   OR p.drawdown_pct < 0
   OR p.drawdown_pct > 1
   OR p.total_exposure_pct < 0
   OR p.total_exposure_pct > 1;

-- 6) Risk tier mapping and HALT20 controls.
SELECT
    'phase5_risk_tier_consistency' AS check_name,
    COUNT(*) AS violations
FROM risk_hourly_state r
WHERE NOT (
    (r.drawdown_pct < 0.10 AND r.drawdown_tier = 'NORMAL') OR
    (r.drawdown_pct >= 0.10 AND r.drawdown_pct < 0.15 AND r.drawdown_tier = 'DD10') OR
    (r.drawdown_pct >= 0.15 AND r.drawdown_pct < 0.20 AND r.drawdown_tier = 'DD15') OR
    (r.drawdown_pct >= 0.20 AND r.drawdown_tier = 'HALT20')
)
OR (
    r.drawdown_pct >= 0.20
    AND NOT (
        r.halt_new_entries = TRUE
        AND r.requires_manual_review = TRUE
        AND r.base_risk_fraction = 0
        AND r.drawdown_tier = 'HALT20'
    )
);

-- 7) Cluster parent hash must equal risk row_hash for the same identity key.
SELECT
    'phase5_cluster_parent_hash_integrity' AS check_name,
    COUNT(*) AS violations
FROM cluster_exposure_hourly_state c
LEFT JOIN risk_hourly_state r
  ON r.run_mode = c.run_mode
 AND r.account_id = c.account_id
 AND r.hour_ts_utc = c.hour_ts_utc
 AND r.source_run_id = c.source_run_id
WHERE r.row_hash IS NULL
   OR c.parent_risk_hash <> r.row_hash;

-- 8) Aggregate cluster exposure must not exceed total portfolio exposure (with tolerance).
WITH cluster_rollup AS (
    SELECT
        c.run_mode,
        c.account_id,
        c.hour_ts_utc,
        c.source_run_id,
        COALESCE(SUM(c.exposure_pct), 0::numeric) AS total_cluster_exposure_pct
    FROM cluster_exposure_hourly_state c
    GROUP BY c.run_mode, c.account_id, c.hour_ts_utc, c.source_run_id
)
SELECT
    'phase5_cluster_vs_total_exposure_consistency' AS check_name,
    COUNT(*) AS violations
FROM cluster_rollup cr
JOIN portfolio_hourly_state p
  ON p.run_mode = cr.run_mode
 AND p.account_id = cr.account_id
 AND p.hour_ts_utc = cr.hour_ts_utc
 AND p.source_run_id = cr.source_run_id
WHERE cr.total_cluster_exposure_pct > p.total_exposure_pct + 0.0000000001::numeric;
