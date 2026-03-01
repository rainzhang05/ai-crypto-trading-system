ALTER TABLE model_prediction ADD COLUMN IF NOT EXISTS account_id SMALLINT;
ALTER TABLE regime_output ADD COLUMN IF NOT EXISTS account_id SMALLINT;
ALTER TABLE meta_learner_component ADD COLUMN IF NOT EXISTS account_id SMALLINT;

ALTER TABLE trade_signal
    DROP CONSTRAINT IF EXISTS fk_trade_signal_run_context_run_account_mode_hour;

ALTER TABLE trade_signal
    ADD CONSTRAINT fk_trade_signal_run_context_run_account_mode_hour
    FOREIGN KEY (run_id, account_id, run_mode, hour_ts_utc)
    REFERENCES run_context (run_id, account_id, run_mode, hour_ts_utc)
    ON UPDATE RESTRICT ON DELETE RESTRICT
    NOT VALID;

ALTER TABLE model_prediction
    DROP CONSTRAINT IF EXISTS fk_model_prediction_run_context_run_account_mode_hour;

ALTER TABLE model_prediction
    ADD CONSTRAINT fk_model_prediction_run_context_run_account_mode_hour
    FOREIGN KEY (run_id, account_id, run_mode, hour_ts_utc)
    REFERENCES run_context (run_id, account_id, run_mode, hour_ts_utc)
    ON UPDATE RESTRICT ON DELETE RESTRICT
    NOT VALID;

ALTER TABLE regime_output
    DROP CONSTRAINT IF EXISTS fk_regime_output_run_context_run_account_mode_hour;

ALTER TABLE regime_output
    ADD CONSTRAINT fk_regime_output_run_context_run_account_mode_hour
    FOREIGN KEY (run_id, account_id, run_mode, hour_ts_utc)
    REFERENCES run_context (run_id, account_id, run_mode, hour_ts_utc)
    ON UPDATE RESTRICT ON DELETE RESTRICT
    NOT VALID;

ALTER TABLE meta_learner_component
    DROP CONSTRAINT IF EXISTS fk_meta_learner_component_run_context_run_account_mode_hour;

ALTER TABLE meta_learner_component
    ADD CONSTRAINT fk_meta_learner_component_run_context_run_account_mode_hour
    FOREIGN KEY (run_id, account_id, run_mode, hour_ts_utc)
    REFERENCES run_context (run_id, account_id, run_mode, hour_ts_utc)
    ON UPDATE RESTRICT ON DELETE RESTRICT
    NOT VALID;

ALTER TABLE model_prediction
    DROP CONSTRAINT IF EXISTS fk_model_prediction_account;

ALTER TABLE model_prediction
    ADD CONSTRAINT fk_model_prediction_account
    FOREIGN KEY (account_id)
    REFERENCES account (account_id)
    ON UPDATE RESTRICT ON DELETE RESTRICT
    NOT VALID;

ALTER TABLE regime_output
    DROP CONSTRAINT IF EXISTS fk_regime_output_account;

ALTER TABLE regime_output
    ADD CONSTRAINT fk_regime_output_account
    FOREIGN KEY (account_id)
    REFERENCES account (account_id)
    ON UPDATE RESTRICT ON DELETE RESTRICT
    NOT VALID;

ALTER TABLE meta_learner_component
    DROP CONSTRAINT IF EXISTS fk_meta_learner_component_account;

ALTER TABLE meta_learner_component
    ADD CONSTRAINT fk_meta_learner_component_account
    FOREIGN KEY (account_id)
    REFERENCES account (account_id)
    ON UPDATE RESTRICT ON DELETE RESTRICT
    NOT VALID;

ALTER TABLE model_prediction ALTER COLUMN account_id SET NOT NULL;
ALTER TABLE regime_output ALTER COLUMN account_id SET NOT NULL;
ALTER TABLE meta_learner_component ALTER COLUMN account_id SET NOT NULL;

ALTER TABLE trade_signal VALIDATE CONSTRAINT fk_trade_signal_run_context_run_account_mode_hour;
ALTER TABLE model_prediction VALIDATE CONSTRAINT fk_model_prediction_run_context_run_account_mode_hour;
ALTER TABLE regime_output VALIDATE CONSTRAINT fk_regime_output_run_context_run_account_mode_hour;
ALTER TABLE meta_learner_component VALIDATE CONSTRAINT fk_meta_learner_component_run_context_run_account_mode_hour;
ALTER TABLE model_prediction VALIDATE CONSTRAINT fk_model_prediction_account;
ALTER TABLE regime_output VALIDATE CONSTRAINT fk_regime_output_account;
ALTER TABLE meta_learner_component VALIDATE CONSTRAINT fk_meta_learner_component_account;

