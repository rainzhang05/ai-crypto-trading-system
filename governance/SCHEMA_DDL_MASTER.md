# AI CRYPTO TRADING SYSTEM
## MASTER SCHEMA DDL CONTRACT
Version: 1.0
Status: LOCKED
Scope: Production Trading Core
Database: PostgreSQL + TimescaleDB (GCP Cloud SQL)

---

# ENUM DEFINITIONS

CREATE TYPE run_mode_enum AS ENUM ('BACKTEST', 'PAPER', 'LIVE');
CREATE TYPE horizon_enum AS ENUM ('H1', 'H4', 'H24');
CREATE TYPE model_role_enum AS ENUM ('BASE_TREE', 'BASE_DEEP', 'REGIME', 'META');
CREATE TYPE signal_action_enum AS ENUM ('ENTER', 'EXIT', 'HOLD');
CREATE TYPE order_side_enum AS ENUM ('BUY', 'SELL');
CREATE TYPE order_type_enum AS ENUM ('LIMIT', 'MARKET');
CREATE TYPE order_status_enum AS ENUM ('NEW', 'ACK', 'PARTIAL', 'FILLED', 'CANCELLED', 'REJECTED');
CREATE TYPE drawdown_tier_enum AS ENUM ('NORMAL', 'DD10', 'DD15', 'HALT20');

---

# TABLE DEFINITIONS (CORRECTED + FINAL)

-- NOTE:
-- NUMERIC(38,18) used for all monetary fields.
-- All timestamps stored as TIMESTAMPTZ in UTC.
-- All financial invariants enforced at schema level.

------------------------------------------------------------
-- run_context (FIXED UNIQUE SET)
------------------------------------------------------------

CREATE TABLE run_context (
    run_id UUID NOT NULL,
    account_id SMALLINT NOT NULL,
    run_mode run_mode_enum NOT NULL,
    hour_ts_utc TIMESTAMPTZ NOT NULL,
    cycle_seq BIGINT NOT NULL,
    code_version_sha CHAR(40) NOT NULL,
    config_hash CHAR(64) NOT NULL,
    data_snapshot_hash CHAR(64) NOT NULL,
    random_seed INTEGER NOT NULL,
    backtest_run_id UUID,
    started_at_utc TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at_utc TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'STARTED',

    CONSTRAINT pk_run_context PRIMARY KEY (run_id),

    CONSTRAINT uq_run_context_account_mode_hour
        UNIQUE (account_id, run_mode, hour_ts_utc),

    CONSTRAINT uq_run_context_run_mode_hour
        UNIQUE (run_id, run_mode, hour_ts_utc),

    CONSTRAINT ck_run_context_hour_aligned
        CHECK (date_trunc('hour', hour_ts_utc) = hour_ts_utc),

    CONSTRAINT ck_run_context_cycle_seq_pos CHECK (cycle_seq >= 0),

    CONSTRAINT ck_run_context_status
        CHECK (status IN ('STARTED', 'COMPLETED', 'FAILED', 'SKIPPED')),

    CONSTRAINT ck_run_context_completed_after_started
        CHECK (completed_at_utc IS NULL OR completed_at_utc >= started_at_utc),

    CONSTRAINT ck_run_context_backtest_link CHECK (
        (run_mode = 'BACKTEST' AND backtest_run_id IS NOT NULL)
        OR
        (run_mode IN ('PAPER','LIVE') AND backtest_run_id IS NULL)
    )
);

------------------------------------------------------------
-- order_book_snapshot (FIXED spread_bps PRECISION)
------------------------------------------------------------

CREATE TABLE order_book_snapshot (
    asset_id SMALLINT NOT NULL,
    snapshot_ts_utc TIMESTAMPTZ NOT NULL,
    hour_ts_utc TIMESTAMPTZ NOT NULL,
    best_bid_price NUMERIC(38,18) NOT NULL,
    best_ask_price NUMERIC(38,18) NOT NULL,
    best_bid_size NUMERIC(38,18) NOT NULL,
    best_ask_size NUMERIC(38,18) NOT NULL,

    spread_abs NUMERIC(38,18)
        GENERATED ALWAYS AS (best_ask_price - best_bid_price) STORED,

    spread_bps NUMERIC(12,8)
        GENERATED ALWAYS AS (
            ((best_ask_price - best_bid_price)
             / NULLIF(best_bid_price,0)) * 10000::numeric
        ) STORED,

    source_venue TEXT NOT NULL,
    ingest_run_id UUID NOT NULL,

    CONSTRAINT pk_order_book_snapshot
        PRIMARY KEY (asset_id, snapshot_ts_utc, source_venue),

    CONSTRAINT ck_order_book_snapshot_hour_aligned
        CHECK (date_trunc('hour', hour_ts_utc) = hour_ts_utc),

    CONSTRAINT ck_order_book_snapshot_bucket_match
        CHECK (hour_ts_utc = date_trunc('hour', snapshot_ts_utc)),

    CONSTRAINT ck_order_book_snapshot_ask_ge_bid
        CHECK (best_ask_price >= best_bid_price)
);

------------------------------------------------------------
-- order_request → trade_signal FK SIMPLIFIED
------------------------------------------------------------

