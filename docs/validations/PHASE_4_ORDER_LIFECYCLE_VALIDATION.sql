-- Phase 4 order lifecycle validation gates.
-- Each query returns: check_name|violations

-- 1) Fill causality and order linkage must hold.
SELECT
    'phase4_fill_causality_and_order_link' AS check_name,
    COUNT(*) AS violations
FROM order_fill f
LEFT JOIN order_request r
  ON r.order_id = f.order_id
 AND r.run_id = f.run_id
 AND r.run_mode = f.run_mode
 AND r.account_id = f.account_id
 AND r.asset_id = f.asset_id
WHERE r.order_id IS NULL
   OR f.fill_ts_utc < r.request_ts_utc;

-- 2) Order terminal status must match summed fills for each attempt row.
WITH fill_rollup AS (
    SELECT order_id, COALESCE(SUM(fill_qty), 0::numeric) AS filled_qty
    FROM order_fill
    GROUP BY order_id
)
SELECT
    'phase4_order_status_vs_fill_rollup' AS check_name,
    COUNT(*) AS violations
FROM order_request o
LEFT JOIN fill_rollup fr
  ON fr.order_id = o.order_id
WHERE (
    o.status = 'FILLED'
    AND COALESCE(fr.filled_qty, 0::numeric) <> o.requested_qty
) OR (
    o.status = 'PARTIAL'
    AND NOT (
        COALESCE(fr.filled_qty, 0::numeric) > 0::numeric
        AND COALESCE(fr.filled_qty, 0::numeric) < o.requested_qty
    )
) OR (
    o.status = 'CANCELLED'
    AND COALESCE(fr.filled_qty, 0::numeric) <> 0::numeric
);

-- 3) Executed trade quantity may never exceed the source lot open quantity.
WITH trade_rollup AS (
    SELECT lot_id, COALESCE(SUM(quantity), 0::numeric) AS consumed_qty
    FROM executed_trade
    GROUP BY lot_id
)
SELECT
    'phase4_lot_trade_quantity_conservation' AS check_name,
    COUNT(*) AS violations
FROM position_lot l
LEFT JOIN trade_rollup tr
  ON tr.lot_id = l.lot_id
WHERE COALESCE(tr.consumed_qty, 0::numeric) > l.open_qty;

-- 4) Executed trade formula and chronology sanity checks.
SELECT
    'phase4_executed_trade_formula_sanity' AS check_name,
    COUNT(*) AS violations
FROM executed_trade t
WHERE t.net_pnl <> t.gross_pnl - t.total_fee - t.total_slippage_cost
   OR t.exit_ts_utc < t.entry_ts_utc
   OR t.holding_hours < 0;

-- 5) De-risk intent must be accompanied by at least one SELL order attempt.
SELECT
    'phase4_derisk_intent_sell_order_coverage' AS check_name,
    COUNT(*) AS violations
FROM risk_event e
WHERE e.reason_code = 'SEVERE_RECOVERY_DERISK_ORDER_EMITTED'
  AND NOT EXISTS (
      SELECT 1
      FROM order_request o
      WHERE o.run_id = e.run_id
        AND o.account_id = e.account_id
        AND o.origin_hour_ts_utc = e.origin_hour_ts_utc
        AND o.side = 'SELL'
  );
