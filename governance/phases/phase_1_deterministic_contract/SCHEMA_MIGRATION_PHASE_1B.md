# 1. Migration Strategy Overview

- Migration classification: Freeze-required staged hard break with shadow-table cutover and deterministic regeneration.
- Trading halt requirement: Mandatory full trading halt (BACKTEST/PAPER/LIVE writes blocked) from migration lock activation until post-cutover validation pass.
- Replay-authoritative tables impacted: `run_context`, `model_training_window`, `backtest_fold_result`, `feature_snapshot`, `regime_output`, `model_prediction`, `meta_learner_component`, `trade_signal`, `order_request`, `order_fill`, `position_lot`, `executed_trade`, `cash_ledger`, `position_hourly_state`, `portfolio_hourly_state`, `risk_hourly_state`, `risk_event`.
- Downtime expectations: 4-12 hours cutover window, depending on replay regeneration volume and validation runtime.
- Regeneration requirements: Full deterministic regeneration for decision/execution/risk/accounting lineage tables; raw market tables may be deterministic backfilled into v2 structures.
- Data freeze requirements: Hard freeze at cutpoint timestamp `T0`; no new writes to replay-authoritative tables after `T0`; snapshot checksum captured before DDL.
- Risk posture during migration: Capital protection mode; no entries, no order placement, no strategy execution, no risk-threshold overrides; only infrastructure maintenance actions allowed.

APPROVED MIGRATION MODE: FREEZE-REQUIRED STAGED HARD BREAK (SHADOW TABLE CUTOVER + DETERMINISTIC REGENERATION)

# 2. Ordered Migration Phases

## M1 — Pre-Migration Safety Lock

### Purpose
Establish immutable migration boundary, halt trading writes, and preserve pre-migration evidence for audit and rollback.

### Affected Tables
`run_context`, `trade_signal`, `order_request`, `order_fill`, `cash_ledger`, `position_hourly_state`, `portfolio_hourly_state`, `risk_hourly_state`, `risk_event`, plus Timescale policies for touched hypertables.

### Exact DDL Operations
```sql
CREATE TABLE IF NOT EXISTS schema_migration_control (
    migration_name TEXT PRIMARY KEY,
    locked BOOLEAN NOT NULL,
    lock_reason TEXT NOT NULL,
    locked_at_utc TIMESTAMPTZ NOT NULL DEFAULT now(),
    unlocked_at_utc TIMESTAMPTZ
);

INSERT INTO schema_migration_control (migration_name, locked, lock_reason)
VALUES ('phase_1b_schema', TRUE, 'Phase 1B deterministic contract migration')
ON CONFLICT (migration_name)
DO UPDATE SET locked = EXCLUDED.locked, lock_reason = EXCLUDED.lock_reason, locked_at_utc = now(), unlocked_at_utc = NULL;

CREATE OR REPLACE FUNCTION fn_reject_writes_when_phase_1b_locked()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM schema_migration_control
        WHERE migration_name = 'phase_1b_schema'
          AND locked = TRUE
    ) THEN
        RAISE EXCEPTION 'phase_1b_schema lock active: writes blocked on %', TG_TABLE_NAME;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_run_context_phase_1b_lock
BEFORE INSERT ON run_context
FOR EACH ROW EXECUTE FUNCTION fn_reject_writes_when_phase_1b_locked();

CREATE TRIGGER trg_order_request_phase_1b_lock
BEFORE INSERT ON order_request
FOR EACH ROW EXECUTE FUNCTION fn_reject_writes_when_phase_1b_locked();

CREATE TRIGGER trg_order_fill_phase_1b_lock
BEFORE INSERT ON order_fill
FOR EACH ROW EXECUTE FUNCTION fn_reject_writes_when_phase_1b_locked();

CREATE TRIGGER trg_cash_ledger_phase_1b_lock
BEFORE INSERT ON cash_ledger
FOR EACH ROW EXECUTE FUNCTION fn_reject_writes_when_phase_1b_locked();
```

### Constraint Type (Immediate / DEFERRABLE INITIALLY DEFERRED)
Immediate.

### Data Backfill Plan
No backfill. Capture pre-cutover row counts and SHA256 checksums per table as immutable baseline.

### Replay Impact
Defines deterministic replay cutpoint `T0`; all post-`T0` replay-authoritative rows originate only from regenerated phase-1B flow.

### Failure Risk If Skipped
Concurrent writes during migration create split lineage, non-reproducible replay roots, and audit invalidation.

## M2 — Account Context Isolation Refactor

### Purpose
Enforce strict account/run binding for all trading and accounting rows to eliminate cross-account context contamination.

### Affected Tables
`run_context`, `trade_signal`, `order_request`, `order_fill`, `position_lot`, `executed_trade`, `cash_ledger`, `position_hourly_state`, `portfolio_hourly_state`, `risk_hourly_state`, `risk_event`.

### Exact DDL Operations
```sql
ALTER TABLE run_context
    ADD CONSTRAINT uq_run_context_run_account_mode_hour
    UNIQUE (run_id, account_id, run_mode, hour_ts_utc);

ALTER TABLE trade_signal
    ADD CONSTRAINT fk_trade_signal_run_context_account_hour
    FOREIGN KEY (run_id, account_id, run_mode, hour_ts_utc)
    REFERENCES run_context (run_id, account_id, run_mode, hour_ts_utc)
    ON UPDATE RESTRICT
    ON DELETE RESTRICT
    NOT VALID;

ALTER TABLE order_request
    ADD CONSTRAINT fk_order_request_run_context_account_hour
    FOREIGN KEY (run_id, account_id, run_mode, hour_ts_utc)
    REFERENCES run_context (run_id, account_id, run_mode, hour_ts_utc)
    ON UPDATE RESTRICT
    ON DELETE RESTRICT
    NOT VALID;

ALTER TABLE order_fill
    ADD CONSTRAINT fk_order_fill_run_context_account_hour
    FOREIGN KEY (run_id, account_id, run_mode, hour_ts_utc)
    REFERENCES run_context (run_id, account_id, run_mode, hour_ts_utc)
    ON UPDATE RESTRICT
    ON DELETE RESTRICT
    NOT VALID;

ALTER TABLE position_lot
    ADD CONSTRAINT fk_position_lot_run_context_account_hour
    FOREIGN KEY (run_id, account_id, run_mode, hour_ts_utc)
    REFERENCES run_context (run_id, account_id, run_mode, hour_ts_utc)
    ON UPDATE RESTRICT
    ON DELETE RESTRICT
    NOT VALID;

ALTER TABLE executed_trade
    ADD CONSTRAINT fk_executed_trade_run_context_account_hour
    FOREIGN KEY (run_id, account_id, run_mode, hour_ts_utc)
    REFERENCES run_context (run_id, account_id, run_mode, hour_ts_utc)
    ON UPDATE RESTRICT
    ON DELETE RESTRICT
    NOT VALID;

ALTER TABLE cash_ledger
    ADD CONSTRAINT fk_cash_ledger_run_context_account_hour
    FOREIGN KEY (run_id, account_id, run_mode, hour_ts_utc)
    REFERENCES run_context (run_id, account_id, run_mode, hour_ts_utc)
    ON UPDATE RESTRICT
    ON DELETE RESTRICT
    NOT VALID;

ALTER TABLE position_hourly_state
    ADD CONSTRAINT fk_position_hourly_state_run_context_account_hour
    FOREIGN KEY (source_run_id, account_id, run_mode, hour_ts_utc)
    REFERENCES run_context (run_id, account_id, run_mode, hour_ts_utc)
    ON UPDATE RESTRICT
    ON DELETE RESTRICT
    NOT VALID;

ALTER TABLE portfolio_hourly_state
    ADD CONSTRAINT fk_portfolio_hourly_state_run_context_account_hour
    FOREIGN KEY (source_run_id, account_id, run_mode, hour_ts_utc)
    REFERENCES run_context (run_id, account_id, run_mode, hour_ts_utc)
    ON UPDATE RESTRICT
    ON DELETE RESTRICT
    NOT VALID;

ALTER TABLE risk_hourly_state
    ADD CONSTRAINT fk_risk_hourly_state_run_context_account_hour
    FOREIGN KEY (source_run_id, account_id, run_mode, hour_ts_utc)
    REFERENCES run_context (run_id, account_id, run_mode, hour_ts_utc)
    ON UPDATE RESTRICT
    ON DELETE RESTRICT
    NOT VALID;

ALTER TABLE risk_event
    ADD CONSTRAINT fk_risk_event_run_context_account_hour
    FOREIGN KEY (run_id, account_id, run_mode, hour_ts_utc)
    REFERENCES run_context (run_id, account_id, run_mode, hour_ts_utc)
    ON UPDATE RESTRICT
    ON DELETE RESTRICT
    NOT VALID;
```