ALTER TABLE model_prediction
    DROP CONSTRAINT IF EXISTS uq_model_prediction_identity_run_account_mode_hour;

ALTER TABLE model_prediction
    ADD CONSTRAINT uq_model_prediction_identity_run_account_mode_hour
    UNIQUE (run_id, account_id, run_mode, asset_id, horizon, model_version_id, hour_ts_utc);

ALTER TABLE regime_output
    DROP CONSTRAINT IF EXISTS uq_regime_output_identity_run_account_mode_hour;

ALTER TABLE regime_output
    ADD CONSTRAINT uq_regime_output_identity_run_account_mode_hour
    UNIQUE (run_id, account_id, run_mode, asset_id, model_version_id, hour_ts_utc);

ALTER TABLE meta_learner_component
    DROP CONSTRAINT IF EXISTS uq_meta_learner_component_identity_run_account_mode_hour;

ALTER TABLE meta_learner_component
    ADD CONSTRAINT uq_meta_learner_component_identity_run_account_mode_hour
    UNIQUE (run_id, account_id, run_mode, asset_id, horizon, meta_model_version_id, base_model_version_id, hour_ts_utc);

DROP TRIGGER IF EXISTS trg_trade_signal_append_only ON trade_signal;
CREATE TRIGGER trg_trade_signal_append_only
BEFORE UPDATE OR DELETE ON trade_signal
FOR EACH ROW EXECUTE FUNCTION fn_enforce_append_only();

DROP TRIGGER IF EXISTS trg_order_request_append_only ON order_request;
CREATE TRIGGER trg_order_request_append_only
BEFORE UPDATE OR DELETE ON order_request
FOR EACH ROW EXECUTE FUNCTION fn_enforce_append_only();

DROP TRIGGER IF EXISTS trg_position_lot_append_only ON position_lot;
CREATE TRIGGER trg_position_lot_append_only
BEFORE UPDATE OR DELETE ON position_lot
FOR EACH ROW EXECUTE FUNCTION fn_enforce_append_only();

DROP TRIGGER IF EXISTS trg_executed_trade_append_only ON executed_trade;
CREATE TRIGGER trg_executed_trade_append_only
BEFORE UPDATE OR DELETE ON executed_trade
FOR EACH ROW EXECUTE FUNCTION fn_enforce_append_only();

CREATE OR REPLACE FUNCTION fn_validate_execution_causality()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    request_ts TIMESTAMPTZ;
BEGIN
    SELECT r.request_ts_utc
      INTO request_ts
    FROM order_request r
    WHERE r.order_id = NEW.order_id
      AND r.run_id = NEW.run_id
      AND r.run_mode = NEW.run_mode
      AND r.account_id = NEW.account_id;

    IF request_ts IS NULL THEN
        RAISE EXCEPTION 'causality violation: missing order_request row for order %', NEW.order_id;
    END IF;

    IF NEW.fill_ts_utc < request_ts THEN
        RAISE EXCEPTION 'causality violation: fill before request for order %', NEW.order_id;
    END IF;

    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION fn_validate_cash_ledger_chain()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    prev_row RECORD;
BEGIN
    SELECT ledger_seq, balance_after, ledger_hash
      INTO prev_row
    FROM cash_ledger
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

CREATE OR REPLACE FUNCTION fn_validate_trade_fee_rollup()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.total_fee < 0 OR NEW.total_slippage_cost < 0 THEN
        RAISE EXCEPTION 'invalid fee/slippage rollup for trade %', NEW.trade_id;
    END IF;

    IF NEW.net_pnl <> NEW.gross_pnl - NEW.total_fee - NEW.total_slippage_cost THEN
        RAISE EXCEPTION 'net_pnl formula violation for trade %', NEW.trade_id;
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS ctrg_order_fill_v2_causality ON order_fill;
DROP TRIGGER IF EXISTS ctrg_order_fill_causality ON order_fill;
CREATE CONSTRAINT TRIGGER ctrg_order_fill_causality
AFTER INSERT ON order_fill
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fn_validate_execution_causality();