ALTER TABLE order_request
    DROP CONSTRAINT IF EXISTS fk_order_request_signal_identity;

ALTER TABLE order_request
    ADD CONSTRAINT fk_order_request_signal_identity
        FOREIGN KEY (signal_id)
        REFERENCES trade_signal (signal_id)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT;

------------------------------------------------------------
-- ACTIVE MODEL PARTIAL INDEX FIX
------------------------------------------------------------

DROP INDEX IF EXISTS uqix_model_version_one_active_per_name;

CREATE UNIQUE INDEX uqix_model_version_one_active_per_name_role
ON model_version (model_name, model_role)
WHERE is_active = TRUE;

------------------------------------------------------------
-- APPEND-ONLY ENFORCEMENT (CORRECTED SCOPE)
------------------------------------------------------------

CREATE OR REPLACE FUNCTION fn_enforce_append_only()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION
    'append-only violation on table %, operation % is not allowed',
    TG_TABLE_NAME, TG_OP;
END;
$$;

-- ENFORCED TABLES

CREATE TRIGGER trg_market_ohlcv_hourly_append_only
BEFORE UPDATE OR DELETE ON market_ohlcv_hourly
FOR EACH ROW EXECUTE FUNCTION fn_enforce_append_only();

CREATE TRIGGER trg_order_book_snapshot_append_only
BEFORE UPDATE OR DELETE ON order_book_snapshot
FOR EACH ROW EXECUTE FUNCTION fn_enforce_append_only();

CREATE TRIGGER trg_feature_snapshot_append_only
BEFORE UPDATE OR DELETE ON feature_snapshot
FOR EACH ROW EXECUTE FUNCTION fn_enforce_append_only();

CREATE TRIGGER trg_regime_output_append_only
BEFORE UPDATE OR DELETE ON regime_output
FOR EACH ROW EXECUTE FUNCTION fn_enforce_append_only();

CREATE TRIGGER trg_model_prediction_append_only
BEFORE UPDATE OR DELETE ON model_prediction
FOR EACH ROW EXECUTE FUNCTION fn_enforce_append_only();

CREATE TRIGGER trg_meta_learner_component_append_only
BEFORE UPDATE OR DELETE ON meta_learner_component
FOR EACH ROW EXECUTE FUNCTION fn_enforce_append_only();

CREATE TRIGGER trg_trade_signal_append_only
BEFORE UPDATE OR DELETE ON trade_signal
FOR EACH ROW EXECUTE FUNCTION fn_enforce_append_only();

CREATE TRIGGER trg_order_fill_append_only
BEFORE UPDATE OR DELETE ON order_fill
FOR EACH ROW EXECUTE FUNCTION fn_enforce_append_only();

CREATE TRIGGER trg_executed_trade_append_only
BEFORE UPDATE OR DELETE ON executed_trade
FOR EACH ROW EXECUTE FUNCTION fn_enforce_append_only();

CREATE TRIGGER trg_cash_ledger_append_only
BEFORE UPDATE OR DELETE ON cash_ledger
FOR EACH ROW EXECUTE FUNCTION fn_enforce_append_only();

CREATE TRIGGER trg_risk_event_append_only
BEFORE UPDATE OR DELETE ON risk_event
FOR EACH ROW EXECUTE FUNCTION fn_enforce_append_only();

CREATE TRIGGER trg_backtest_fold_result_append_only
BEFORE UPDATE OR DELETE ON backtest_fold_result
FOR EACH ROW EXECUTE FUNCTION fn_enforce_append_only();

-- NOT append-only:
-- portfolio_hourly_state
-- risk_hourly_state
-- position_hourly_state

------------------------------------------------------------
-- TIMESCALEDB STRATEGY
------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS timescaledb;

SELECT create_hypertable('market_ohlcv_hourly','hour_ts_utc',if_not_exists => TRUE);
SELECT create_hypertable('order_book_snapshot','snapshot_ts_utc',if_not_exists => TRUE);
SELECT create_hypertable('feature_snapshot','hour_ts_utc',if_not_exists => TRUE);
SELECT create_hypertable('regime_output','hour_ts_utc',if_not_exists => TRUE);
SELECT create_hypertable('model_prediction','hour_ts_utc',if_not_exists => TRUE);
SELECT create_hypertable('meta_learner_component','hour_ts_utc',if_not_exists => TRUE);
SELECT create_hypertable('position_hourly_state','hour_ts_utc',if_not_exists => TRUE);
SELECT create_hypertable('portfolio_hourly_state','hour_ts_utc',if_not_exists => TRUE);
SELECT create_hypertable('risk_hourly_state','hour_ts_utc',if_not_exists => TRUE);

------------------------------------------------------------
-- FINANCIAL SAFETY GUARANTEES
------------------------------------------------------------

• No leverage enforced via:
  requested_notional <= pre_order_cash_available

• 20% hard drawdown stop enforced in:
  ck_risk_hourly_state_dd20_halt

• No duplicate fill inflation:
  UNIQUE(order_id, exchange_trade_id)

• Deterministic replay:
  run_context uniqueness + append-only decision tables

• No lookahead:
  feature_snapshot window constraint

• All financial columns NOT NULL

------------------------------------------------------------
END OF MASTER DDL CONTRACT
------------------------------------------------------------