### Constraint Type (Immediate / DEFERRABLE INITIALLY DEFERRED)
Immediate for unique and FK enforcement.

### Data Backfill Plan
No in-place updates. Constraint validation occurs after regenerated data load; legacy rows that fail are invalidated and excluded from cutover.

### Replay Impact
Every replay-authoritative execution row becomes account-isolated by structure, not by convention.

### Failure Risk If Skipped
Cross-account leakage remains possible, invalidating deterministic capital attribution and compliance evidence.

## M3 — Dual-Hour Temporal Refactor

### Purpose
Decouple decision hour from execution/event hour to support multi-hour lifecycle events without structural FK violations.

### Affected Tables
`run_context`, `order_request`, `order_fill`, `position_lot`, `executed_trade`, `cash_ledger`, `risk_event`.

### Exact DDL Operations
```sql
ALTER TABLE run_context
    ADD COLUMN origin_hour_ts_utc TIMESTAMPTZ;

UPDATE run_context
SET origin_hour_ts_utc = hour_ts_utc
WHERE origin_hour_ts_utc IS NULL;

ALTER TABLE run_context
    ALTER COLUMN origin_hour_ts_utc SET NOT NULL;

ALTER TABLE run_context
    ADD CONSTRAINT ck_run_context_origin_hour_aligned
    CHECK (date_trunc('hour', origin_hour_ts_utc) = origin_hour_ts_utc);

ALTER TABLE run_context
    ADD CONSTRAINT uq_run_context_run_account_mode_origin_hour
    UNIQUE (run_id, account_id, run_mode, origin_hour_ts_utc);

CREATE TABLE order_request_v2 (LIKE order_request INCLUDING ALL);
ALTER TABLE order_request_v2
    ADD COLUMN origin_hour_ts_utc TIMESTAMPTZ NOT NULL,
    ADD CONSTRAINT ck_order_request_v2_origin_hour_aligned CHECK (date_trunc('hour', origin_hour_ts_utc) = origin_hour_ts_utc),
    ADD CONSTRAINT ck_order_request_v2_request_after_origin CHECK (request_ts_utc >= origin_hour_ts_utc),
    ADD CONSTRAINT fk_order_request_v2_run_context_origin
        FOREIGN KEY (run_id, account_id, run_mode, origin_hour_ts_utc)
        REFERENCES run_context (run_id, account_id, run_mode, origin_hour_ts_utc)
        ON UPDATE RESTRICT ON DELETE RESTRICT;

CREATE TABLE order_fill_v2 (LIKE order_fill INCLUDING ALL);
ALTER TABLE order_fill_v2
    ADD COLUMN origin_hour_ts_utc TIMESTAMPTZ NOT NULL,
    ADD CONSTRAINT ck_order_fill_v2_origin_hour_aligned CHECK (date_trunc('hour', origin_hour_ts_utc) = origin_hour_ts_utc),
    ADD CONSTRAINT ck_order_fill_v2_fill_after_origin CHECK (fill_ts_utc >= origin_hour_ts_utc),
    ADD CONSTRAINT fk_order_fill_v2_run_context_origin
        FOREIGN KEY (run_id, account_id, run_mode, origin_hour_ts_utc)
        REFERENCES run_context (run_id, account_id, run_mode, origin_hour_ts_utc)
        ON UPDATE RESTRICT ON DELETE RESTRICT;

CREATE TABLE position_lot_v2 (LIKE position_lot INCLUDING ALL);
ALTER TABLE position_lot_v2
    ADD COLUMN origin_hour_ts_utc TIMESTAMPTZ NOT NULL,
    ADD CONSTRAINT ck_position_lot_v2_origin_hour_aligned CHECK (date_trunc('hour', origin_hour_ts_utc) = origin_hour_ts_utc),
    ADD CONSTRAINT ck_position_lot_v2_open_after_origin CHECK (open_ts_utc >= origin_hour_ts_utc),
    ADD CONSTRAINT fk_position_lot_v2_run_context_origin
        FOREIGN KEY (run_id, account_id, run_mode, origin_hour_ts_utc)
        REFERENCES run_context (run_id, account_id, run_mode, origin_hour_ts_utc)
        ON UPDATE RESTRICT ON DELETE RESTRICT;

CREATE TABLE executed_trade_v2 (LIKE executed_trade INCLUDING ALL);
ALTER TABLE executed_trade_v2
    ADD COLUMN origin_hour_ts_utc TIMESTAMPTZ NOT NULL,
    ADD CONSTRAINT ck_executed_trade_v2_origin_hour_aligned CHECK (date_trunc('hour', origin_hour_ts_utc) = origin_hour_ts_utc),
    ADD CONSTRAINT ck_executed_trade_v2_exit_after_origin CHECK (exit_ts_utc >= origin_hour_ts_utc),
    ADD CONSTRAINT fk_executed_trade_v2_run_context_origin
        FOREIGN KEY (run_id, account_id, run_mode, origin_hour_ts_utc)
        REFERENCES run_context (run_id, account_id, run_mode, origin_hour_ts_utc)
        ON UPDATE RESTRICT ON DELETE RESTRICT;

CREATE TABLE cash_ledger_v2 (LIKE cash_ledger INCLUDING ALL);
ALTER TABLE cash_ledger_v2
    ADD COLUMN origin_hour_ts_utc TIMESTAMPTZ NOT NULL,
    ADD CONSTRAINT ck_cash_ledger_v2_origin_hour_aligned CHECK (date_trunc('hour', origin_hour_ts_utc) = origin_hour_ts_utc),
    ADD CONSTRAINT ck_cash_ledger_v2_event_after_origin CHECK (event_ts_utc >= origin_hour_ts_utc),
    ADD CONSTRAINT fk_cash_ledger_v2_run_context_origin
        FOREIGN KEY (run_id, account_id, run_mode, origin_hour_ts_utc)
        REFERENCES run_context (run_id, account_id, run_mode, origin_hour_ts_utc)
        ON UPDATE RESTRICT ON DELETE RESTRICT;

CREATE TABLE risk_event_v2 (LIKE risk_event INCLUDING ALL);
ALTER TABLE risk_event_v2
    ADD COLUMN origin_hour_ts_utc TIMESTAMPTZ NOT NULL,
    ADD CONSTRAINT ck_risk_event_v2_origin_hour_aligned CHECK (date_trunc('hour', origin_hour_ts_utc) = origin_hour_ts_utc),
    ADD CONSTRAINT ck_risk_event_v2_event_after_origin CHECK (event_ts_utc >= origin_hour_ts_utc),
    ADD CONSTRAINT fk_risk_event_v2_run_context_origin
        FOREIGN KEY (run_id, account_id, run_mode, origin_hour_ts_utc)
        REFERENCES run_context (run_id, account_id, run_mode, origin_hour_ts_utc)
        ON UPDATE RESTRICT ON DELETE RESTRICT;

CREATE OR REPLACE FUNCTION fn_validate_execution_causality_v2()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_TABLE_NAME = 'order_fill_v2' THEN
        IF EXISTS (
            SELECT 1
            FROM order_request_v2 r
            WHERE r.order_id = NEW.order_id
              AND NEW.fill_ts_utc < r.request_ts_utc
        ) THEN
            RAISE EXCEPTION 'causality violation: fill before request for order %', NEW.order_id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE CONSTRAINT TRIGGER ctrg_order_fill_v2_causality
AFTER INSERT ON order_fill_v2
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fn_validate_execution_causality_v2();
```

### Constraint Type (Immediate / DEFERRABLE INITIALLY DEFERRED)
Immediate for structural FKs/CHECKs; DEFERRABLE INITIALLY DEFERRED for causality triggers crossing rows/tables.