DROP TRIGGER IF EXISTS ctrg_cash_ledger_v2_chain ON cash_ledger;
DROP TRIGGER IF EXISTS ctrg_cash_ledger_chain ON cash_ledger;
CREATE CONSTRAINT TRIGGER ctrg_cash_ledger_chain
AFTER INSERT ON cash_ledger
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fn_validate_cash_ledger_chain();

DROP TRIGGER IF EXISTS ctrg_executed_trade_v2_fee_rollup ON executed_trade;
DROP TRIGGER IF EXISTS ctrg_executed_trade_fee_rollup ON executed_trade;
CREATE CONSTRAINT TRIGGER ctrg_executed_trade_fee_rollup
AFTER INSERT ON executed_trade
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fn_validate_trade_fee_rollup();

DROP FUNCTION IF EXISTS fn_validate_execution_causality_v2();
DROP FUNCTION IF EXISTS fn_validate_cash_ledger_chain_v2();
DROP FUNCTION IF EXISTS fn_validate_trade_fee_rollup_v2();

ALTER TABLE model_training_window
    ADD COLUMN IF NOT EXISTS backtest_run_id UUID,
    ADD COLUMN IF NOT EXISTS training_window_hash CHAR(64);

ALTER TABLE model_training_window
    DROP CONSTRAINT IF EXISTS uq_model_training_window_model_fold_horizon;

ALTER TABLE model_training_window
    DROP CONSTRAINT IF EXISTS uq_model_training_window_run_model_fold_horizon;

ALTER TABLE model_training_window
    ADD CONSTRAINT uq_model_training_window_run_model_fold_horizon
    UNIQUE (backtest_run_id, model_version_id, fold_index, horizon);

ALTER TABLE model_training_window
    DROP CONSTRAINT IF EXISTS fk_model_training_window_backtest_fold;

ALTER TABLE model_training_window
    ADD CONSTRAINT fk_model_training_window_backtest_fold
    FOREIGN KEY (backtest_run_id, fold_index)
    REFERENCES backtest_fold_result (backtest_run_id, fold_index)
    ON UPDATE RESTRICT ON DELETE RESTRICT
    NOT VALID;