### Data Backfill Plan
No legacy update in append-only tables. Populate `*_v2` tables only through deterministic replay regeneration with explicit `origin_hour_ts_utc`.

### Replay Impact
Execution lifecycle can span multiple event hours while remaining linked to original decision context.

### Failure Risk If Skipped
Legitimate fills/exits outside decision hour remain structurally invalid, forcing data distortion or dropped events.

## M4 — Ledger Chain Refactor

### Purpose
Enforce ordered cash arithmetic continuity with cryptographic linkage between ledger events.

### Affected Tables
`cash_ledger_v2`, `order_fill_v2`, `executed_trade_v2`, `backtest_run`.

### Exact DDL Operations
```sql
ALTER TABLE cash_ledger_v2
    ADD COLUMN ledger_seq BIGINT NOT NULL,
    ADD COLUMN balance_before NUMERIC(38,18) NOT NULL,
    ADD COLUMN prev_ledger_hash CHAR(64),
    ADD COLUMN economic_event_hash CHAR(64) NOT NULL,
    ADD COLUMN ledger_hash CHAR(64) NOT NULL;

ALTER TABLE cash_ledger_v2
    ADD CONSTRAINT uq_cash_ledger_v2_account_mode_seq
    UNIQUE (account_id, run_mode, ledger_seq);

ALTER TABLE cash_ledger_v2
    ADD CONSTRAINT ck_cash_ledger_v2_balance_chain
    CHECK (balance_after = balance_before + delta_cash);

ALTER TABLE cash_ledger_v2
    ADD CONSTRAINT ck_cash_ledger_v2_prev_hash_presence
    CHECK (
        (ledger_seq = 1 AND prev_ledger_hash IS NULL) OR
        (ledger_seq > 1 AND prev_ledger_hash IS NOT NULL)
    );

CREATE INDEX idx_cash_ledger_v2_account_mode_event_seq
    ON cash_ledger_v2 (account_id, run_mode, event_ts_utc, ledger_seq);

CREATE OR REPLACE FUNCTION fn_validate_cash_ledger_chain_v2()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    prev_row RECORD;
BEGIN
    SELECT ledger_seq, balance_after, ledger_hash
    INTO prev_row
    FROM cash_ledger_v2
    WHERE account_id = NEW.account_id
      AND run_mode = NEW.run_mode
      AND ledger_seq = NEW.ledger_seq - 1;

    IF NEW.ledger_seq > 1 THEN
        IF prev_row.ledger_seq IS NULL THEN
            RAISE EXCEPTION 'ledger gap for account %, mode %, seq %', NEW.account_id, NEW.run_mode, NEW.ledger_seq;
        END IF;
        IF NEW.balance_before <> prev_row.balance_after THEN
            RAISE EXCEPTION 'balance chain break at seq %', NEW.ledger_seq;
        END IF;
        IF NEW.prev_ledger_hash <> prev_row.ledger_hash THEN
            RAISE EXCEPTION 'hash chain break at seq %', NEW.ledger_seq;
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

CREATE CONSTRAINT TRIGGER ctrg_cash_ledger_v2_chain
AFTER INSERT ON cash_ledger_v2
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fn_validate_cash_ledger_chain_v2();
```

### Constraint Type (Immediate / DEFERRABLE INITIALLY DEFERRED)
Immediate for arithmetic/uniqueness; DEFERRABLE INITIALLY DEFERRED for chain continuity validation.

### Data Backfill Plan
Do not retrofit legacy `cash_ledger`. Recompute full ledger stream deterministically from regenerated execution events and initial capital state.

### Replay Impact
Cash movement becomes sequence-ordered, arithmetic-closed, and hash-chain verifiable.

### Failure Risk If Skipped
Silent ledger drift and non-deterministic balance reconstruction remain possible.

## M5 — Economic Formula Enforcement

### Purpose
Enforce exact fee/slippage/net-edge formulas at schema level; remove tolerance for implicit or inconsistent arithmetic.

### Affected Tables
`trade_signal_v2`, `order_fill_v2`, `executed_trade_v2`.

### Exact DDL Operations
```sql
ALTER TABLE trade_signal_v2
    ADD COLUMN expected_cost_rate NUMERIC(10,6)
        GENERATED ALWAYS AS (assumed_fee_rate + assumed_slippage_rate) STORED,
    ADD CONSTRAINT ck_trade_signal_v2_net_edge_formula
        CHECK (net_edge = expected_return - expected_cost_rate),
    ADD CONSTRAINT ck_trade_signal_v2_enter_cost_gate
        CHECK (action <> 'ENTER' OR expected_return > expected_cost_rate);

ALTER TABLE order_fill_v2
    ADD COLUMN fee_expected NUMERIC(38,18)
        GENERATED ALWAYS AS (fill_notional * fee_rate) STORED,
    ADD COLUMN slippage_cost NUMERIC(38,18) NOT NULL,
    ADD CONSTRAINT ck_order_fill_v2_fee_formula
        CHECK (fee_paid = fee_expected),
    ADD CONSTRAINT ck_order_fill_v2_slippage_formula
        CHECK (slippage_cost = fill_notional * realized_slippage_rate);

ALTER TABLE executed_trade_v2
    ADD CONSTRAINT ck_executed_trade_v2_net_pnl_formula
        CHECK (net_pnl = gross_pnl - total_fee - total_slippage_cost);

CREATE OR REPLACE FUNCTION fn_validate_trade_fee_rollup_v2()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM executed_trade_v2 et
        WHERE et.trade_id = NEW.trade_id
          AND et.total_fee < 0
    ) THEN
        RAISE EXCEPTION 'invalid total_fee rollup for trade %', NEW.trade_id;
    END IF;
    RETURN NEW;
END;
$$;

CREATE CONSTRAINT TRIGGER ctrg_executed_trade_v2_fee_rollup
AFTER INSERT ON executed_trade_v2
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fn_validate_trade_fee_rollup_v2();
```

### Constraint Type (Immediate / DEFERRABLE INITIALLY DEFERRED)
Immediate for row-level formulas; DEFERRABLE INITIALLY DEFERRED for cross-row aggregate consistency checks.

### Data Backfill Plan
No backfill edits on append-only history. Regenerate `trade_signal_v2`, `order_fill_v2`, `executed_trade_v2` so all rows satisfy exact formulas at insert time.

### Replay Impact
Economic outcomes become deterministic and formula-auditable across replay and production.

### Failure Risk If Skipped
PnL integrity becomes unverifiable and fee/slippage under-accounting can pass silently.

## M6 — Risk-State Binding Enforcement

### Purpose
Bind each decision/admission event to an exact risk-state snapshot and source run lineage.

### Affected Tables
`risk_hourly_state`, `trade_signal_v2`, `order_request_v2`.

### Exact DDL Operations
```sql
ALTER TABLE risk_hourly_state
    ADD CONSTRAINT uq_risk_hourly_state_with_source
    UNIQUE (run_mode, account_id, hour_ts_utc, source_run_id);

ALTER TABLE trade_signal_v2
    ADD COLUMN risk_state_run_id UUID NOT NULL,
    ADD CONSTRAINT fk_trade_signal_v2_risk_state_exact
        FOREIGN KEY (run_mode, account_id, risk_state_hour_ts_utc, risk_state_run_id)
        REFERENCES risk_hourly_state (run_mode, account_id, hour_ts_utc, source_run_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    ADD CONSTRAINT ck_trade_signal_v2_risk_not_future
        CHECK (risk_state_hour_ts_utc <= hour_ts_utc);

ALTER TABLE trade_signal_v2
    ADD CONSTRAINT uq_trade_signal_v2_signal_riskrun UNIQUE (signal_id, risk_state_run_id);

ALTER TABLE order_request_v2
    ADD COLUMN risk_state_run_id UUID NOT NULL,
    ADD CONSTRAINT fk_order_request_v2_signal_riskrun
        FOREIGN KEY (signal_id, risk_state_run_id)
        REFERENCES trade_signal_v2 (signal_id, risk_state_run_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT;

CREATE OR REPLACE FUNCTION fn_enforce_runtime_risk_gate_v2()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    halt_flag BOOLEAN;
    kill_flag BOOLEAN;
BEGIN
    SELECT halt_new_entries, kill_switch_active
    INTO halt_flag, kill_flag
    FROM risk_hourly_state
    WHERE run_mode = NEW.run_mode
      AND account_id = NEW.account_id
      AND hour_ts_utc = NEW.hour_ts_utc
      AND source_run_id = NEW.risk_state_run_id;

    IF NEW.status <> 'REJECTED' AND (halt_flag OR kill_flag) THEN
        RAISE EXCEPTION 'risk gate violation: halted or kill switch active';
    END IF;

    RETURN NEW;
END;
$$;

CREATE CONSTRAINT TRIGGER ctrg_order_request_v2_risk_gate
AFTER INSERT ON order_request_v2
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fn_enforce_runtime_risk_gate_v2();
```

### Constraint Type (Immediate / DEFERRABLE INITIALLY DEFERRED)
Immediate for FK and key constraints; DEFERRABLE INITIALLY DEFERRED for risk admission gate trigger.

### Data Backfill Plan
`risk_state_run_id` is populated only via regenerated decision stream from phase-1B replay.

### Replay Impact
Every signal/order is provably attached to an exact risk state used at decision time.

### Failure Risk If Skipped
Orders can be attributed to wrong risk snapshots, undermining halt and drawdown enforcement evidence.

## M7 — Cluster Exposure Model Introduction

### Purpose
Introduce enforceable correlation-cluster admission controls with persistent lineage and hourly exposure state.

### Affected Tables
New: `correlation_cluster`, `asset_cluster_membership`, `cluster_exposure_hourly_state`.  
Modified: `trade_signal_v2`, `order_request_v2`, `risk_hourly_state`.

### Exact DDL Operations
```sql
CREATE TABLE correlation_cluster (
    cluster_id SMALLINT GENERATED ALWAYS AS IDENTITY,
    cluster_code TEXT NOT NULL,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at_utc TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_correlation_cluster PRIMARY KEY (cluster_id),
    CONSTRAINT uq_correlation_cluster_code UNIQUE (cluster_code),
    CONSTRAINT ck_correlation_cluster_code_not_blank CHECK (length(btrim(cluster_code)) > 0)
);

CREATE TABLE asset_cluster_membership (
    membership_id BIGINT GENERATED ALWAYS AS IDENTITY,
    asset_id SMALLINT NOT NULL,
    cluster_id SMALLINT NOT NULL,
    effective_from_utc TIMESTAMPTZ NOT NULL,
    effective_to_utc TIMESTAMPTZ,
    membership_hash CHAR(64) NOT NULL,
    CONSTRAINT pk_asset_cluster_membership PRIMARY KEY (membership_id),
    CONSTRAINT uq_asset_cluster_membership_asset_effective_from UNIQUE (asset_id, effective_from_utc),
    CONSTRAINT ck_asset_cluster_membership_window CHECK (effective_to_utc IS NULL OR effective_to_utc > effective_from_utc),
    CONSTRAINT fk_asset_cluster_membership_asset FOREIGN KEY (asset_id)
        REFERENCES asset (asset_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_asset_cluster_membership_cluster FOREIGN KEY (cluster_id)
        REFERENCES correlation_cluster (cluster_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE cluster_exposure_hourly_state (
    run_mode run_mode_enum NOT NULL,
    account_id SMALLINT NOT NULL,
    cluster_id SMALLINT NOT NULL,
    hour_ts_utc TIMESTAMPTZ NOT NULL,
    source_run_id UUID NOT NULL,
    gross_exposure_notional NUMERIC(38,18) NOT NULL,
    exposure_pct NUMERIC(12,10) NOT NULL,
    max_cluster_exposure_pct NUMERIC(12,10) NOT NULL,
    state_hash CHAR(64) NOT NULL,
    CONSTRAINT pk_cluster_exposure_hourly_state PRIMARY KEY (run_mode, account_id, cluster_id, hour_ts_utc),
    CONSTRAINT ck_cluster_exposure_hourly_state_hour_aligned CHECK (date_trunc('hour', hour_ts_utc) = hour_ts_utc),
    CONSTRAINT ck_cluster_exposure_hourly_state_exposure_range CHECK (exposure_pct >= 0 AND exposure_pct <= 1),
    CONSTRAINT ck_cluster_exposure_hourly_state_cap_range CHECK (max_cluster_exposure_pct > 0 AND max_cluster_exposure_pct <= 0.08),
    CONSTRAINT fk_cluster_exposure_hourly_state_risk FOREIGN KEY (run_mode, account_id, hour_ts_utc, source_run_id)
        REFERENCES risk_hourly_state (run_mode, account_id, hour_ts_utc, source_run_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_cluster_exposure_hourly_state_cluster FOREIGN KEY (cluster_id)
        REFERENCES correlation_cluster (cluster_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE INDEX idx_asset_cluster_membership_asset_effective
    ON asset_cluster_membership (asset_id, effective_from_utc DESC);
CREATE INDEX idx_cluster_exposure_hourly_account_hour
    ON cluster_exposure_hourly_state (account_id, hour_ts_utc DESC);
CREATE INDEX idx_cluster_exposure_hourly_cluster_hour
    ON cluster_exposure_hourly_state (cluster_id, hour_ts_utc DESC);

ALTER TABLE trade_signal_v2
    ADD COLUMN cluster_membership_id BIGINT NOT NULL,
    ADD CONSTRAINT fk_trade_signal_v2_cluster_membership
        FOREIGN KEY (cluster_membership_id)
        REFERENCES asset_cluster_membership (membership_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT;

ALTER TABLE order_request_v2
    ADD COLUMN cluster_membership_id BIGINT NOT NULL;

ALTER TABLE trade_signal_v2
    ADD CONSTRAINT uq_trade_signal_v2_signal_cluster UNIQUE (signal_id, cluster_membership_id);

ALTER TABLE order_request_v2
    ADD CONSTRAINT fk_order_request_v2_signal_cluster
        FOREIGN KEY (signal_id, cluster_membership_id)
        REFERENCES trade_signal_v2 (signal_id, cluster_membership_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT;

CREATE OR REPLACE FUNCTION fn_enforce_cluster_cap_on_admission_v2()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    current_pct NUMERIC(12,10);
    cap_pct NUMERIC(12,10);
BEGIN
    SELECT coalesce(ce.exposure_pct, 0), ce.max_cluster_exposure_pct
    INTO current_pct, cap_pct
    FROM cluster_exposure_hourly_state ce
    JOIN asset_cluster_membership acm
      ON acm.membership_id = NEW.cluster_membership_id
     AND acm.cluster_id = ce.cluster_id
    WHERE ce.run_mode = NEW.run_mode
      AND ce.account_id = NEW.account_id
      AND ce.hour_ts_utc = NEW.hour_ts_utc
      AND ce.source_run_id = NEW.risk_state_run_id;

    IF current_pct > cap_pct THEN
        RAISE EXCEPTION 'cluster cap violation at admission';
    END IF;

    RETURN NEW;
END;
$$;

CREATE CONSTRAINT TRIGGER ctrg_order_request_v2_cluster_cap
AFTER INSERT ON order_request_v2
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fn_enforce_cluster_cap_on_admission_v2();
```

### Constraint Type (Immediate / DEFERRABLE INITIALLY DEFERRED)
Immediate for structural PK/FK/CHECK/indexed integrity; DEFERRABLE INITIALLY DEFERRED for admission-time exposure cap trigger.

### Data Backfill Plan
Backfill `correlation_cluster` and `asset_cluster_membership` from deterministic clustering snapshots; regenerate `cluster_exposure_hourly_state`, `trade_signal_v2`, and `order_request_v2` from replay engine.

### Replay Impact
Cluster exposure control becomes replay-auditable at admission and hourly state levels.

### Failure Risk If Skipped
Cluster cap remains policy-only and cannot be structurally enforced or audited.

## M8 — Walk-Forward Lineage Enforcement

### Purpose
Attach predictions and regime outputs to explicit fold lineage and block contamination by non-validation-window inference.

### Affected Tables
`model_training_window`, `backtest_fold_result`, `model_prediction_v2`, `regime_output_v2`, new `model_activation_gate`.