CREATE TABLE IF NOT EXISTS model_activation_gate (
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

CREATE UNIQUE INDEX IF NOT EXISTS uqix_model_activation_gate_one_approved
    ON model_activation_gate (model_version_id, run_mode)
    WHERE status = 'APPROVED';

ALTER TABLE model_activation_gate
    DROP CONSTRAINT IF EXISTS uq_model_activation_gate_activation_model_mode;

ALTER TABLE model_activation_gate
    ADD CONSTRAINT uq_model_activation_gate_activation_model_mode
    UNIQUE (activation_id, model_version_id, run_mode);

ALTER TABLE model_prediction
    ADD COLUMN IF NOT EXISTS training_window_id BIGINT,
    ADD COLUMN IF NOT EXISTS lineage_backtest_run_id UUID,
    ADD COLUMN IF NOT EXISTS lineage_fold_index INTEGER,
    ADD COLUMN IF NOT EXISTS lineage_horizon horizon_enum,
    ADD COLUMN IF NOT EXISTS activation_id BIGINT;

ALTER TABLE model_prediction
    DROP CONSTRAINT IF EXISTS fk_model_prediction_training_window;

ALTER TABLE model_prediction
    ADD CONSTRAINT fk_model_prediction_training_window
    FOREIGN KEY (training_window_id)
    REFERENCES model_training_window (training_window_id)
    ON UPDATE RESTRICT ON DELETE RESTRICT
    NOT VALID;

ALTER TABLE model_prediction
    DROP CONSTRAINT IF EXISTS fk_model_prediction_lineage_fold_horizon;

ALTER TABLE model_prediction
    ADD CONSTRAINT fk_model_prediction_lineage_fold_horizon
    FOREIGN KEY (lineage_backtest_run_id, model_version_id, lineage_fold_index, lineage_horizon)
    REFERENCES model_training_window (backtest_run_id, model_version_id, fold_index, horizon)
    ON UPDATE RESTRICT ON DELETE RESTRICT
    NOT VALID;

ALTER TABLE model_prediction
    DROP CONSTRAINT IF EXISTS fk_model_prediction_lineage_fold;

ALTER TABLE model_prediction
    ADD CONSTRAINT fk_model_prediction_lineage_fold
    FOREIGN KEY (lineage_backtest_run_id, lineage_fold_index)
    REFERENCES backtest_fold_result (backtest_run_id, fold_index)
    ON UPDATE RESTRICT ON DELETE RESTRICT
    NOT VALID;

ALTER TABLE model_prediction
    DROP CONSTRAINT IF EXISTS fk_model_prediction_activation;

ALTER TABLE model_prediction
    ADD CONSTRAINT fk_model_prediction_activation
    FOREIGN KEY (activation_id, model_version_id, run_mode)
    REFERENCES model_activation_gate (activation_id, model_version_id, run_mode)
    ON UPDATE RESTRICT ON DELETE RESTRICT
    NOT VALID;

ALTER TABLE model_prediction
    DROP CONSTRAINT IF EXISTS ck_model_prediction_mode_lineage_activation;

ALTER TABLE model_prediction
    ADD CONSTRAINT ck_model_prediction_mode_lineage_activation
    CHECK (
        (run_mode = 'BACKTEST'
            AND training_window_id IS NOT NULL
            AND lineage_backtest_run_id IS NOT NULL
            AND lineage_fold_index IS NOT NULL
            AND lineage_horizon IS NOT NULL
            AND activation_id IS NULL
            AND horizon = lineage_horizon)
        OR
        (run_mode IN ('PAPER','LIVE')
            AND training_window_id IS NULL
            AND lineage_backtest_run_id IS NULL
            AND lineage_fold_index IS NULL
            AND lineage_horizon IS NULL
            AND activation_id IS NOT NULL)
    )
    NOT VALID;

ALTER TABLE regime_output
    ADD COLUMN IF NOT EXISTS training_window_id BIGINT,
    ADD COLUMN IF NOT EXISTS lineage_backtest_run_id UUID,
    ADD COLUMN IF NOT EXISTS lineage_fold_index INTEGER,
    ADD COLUMN IF NOT EXISTS lineage_horizon horizon_enum,
    ADD COLUMN IF NOT EXISTS activation_id BIGINT;

ALTER TABLE regime_output
    DROP CONSTRAINT IF EXISTS fk_regime_output_training_window;

ALTER TABLE regime_output
    ADD CONSTRAINT fk_regime_output_training_window
    FOREIGN KEY (training_window_id)
    REFERENCES model_training_window (training_window_id)
    ON UPDATE RESTRICT ON DELETE RESTRICT
    NOT VALID;

ALTER TABLE regime_output
    DROP CONSTRAINT IF EXISTS fk_regime_output_lineage_fold_horizon;

ALTER TABLE regime_output
    ADD CONSTRAINT fk_regime_output_lineage_fold_horizon
    FOREIGN KEY (lineage_backtest_run_id, model_version_id, lineage_fold_index, lineage_horizon)
    REFERENCES model_training_window (backtest_run_id, model_version_id, fold_index, horizon)
    ON UPDATE RESTRICT ON DELETE RESTRICT
    NOT VALID;

ALTER TABLE regime_output
    DROP CONSTRAINT IF EXISTS fk_regime_output_lineage_fold;

ALTER TABLE regime_output
    ADD CONSTRAINT fk_regime_output_lineage_fold
    FOREIGN KEY (lineage_backtest_run_id, lineage_fold_index)
    REFERENCES backtest_fold_result (backtest_run_id, fold_index)
    ON UPDATE RESTRICT ON DELETE RESTRICT
    NOT VALID;

ALTER TABLE regime_output
    DROP CONSTRAINT IF EXISTS fk_regime_output_activation;

ALTER TABLE regime_output
    ADD CONSTRAINT fk_regime_output_activation
    FOREIGN KEY (activation_id, model_version_id, run_mode)
    REFERENCES model_activation_gate (activation_id, model_version_id, run_mode)
    ON UPDATE RESTRICT ON DELETE RESTRICT
    NOT VALID;

ALTER TABLE regime_output
    DROP CONSTRAINT IF EXISTS ck_regime_output_mode_lineage_activation;

ALTER TABLE regime_output
    ADD CONSTRAINT ck_regime_output_mode_lineage_activation
    CHECK (
        (run_mode = 'BACKTEST'
            AND training_window_id IS NOT NULL
            AND lineage_backtest_run_id IS NOT NULL
            AND lineage_fold_index IS NOT NULL
            AND lineage_horizon IS NOT NULL
            AND activation_id IS NULL)
        OR
        (run_mode IN ('PAPER','LIVE')
            AND training_window_id IS NULL
            AND lineage_backtest_run_id IS NULL
            AND lineage_fold_index IS NULL
            AND lineage_horizon IS NULL
            AND activation_id IS NOT NULL)
    )
    NOT VALID;

CREATE OR REPLACE FUNCTION fn_enforce_model_prediction_walk_forward()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    w RECORD;
BEGIN
    IF NEW.run_mode = 'BACKTEST' THEN
        SELECT backtest_run_id, model_version_id, fold_index, horizon, train_end_utc, valid_start_utc, valid_end_utc
          INTO w
        FROM model_training_window
        WHERE training_window_id = NEW.training_window_id;

        IF w.backtest_run_id IS NULL THEN
            RAISE EXCEPTION 'walk-forward violation: missing training_window_id %', NEW.training_window_id;
        END IF;

        IF NEW.lineage_backtest_run_id <> w.backtest_run_id
           OR NEW.lineage_fold_index <> w.fold_index
           OR NEW.lineage_horizon <> w.horizon
           OR NEW.model_version_id <> w.model_version_id THEN
            RAISE EXCEPTION 'walk-forward lineage mismatch on model_prediction';
        END IF;

        IF NEW.hour_ts_utc <= w.train_end_utc
           OR NEW.hour_ts_utc < w.valid_start_utc
           OR NEW.hour_ts_utc >= w.valid_end_utc THEN
            RAISE EXCEPTION 'walk-forward contamination violation on model_prediction';
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION fn_enforce_regime_output_walk_forward()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    w RECORD;
BEGIN
    IF NEW.run_mode = 'BACKTEST' THEN
        SELECT backtest_run_id, model_version_id, fold_index, horizon, train_end_utc, valid_start_utc, valid_end_utc
          INTO w
        FROM model_training_window
        WHERE training_window_id = NEW.training_window_id;

        IF w.backtest_run_id IS NULL THEN
            RAISE EXCEPTION 'walk-forward violation: missing training_window_id %', NEW.training_window_id;
        END IF;

        IF NEW.lineage_backtest_run_id <> w.backtest_run_id
           OR NEW.lineage_fold_index <> w.fold_index
           OR NEW.lineage_horizon <> w.horizon
           OR NEW.model_version_id <> w.model_version_id THEN
            RAISE EXCEPTION 'walk-forward lineage mismatch on regime_output';
        END IF;

        IF NEW.hour_ts_utc <= w.train_end_utc
           OR NEW.hour_ts_utc < w.valid_start_utc
           OR NEW.hour_ts_utc >= w.valid_end_utc THEN
            RAISE EXCEPTION 'walk-forward contamination violation on regime_output';
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS ctrg_model_prediction_walk_forward ON model_prediction;
CREATE CONSTRAINT TRIGGER ctrg_model_prediction_walk_forward
AFTER INSERT ON model_prediction
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fn_enforce_model_prediction_walk_forward();

DROP TRIGGER IF EXISTS ctrg_regime_output_walk_forward ON regime_output;
CREATE CONSTRAINT TRIGGER ctrg_regime_output_walk_forward
AFTER INSERT ON regime_output
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fn_enforce_regime_output_walk_forward();

ALTER TABLE model_training_window ALTER COLUMN backtest_run_id SET NOT NULL;
ALTER TABLE model_training_window ALTER COLUMN training_window_hash SET NOT NULL;

ALTER TABLE model_training_window VALIDATE CONSTRAINT fk_model_training_window_backtest_fold;

ALTER TABLE model_prediction VALIDATE CONSTRAINT fk_model_prediction_training_window;
ALTER TABLE model_prediction VALIDATE CONSTRAINT fk_model_prediction_lineage_fold_horizon;
ALTER TABLE model_prediction VALIDATE CONSTRAINT fk_model_prediction_lineage_fold;
ALTER TABLE model_prediction VALIDATE CONSTRAINT fk_model_prediction_activation;
ALTER TABLE model_prediction VALIDATE CONSTRAINT ck_model_prediction_mode_lineage_activation;

ALTER TABLE regime_output VALIDATE CONSTRAINT fk_regime_output_training_window;
ALTER TABLE regime_output VALIDATE CONSTRAINT fk_regime_output_lineage_fold_horizon;
ALTER TABLE regime_output VALIDATE CONSTRAINT fk_regime_output_lineage_fold;
ALTER TABLE regime_output VALIDATE CONSTRAINT fk_regime_output_activation;
ALTER TABLE regime_output VALIDATE CONSTRAINT ck_regime_output_mode_lineage_activation;

ALTER TABLE run_context
    ALTER COLUMN run_seed_hash SET NOT NULL,
    ALTER COLUMN context_hash SET NOT NULL,
    ALTER COLUMN replay_root_hash SET NOT NULL;

ALTER TABLE backtest_run
    ALTER COLUMN row_hash SET NOT NULL;

ALTER TABLE model_training_window
    ALTER COLUMN training_window_hash SET NOT NULL,
    ALTER COLUMN row_hash SET NOT NULL;

ALTER TABLE backtest_fold_result
    ALTER COLUMN row_hash SET NOT NULL;

ALTER TABLE market_ohlcv_hourly
    ALTER COLUMN row_hash SET NOT NULL;

ALTER TABLE order_book_snapshot
    ALTER COLUMN row_hash SET NOT NULL;

ALTER TABLE feature_snapshot
    ALTER COLUMN row_hash SET NOT NULL;

ALTER TABLE regime_output
    ALTER COLUMN upstream_hash SET NOT NULL,
    ALTER COLUMN row_hash SET NOT NULL;

ALTER TABLE model_prediction
    ALTER COLUMN upstream_hash SET NOT NULL,
    ALTER COLUMN row_hash SET NOT NULL;

ALTER TABLE meta_learner_component
    ALTER COLUMN row_hash SET NOT NULL;

ALTER TABLE trade_signal
    ALTER COLUMN upstream_hash SET NOT NULL,
    ALTER COLUMN row_hash SET NOT NULL;

ALTER TABLE order_request
    ALTER COLUMN parent_signal_hash SET NOT NULL,
    ALTER COLUMN row_hash SET NOT NULL;

ALTER TABLE order_fill
    ALTER COLUMN parent_order_hash SET NOT NULL,
    ALTER COLUMN row_hash SET NOT NULL;

ALTER TABLE position_lot
    ALTER COLUMN parent_fill_hash SET NOT NULL,
    ALTER COLUMN row_hash SET NOT NULL;

ALTER TABLE executed_trade
    ALTER COLUMN parent_lot_hash SET NOT NULL,
    ALTER COLUMN row_hash SET NOT NULL;

ALTER TABLE cash_ledger
    ALTER COLUMN row_hash SET NOT NULL;

ALTER TABLE position_hourly_state
    ALTER COLUMN row_hash SET NOT NULL;

ALTER TABLE portfolio_hourly_state
    ALTER COLUMN row_hash SET NOT NULL;

ALTER TABLE risk_hourly_state
    ALTER COLUMN row_hash SET NOT NULL;

ALTER TABLE risk_event
    ALTER COLUMN parent_state_hash SET NOT NULL,
    ALTER COLUMN row_hash SET NOT NULL;

ALTER TABLE cluster_exposure_hourly_state
    ALTER COLUMN parent_risk_hash SET NOT NULL,
    ALTER COLUMN row_hash SET NOT NULL;

SELECT
    child_ns.nspname AS child_schema,
    child_tbl.relname AS child_table,
    c.conname AS fk_name,
    parent_ns.nspname AS parent_schema,
    parent_tbl.relname AS parent_table
FROM pg_constraint c
JOIN pg_class child_tbl ON child_tbl.oid = c.conrelid
JOIN pg_namespace child_ns ON child_ns.oid = child_tbl.relnamespace
JOIN pg_class parent_tbl ON parent_tbl.oid = c.confrelid
JOIN pg_namespace parent_ns ON parent_ns.oid = parent_tbl.relnamespace
JOIN timescaledb_information.hypertables h
  ON h.hypertable_schema = parent_ns.nspname
 AND h.hypertable_name = parent_tbl.relname
WHERE c.contype = 'f'
  AND child_ns.nspname = 'public';

SELECT n.nspname AS schema_name, p.proname
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public'
  AND (
      p.prosrc ILIKE '%cash_ledger_v2%'
   OR p.prosrc ILIKE '%order_request_v2%'
   OR p.prosrc ILIKE '%executed_trade_v2%'
  );

SELECT c.relname AS table_name, t.tgname AS trigger_name, pg_get_triggerdef(t.oid) AS trigger_def
FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND NOT t.tgisinternal
  AND pg_get_triggerdef(t.oid) ILIKE '%_v2%';

SELECT relname
FROM pg_class
WHERE relnamespace = 'public'::regnamespace
  AND relkind IN ('r','p','v','m','f')
  AND relname LIKE '%\_v2' ESCAPE '\\';

SELECT table_name, column_name
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