### Exact DDL Operations
```sql
ALTER TABLE model_training_window
    ADD COLUMN backtest_run_id UUID,
    ADD COLUMN training_window_hash CHAR(64);

UPDATE model_training_window mtw
SET backtest_run_id = bfr.backtest_run_id
FROM backtest_fold_result bfr
WHERE mtw.fold_index = bfr.fold_index
  AND mtw.valid_start_utc = bfr.valid_start_utc
  AND mtw.valid_end_utc = bfr.valid_end_utc
  AND mtw.backtest_run_id IS NULL;

ALTER TABLE model_training_window
    ALTER COLUMN backtest_run_id SET NOT NULL,
    ALTER COLUMN training_window_hash SET NOT NULL;

ALTER TABLE model_training_window
    DROP CONSTRAINT uq_model_training_window_model_fold_horizon;

ALTER TABLE model_training_window
    ADD CONSTRAINT uq_model_training_window_run_model_fold_horizon
    UNIQUE (backtest_run_id, model_version_id, fold_index, horizon);

ALTER TABLE model_training_window
    ADD CONSTRAINT fk_model_training_window_backtest_fold
    FOREIGN KEY (backtest_run_id, fold_index)
    REFERENCES backtest_fold_result (backtest_run_id, fold_index)
    ON UPDATE RESTRICT ON DELETE RESTRICT;

ALTER TABLE model_prediction_v2
    ADD COLUMN training_window_id BIGINT,
    ADD COLUMN lineage_backtest_run_id UUID,
    ADD COLUMN lineage_fold_index INTEGER,
    ADD CONSTRAINT fk_model_prediction_v2_training_window
        FOREIGN KEY (training_window_id)
        REFERENCES model_training_window (training_window_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    ADD CONSTRAINT fk_model_prediction_v2_lineage_fold
        FOREIGN KEY (lineage_backtest_run_id, lineage_fold_index)
        REFERENCES backtest_fold_result (backtest_run_id, fold_index)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    ADD CONSTRAINT ck_model_prediction_v2_mode_lineage
        CHECK (
            (run_mode = 'BACKTEST' AND training_window_id IS NOT NULL AND lineage_backtest_run_id IS NOT NULL AND lineage_fold_index IS NOT NULL)
            OR
            (run_mode IN ('PAPER','LIVE') AND training_window_id IS NULL AND lineage_backtest_run_id IS NULL AND lineage_fold_index IS NULL)
        );

ALTER TABLE regime_output_v2
    ADD COLUMN training_window_id BIGINT,
    ADD COLUMN lineage_backtest_run_id UUID,
    ADD COLUMN lineage_fold_index INTEGER,
    ADD CONSTRAINT fk_regime_output_v2_training_window
        FOREIGN KEY (training_window_id)
        REFERENCES model_training_window (training_window_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    ADD CONSTRAINT fk_regime_output_v2_lineage_fold
        FOREIGN KEY (lineage_backtest_run_id, lineage_fold_index)
        REFERENCES backtest_fold_result (backtest_run_id, fold_index)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    ADD CONSTRAINT ck_regime_output_v2_mode_lineage
        CHECK (
            (run_mode = 'BACKTEST' AND training_window_id IS NOT NULL AND lineage_backtest_run_id IS NOT NULL AND lineage_fold_index IS NOT NULL)
            OR
            (run_mode IN ('PAPER','LIVE') AND training_window_id IS NULL AND lineage_backtest_run_id IS NULL AND lineage_fold_index IS NULL)
        );

CREATE TABLE model_activation_gate (
    activation_id BIGINT GENERATED ALWAYS AS IDENTITY,
    model_version_id BIGINT NOT NULL,
    run_mode run_mode_enum NOT NULL,
    validation_backtest_run_id UUID NOT NULL,
    validation_window_end_utc TIMESTAMPTZ NOT NULL,
    approved_at_utc TIMESTAMPTZ NOT NULL DEFAULT now(),
    status TEXT NOT NULL,
    approval_hash CHAR(64) NOT NULL,
    CONSTRAINT pk_model_activation_gate PRIMARY KEY (activation_id),
    CONSTRAINT ck_model_activation_gate_status CHECK (status IN ('APPROVED', 'REVOKED')),
    CONSTRAINT fk_model_activation_gate_model FOREIGN KEY (model_version_id)
        REFERENCES model_version (model_version_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_model_activation_gate_backtest FOREIGN KEY (validation_backtest_run_id)
        REFERENCES backtest_run (backtest_run_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE UNIQUE INDEX uqix_model_activation_gate_one_approved
    ON model_activation_gate (model_version_id, run_mode)
    WHERE status = 'APPROVED';

ALTER TABLE model_prediction_v2
    ADD COLUMN activation_id BIGINT,
    ADD CONSTRAINT fk_model_prediction_v2_activation
        FOREIGN KEY (activation_id)
        REFERENCES model_activation_gate (activation_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    ADD CONSTRAINT ck_model_prediction_v2_activation_mode
        CHECK (
            (run_mode = 'BACKTEST' AND activation_id IS NULL)
            OR
            (run_mode IN ('PAPER','LIVE') AND activation_id IS NOT NULL)
        );

ALTER TABLE regime_output_v2
    ADD COLUMN activation_id BIGINT,
    ADD CONSTRAINT fk_regime_output_v2_activation
        FOREIGN KEY (activation_id)
        REFERENCES model_activation_gate (activation_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    ADD CONSTRAINT ck_regime_output_v2_activation_mode
        CHECK (
            (run_mode = 'BACKTEST' AND activation_id IS NULL)
            OR
            (run_mode IN ('PAPER','LIVE') AND activation_id IS NOT NULL)
        );

CREATE OR REPLACE FUNCTION fn_enforce_walk_forward_window_v2()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    w RECORD;
BEGIN
    IF NEW.run_mode = 'BACKTEST' THEN
        SELECT train_end_utc, valid_start_utc, valid_end_utc
        INTO w
        FROM model_training_window
        WHERE training_window_id = NEW.training_window_id;

        IF NEW.hour_ts_utc < w.valid_start_utc OR NEW.hour_ts_utc >= w.valid_end_utc OR NEW.hour_ts_utc <= w.train_end_utc THEN
            RAISE EXCEPTION 'walk-forward contamination violation';
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

CREATE CONSTRAINT TRIGGER ctrg_model_prediction_v2_walk_forward
AFTER INSERT ON model_prediction_v2
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fn_enforce_walk_forward_window_v2();

CREATE CONSTRAINT TRIGGER ctrg_regime_output_v2_walk_forward
AFTER INSERT ON regime_output_v2
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fn_enforce_walk_forward_window_v2();
```

### Constraint Type (Immediate / DEFERRABLE INITIALLY DEFERRED)
Immediate for FK/nullability mode gates; DEFERRABLE INITIALLY DEFERRED for contamination-proof window checks.

### Data Backfill Plan
Regenerate backtest predictions/regime rows with explicit lineage columns; no blind backfill accepted.

### Replay Impact
Every BACKTEST prediction/regime record becomes fold-lineage verifiable and contamination-auditable.

### Failure Risk If Skipped
Walk-forward leakage remains structurally possible, invalidating model performance evidence.

## M9 — Hash Propagation Introduction

### Purpose
Propagate deterministic row hashes across all replay-authoritative lineage edges and materialize run-level replay roots.

### Affected Tables
`run_context`, `backtest_run`, `model_training_window`, `backtest_fold_result`, `market_ohlcv_hourly`, `order_book_snapshot`, `feature_snapshot`, `regime_output_v2`, `model_prediction_v2`, `meta_learner_component`, `trade_signal_v2`, `order_request_v2`, `order_fill_v2`, `position_lot_v2`, `executed_trade_v2`, `cash_ledger_v2`, `position_hourly_state`, `portfolio_hourly_state`, `risk_hourly_state`, `risk_event_v2`, `cluster_exposure_hourly_state`, new `replay_manifest`.

### Exact DDL Operations
```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE replay_manifest (
    run_id UUID NOT NULL,
    account_id SMALLINT NOT NULL,
    run_mode run_mode_enum NOT NULL,
    origin_hour_ts_utc TIMESTAMPTZ NOT NULL,
    run_seed_hash CHAR(64) NOT NULL,
    replay_root_hash CHAR(64) NOT NULL,
    authoritative_row_count BIGINT NOT NULL,
    generated_at_utc TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_replay_manifest PRIMARY KEY (run_id),
    CONSTRAINT fk_replay_manifest_run_context FOREIGN KEY (run_id, account_id, run_mode, origin_hour_ts_utc)
        REFERENCES run_context (run_id, account_id, run_mode, origin_hour_ts_utc)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

ALTER TABLE run_context
    ADD COLUMN run_seed_hash CHAR(64),
    ADD COLUMN context_hash CHAR(64),
    ADD COLUMN replay_root_hash CHAR(64);

ALTER TABLE backtest_run            ADD COLUMN row_hash CHAR(64);
ALTER TABLE model_training_window   ADD COLUMN row_hash CHAR(64);
ALTER TABLE backtest_fold_result    ADD COLUMN row_hash CHAR(64);
ALTER TABLE market_ohlcv_hourly     ADD COLUMN row_hash CHAR(64);
ALTER TABLE order_book_snapshot     ADD COLUMN row_hash CHAR(64);
ALTER TABLE feature_snapshot        ADD COLUMN row_hash CHAR(64);
ALTER TABLE meta_learner_component  ADD COLUMN row_hash CHAR(64);
ALTER TABLE position_hourly_state   ADD COLUMN row_hash CHAR(64);
ALTER TABLE portfolio_hourly_state  ADD COLUMN row_hash CHAR(64);
ALTER TABLE risk_hourly_state       ADD COLUMN row_hash CHAR(64);

ALTER TABLE regime_output_v2
    ADD COLUMN upstream_hash CHAR(64) NOT NULL,
    ADD COLUMN row_hash CHAR(64) NOT NULL;

ALTER TABLE model_prediction_v2
    ADD COLUMN upstream_hash CHAR(64) NOT NULL,
    ADD COLUMN row_hash CHAR(64) NOT NULL;

ALTER TABLE trade_signal_v2
    ADD COLUMN upstream_hash CHAR(64) NOT NULL,
    ADD COLUMN row_hash CHAR(64) NOT NULL;

ALTER TABLE order_request_v2
    ADD COLUMN parent_signal_hash CHAR(64) NOT NULL,
    ADD COLUMN row_hash CHAR(64) NOT NULL;

ALTER TABLE order_fill_v2
    ADD COLUMN parent_order_hash CHAR(64) NOT NULL,
    ADD COLUMN row_hash CHAR(64) NOT NULL;

ALTER TABLE position_lot_v2
    ADD COLUMN parent_fill_hash CHAR(64) NOT NULL,
    ADD COLUMN row_hash CHAR(64) NOT NULL;

ALTER TABLE executed_trade_v2
    ADD COLUMN parent_lot_hash CHAR(64) NOT NULL,
    ADD COLUMN row_hash CHAR(64) NOT NULL;

ALTER TABLE cash_ledger_v2
    ADD COLUMN row_hash CHAR(64) NOT NULL;

ALTER TABLE risk_event_v2
    ADD COLUMN parent_state_hash CHAR(64) NOT NULL,
    ADD COLUMN row_hash CHAR(64) NOT NULL;

ALTER TABLE cluster_exposure_hourly_state
    ADD COLUMN parent_risk_hash CHAR(64) NOT NULL,
    ADD COLUMN row_hash CHAR(64) NOT NULL;

CREATE OR REPLACE FUNCTION fn_sha256_hex(input_text TEXT)
RETURNS CHAR(64)
LANGUAGE SQL
IMMUTABLE
AS $$
    SELECT encode(digest(input_text, 'sha256'), 'hex')::char(64);
$$;

CREATE OR REPLACE FUNCTION fn_assert_parent_hash_not_null()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.row_hash IS NULL THEN
        RAISE EXCEPTION 'row_hash cannot be null on %', TG_TABLE_NAME;
    END IF;
    RETURN NEW;
END;
$$;
```

### Constraint Type (Immediate / DEFERRABLE INITIALLY DEFERRED)
Immediate for NOT NULL/hash presence; DEFERRABLE INITIALLY DEFERRED for cross-table parent-hash continuity checks during batched inserts.

### Data Backfill Plan
Reference/raw tables: deterministic backfill into v2/hashed rows.  
Decision/execution/risk/accounting tables: full regeneration only; hashes computed during insert using canonical preimages and `run_seed_hash`.

### Replay Impact
All replay-authoritative lineage rows become hash-bound, and each run produces a deterministic `replay_root_hash`.

### Failure Risk If Skipped
End-to-end integrity proof remains incomplete; replay parity cannot be cryptographically attested.

## M10 — Constraint Hardening & Final Validation

### Purpose
Finalize constraints, perform atomic table cutover, restore Timescale policies, and lock schema contract v1.0.

### Affected Tables
All modified canonical tables and all `*_v2` replacements; hypertables with compression policies; append-only trigger targets.

### Exact DDL Operations
```sql
ALTER TABLE trade_signal              VALIDATE CONSTRAINT fk_trade_signal_run_context_account_hour;
ALTER TABLE order_request             VALIDATE CONSTRAINT fk_order_request_run_context_account_hour;
ALTER TABLE order_fill                VALIDATE CONSTRAINT fk_order_fill_run_context_account_hour;
ALTER TABLE position_lot              VALIDATE CONSTRAINT fk_position_lot_run_context_account_hour;
ALTER TABLE executed_trade            VALIDATE CONSTRAINT fk_executed_trade_run_context_account_hour;
ALTER TABLE cash_ledger               VALIDATE CONSTRAINT fk_cash_ledger_run_context_account_hour;
ALTER TABLE position_hourly_state     VALIDATE CONSTRAINT fk_position_hourly_state_run_context_account_hour;
ALTER TABLE portfolio_hourly_state    VALIDATE CONSTRAINT fk_portfolio_hourly_state_run_context_account_hour;
ALTER TABLE risk_hourly_state         VALIDATE CONSTRAINT fk_risk_hourly_state_run_context_account_hour;
ALTER TABLE risk_event                VALIDATE CONSTRAINT fk_risk_event_run_context_account_hour;

BEGIN;
LOCK TABLE order_request, order_fill, position_lot, executed_trade, cash_ledger, risk_event IN ACCESS EXCLUSIVE MODE;

ALTER TABLE order_request RENAME TO order_request_phase1a_archive;
ALTER TABLE order_fill RENAME TO order_fill_phase1a_archive;
ALTER TABLE position_lot RENAME TO position_lot_phase1a_archive;
ALTER TABLE executed_trade RENAME TO executed_trade_phase1a_archive;
ALTER TABLE cash_ledger RENAME TO cash_ledger_phase1a_archive;
ALTER TABLE risk_event RENAME TO risk_event_phase1a_archive;

ALTER TABLE order_request_v2 RENAME TO order_request;
ALTER TABLE order_fill_v2 RENAME TO order_fill;
ALTER TABLE position_lot_v2 RENAME TO position_lot;
ALTER TABLE executed_trade_v2 RENAME TO executed_trade;
ALTER TABLE cash_ledger_v2 RENAME TO cash_ledger;
ALTER TABLE risk_event_v2 RENAME TO risk_event;
COMMIT;

CREATE OR REPLACE FUNCTION fn_enforce_append_only()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'append-only violation on table %, operation % is not allowed', TG_TABLE_NAME, TG_OP;
END;
$$;

CREATE TRIGGER trg_order_fill_append_only
BEFORE UPDATE OR DELETE ON order_fill
FOR EACH ROW EXECUTE FUNCTION fn_enforce_append_only();

CREATE TRIGGER trg_cash_ledger_append_only
BEFORE UPDATE OR DELETE ON cash_ledger
FOR EACH ROW EXECUTE FUNCTION fn_enforce_append_only();

CREATE TRIGGER trg_risk_event_append_only
BEFORE UPDATE OR DELETE ON risk_event
FOR EACH ROW EXECUTE FUNCTION fn_enforce_append_only();

SELECT add_compression_policy('feature_snapshot', INTERVAL '14 days', if_not_exists => TRUE);
SELECT add_compression_policy('model_prediction', INTERVAL '14 days', if_not_exists => TRUE);
SELECT add_compression_policy('meta_learner_component', INTERVAL '14 days', if_not_exists => TRUE);
SELECT add_compression_policy('order_fill', INTERVAL '14 days', if_not_exists => TRUE);
SELECT add_compression_policy('cash_ledger', INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_compression_policy('position_hourly_state', INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_compression_policy('portfolio_hourly_state', INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_compression_policy('risk_hourly_state', INTERVAL '30 days', if_not_exists => TRUE);

UPDATE schema_migration_control
SET locked = FALSE, unlocked_at_utc = now()
WHERE migration_name = 'phase_1b_schema';
```

### Constraint Type (Immediate / DEFERRABLE INITIALLY DEFERRED)
Immediate validation at cutover; DEFERRABLE INITIALLY DEFERRED triggers remain active for multi-row invariants (causality, ledger chain, cluster cap, walk-forward contamination).

### Data Backfill Plan
No additional backfill in M10. Only cutover to fully regenerated and pre-validated phase-1B tables.

### Replay Impact
Canonical schema now enforces deterministic replay contract v1.0 in production objects.

### Failure Risk If Skipped
Migration remains partial, leaving mixed-contract tables and unverifiable deterministic lineage.

# 3. Temporal Refactor Specification

- `origin_hour_ts_utc` is introduced in `run_context` as the immutable decision-hour anchor.
- Event-hour remains represented by existing `hour_ts_utc` columns in event tables (`order_request`, `order_fill`, `position_lot`, `executed_trade`, `cash_ledger`, `risk_event`) and always maps to actual event timestamp buckets.
- `run_context` FKs are migrated from hour-coupled form:
  - `(run_id, run_mode, hour_ts_utc)`
  to origin-bound account-isolated form:
  - `(run_id, account_id, run_mode, origin_hour_ts_utc)`.
- Hour-coupled run-context FKs are removed from execution/accounting tables during cutover and replaced by origin-bound FKs.
- Causality enforcement constraints:
  - `order_request.request_ts_utc >= origin_hour_ts_utc`
  - `order_fill.fill_ts_utc >= order_request.request_ts_utc` (deferred trigger)
  - `position_lot.open_ts_utc >= order_fill.fill_ts_utc` (deferred trigger)
  - `executed_trade.exit_ts_utc >= executed_trade.entry_ts_utc` (immediate check)
  - `cash_ledger.event_ts_utc >= origin_hour_ts_utc`
- Multi-hour lifecycle safety:
  - No constraint requires event timestamps to remain within origin decision hour.
  - Event bucket (`hour_ts_utc`) and origin decision hour (`origin_hour_ts_utc`) are intentionally decoupled.

Execution rows can exist outside decision hour without structural violation.

# 4. Ledger Chain Reconstruction Plan

- `ledger_seq` generation logic:
  - Deterministic `ROW_NUMBER()` partitioned by `(run_mode, account_id)` and ordered by:
    1. `event_ts_utc`
    2. `origin_hour_ts_utc`
    3. `event_type`
    4. `ref_type`
    5. `ref_id`
    6. `run_id`
    7. stable ingest surrogate
- `prev_ledger_hash` generation logic:
  - `LAG(ledger_hash)` over the same partition/order.
  - Must be `NULL` only for `ledger_seq = 1`.
- `balance_before` derivation:
  - `ledger_seq = 1`: from deterministic initial account capital snapshot for the run/mode.
  - `ledger_seq > 1`: previous row `balance_after`.
- `economic_event_hash` generation:
  - SHA256 over canonical preimage:
    - `run_seed_hash`
    - `run_id`, `account_id`, `run_mode`
    - `origin_hour_ts_utc`, `event_ts_utc`
    - `event_type`, `ref_type`, `ref_id`
    - `delta_cash`, `balance_before`, `balance_after`
    - parent execution hash (order/fill/trade lineage key)
- Required ordering guarantees:
  - No ties without deterministic tie-break key.
  - Insert order must be irrelevant; chain order always materialized by deterministic sort tuple above.
  - Chain validator runs deferred at transaction end.
- Full ledger recomputation:
  - Mandatory from deterministic execution event stream to avoid append-only update bypass and to guarantee contiguous sequence/hash chain.

FULL REGENERATION REQUIRED

# 5. Hash Propagation Implementation Plan

- New hash columns per table:
  - `run_context`: `run_seed_hash`, `context_hash`, `replay_root_hash`
  - `backtest_run`, `model_training_window`, `backtest_fold_result`: `row_hash`
  - `market_ohlcv_hourly`, `order_book_snapshot`, `feature_snapshot`, `meta_learner_component`, `position_hourly_state`, `portfolio_hourly_state`, `risk_hourly_state`: `row_hash`
  - `regime_output`, `model_prediction`: `upstream_hash`, `row_hash`
  - `trade_signal`: `upstream_hash`, `row_hash`
  - `order_request`: `parent_signal_hash`, `row_hash`
  - `order_fill`: `parent_order_hash`, `row_hash`
  - `position_lot`: `parent_fill_hash`, `row_hash`
  - `executed_trade`: `parent_lot_hash`, `row_hash`
  - `cash_ledger`: `economic_event_hash`, `prev_ledger_hash`, `ledger_hash`, `row_hash`
  - `risk_event`: `parent_state_hash`, `row_hash`
  - `cluster_exposure_hourly_state`: `parent_risk_hash`, `row_hash`
  - `replay_manifest`: `run_seed_hash`, `replay_root_hash`

- Preimage canonicalization rules:
  - Delimiter: pipe (`|`) with fixed field order per table contract.
  - Null encoding: literal `\N`.
  - Timestamp encoding: UTC ISO-8601 with microseconds.
  - Numeric encoding: fixed-scale canonical decimal string (`NUMERIC(38,18)` normalized; `-0` canonicalized to `0`).
  - Enum/text encoding: trimmed exact value, case preserved unless constrained uppercase by schema.
  - JSON encoding: sorted keys, no whitespace, stable canonical serializer.
  - Hash algorithm: SHA256 hex lower-case, exactly 64 chars.

- `run_seed` integration:
  - `run_seed_hash = SHA256(run_id|account_id|run_mode|origin_hour_ts_utc|random_seed|config_hash|data_snapshot_hash|code_version_sha)`.
  - Every replay-authoritative row preimage must include `run_seed_hash` as first token.

- `replay_root_hash` generation:
  - For each table `T`, compute `table_hash_T = SHA256(string_agg(row_hash ORDER BY deterministic_primary_key))`.
  - Ordered table list is fixed and versioned.
  - `replay_root_hash = SHA256(run_seed_hash|table_hash_1|...|table_hash_n|authoritative_row_count)`.
  - Persisted in both `run_context.replay_root_hash` and `replay_manifest.replay_root_hash`.

- Upstream inclusion rules:
  - Decision rows must include hashes of immediate model/risk inputs.
  - Execution rows must include hashes of parent decision/order lineage.
  - Ledger rows must include hashes of economic source events.
  - Risk/cluster rows must include upstream portfolio/risk hashes.

- Backfill vs regeneration strategy:
  - Raw/reference context rows: deterministic backfill permitted.
  - Decision/execution/risk/accounting rows: regeneration only.
  - No UPDATE-based retrofit on append-only tables.

All replay-authoritative rows must end this phase hash-bound.

# 6. Walk-Forward Enforcement Plan

- `model_training_window` augmentation:
  - Add `backtest_run_id` and `training_window_hash`.
  - Add FK `(backtest_run_id, fold_index) -> backtest_fold_result(backtest_run_id, fold_index)`.
  - Replace uniqueness with `(backtest_run_id, model_version_id, fold_index, horizon)`.

- FK linkage to `backtest_fold_result`:
  - Enforced directly in `model_training_window`.
  - Propagated to prediction/regime outputs via lineage columns.

- `model_prediction` and `regime_output` augmentation:
  - Add `training_window_id`, `lineage_backtest_run_id`, `lineage_fold_index`.
  - Add FK to `model_training_window(training_window_id)`.
  - Add FK to `backtest_fold_result(backtest_run_id, fold_index)`.
  - Add `activation_id` FK to `model_activation_gate` for PAPER/LIVE enforcement.

- Mode-specific nullability enforcement:
  - BACKTEST: lineage columns required, `activation_id` must be null.
  - PAPER/LIVE: lineage columns must be null, `activation_id` required and must reference approved activation record.

- Contamination-proof constraints:
  - Deferred trigger verifies BACKTEST prediction/regime `hour_ts_utc` is in `[valid_start_utc, valid_end_utc)`.
  - Deferred trigger verifies `hour_ts_utc > train_end_utc` for linked training window.
  - Violations hard-fail transaction.

# 7. Cluster Exposure Enforcement Plan

- New cluster tables:
  - `correlation_cluster`: cluster registry.
  - `asset_cluster_membership`: time-bounded asset-to-cluster assignment.
  - `cluster_exposure_hourly_state`: per-account per-cluster hourly exposure state with cap.

- Required indexes:
  - `idx_asset_cluster_membership_asset_effective` on `(asset_id, effective_from_utc DESC)`.
  - `idx_cluster_exposure_hourly_account_hour` on `(account_id, hour_ts_utc DESC)`.
  - `idx_cluster_exposure_hourly_cluster_hour` on `(cluster_id, hour_ts_utc DESC)`.
  - Unique cluster code index and active-approved activation index remain mandatory.

- Admission-time binding:
  - `trade_signal.cluster_membership_id` required.
  - `order_request.cluster_membership_id` required and FK-coupled to signal binding.
  - Admission trigger computes projected cluster exposure and rejects cap violations.

- Exposure calculation invariants:
  - `0 <= exposure_pct <= 1`.
  - `0 < max_cluster_exposure_pct <= 0.08`.
  - `exposure_pct <= max_cluster_exposure_pct` enforced by deferred trigger with risk-state source binding.

- Backfill or reset policy:
  - `correlation_cluster` and `asset_cluster_membership` are deterministic backfilled from archived clustering snapshots.
  - `cluster_exposure_hourly_state` is regenerated from replay; no legacy carry-forward reset bypass.

# 8. Data Invalidation & Regeneration Matrix

| Table | Drop Required | Backfill Possible | Full Regeneration Required | Reason |
|---|---|---|---|---|
| `asset` | No | No | No | Static reference table; no phase-1B structural dependency. |
| `account` | No | No | No | Static account master; preserved as-is. |
| `cost_profile` | No | No | No | Fee/slippage parameters already canonical and locked. |
| `model_version` | No | No | No | Model identities preserved; activation gating added separately. |
| `feature_definition` | No | No | No | Feature catalog unchanged structurally. |
| `backtest_run` | No | Yes | No | Additive hash columns can be deterministic backfilled. |
| `run_context` | Yes | No | Yes | Introduces `origin_hour_ts_utc`, run-seed/root-hash contract, account-bound origin keys. |
| `model_training_window` | Yes | No | Yes | Requires fold FK lineage and contamination-safe uniqueness remap. |
| `backtest_fold_result` | Yes | No | Yes | Must align with new lineage/hash contract and regenerated backtests. |
| `market_ohlcv_hourly` | Yes | Yes | No | Hash-bound v2 rebuild from immutable raw market rows. |
| `order_book_snapshot` | Yes | Yes | No | Hash-bound v2 rebuild from immutable snapshot rows. |
| `feature_snapshot` | Yes | No | Yes | Replay-authoritative feature lineage must be regenerated under new hash contract. |
| `regime_output` | Yes | No | Yes | Walk-forward lineage + activation gating + hash propagation required. |
| `model_prediction` | Yes | No | Yes | Walk-forward lineage + activation gating + hash propagation required. |
| `meta_learner_component` | Yes | No | Yes | Upstream hash lineage required for deterministic replay root. |
| `trade_signal` | Yes | No | Yes | Risk-state run binding, cluster binding, exact economic formula, hash chain. |
| `order_request` | Yes | No | Yes | Origin-hour decoupling, risk/cluster binding, parent hash propagation. |
| `order_fill` | Yes | No | Yes | Origin-hour decoupling, fee/slippage formula hard checks, parent hash propagation. |
| `position_lot` | Yes | No | Yes | Multi-hour causal lineage and parent-hash continuity required. |
| `executed_trade` | Yes | No | Yes | Net formula hardening + parent-lot hash and multi-hour lineage. |
| `cash_ledger` | Yes | No | Yes | Ledger sequence/hash chain and balance-before continuity require full rebuild. |
| `position_hourly_state` | Yes | No | Yes | Replay/hash lineage and strict run-account binding under new contract. |
| `portfolio_hourly_state` | Yes | No | Yes | Replay/hash lineage and strict run-account binding under new contract. |
| `risk_hourly_state` | Yes | No | Yes | Source-run bound risk-state key required for admission enforcement. |
| `risk_event` | Yes | No | Yes | Origin-hour linkage + parent risk hash propagation required. |
| `correlation_cluster` | No | Yes | No | New registry table initialized from deterministic cluster taxonomy. |
| `asset_cluster_membership` | No | Yes | No | New time-bounded membership table backfilled from cluster snapshots. |
| `cluster_exposure_hourly_state` | No | No | Yes | New replay-authoritative risk state requiring regeneration. |
| `model_activation_gate` | No | Yes | No | New gating table backfilled from approved validation records. |
| `replay_manifest` | No | No | Yes | New run-level replay root evidence generated from regenerated rows. |

# 9. Post-Migration Validation Protocol

- Cross-account isolation:
```sql
SELECT COUNT(*) AS violations
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
) s;
```
Pass criterion: `violations = 0`.

- Ledger arithmetic continuity:
```sql
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
        LAG(balance_after) OVER (PARTITION BY account_id, run_mode ORDER BY ledger_seq) AS expected_before,
        LAG(ledger_hash) OVER (PARTITION BY account_id, run_mode ORDER BY ledger_seq) AS expected_prev_hash
    FROM cash_ledger
)
SELECT COUNT(*) AS violations
FROM ordered
WHERE balance_after <> balance_before + delta_cash
   OR (ledger_seq > 1 AND balance_before <> expected_before)
   OR (ledger_seq > 1 AND prev_ledger_hash <> expected_prev_hash);
```
Pass criterion: `violations = 0`.

- Fee formula correctness:
```sql
SELECT COUNT(*) AS violations
FROM order_fill
WHERE fee_paid <> fill_notional * fee_rate;
```
Pass criterion: `violations = 0`.

- Slippage formula correctness:
```sql
SELECT COUNT(*) AS violations
FROM order_fill
WHERE slippage_cost <> fill_notional * realized_slippage_rate;
```
Pass criterion: `violations = 0`.

- Quantity conservation:
```sql
SELECT COUNT(*) AS violations
FROM position_lot
WHERE remaining_qty < 0 OR remaining_qty > open_qty;
```
Pass criterion: `violations = 0`.

- Long-only enforcement:
```sql
SELECT COUNT(*) AS violations
FROM position_hourly_state
WHERE quantity < 0;
```
Pass criterion: `violations = 0`.

- Cluster cap enforcement:
```sql
SELECT COUNT(*) AS violations
FROM cluster_exposure_hourly_state
WHERE exposure_pct > max_cluster_exposure_pct;
```
Pass criterion: `violations = 0`.

- Walk-forward contamination exclusion:
```sql
SELECT COUNT(*) AS violations
FROM model_prediction mp
JOIN model_training_window tw
  ON tw.training_window_id = mp.training_window_id
WHERE mp.run_mode = 'BACKTEST'
  AND (
      mp.hour_ts_utc < tw.valid_start_utc
      OR mp.hour_ts_utc >= tw.valid_end_utc
      OR mp.hour_ts_utc <= tw.train_end_utc
  );
```
Pass criterion: `violations = 0`.

- Hash continuity:
```sql
SELECT COUNT(*) AS missing_hashes
FROM (
    SELECT row_hash FROM feature_snapshot
    UNION ALL SELECT row_hash FROM regime_output
    UNION ALL SELECT row_hash FROM model_prediction
    UNION ALL SELECT row_hash FROM trade_signal
    UNION ALL SELECT row_hash FROM order_request
    UNION ALL SELECT row_hash FROM order_fill
    UNION ALL SELECT row_hash FROM position_lot
    UNION ALL SELECT row_hash FROM executed_trade
    UNION ALL SELECT row_hash FROM cash_ledger
) h
WHERE row_hash IS NULL;
```
Pass criterion: `missing_hashes = 0`.

- Deterministic replay parity:
```sql
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
  AND a.run_seed_hash = b.run_seed_hash;
```
Pass criterion: all compared pairs have `root_hash_match = TRUE` and `row_count_match = TRUE`.

# 10. Architect Final Declaration

APPROVED FOR IMPLEMENTATION
