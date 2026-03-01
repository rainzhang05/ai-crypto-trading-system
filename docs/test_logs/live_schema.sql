--
-- PostgreSQL database dump
--

-- Dumped from database version 15.5
-- Dumped by pg_dump version 15.5

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: timescaledb; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS timescaledb WITH SCHEMA public;


--
-- Name: EXTENSION timescaledb; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION timescaledb IS 'Enables scalable inserts and complex queries for time-series data (Community Edition)';


--
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- Name: EXTENSION pgcrypto; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pgcrypto IS 'cryptographic functions';


--
-- Name: drawdown_tier_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.drawdown_tier_enum AS ENUM (
    'NORMAL',
    'DD10',
    'DD15',
    'HALT20'
);


--
-- Name: horizon_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.horizon_enum AS ENUM (
    'H1',
    'H4',
    'H24'
);


--
-- Name: model_role_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.model_role_enum AS ENUM (
    'BASE_TREE',
    'BASE_DEEP',
    'REGIME',
    'META'
);


--
-- Name: order_side_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.order_side_enum AS ENUM (
    'BUY',
    'SELL'
);


--
-- Name: order_status_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.order_status_enum AS ENUM (
    'NEW',
    'ACK',
    'PARTIAL',
    'FILLED',
    'CANCELLED',
    'REJECTED'
);


--
-- Name: order_type_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.order_type_enum AS ENUM (
    'LIMIT',
    'MARKET'
);


--
-- Name: run_mode_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.run_mode_enum AS ENUM (
    'BACKTEST',
    'PAPER',
    'LIVE'
);


--
-- Name: signal_action_enum; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.signal_action_enum AS ENUM (
    'ENTER',
    'EXIT',
    'HOLD'
);


--
-- Name: fn_enforce_append_only(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.fn_enforce_append_only() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    RAISE EXCEPTION 'append-only violation on table %, operation % is not allowed', TG_TABLE_NAME, TG_OP;
END;
$$;


--
-- Name: fn_enforce_cluster_cap_on_admission(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.fn_enforce_cluster_cap_on_admission() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    current_pct NUMERIC(12,10);
    cap_pct NUMERIC(12,10);
BEGIN
    SELECT COALESCE(ce.exposure_pct, 0), ce.max_cluster_exposure_pct
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


--
-- Name: fn_enforce_model_prediction_walk_forward(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.fn_enforce_model_prediction_walk_forward() RETURNS trigger
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


--
-- Name: fn_enforce_regime_output_walk_forward(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.fn_enforce_regime_output_walk_forward() RETURNS trigger
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


--
-- Name: fn_enforce_runtime_risk_gate(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.fn_enforce_runtime_risk_gate() RETURNS trigger
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

    IF NOT FOUND THEN
        RAISE EXCEPTION 'risk gate violation: missing exact risk_hourly_state row for run_mode %, account %, hour %, source_run_id %',
            NEW.run_mode, NEW.account_id, NEW.hour_ts_utc, NEW.risk_state_run_id;
    END IF;

    IF NEW.status <> 'REJECTED' AND (halt_flag OR kill_flag) THEN
        RAISE EXCEPTION 'risk gate violation: halted or kill switch active';
    END IF;

    RETURN NEW;
END;
$$;


--
-- Name: fn_guard_portfolio_hourly_state_identity_key_mutation(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.fn_guard_portfolio_hourly_state_identity_key_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'portfolio_hourly_state is append-only for identity synchronization';
    END IF;

    IF NEW.run_mode IS DISTINCT FROM OLD.run_mode
       OR NEW.account_id IS DISTINCT FROM OLD.account_id
       OR NEW.hour_ts_utc IS DISTINCT FROM OLD.hour_ts_utc THEN
        RAISE EXCEPTION 'portfolio_hourly_state identity key mutation is not allowed';
    END IF;

    RETURN NEW;
END;
$$;


--
-- Name: fn_guard_risk_hourly_state_identity_key_mutation(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.fn_guard_risk_hourly_state_identity_key_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'risk_hourly_state is append-only for identity synchronization';
    END IF;

    IF NEW.run_mode IS DISTINCT FROM OLD.run_mode
       OR NEW.account_id IS DISTINCT FROM OLD.account_id
       OR NEW.hour_ts_utc IS DISTINCT FROM OLD.hour_ts_utc
       OR NEW.source_run_id IS DISTINCT FROM OLD.source_run_id THEN
        RAISE EXCEPTION 'risk_hourly_state identity key mutation is not allowed';
    END IF;

    RETURN NEW;
END;
$$;


--
-- Name: fn_reject_writes_when_phase_1b_locked(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.fn_reject_writes_when_phase_1b_locked() RETURNS trigger
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


--
-- Name: fn_sha256_hex(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.fn_sha256_hex(input_text text) RETURNS character
    LANGUAGE sql IMMUTABLE
    AS $$
    SELECT encode(digest(input_text, 'sha256'), 'hex')::char(64);
$$;


--
-- Name: fn_sync_portfolio_hourly_state_identity_ins(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.fn_sync_portfolio_hourly_state_identity_ins() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    INSERT INTO portfolio_hourly_state_identity (run_mode, account_id, hour_ts_utc)
    VALUES (NEW.run_mode, NEW.account_id, NEW.hour_ts_utc)
    ON CONFLICT DO NOTHING;

    RETURN NEW;
END;
$$;


--
-- Name: fn_sync_risk_hourly_state_identity_ins(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.fn_sync_risk_hourly_state_identity_ins() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    INSERT INTO risk_hourly_state_identity (run_mode, account_id, hour_ts_utc, source_run_id)
    VALUES (NEW.run_mode, NEW.account_id, NEW.hour_ts_utc, NEW.source_run_id)
    ON CONFLICT DO NOTHING;

    RETURN NEW;
END;
$$;


--
-- Name: fn_validate_cash_ledger_chain(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.fn_validate_cash_ledger_chain() RETURNS trigger
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


--
-- Name: fn_validate_cluster_exposure_parent_risk_hash(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.fn_validate_cluster_exposure_parent_risk_hash() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    expected_parent_hash CHAR(64);
BEGIN
    SELECT r.row_hash
      INTO expected_parent_hash
    FROM risk_hourly_state r
    WHERE r.run_mode = NEW.run_mode
      AND r.account_id = NEW.account_id
      AND r.hour_ts_utc = NEW.hour_ts_utc
      AND r.source_run_id = NEW.source_run_id;

    IF expected_parent_hash IS NULL THEN
        RAISE EXCEPTION 'cluster_exposure parent hash violation: missing exact parent risk row';
    END IF;

    IF NEW.parent_risk_hash <> expected_parent_hash THEN
        RAISE EXCEPTION 'cluster_exposure parent hash mismatch';
    END IF;

    RETURN NEW;
END;
$$;


--
-- Name: fn_validate_execution_causality(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.fn_validate_execution_causality() RETURNS trigger
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


--
-- Name: fn_validate_portfolio_identity_source_exists(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.fn_validate_portfolio_identity_source_exists() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM portfolio_hourly_state p
        WHERE p.run_mode = NEW.run_mode
          AND p.account_id = NEW.account_id
          AND p.hour_ts_utc = NEW.hour_ts_utc
    ) THEN
        RAISE EXCEPTION 'portfolio identity row has no source hypertable row';
    END IF;

    RETURN NEW;
END;
$$;


--
-- Name: fn_validate_risk_event_parent_state_hash(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.fn_validate_risk_event_parent_state_hash() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    expected_parent_hash CHAR(64);
BEGIN
    SELECT r.row_hash
      INTO expected_parent_hash
    FROM risk_hourly_state r
    WHERE r.run_mode = NEW.run_mode
      AND r.account_id = NEW.account_id
      AND r.hour_ts_utc = NEW.related_state_hour_ts_utc;

    IF expected_parent_hash IS NULL THEN
        RAISE EXCEPTION 'risk_event parent hash violation: missing parent risk row';
    END IF;

    IF NEW.parent_state_hash <> expected_parent_hash THEN
        RAISE EXCEPTION 'risk_event parent hash mismatch';
    END IF;

    RETURN NEW;
END;
$$;


--
-- Name: fn_validate_risk_identity_source_exists(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.fn_validate_risk_identity_source_exists() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM risk_hourly_state r
        WHERE r.run_mode = NEW.run_mode
          AND r.account_id = NEW.account_id
          AND r.hour_ts_utc = NEW.hour_ts_utc
          AND r.source_run_id = NEW.source_run_id
    ) THEN
        RAISE EXCEPTION 'risk identity row has no source hypertable row';
    END IF;

    RETURN NEW;
END;
$$;


--
-- Name: fn_validate_trade_fee_rollup(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.fn_validate_trade_fee_rollup() RETURNS trigger
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


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: account; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.account (
    account_id smallint NOT NULL,
    account_code text NOT NULL,
    base_currency text NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at_utc timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_account_base_currency_upper CHECK ((base_currency = upper(base_currency))),
    CONSTRAINT ck_account_code_not_blank CHECK ((length(btrim(account_code)) > 0))
);


--
-- Name: account_account_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.account ALTER COLUMN account_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.account_account_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: asset; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.asset (
    asset_id smallint NOT NULL,
    venue text NOT NULL,
    symbol text NOT NULL,
    base_asset text NOT NULL,
    quote_asset text NOT NULL,
    tick_size numeric(38,18) NOT NULL,
    lot_size numeric(38,18) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    listed_at_utc timestamp with time zone NOT NULL,
    delisted_at_utc timestamp with time zone,
    CONSTRAINT ck_asset_base_upper CHECK ((base_asset = upper(base_asset))),
    CONSTRAINT ck_asset_delisted_after_listed CHECK (((delisted_at_utc IS NULL) OR (delisted_at_utc > listed_at_utc))),
    CONSTRAINT ck_asset_lot_size_pos CHECK ((lot_size > (0)::numeric)),
    CONSTRAINT ck_asset_quote_upper CHECK ((quote_asset = upper(quote_asset))),
    CONSTRAINT ck_asset_symbol_not_blank CHECK ((length(btrim(symbol)) > 0)),
    CONSTRAINT ck_asset_symbol_upper CHECK ((symbol = upper(symbol))),
    CONSTRAINT ck_asset_tick_size_pos CHECK ((tick_size > (0)::numeric)),
    CONSTRAINT ck_asset_venue_not_blank CHECK ((length(btrim(venue)) > 0))
);


--
-- Name: asset_asset_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.asset ALTER COLUMN asset_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.asset_asset_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: asset_cluster_membership; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.asset_cluster_membership (
    membership_id bigint NOT NULL,
    asset_id smallint NOT NULL,
    cluster_id smallint NOT NULL,
    effective_from_utc timestamp with time zone NOT NULL,
    effective_to_utc timestamp with time zone,
    membership_hash character(64) NOT NULL,
    CONSTRAINT ck_asset_cluster_membership_window CHECK (((effective_to_utc IS NULL) OR (effective_to_utc > effective_from_utc)))
);


--
-- Name: asset_cluster_membership_membership_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.asset_cluster_membership ALTER COLUMN membership_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.asset_cluster_membership_membership_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: backtest_fold_result; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.backtest_fold_result (
    backtest_run_id uuid NOT NULL,
    fold_index integer NOT NULL,
    train_start_utc timestamp with time zone NOT NULL,
    train_end_utc timestamp with time zone NOT NULL,
    valid_start_utc timestamp with time zone NOT NULL,
    valid_end_utc timestamp with time zone NOT NULL,
    trades_count integer NOT NULL,
    sharpe numeric(20,10) NOT NULL,
    max_drawdown_pct numeric(12,10) NOT NULL,
    net_return_pct numeric(38,18) NOT NULL,
    win_rate numeric(12,10) NOT NULL,
    row_hash character(64) NOT NULL,
    CONSTRAINT ck_backtest_fold_result_drawdown_range CHECK (((max_drawdown_pct >= (0)::numeric) AND (max_drawdown_pct <= (1)::numeric))),
    CONSTRAINT ck_backtest_fold_result_fold_nonneg CHECK ((fold_index >= 0)),
    CONSTRAINT ck_backtest_fold_result_trades_nonneg CHECK ((trades_count >= 0)),
    CONSTRAINT ck_backtest_fold_result_win_rate_range CHECK (((win_rate >= (0)::numeric) AND (win_rate <= (1)::numeric))),
    CONSTRAINT ck_backtest_fold_result_window_order CHECK (((train_start_utc < train_end_utc) AND (train_end_utc < valid_start_utc) AND (valid_start_utc < valid_end_utc)))
);


--
-- Name: backtest_run; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.backtest_run (
    backtest_run_id uuid NOT NULL,
    account_id smallint NOT NULL,
    started_at_utc timestamp with time zone NOT NULL,
    completed_at_utc timestamp with time zone,
    status text NOT NULL,
    strategy_code_sha character(40) NOT NULL,
    config_hash character(64) NOT NULL,
    universe_hash character(64) NOT NULL,
    initial_capital numeric(38,18) NOT NULL,
    cost_profile_id smallint NOT NULL,
    random_seed integer NOT NULL,
    row_hash character(64) NOT NULL,
    CONSTRAINT ck_backtest_run_completed_after_started CHECK (((completed_at_utc IS NULL) OR (completed_at_utc >= started_at_utc))),
    CONSTRAINT ck_backtest_run_initial_capital_pos CHECK ((initial_capital > (0)::numeric)),
    CONSTRAINT ck_backtest_run_status CHECK ((status = ANY (ARRAY['QUEUED'::text, 'RUNNING'::text, 'COMPLETED'::text, 'FAILED'::text, 'CANCELLED'::text])))
);


--
-- Name: cash_ledger; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cash_ledger (
    ledger_id bigint NOT NULL,
    run_id uuid NOT NULL,
    run_mode public.run_mode_enum NOT NULL,
    account_id smallint NOT NULL,
    event_ts_utc timestamp with time zone NOT NULL,
    hour_ts_utc timestamp with time zone NOT NULL,
    event_type text NOT NULL,
    ref_type text NOT NULL,
    ref_id uuid NOT NULL,
    delta_cash numeric(38,18) NOT NULL,
    balance_after numeric(38,18) NOT NULL,
    origin_hour_ts_utc timestamp with time zone NOT NULL,
    ledger_seq bigint NOT NULL,
    balance_before numeric(38,18) NOT NULL,
    prev_ledger_hash character(64),
    economic_event_hash character(64) NOT NULL,
    ledger_hash character(64) NOT NULL,
    row_hash character(64) NOT NULL,
    CONSTRAINT ck_cash_ledger_balance_nonneg CHECK ((balance_after >= (0)::numeric)),
    CONSTRAINT ck_cash_ledger_bucket_match CHECK ((hour_ts_utc = date_trunc('hour'::text, event_ts_utc))),
    CONSTRAINT ck_cash_ledger_event_type_not_blank CHECK ((length(btrim(event_type)) > 0)),
    CONSTRAINT ck_cash_ledger_hour_aligned CHECK ((date_trunc('hour'::text, hour_ts_utc) = hour_ts_utc)),
    CONSTRAINT ck_cash_ledger_ref_type_not_blank CHECK ((length(btrim(ref_type)) > 0)),
    CONSTRAINT ck_cash_ledger_v2_balance_chain CHECK ((balance_after = (balance_before + delta_cash))),
    CONSTRAINT ck_cash_ledger_v2_event_after_origin CHECK ((event_ts_utc >= origin_hour_ts_utc)),
    CONSTRAINT ck_cash_ledger_v2_origin_hour_aligned CHECK ((date_trunc('hour'::text, origin_hour_ts_utc) = origin_hour_ts_utc)),
    CONSTRAINT ck_cash_ledger_v2_prev_hash_presence CHECK ((((ledger_seq = 1) AND (prev_ledger_hash IS NULL)) OR ((ledger_seq > 1) AND (prev_ledger_hash IS NOT NULL))))
);


--
-- Name: cash_ledger_phase1a_archive; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cash_ledger_phase1a_archive (
    ledger_id bigint NOT NULL,
    run_id uuid NOT NULL,
    run_mode public.run_mode_enum NOT NULL,
    account_id smallint NOT NULL,
    event_ts_utc timestamp with time zone NOT NULL,
    hour_ts_utc timestamp with time zone NOT NULL,
    event_type text NOT NULL,
    ref_type text NOT NULL,
    ref_id uuid NOT NULL,
    delta_cash numeric(38,18) NOT NULL,
    balance_after numeric(38,18) NOT NULL,
    CONSTRAINT ck_cash_ledger_balance_nonneg CHECK ((balance_after >= (0)::numeric)),
    CONSTRAINT ck_cash_ledger_bucket_match CHECK ((hour_ts_utc = date_trunc('hour'::text, event_ts_utc))),
    CONSTRAINT ck_cash_ledger_event_type_not_blank CHECK ((length(btrim(event_type)) > 0)),
    CONSTRAINT ck_cash_ledger_hour_aligned CHECK ((date_trunc('hour'::text, hour_ts_utc) = hour_ts_utc)),
    CONSTRAINT ck_cash_ledger_ref_type_not_blank CHECK ((length(btrim(ref_type)) > 0))
);


--
-- Name: cash_ledger_ledger_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.cash_ledger_phase1a_archive ALTER COLUMN ledger_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.cash_ledger_ledger_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: cash_ledger_v2_ledger_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.cash_ledger ALTER COLUMN ledger_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.cash_ledger_v2_ledger_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: cluster_exposure_hourly_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cluster_exposure_hourly_state (
    run_mode public.run_mode_enum NOT NULL,
    account_id smallint NOT NULL,
    cluster_id smallint NOT NULL,
    hour_ts_utc timestamp with time zone NOT NULL,
    source_run_id uuid NOT NULL,
    gross_exposure_notional numeric(38,18) NOT NULL,
    exposure_pct numeric(12,10) NOT NULL,
    max_cluster_exposure_pct numeric(12,10) NOT NULL,
    state_hash character(64) NOT NULL,
    parent_risk_hash character(64) NOT NULL,
    row_hash character(64) NOT NULL,
    CONSTRAINT ck_cluster_exposure_hourly_state_cap_range CHECK (((max_cluster_exposure_pct > (0)::numeric) AND (max_cluster_exposure_pct <= 0.08))),
    CONSTRAINT ck_cluster_exposure_hourly_state_exposure_range CHECK (((exposure_pct >= (0)::numeric) AND (exposure_pct <= (1)::numeric))),
    CONSTRAINT ck_cluster_exposure_hourly_state_hour_aligned CHECK ((date_trunc('hour'::text, hour_ts_utc) = hour_ts_utc))
);


--
-- Name: correlation_cluster; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.correlation_cluster (
    cluster_id smallint NOT NULL,
    cluster_code text NOT NULL,
    description text,
    is_active boolean DEFAULT true NOT NULL,
    created_at_utc timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_correlation_cluster_code_not_blank CHECK ((length(btrim(cluster_code)) > 0))
);


--
-- Name: correlation_cluster_cluster_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.correlation_cluster ALTER COLUMN cluster_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.correlation_cluster_cluster_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: cost_profile; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cost_profile (
    cost_profile_id smallint NOT NULL,
    venue text NOT NULL,
    fee_rate numeric(10,6) NOT NULL,
    slippage_model_name text NOT NULL,
    slippage_param_hash character(64) NOT NULL,
    effective_from_utc timestamp with time zone NOT NULL,
    effective_to_utc timestamp with time zone,
    is_active boolean DEFAULT true NOT NULL,
    CONSTRAINT ck_cost_profile_effective_window CHECK (((effective_to_utc IS NULL) OR (effective_to_utc > effective_from_utc))),
    CONSTRAINT ck_cost_profile_fee_rate_range CHECK (((fee_rate >= (0)::numeric) AND (fee_rate <= (1)::numeric))),
    CONSTRAINT ck_cost_profile_kraken_fee_fixed CHECK (((venue <> 'KRAKEN'::text) OR (fee_rate = 0.004000))),
    CONSTRAINT ck_cost_profile_slippage_model_not_blank CHECK ((length(btrim(slippage_model_name)) > 0)),
    CONSTRAINT ck_cost_profile_venue_not_blank CHECK ((length(btrim(venue)) > 0)),
    CONSTRAINT ck_cost_profile_venue_upper CHECK ((venue = upper(venue)))
);


--
-- Name: cost_profile_cost_profile_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.cost_profile ALTER COLUMN cost_profile_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.cost_profile_cost_profile_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: executed_trade; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.executed_trade (
    trade_id uuid NOT NULL,
    lot_id uuid NOT NULL,
    run_id uuid NOT NULL,
    run_mode public.run_mode_enum NOT NULL,
    account_id smallint NOT NULL,
    asset_id smallint NOT NULL,
    hour_ts_utc timestamp with time zone NOT NULL,
    entry_ts_utc timestamp with time zone NOT NULL,
    exit_ts_utc timestamp with time zone NOT NULL,
    entry_price numeric(38,18) NOT NULL,
    exit_price numeric(38,18) NOT NULL,
    quantity numeric(38,18) NOT NULL,
    gross_pnl numeric(38,18) NOT NULL,
    net_pnl numeric(38,18) NOT NULL,
    total_fee numeric(38,18) NOT NULL,
    total_slippage_cost numeric(38,18) NOT NULL,
    holding_hours integer NOT NULL,
    origin_hour_ts_utc timestamp with time zone NOT NULL,
    parent_lot_hash character(64) NOT NULL,
    row_hash character(64) NOT NULL,
    CONSTRAINT ck_executed_trade_bucket_match CHECK ((hour_ts_utc = date_trunc('hour'::text, exit_ts_utc))),
    CONSTRAINT ck_executed_trade_entry_price_pos CHECK ((entry_price > (0)::numeric)),
    CONSTRAINT ck_executed_trade_exit_price_pos CHECK ((exit_price > (0)::numeric)),
    CONSTRAINT ck_executed_trade_fee_nonneg CHECK ((total_fee >= (0)::numeric)),
    CONSTRAINT ck_executed_trade_holding_nonneg CHECK ((holding_hours >= 0)),
    CONSTRAINT ck_executed_trade_hour_aligned CHECK ((date_trunc('hour'::text, hour_ts_utc) = hour_ts_utc)),
    CONSTRAINT ck_executed_trade_net_pnl_formula CHECK ((net_pnl = ((gross_pnl - total_fee) - total_slippage_cost))),
    CONSTRAINT ck_executed_trade_qty_pos CHECK ((quantity > (0)::numeric)),
    CONSTRAINT ck_executed_trade_slippage_nonneg CHECK ((total_slippage_cost >= (0)::numeric)),
    CONSTRAINT ck_executed_trade_time_order CHECK ((exit_ts_utc >= entry_ts_utc)),
    CONSTRAINT ck_executed_trade_v2_exit_after_origin CHECK ((exit_ts_utc >= origin_hour_ts_utc)),
    CONSTRAINT ck_executed_trade_v2_net_pnl_formula CHECK ((net_pnl = ((gross_pnl - total_fee) - total_slippage_cost))),
    CONSTRAINT ck_executed_trade_v2_origin_hour_aligned CHECK ((date_trunc('hour'::text, origin_hour_ts_utc) = origin_hour_ts_utc))
);


--
-- Name: executed_trade_phase1a_archive; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.executed_trade_phase1a_archive (
    trade_id uuid NOT NULL,
    lot_id uuid NOT NULL,
    run_id uuid NOT NULL,
    run_mode public.run_mode_enum NOT NULL,
    account_id smallint NOT NULL,
    asset_id smallint NOT NULL,
    hour_ts_utc timestamp with time zone NOT NULL,
    entry_ts_utc timestamp with time zone NOT NULL,
    exit_ts_utc timestamp with time zone NOT NULL,
    entry_price numeric(38,18) NOT NULL,
    exit_price numeric(38,18) NOT NULL,
    quantity numeric(38,18) NOT NULL,
    gross_pnl numeric(38,18) NOT NULL,
    net_pnl numeric(38,18) NOT NULL,
    total_fee numeric(38,18) NOT NULL,
    total_slippage_cost numeric(38,18) NOT NULL,
    holding_hours integer NOT NULL,
    CONSTRAINT ck_executed_trade_bucket_match CHECK ((hour_ts_utc = date_trunc('hour'::text, exit_ts_utc))),
    CONSTRAINT ck_executed_trade_entry_price_pos CHECK ((entry_price > (0)::numeric)),
    CONSTRAINT ck_executed_trade_exit_price_pos CHECK ((exit_price > (0)::numeric)),
    CONSTRAINT ck_executed_trade_fee_nonneg CHECK ((total_fee >= (0)::numeric)),
    CONSTRAINT ck_executed_trade_holding_nonneg CHECK ((holding_hours >= 0)),
    CONSTRAINT ck_executed_trade_hour_aligned CHECK ((date_trunc('hour'::text, hour_ts_utc) = hour_ts_utc)),
    CONSTRAINT ck_executed_trade_net_pnl_formula CHECK ((net_pnl = ((gross_pnl - total_fee) - total_slippage_cost))),
    CONSTRAINT ck_executed_trade_qty_pos CHECK ((quantity > (0)::numeric)),
    CONSTRAINT ck_executed_trade_slippage_nonneg CHECK ((total_slippage_cost >= (0)::numeric)),
    CONSTRAINT ck_executed_trade_time_order CHECK ((exit_ts_utc >= entry_ts_utc))
);


--
-- Name: feature_definition; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.feature_definition (
    feature_id integer NOT NULL,
    feature_name text NOT NULL,
    feature_group text NOT NULL,
    lookback_hours integer NOT NULL,
    value_dtype text DEFAULT 'NUMERIC'::text NOT NULL,
    feature_version text NOT NULL,
    created_at_utc timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_feature_definition_dtype CHECK ((value_dtype = 'NUMERIC'::text)),
    CONSTRAINT ck_feature_definition_group_not_blank CHECK ((length(btrim(feature_group)) > 0)),
    CONSTRAINT ck_feature_definition_lookback_nonneg CHECK ((lookback_hours >= 0)),
    CONSTRAINT ck_feature_definition_name_not_blank CHECK ((length(btrim(feature_name)) > 0))
);


--
-- Name: feature_definition_feature_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.feature_definition ALTER COLUMN feature_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.feature_definition_feature_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: feature_snapshot; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.feature_snapshot (
    run_id uuid NOT NULL,
    run_mode public.run_mode_enum NOT NULL,
    asset_id smallint NOT NULL,
    hour_ts_utc timestamp with time zone NOT NULL,
    feature_id integer NOT NULL,
    feature_value numeric(38,18) NOT NULL,
    source_window_start_utc timestamp with time zone NOT NULL,
    source_window_end_utc timestamp with time zone NOT NULL,
    input_data_hash character(64) NOT NULL,
    row_hash character(64) NOT NULL,
    CONSTRAINT ck_feature_snapshot_hour_aligned CHECK ((date_trunc('hour'::text, hour_ts_utc) = hour_ts_utc)),
    CONSTRAINT ck_feature_snapshot_source_window CHECK (((source_window_start_utc <= source_window_end_utc) AND (source_window_end_utc <= hour_ts_utc)))
);


--
-- Name: market_ohlcv_hourly; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.market_ohlcv_hourly (
    asset_id smallint NOT NULL,
    hour_ts_utc timestamp with time zone NOT NULL,
    open_price numeric(38,18) NOT NULL,
    high_price numeric(38,18) NOT NULL,
    low_price numeric(38,18) NOT NULL,
    close_price numeric(38,18) NOT NULL,
    volume_base numeric(38,18) NOT NULL,
    volume_quote numeric(38,18) NOT NULL,
    trade_count bigint NOT NULL,
    source_venue text NOT NULL,
    ingest_run_id uuid NOT NULL,
    row_hash character(64) NOT NULL,
    CONSTRAINT ck_market_ohlcv_hourly_close_pos CHECK ((close_price > (0)::numeric)),
    CONSTRAINT ck_market_ohlcv_hourly_high_bounds CHECK ((high_price >= GREATEST(open_price, close_price, low_price))),
    CONSTRAINT ck_market_ohlcv_hourly_high_low CHECK ((high_price >= low_price)),
    CONSTRAINT ck_market_ohlcv_hourly_high_pos CHECK ((high_price > (0)::numeric)),
    CONSTRAINT ck_market_ohlcv_hourly_hour_aligned CHECK ((date_trunc('hour'::text, hour_ts_utc) = hour_ts_utc)),
    CONSTRAINT ck_market_ohlcv_hourly_low_bounds CHECK ((low_price <= LEAST(open_price, close_price, high_price))),
    CONSTRAINT ck_market_ohlcv_hourly_low_pos CHECK ((low_price > (0)::numeric)),
    CONSTRAINT ck_market_ohlcv_hourly_open_pos CHECK ((open_price > (0)::numeric)),
    CONSTRAINT ck_market_ohlcv_hourly_trade_count_nonneg CHECK ((trade_count >= 0)),
    CONSTRAINT ck_market_ohlcv_hourly_volume_base_nonneg CHECK ((volume_base >= (0)::numeric)),
    CONSTRAINT ck_market_ohlcv_hourly_volume_quote_nonneg CHECK ((volume_quote >= (0)::numeric))
);


--
-- Name: meta_learner_component; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.meta_learner_component (
    run_id uuid NOT NULL,
    run_mode public.run_mode_enum NOT NULL,
    asset_id smallint NOT NULL,
    hour_ts_utc timestamp with time zone NOT NULL,
    horizon public.horizon_enum NOT NULL,
    meta_model_version_id bigint NOT NULL,
    base_model_version_id bigint NOT NULL,
    base_prob_up numeric(12,10) NOT NULL,
    base_expected_return numeric(38,18) NOT NULL,
    component_weight numeric(38,18) NOT NULL,
    row_hash character(64) NOT NULL,
    account_id smallint NOT NULL,
    CONSTRAINT ck_meta_learner_component_distinct_models CHECK ((meta_model_version_id <> base_model_version_id)),
    CONSTRAINT ck_meta_learner_component_hour_aligned CHECK ((date_trunc('hour'::text, hour_ts_utc) = hour_ts_utc)),
    CONSTRAINT ck_meta_learner_component_prob_range CHECK (((base_prob_up >= (0)::numeric) AND (base_prob_up <= (1)::numeric)))
);


--
-- Name: meta_learner_component_phase1a_archive; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.meta_learner_component_phase1a_archive (
    run_id uuid NOT NULL,
    run_mode public.run_mode_enum NOT NULL,
    asset_id smallint NOT NULL,
    hour_ts_utc timestamp with time zone NOT NULL,
    horizon public.horizon_enum NOT NULL,
    meta_model_version_id bigint NOT NULL,
    base_model_version_id bigint NOT NULL,
    base_prob_up numeric(12,10) NOT NULL,
    base_expected_return numeric(38,18) NOT NULL,
    component_weight numeric(38,18) NOT NULL,
    CONSTRAINT ck_meta_learner_component_distinct_models CHECK ((meta_model_version_id <> base_model_version_id)),
    CONSTRAINT ck_meta_learner_component_hour_aligned CHECK ((date_trunc('hour'::text, hour_ts_utc) = hour_ts_utc)),
    CONSTRAINT ck_meta_learner_component_prob_range CHECK (((base_prob_up >= (0)::numeric) AND (base_prob_up <= (1)::numeric)))
);


--
-- Name: model_activation_gate; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.model_activation_gate (
    activation_id bigint NOT NULL,
    model_version_id bigint NOT NULL,
    run_mode public.run_mode_enum NOT NULL,
    validation_backtest_run_id uuid NOT NULL,
    validation_window_end_utc timestamp with time zone NOT NULL,
    approved_at_utc timestamp with time zone DEFAULT now() NOT NULL,
    status text NOT NULL,
    approval_hash character(64) NOT NULL,
    CONSTRAINT ck_model_activation_gate_status CHECK ((status = ANY (ARRAY['APPROVED'::text, 'REVOKED'::text])))
);


--
-- Name: model_activation_gate_activation_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.model_activation_gate ALTER COLUMN activation_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.model_activation_gate_activation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: model_prediction; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.model_prediction (
    run_id uuid NOT NULL,
    run_mode public.run_mode_enum NOT NULL,
    asset_id smallint NOT NULL,
    hour_ts_utc timestamp with time zone NOT NULL,
    horizon public.horizon_enum NOT NULL,
    model_version_id bigint NOT NULL,
    model_role public.model_role_enum NOT NULL,
    prob_up numeric(12,10) NOT NULL,
    expected_return numeric(38,18) NOT NULL,
    input_feature_hash character(64) NOT NULL,
    upstream_hash character(64) NOT NULL,
    row_hash character(64) NOT NULL,
    account_id smallint NOT NULL,
    training_window_id bigint,
    lineage_backtest_run_id uuid,
    lineage_fold_index integer,
    lineage_horizon public.horizon_enum,
    activation_id bigint,
    CONSTRAINT ck_model_prediction_hour_aligned CHECK ((date_trunc('hour'::text, hour_ts_utc) = hour_ts_utc)),
    CONSTRAINT ck_model_prediction_mode_lineage_activation CHECK ((((run_mode = 'BACKTEST'::public.run_mode_enum) AND (training_window_id IS NOT NULL) AND (lineage_backtest_run_id IS NOT NULL) AND (lineage_fold_index IS NOT NULL) AND (lineage_horizon IS NOT NULL) AND (activation_id IS NULL) AND (horizon = lineage_horizon)) OR ((run_mode = ANY (ARRAY['PAPER'::public.run_mode_enum, 'LIVE'::public.run_mode_enum])) AND (training_window_id IS NULL) AND (lineage_backtest_run_id IS NULL) AND (lineage_fold_index IS NULL) AND (lineage_horizon IS NULL) AND (activation_id IS NOT NULL)))),
    CONSTRAINT ck_model_prediction_prob_range CHECK (((prob_up >= (0)::numeric) AND (prob_up <= (1)::numeric)))
);


--
-- Name: model_prediction_phase1a_archive; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.model_prediction_phase1a_archive (
    run_id uuid NOT NULL,
    run_mode public.run_mode_enum NOT NULL,
    asset_id smallint NOT NULL,
    hour_ts_utc timestamp with time zone NOT NULL,
    horizon public.horizon_enum NOT NULL,
    model_version_id bigint NOT NULL,
    model_role public.model_role_enum NOT NULL,
    prob_up numeric(12,10) NOT NULL,
    expected_return numeric(38,18) NOT NULL,
    input_feature_hash character(64) NOT NULL,
    CONSTRAINT ck_model_prediction_hour_aligned CHECK ((date_trunc('hour'::text, hour_ts_utc) = hour_ts_utc)),
    CONSTRAINT ck_model_prediction_prob_range CHECK (((prob_up >= (0)::numeric) AND (prob_up <= (1)::numeric)))
);


--
-- Name: model_training_window; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.model_training_window (
    training_window_id bigint NOT NULL,
    model_version_id bigint NOT NULL,
    fold_index integer NOT NULL,
    horizon public.horizon_enum NOT NULL,
    train_start_utc timestamp with time zone NOT NULL,
    train_end_utc timestamp with time zone NOT NULL,
    valid_start_utc timestamp with time zone NOT NULL,
    valid_end_utc timestamp with time zone NOT NULL,
    row_hash character(64) NOT NULL,
    backtest_run_id uuid NOT NULL,
    training_window_hash character(64) NOT NULL,
    CONSTRAINT ck_model_training_window_fold_nonneg CHECK ((fold_index >= 0)),
    CONSTRAINT ck_model_training_window_ordering CHECK (((train_start_utc < train_end_utc) AND (train_end_utc < valid_start_utc) AND (valid_start_utc < valid_end_utc)))
);


--
-- Name: model_training_window_training_window_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.model_training_window ALTER COLUMN training_window_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.model_training_window_training_window_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: model_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.model_version (
    model_version_id bigint NOT NULL,
    model_name text NOT NULL,
    model_role public.model_role_enum NOT NULL,
    version_label text NOT NULL,
    mlflow_model_uri text NOT NULL,
    mlflow_run_id text NOT NULL,
    feature_set_version text NOT NULL,
    hyperparams_hash character(64) NOT NULL,
    training_data_hash character(64) NOT NULL,
    created_at_utc timestamp with time zone DEFAULT now() NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    CONSTRAINT ck_model_version_mlflow_run_id_not_blank CHECK ((length(btrim(mlflow_run_id)) > 0)),
    CONSTRAINT ck_model_version_mlflow_uri_not_blank CHECK ((length(btrim(mlflow_model_uri)) > 0)),
    CONSTRAINT ck_model_version_model_name_not_blank CHECK ((length(btrim(model_name)) > 0)),
    CONSTRAINT ck_model_version_version_label_not_blank CHECK ((length(btrim(version_label)) > 0))
);


--
-- Name: model_version_model_version_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.model_version ALTER COLUMN model_version_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.model_version_model_version_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: order_book_snapshot; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.order_book_snapshot (
    asset_id smallint NOT NULL,
    snapshot_ts_utc timestamp with time zone NOT NULL,
    hour_ts_utc timestamp with time zone NOT NULL,
    best_bid_price numeric(38,18) NOT NULL,
    best_ask_price numeric(38,18) NOT NULL,
    best_bid_size numeric(38,18) NOT NULL,
    best_ask_size numeric(38,18) NOT NULL,
    spread_abs numeric(38,18) GENERATED ALWAYS AS ((best_ask_price - best_bid_price)) STORED,
    spread_bps numeric(12,8) GENERATED ALWAYS AS ((((best_ask_price - best_bid_price) / NULLIF(best_bid_price, (0)::numeric)) * (10000)::numeric)) STORED,
    source_venue text NOT NULL,
    ingest_run_id uuid NOT NULL,
    row_hash character(64) NOT NULL,
    CONSTRAINT ck_order_book_snapshot_ask_ge_bid CHECK ((best_ask_price >= best_bid_price)),
    CONSTRAINT ck_order_book_snapshot_ask_pos CHECK ((best_ask_price > (0)::numeric)),
    CONSTRAINT ck_order_book_snapshot_ask_size_nonneg CHECK ((best_ask_size >= (0)::numeric)),
    CONSTRAINT ck_order_book_snapshot_bid_pos CHECK ((best_bid_price > (0)::numeric)),
    CONSTRAINT ck_order_book_snapshot_bid_size_nonneg CHECK ((best_bid_size >= (0)::numeric)),
    CONSTRAINT ck_order_book_snapshot_bucket_match CHECK ((hour_ts_utc = date_trunc('hour'::text, snapshot_ts_utc))),
    CONSTRAINT ck_order_book_snapshot_hour_aligned CHECK ((date_trunc('hour'::text, hour_ts_utc) = hour_ts_utc))
);


--
-- Name: order_fill; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.order_fill (
    fill_id uuid NOT NULL,
    order_id uuid NOT NULL,
    run_id uuid NOT NULL,
    run_mode public.run_mode_enum NOT NULL,
    account_id smallint NOT NULL,
    asset_id smallint NOT NULL,
    exchange_trade_id text NOT NULL,
    fill_ts_utc timestamp with time zone NOT NULL,
    hour_ts_utc timestamp with time zone NOT NULL,
    fill_price numeric(38,18) NOT NULL,
    fill_qty numeric(38,18) NOT NULL,
    fill_notional numeric(38,18) NOT NULL,
    fee_paid numeric(38,18) NOT NULL,
    fee_rate numeric(10,6) NOT NULL,
    realized_slippage_rate numeric(10,6) NOT NULL,
    liquidity_flag text DEFAULT 'UNKNOWN'::text NOT NULL,
    origin_hour_ts_utc timestamp with time zone NOT NULL,
    fee_expected numeric(38,18) GENERATED ALWAYS AS ((fill_notional * fee_rate)) STORED,
    slippage_cost numeric(38,18) NOT NULL,
    parent_order_hash character(64) NOT NULL,
    row_hash character(64) NOT NULL,
    CONSTRAINT ck_order_fill_bucket_match CHECK ((hour_ts_utc = date_trunc('hour'::text, fill_ts_utc))),
    CONSTRAINT ck_order_fill_exchange_trade_id_not_blank CHECK ((length(btrim(exchange_trade_id)) > 0)),
    CONSTRAINT ck_order_fill_fee_nonneg CHECK ((fee_paid >= (0)::numeric)),
    CONSTRAINT ck_order_fill_fee_rate_range CHECK (((fee_rate >= (0)::numeric) AND (fee_rate <= (1)::numeric))),
    CONSTRAINT ck_order_fill_hour_aligned CHECK ((date_trunc('hour'::text, hour_ts_utc) = hour_ts_utc)),
    CONSTRAINT ck_order_fill_liquidity_flag CHECK ((liquidity_flag = ANY (ARRAY['MAKER'::text, 'TAKER'::text, 'UNKNOWN'::text]))),
    CONSTRAINT ck_order_fill_notional_formula CHECK ((fill_notional = (fill_price * fill_qty))),
    CONSTRAINT ck_order_fill_notional_pos CHECK ((fill_notional > (0)::numeric)),
    CONSTRAINT ck_order_fill_price_pos CHECK ((fill_price > (0)::numeric)),
    CONSTRAINT ck_order_fill_qty_pos CHECK ((fill_qty > (0)::numeric)),
    CONSTRAINT ck_order_fill_slippage_nonneg CHECK ((realized_slippage_rate >= (0)::numeric)),
    CONSTRAINT ck_order_fill_v2_fee_formula CHECK ((fee_paid = fee_expected)),
    CONSTRAINT ck_order_fill_v2_fill_after_origin CHECK ((fill_ts_utc >= origin_hour_ts_utc)),
    CONSTRAINT ck_order_fill_v2_origin_hour_aligned CHECK ((date_trunc('hour'::text, origin_hour_ts_utc) = origin_hour_ts_utc)),
    CONSTRAINT ck_order_fill_v2_slippage_formula CHECK ((slippage_cost = (fill_notional * realized_slippage_rate)))
);


--
-- Name: order_fill_phase1a_archive; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.order_fill_phase1a_archive (
    fill_id uuid NOT NULL,
    order_id uuid NOT NULL,
    run_id uuid NOT NULL,
    run_mode public.run_mode_enum NOT NULL,
    account_id smallint NOT NULL,
    asset_id smallint NOT NULL,
    exchange_trade_id text NOT NULL,
    fill_ts_utc timestamp with time zone NOT NULL,
    hour_ts_utc timestamp with time zone NOT NULL,
    fill_price numeric(38,18) NOT NULL,
    fill_qty numeric(38,18) NOT NULL,
    fill_notional numeric(38,18) NOT NULL,
    fee_paid numeric(38,18) NOT NULL,
    fee_rate numeric(10,6) NOT NULL,
    realized_slippage_rate numeric(10,6) NOT NULL,
    liquidity_flag text DEFAULT 'UNKNOWN'::text NOT NULL,
    CONSTRAINT ck_order_fill_bucket_match CHECK ((hour_ts_utc = date_trunc('hour'::text, fill_ts_utc))),
    CONSTRAINT ck_order_fill_exchange_trade_id_not_blank CHECK ((length(btrim(exchange_trade_id)) > 0)),
    CONSTRAINT ck_order_fill_fee_nonneg CHECK ((fee_paid >= (0)::numeric)),
    CONSTRAINT ck_order_fill_fee_rate_range CHECK (((fee_rate >= (0)::numeric) AND (fee_rate <= (1)::numeric))),
    CONSTRAINT ck_order_fill_hour_aligned CHECK ((date_trunc('hour'::text, hour_ts_utc) = hour_ts_utc)),
    CONSTRAINT ck_order_fill_liquidity_flag CHECK ((liquidity_flag = ANY (ARRAY['MAKER'::text, 'TAKER'::text, 'UNKNOWN'::text]))),
    CONSTRAINT ck_order_fill_notional_formula CHECK ((fill_notional = (fill_price * fill_qty))),
    CONSTRAINT ck_order_fill_notional_pos CHECK ((fill_notional > (0)::numeric)),
    CONSTRAINT ck_order_fill_price_pos CHECK ((fill_price > (0)::numeric)),
    CONSTRAINT ck_order_fill_qty_pos CHECK ((fill_qty > (0)::numeric)),
    CONSTRAINT ck_order_fill_slippage_nonneg CHECK ((realized_slippage_rate >= (0)::numeric))
);


--
-- Name: order_request; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.order_request (
    order_id uuid NOT NULL,
    signal_id uuid NOT NULL,
    run_id uuid NOT NULL,
    run_mode public.run_mode_enum NOT NULL,
    account_id smallint NOT NULL,
    asset_id smallint NOT NULL,
    client_order_id text NOT NULL,
    request_ts_utc timestamp with time zone NOT NULL,
    hour_ts_utc timestamp with time zone NOT NULL,
    side public.order_side_enum NOT NULL,
    order_type public.order_type_enum NOT NULL,
    tif text NOT NULL,
    limit_price numeric(38,18),
    requested_qty numeric(38,18) NOT NULL,
    requested_notional numeric(38,18) NOT NULL,
    pre_order_cash_available numeric(38,18) NOT NULL,
    risk_check_passed boolean NOT NULL,
    status public.order_status_enum NOT NULL,
    cost_profile_id smallint NOT NULL,
    origin_hour_ts_utc timestamp with time zone NOT NULL,
    risk_state_run_id uuid NOT NULL,
    cluster_membership_id bigint NOT NULL,
    parent_signal_hash character(64) NOT NULL,
    row_hash character(64) NOT NULL,
    CONSTRAINT ck_order_request_cash_nonneg CHECK ((pre_order_cash_available >= (0)::numeric)),
    CONSTRAINT ck_order_request_client_order_id_not_blank CHECK ((length(btrim(client_order_id)) > 0)),
    CONSTRAINT ck_order_request_hour_aligned CHECK ((date_trunc('hour'::text, hour_ts_utc) = hour_ts_utc)),
    CONSTRAINT ck_order_request_limit_price_rule CHECK ((((order_type = 'LIMIT'::public.order_type_enum) AND (limit_price IS NOT NULL) AND (limit_price > (0)::numeric)) OR ((order_type = 'MARKET'::public.order_type_enum) AND (limit_price IS NULL)))),
    CONSTRAINT ck_order_request_no_leverage_buy CHECK (((side <> 'BUY'::public.order_side_enum) OR (requested_notional <= pre_order_cash_available))),
    CONSTRAINT ck_order_request_notional_pos CHECK ((requested_notional > (0)::numeric)),
    CONSTRAINT ck_order_request_qty_pos CHECK ((requested_qty > (0)::numeric)),
    CONSTRAINT ck_order_request_request_in_hour CHECK (((request_ts_utc >= hour_ts_utc) AND (request_ts_utc < (hour_ts_utc + '01:00:00'::interval)))),
    CONSTRAINT ck_order_request_risk_gate CHECK (((risk_check_passed = true) OR (status = 'REJECTED'::public.order_status_enum))),
    CONSTRAINT ck_order_request_tif CHECK ((tif = ANY (ARRAY['GTC'::text, 'IOC'::text, 'FOK'::text]))),
    CONSTRAINT ck_order_request_v2_origin_hour_aligned CHECK ((date_trunc('hour'::text, origin_hour_ts_utc) = origin_hour_ts_utc)),
    CONSTRAINT ck_order_request_v2_request_after_origin CHECK ((request_ts_utc >= origin_hour_ts_utc))
);


--
-- Name: order_request_phase1a_archive; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.order_request_phase1a_archive (
    order_id uuid NOT NULL,
    signal_id uuid NOT NULL,
    run_id uuid NOT NULL,
    run_mode public.run_mode_enum NOT NULL,
    account_id smallint NOT NULL,
    asset_id smallint NOT NULL,
    client_order_id text NOT NULL,
    request_ts_utc timestamp with time zone NOT NULL,
    hour_ts_utc timestamp with time zone NOT NULL,
    side public.order_side_enum NOT NULL,
    order_type public.order_type_enum NOT NULL,
    tif text NOT NULL,
    limit_price numeric(38,18),
    requested_qty numeric(38,18) NOT NULL,
    requested_notional numeric(38,18) NOT NULL,
    pre_order_cash_available numeric(38,18) NOT NULL,
    risk_check_passed boolean NOT NULL,
    status public.order_status_enum NOT NULL,
    cost_profile_id smallint NOT NULL,
    CONSTRAINT ck_order_request_cash_nonneg CHECK ((pre_order_cash_available >= (0)::numeric)),
    CONSTRAINT ck_order_request_client_order_id_not_blank CHECK ((length(btrim(client_order_id)) > 0)),
    CONSTRAINT ck_order_request_hour_aligned CHECK ((date_trunc('hour'::text, hour_ts_utc) = hour_ts_utc)),
    CONSTRAINT ck_order_request_limit_price_rule CHECK ((((order_type = 'LIMIT'::public.order_type_enum) AND (limit_price IS NOT NULL) AND (limit_price > (0)::numeric)) OR ((order_type = 'MARKET'::public.order_type_enum) AND (limit_price IS NULL)))),
    CONSTRAINT ck_order_request_no_leverage_buy CHECK (((side <> 'BUY'::public.order_side_enum) OR (requested_notional <= pre_order_cash_available))),
    CONSTRAINT ck_order_request_notional_pos CHECK ((requested_notional > (0)::numeric)),
    CONSTRAINT ck_order_request_qty_pos CHECK ((requested_qty > (0)::numeric)),
    CONSTRAINT ck_order_request_request_in_hour CHECK (((request_ts_utc >= hour_ts_utc) AND (request_ts_utc < (hour_ts_utc + '01:00:00'::interval)))),
    CONSTRAINT ck_order_request_risk_gate CHECK (((risk_check_passed = true) OR (status = 'REJECTED'::public.order_status_enum))),
    CONSTRAINT ck_order_request_tif CHECK ((tif = ANY (ARRAY['GTC'::text, 'IOC'::text, 'FOK'::text])))
);


--
-- Name: portfolio_hourly_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.portfolio_hourly_state (
    run_mode public.run_mode_enum NOT NULL,
    account_id smallint NOT NULL,
    hour_ts_utc timestamp with time zone NOT NULL,
    cash_balance numeric(38,18) NOT NULL,
    market_value numeric(38,18) NOT NULL,
    portfolio_value numeric(38,18) NOT NULL,
    peak_portfolio_value numeric(38,18) NOT NULL,
    drawdown_pct numeric(12,10) NOT NULL,
    total_exposure_pct numeric(12,10) NOT NULL,
    open_position_count integer NOT NULL,
    halted boolean DEFAULT false NOT NULL,
    source_run_id uuid NOT NULL,
    reconciliation_hash character(64) NOT NULL,
    row_hash character(64) NOT NULL,
    CONSTRAINT ck_portfolio_hourly_state_cash_nonneg CHECK ((cash_balance >= (0)::numeric)),
    CONSTRAINT ck_portfolio_hourly_state_drawdown_range CHECK (((drawdown_pct >= (0)::numeric) AND (drawdown_pct <= (1)::numeric))),
    CONSTRAINT ck_portfolio_hourly_state_exposure_range CHECK (((total_exposure_pct >= (0)::numeric) AND (total_exposure_pct <= (1)::numeric))),
    CONSTRAINT ck_portfolio_hourly_state_hour_aligned CHECK ((date_trunc('hour'::text, hour_ts_utc) = hour_ts_utc)),
    CONSTRAINT ck_portfolio_hourly_state_market_nonneg CHECK ((market_value >= (0)::numeric)),
    CONSTRAINT ck_portfolio_hourly_state_peak_ge_value CHECK ((peak_portfolio_value >= portfolio_value)),
    CONSTRAINT ck_portfolio_hourly_state_peak_nonneg CHECK ((peak_portfolio_value >= (0)::numeric)),
    CONSTRAINT ck_portfolio_hourly_state_pos_count_range CHECK (((open_position_count >= 0) AND (open_position_count <= 10))),
    CONSTRAINT ck_portfolio_hourly_state_value_nonneg CHECK ((portfolio_value >= (0)::numeric)),
    CONSTRAINT ck_portfolio_hourly_state_value_reconcile CHECK ((portfolio_value = (cash_balance + market_value)))
);


--
-- Name: portfolio_hourly_state_identity; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.portfolio_hourly_state_identity (
    run_mode public.run_mode_enum NOT NULL,
    account_id smallint NOT NULL,
    hour_ts_utc timestamp with time zone NOT NULL,
    CONSTRAINT ck_portfolio_hourly_state_identity_hour_aligned CHECK ((date_trunc('hour'::text, hour_ts_utc) = hour_ts_utc))
);


--
-- Name: position_hourly_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.position_hourly_state (
    run_mode public.run_mode_enum NOT NULL,
    account_id smallint NOT NULL,
    asset_id smallint NOT NULL,
    hour_ts_utc timestamp with time zone NOT NULL,
    quantity numeric(38,18) NOT NULL,
    avg_cost numeric(38,18) NOT NULL,
    mark_price numeric(38,18) NOT NULL,
    market_value numeric(38,18) NOT NULL,
    unrealized_pnl numeric(38,18) NOT NULL,
    realized_pnl_cum numeric(38,18) NOT NULL,
    exposure_pct numeric(12,10) NOT NULL,
    source_run_id uuid NOT NULL,
    row_hash character(64) NOT NULL,
    CONSTRAINT ck_position_hourly_state_avg_cost_nonneg CHECK ((avg_cost >= (0)::numeric)),
    CONSTRAINT ck_position_hourly_state_exposure_range CHECK (((exposure_pct >= (0)::numeric) AND (exposure_pct <= (1)::numeric))),
    CONSTRAINT ck_position_hourly_state_hour_aligned CHECK ((date_trunc('hour'::text, hour_ts_utc) = hour_ts_utc)),
    CONSTRAINT ck_position_hourly_state_mark_price_pos CHECK ((mark_price > (0)::numeric)),
    CONSTRAINT ck_position_hourly_state_market_value_formula CHECK ((market_value = (quantity * mark_price))),
    CONSTRAINT ck_position_hourly_state_market_value_nonneg CHECK ((market_value >= (0)::numeric)),
    CONSTRAINT ck_position_hourly_state_qty_nonneg CHECK ((quantity >= (0)::numeric))
);


--
-- Name: position_lot; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.position_lot (
    lot_id uuid NOT NULL,
    open_fill_id uuid NOT NULL,
    run_id uuid NOT NULL,
    run_mode public.run_mode_enum NOT NULL,
    account_id smallint NOT NULL,
    asset_id smallint NOT NULL,
    hour_ts_utc timestamp with time zone NOT NULL,
    open_ts_utc timestamp with time zone NOT NULL,
    open_price numeric(38,18) NOT NULL,
    open_qty numeric(38,18) NOT NULL,
    open_notional numeric(38,18) NOT NULL,
    open_fee numeric(38,18) NOT NULL,
    remaining_qty numeric(38,18) NOT NULL,
    origin_hour_ts_utc timestamp with time zone NOT NULL,
    parent_fill_hash character(64) NOT NULL,
    row_hash character(64) NOT NULL,
    CONSTRAINT ck_position_lot_bucket_match CHECK ((hour_ts_utc = date_trunc('hour'::text, open_ts_utc))),
    CONSTRAINT ck_position_lot_hour_aligned CHECK ((date_trunc('hour'::text, hour_ts_utc) = hour_ts_utc)),
    CONSTRAINT ck_position_lot_notional_formula CHECK ((open_notional = (open_price * open_qty))),
    CONSTRAINT ck_position_lot_open_fee_nonneg CHECK ((open_fee >= (0)::numeric)),
    CONSTRAINT ck_position_lot_open_notional_pos CHECK ((open_notional > (0)::numeric)),
    CONSTRAINT ck_position_lot_open_price_pos CHECK ((open_price > (0)::numeric)),
    CONSTRAINT ck_position_lot_open_qty_pos CHECK ((open_qty > (0)::numeric)),
    CONSTRAINT ck_position_lot_remaining_range CHECK (((remaining_qty >= (0)::numeric) AND (remaining_qty <= open_qty))),
    CONSTRAINT ck_position_lot_v2_open_after_origin CHECK ((open_ts_utc >= origin_hour_ts_utc)),
    CONSTRAINT ck_position_lot_v2_origin_hour_aligned CHECK ((date_trunc('hour'::text, origin_hour_ts_utc) = origin_hour_ts_utc))
);


--
-- Name: position_lot_phase1a_archive; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.position_lot_phase1a_archive (
    lot_id uuid NOT NULL,
    open_fill_id uuid NOT NULL,
    run_id uuid NOT NULL,
    run_mode public.run_mode_enum NOT NULL,
    account_id smallint NOT NULL,
    asset_id smallint NOT NULL,
    hour_ts_utc timestamp with time zone NOT NULL,
    open_ts_utc timestamp with time zone NOT NULL,
    open_price numeric(38,18) NOT NULL,
    open_qty numeric(38,18) NOT NULL,
    open_notional numeric(38,18) NOT NULL,
    open_fee numeric(38,18) NOT NULL,
    remaining_qty numeric(38,18) NOT NULL,
    CONSTRAINT ck_position_lot_bucket_match CHECK ((hour_ts_utc = date_trunc('hour'::text, open_ts_utc))),
    CONSTRAINT ck_position_lot_hour_aligned CHECK ((date_trunc('hour'::text, hour_ts_utc) = hour_ts_utc)),
    CONSTRAINT ck_position_lot_notional_formula CHECK ((open_notional = (open_price * open_qty))),
    CONSTRAINT ck_position_lot_open_fee_nonneg CHECK ((open_fee >= (0)::numeric)),
    CONSTRAINT ck_position_lot_open_notional_pos CHECK ((open_notional > (0)::numeric)),
    CONSTRAINT ck_position_lot_open_price_pos CHECK ((open_price > (0)::numeric)),
    CONSTRAINT ck_position_lot_open_qty_pos CHECK ((open_qty > (0)::numeric)),
    CONSTRAINT ck_position_lot_remaining_range CHECK (((remaining_qty >= (0)::numeric) AND (remaining_qty <= open_qty)))
);


--
-- Name: regime_output; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.regime_output (
    run_id uuid NOT NULL,
    run_mode public.run_mode_enum NOT NULL,
    asset_id smallint NOT NULL,
    hour_ts_utc timestamp with time zone NOT NULL,
    model_version_id bigint NOT NULL,
    regime_label text NOT NULL,
    regime_probability numeric(12,10) NOT NULL,
    input_feature_hash character(64) NOT NULL,
    upstream_hash character(64) NOT NULL,
    row_hash character(64) NOT NULL,
    account_id smallint NOT NULL,
    training_window_id bigint,
    lineage_backtest_run_id uuid,
    lineage_fold_index integer,
    lineage_horizon public.horizon_enum,
    activation_id bigint,
    CONSTRAINT ck_regime_output_hour_aligned CHECK ((date_trunc('hour'::text, hour_ts_utc) = hour_ts_utc)),
    CONSTRAINT ck_regime_output_label_not_blank CHECK ((length(btrim(regime_label)) > 0)),
    CONSTRAINT ck_regime_output_mode_lineage_activation CHECK ((((run_mode = 'BACKTEST'::public.run_mode_enum) AND (training_window_id IS NOT NULL) AND (lineage_backtest_run_id IS NOT NULL) AND (lineage_fold_index IS NOT NULL) AND (lineage_horizon IS NOT NULL) AND (activation_id IS NULL)) OR ((run_mode = ANY (ARRAY['PAPER'::public.run_mode_enum, 'LIVE'::public.run_mode_enum])) AND (training_window_id IS NULL) AND (lineage_backtest_run_id IS NULL) AND (lineage_fold_index IS NULL) AND (lineage_horizon IS NULL) AND (activation_id IS NOT NULL)))),
    CONSTRAINT ck_regime_output_probability_range CHECK (((regime_probability >= (0)::numeric) AND (regime_probability <= (1)::numeric)))
);


--
-- Name: regime_output_phase1a_archive; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.regime_output_phase1a_archive (
    run_id uuid NOT NULL,
    run_mode public.run_mode_enum NOT NULL,
    asset_id smallint NOT NULL,
    hour_ts_utc timestamp with time zone NOT NULL,
    model_version_id bigint NOT NULL,
    regime_label text NOT NULL,
    regime_probability numeric(12,10) NOT NULL,
    input_feature_hash character(64) NOT NULL,
    CONSTRAINT ck_regime_output_hour_aligned CHECK ((date_trunc('hour'::text, hour_ts_utc) = hour_ts_utc)),
    CONSTRAINT ck_regime_output_label_not_blank CHECK ((length(btrim(regime_label)) > 0)),
    CONSTRAINT ck_regime_output_probability_range CHECK (((regime_probability >= (0)::numeric) AND (regime_probability <= (1)::numeric)))
);


--
-- Name: replay_manifest; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.replay_manifest (
    run_id uuid NOT NULL,
    account_id smallint NOT NULL,
    run_mode public.run_mode_enum NOT NULL,
    origin_hour_ts_utc timestamp with time zone NOT NULL,
    run_seed_hash character(64) NOT NULL,
    replay_root_hash character(64) NOT NULL,
    authoritative_row_count bigint NOT NULL,
    generated_at_utc timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: risk_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.risk_event (
    risk_event_id uuid NOT NULL,
    run_id uuid NOT NULL,
    run_mode public.run_mode_enum NOT NULL,
    account_id smallint NOT NULL,
    event_ts_utc timestamp with time zone NOT NULL,
    hour_ts_utc timestamp with time zone NOT NULL,
    event_type text NOT NULL,
    severity text NOT NULL,
    reason_code text NOT NULL,
    details jsonb DEFAULT '{}'::jsonb NOT NULL,
    related_state_hour_ts_utc timestamp with time zone NOT NULL,
    origin_hour_ts_utc timestamp with time zone NOT NULL,
    parent_state_hash character(64) NOT NULL,
    row_hash character(64) NOT NULL,
    CONSTRAINT ck_risk_event_bucket_match CHECK ((hour_ts_utc = date_trunc('hour'::text, event_ts_utc))),
    CONSTRAINT ck_risk_event_event_type_not_blank CHECK ((length(btrim(event_type)) > 0)),
    CONSTRAINT ck_risk_event_hour_aligned CHECK ((date_trunc('hour'::text, hour_ts_utc) = hour_ts_utc)),
    CONSTRAINT ck_risk_event_reason_not_blank CHECK ((length(btrim(reason_code)) > 0)),
    CONSTRAINT ck_risk_event_related_state_not_future CHECK ((related_state_hour_ts_utc <= hour_ts_utc)),
    CONSTRAINT ck_risk_event_severity CHECK ((severity = ANY (ARRAY['LOW'::text, 'MEDIUM'::text, 'HIGH'::text, 'CRITICAL'::text]))),
    CONSTRAINT ck_risk_event_v2_event_after_origin CHECK ((event_ts_utc >= origin_hour_ts_utc)),
    CONSTRAINT ck_risk_event_v2_origin_hour_aligned CHECK ((date_trunc('hour'::text, origin_hour_ts_utc) = origin_hour_ts_utc))
);


--
-- Name: risk_event_phase1a_archive; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.risk_event_phase1a_archive (
    risk_event_id uuid NOT NULL,
    run_id uuid NOT NULL,
    run_mode public.run_mode_enum NOT NULL,
    account_id smallint NOT NULL,
    event_ts_utc timestamp with time zone NOT NULL,
    hour_ts_utc timestamp with time zone NOT NULL,
    event_type text NOT NULL,
    severity text NOT NULL,
    reason_code text NOT NULL,
    details jsonb DEFAULT '{}'::jsonb NOT NULL,
    related_state_hour_ts_utc timestamp with time zone NOT NULL,
    CONSTRAINT ck_risk_event_bucket_match CHECK ((hour_ts_utc = date_trunc('hour'::text, event_ts_utc))),
    CONSTRAINT ck_risk_event_event_type_not_blank CHECK ((length(btrim(event_type)) > 0)),
    CONSTRAINT ck_risk_event_hour_aligned CHECK ((date_trunc('hour'::text, hour_ts_utc) = hour_ts_utc)),
    CONSTRAINT ck_risk_event_reason_not_blank CHECK ((length(btrim(reason_code)) > 0)),
    CONSTRAINT ck_risk_event_related_state_not_future CHECK ((related_state_hour_ts_utc <= hour_ts_utc)),
    CONSTRAINT ck_risk_event_severity CHECK ((severity = ANY (ARRAY['LOW'::text, 'MEDIUM'::text, 'HIGH'::text, 'CRITICAL'::text])))
);


--
-- Name: risk_hourly_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.risk_hourly_state (
    run_mode public.run_mode_enum NOT NULL,
    account_id smallint NOT NULL,
    hour_ts_utc timestamp with time zone NOT NULL,
    portfolio_value numeric(38,18) NOT NULL,
    peak_portfolio_value numeric(38,18) NOT NULL,
    drawdown_pct numeric(12,10) NOT NULL,
    drawdown_tier public.drawdown_tier_enum NOT NULL,
    base_risk_fraction numeric(12,10) NOT NULL,
    max_concurrent_positions integer NOT NULL,
    max_total_exposure_pct numeric(12,10) NOT NULL,
    max_cluster_exposure_pct numeric(12,10) NOT NULL,
    halt_new_entries boolean DEFAULT false NOT NULL,
    kill_switch_active boolean DEFAULT false NOT NULL,
    kill_switch_reason text,
    requires_manual_review boolean DEFAULT false NOT NULL,
    evaluated_at_utc timestamp with time zone DEFAULT now() NOT NULL,
    source_run_id uuid NOT NULL,
    state_hash character(64) NOT NULL,
    row_hash character(64) NOT NULL,
    CONSTRAINT ck_risk_hourly_state_base_risk_range CHECK (((base_risk_fraction >= (0)::numeric) AND (base_risk_fraction <= 0.02))),
    CONSTRAINT ck_risk_hourly_state_cluster_exposure_cap CHECK (((max_cluster_exposure_pct > (0)::numeric) AND (max_cluster_exposure_pct <= 0.08))),
    CONSTRAINT ck_risk_hourly_state_dd10_controls CHECK (((drawdown_pct < 0.10) OR (base_risk_fraction <= 0.015))),
    CONSTRAINT ck_risk_hourly_state_dd15_controls CHECK (((drawdown_pct < 0.15) OR ((base_risk_fraction <= 0.01) AND (max_concurrent_positions <= 5)))),
    CONSTRAINT ck_risk_hourly_state_dd20_halt CHECK (((drawdown_pct < 0.20) OR ((halt_new_entries = true) AND (requires_manual_review = true) AND (base_risk_fraction = (0)::numeric) AND (drawdown_tier = 'HALT20'::public.drawdown_tier_enum)))),
    CONSTRAINT ck_risk_hourly_state_drawdown_range CHECK (((drawdown_pct >= (0)::numeric) AND (drawdown_pct <= (1)::numeric))),
    CONSTRAINT ck_risk_hourly_state_hour_aligned CHECK ((date_trunc('hour'::text, hour_ts_utc) = hour_ts_utc)),
    CONSTRAINT ck_risk_hourly_state_kill_switch_reason CHECK (((kill_switch_active = false) OR (length(btrim(COALESCE(kill_switch_reason, ''::text))) > 0))),
    CONSTRAINT ck_risk_hourly_state_max_pos_range CHECK (((max_concurrent_positions >= 0) AND (max_concurrent_positions <= 10))),
    CONSTRAINT ck_risk_hourly_state_peak_ge_value CHECK ((peak_portfolio_value >= portfolio_value)),
    CONSTRAINT ck_risk_hourly_state_tier_mapping CHECK ((((drawdown_pct < 0.10) AND (drawdown_tier = 'NORMAL'::public.drawdown_tier_enum)) OR ((drawdown_pct >= 0.10) AND (drawdown_pct < 0.15) AND (drawdown_tier = 'DD10'::public.drawdown_tier_enum)) OR ((drawdown_pct >= 0.15) AND (drawdown_pct < 0.20) AND (drawdown_tier = 'DD15'::public.drawdown_tier_enum)) OR ((drawdown_pct >= 0.20) AND (drawdown_tier = 'HALT20'::public.drawdown_tier_enum)))),
    CONSTRAINT ck_risk_hourly_state_total_exposure_cap CHECK (((max_total_exposure_pct > (0)::numeric) AND (max_total_exposure_pct <= 0.20)))
);


--
-- Name: risk_hourly_state_identity; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.risk_hourly_state_identity (
    run_mode public.run_mode_enum NOT NULL,
    account_id smallint NOT NULL,
    hour_ts_utc timestamp with time zone NOT NULL,
    source_run_id uuid NOT NULL,
    CONSTRAINT ck_risk_hourly_state_identity_hour_aligned CHECK ((date_trunc('hour'::text, hour_ts_utc) = hour_ts_utc))
);


--
-- Name: run_context; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.run_context (
    run_id uuid NOT NULL,
    account_id smallint NOT NULL,
    run_mode public.run_mode_enum NOT NULL,
    hour_ts_utc timestamp with time zone NOT NULL,
    cycle_seq bigint NOT NULL,
    code_version_sha character(40) NOT NULL,
    config_hash character(64) NOT NULL,
    data_snapshot_hash character(64) NOT NULL,
    random_seed integer NOT NULL,
    backtest_run_id uuid,
    started_at_utc timestamp with time zone DEFAULT now() NOT NULL,
    completed_at_utc timestamp with time zone,
    status text DEFAULT 'STARTED'::text NOT NULL,
    origin_hour_ts_utc timestamp with time zone NOT NULL,
    run_seed_hash character(64) NOT NULL,
    context_hash character(64) NOT NULL,
    replay_root_hash character(64) NOT NULL,
    CONSTRAINT ck_run_context_backtest_link CHECK ((((run_mode = 'BACKTEST'::public.run_mode_enum) AND (backtest_run_id IS NOT NULL)) OR ((run_mode = ANY (ARRAY['PAPER'::public.run_mode_enum, 'LIVE'::public.run_mode_enum])) AND (backtest_run_id IS NULL)))),
    CONSTRAINT ck_run_context_completed_after_started CHECK (((completed_at_utc IS NULL) OR (completed_at_utc >= started_at_utc))),
    CONSTRAINT ck_run_context_cycle_seq_pos CHECK ((cycle_seq >= 0)),
    CONSTRAINT ck_run_context_hour_aligned CHECK ((date_trunc('hour'::text, hour_ts_utc) = hour_ts_utc)),
    CONSTRAINT ck_run_context_origin_hour_aligned CHECK ((date_trunc('hour'::text, origin_hour_ts_utc) = origin_hour_ts_utc)),
    CONSTRAINT ck_run_context_status CHECK ((status = ANY (ARRAY['STARTED'::text, 'COMPLETED'::text, 'FAILED'::text, 'SKIPPED'::text])))
);


--
-- Name: schema_migration_control; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schema_migration_control (
    migration_name text NOT NULL,
    locked boolean NOT NULL,
    lock_reason text NOT NULL,
    locked_at_utc timestamp with time zone DEFAULT now() NOT NULL,
    unlocked_at_utc timestamp with time zone
);


--
-- Name: trade_signal; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trade_signal (
    signal_id uuid NOT NULL,
    run_id uuid NOT NULL,
    run_mode public.run_mode_enum NOT NULL,
    account_id smallint NOT NULL,
    asset_id smallint NOT NULL,
    hour_ts_utc timestamp with time zone NOT NULL,
    horizon public.horizon_enum NOT NULL,
    action public.signal_action_enum NOT NULL,
    direction text NOT NULL,
    confidence numeric(12,10) NOT NULL,
    expected_return numeric(38,18) NOT NULL,
    assumed_fee_rate numeric(10,6) NOT NULL,
    assumed_slippage_rate numeric(10,6) NOT NULL,
    net_edge numeric(38,18) NOT NULL,
    target_position_notional numeric(38,18) NOT NULL,
    position_size_fraction numeric(12,10) NOT NULL,
    risk_state_hour_ts_utc timestamp with time zone NOT NULL,
    decision_hash character(64) NOT NULL,
    expected_cost_rate numeric(10,6) GENERATED ALWAYS AS ((assumed_fee_rate + assumed_slippage_rate)) STORED,
    risk_state_run_id uuid NOT NULL,
    cluster_membership_id bigint NOT NULL,
    upstream_hash character(64) NOT NULL,
    row_hash character(64) NOT NULL,
    CONSTRAINT ck_trade_signal_confidence_range CHECK (((confidence >= (0)::numeric) AND (confidence <= (1)::numeric))),
    CONSTRAINT ck_trade_signal_direction CHECK ((direction = ANY (ARRAY['LONG'::text, 'FLAT'::text]))),
    CONSTRAINT ck_trade_signal_enter_direction CHECK (((action <> 'ENTER'::public.signal_action_enum) OR (direction = 'LONG'::text))),
    CONSTRAINT ck_trade_signal_enter_edge CHECK (((action <> 'ENTER'::public.signal_action_enum) OR (net_edge > (0)::numeric))),
    CONSTRAINT ck_trade_signal_enter_return_gt_cost CHECK (((action <> 'ENTER'::public.signal_action_enum) OR (expected_return > (assumed_fee_rate + assumed_slippage_rate)))),
    CONSTRAINT ck_trade_signal_exit_direction CHECK (((action <> 'EXIT'::public.signal_action_enum) OR (direction = 'FLAT'::text))),
    CONSTRAINT ck_trade_signal_fee_rate_range CHECK (((assumed_fee_rate >= (0)::numeric) AND (assumed_fee_rate <= (1)::numeric))),
    CONSTRAINT ck_trade_signal_hour_aligned CHECK ((date_trunc('hour'::text, hour_ts_utc) = hour_ts_utc)),
    CONSTRAINT ck_trade_signal_position_fraction_range CHECK (((position_size_fraction >= (0)::numeric) AND (position_size_fraction <= (1)::numeric))),
    CONSTRAINT ck_trade_signal_risk_hour_aligned CHECK ((date_trunc('hour'::text, risk_state_hour_ts_utc) = risk_state_hour_ts_utc)),
    CONSTRAINT ck_trade_signal_risk_hour_match CHECK ((risk_state_hour_ts_utc = hour_ts_utc)),
    CONSTRAINT ck_trade_signal_slippage_rate_range CHECK (((assumed_slippage_rate >= (0)::numeric) AND (assumed_slippage_rate <= (1)::numeric))),
    CONSTRAINT ck_trade_signal_target_notional_nonneg CHECK ((target_position_notional >= (0)::numeric)),
    CONSTRAINT ck_trade_signal_v2_enter_cost_gate CHECK (((action <> 'ENTER'::public.signal_action_enum) OR (expected_return > expected_cost_rate))),
    CONSTRAINT ck_trade_signal_v2_net_edge_formula CHECK ((net_edge = (expected_return - expected_cost_rate))),
    CONSTRAINT ck_trade_signal_v2_risk_not_future CHECK ((risk_state_hour_ts_utc <= hour_ts_utc))
);


--
-- Name: trade_signal_phase1a_archive; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trade_signal_phase1a_archive (
    signal_id uuid NOT NULL,
    run_id uuid NOT NULL,
    run_mode public.run_mode_enum NOT NULL,
    account_id smallint NOT NULL,
    asset_id smallint NOT NULL,
    hour_ts_utc timestamp with time zone NOT NULL,
    horizon public.horizon_enum NOT NULL,
    action public.signal_action_enum NOT NULL,
    direction text NOT NULL,
    confidence numeric(12,10) NOT NULL,
    expected_return numeric(38,18) NOT NULL,
    assumed_fee_rate numeric(10,6) NOT NULL,
    assumed_slippage_rate numeric(10,6) NOT NULL,
    net_edge numeric(38,18) NOT NULL,
    target_position_notional numeric(38,18) NOT NULL,
    position_size_fraction numeric(12,10) NOT NULL,
    risk_state_hour_ts_utc timestamp with time zone NOT NULL,
    decision_hash character(64) NOT NULL,
    CONSTRAINT ck_trade_signal_confidence_range CHECK (((confidence >= (0)::numeric) AND (confidence <= (1)::numeric))),
    CONSTRAINT ck_trade_signal_direction CHECK ((direction = ANY (ARRAY['LONG'::text, 'FLAT'::text]))),
    CONSTRAINT ck_trade_signal_enter_direction CHECK (((action <> 'ENTER'::public.signal_action_enum) OR (direction = 'LONG'::text))),
    CONSTRAINT ck_trade_signal_enter_edge CHECK (((action <> 'ENTER'::public.signal_action_enum) OR (net_edge > (0)::numeric))),
    CONSTRAINT ck_trade_signal_enter_return_gt_cost CHECK (((action <> 'ENTER'::public.signal_action_enum) OR (expected_return > (assumed_fee_rate + assumed_slippage_rate)))),
    CONSTRAINT ck_trade_signal_exit_direction CHECK (((action <> 'EXIT'::public.signal_action_enum) OR (direction = 'FLAT'::text))),
    CONSTRAINT ck_trade_signal_fee_rate_range CHECK (((assumed_fee_rate >= (0)::numeric) AND (assumed_fee_rate <= (1)::numeric))),
    CONSTRAINT ck_trade_signal_hour_aligned CHECK ((date_trunc('hour'::text, hour_ts_utc) = hour_ts_utc)),
    CONSTRAINT ck_trade_signal_position_fraction_range CHECK (((position_size_fraction >= (0)::numeric) AND (position_size_fraction <= (1)::numeric))),
    CONSTRAINT ck_trade_signal_risk_hour_aligned CHECK ((date_trunc('hour'::text, risk_state_hour_ts_utc) = risk_state_hour_ts_utc)),
    CONSTRAINT ck_trade_signal_risk_hour_match CHECK ((risk_state_hour_ts_utc = hour_ts_utc)),
    CONSTRAINT ck_trade_signal_slippage_rate_range CHECK (((assumed_slippage_rate >= (0)::numeric) AND (assumed_slippage_rate <= (1)::numeric))),
    CONSTRAINT ck_trade_signal_target_notional_nonneg CHECK ((target_position_notional >= (0)::numeric))
);


--
-- Name: cash_ledger cash_ledger_v2_account_id_run_mode_event_ts_utc_ref_type_re_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cash_ledger
    ADD CONSTRAINT cash_ledger_v2_account_id_run_mode_event_ts_utc_ref_type_re_key UNIQUE (account_id, run_mode, event_ts_utc, ref_type, ref_id, event_type);


--
-- Name: cash_ledger cash_ledger_v2_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cash_ledger
    ADD CONSTRAINT cash_ledger_v2_pkey PRIMARY KEY (ledger_id);


--
-- Name: executed_trade executed_trade_v2_lot_id_exit_ts_utc_quantity_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.executed_trade
    ADD CONSTRAINT executed_trade_v2_lot_id_exit_ts_utc_quantity_key UNIQUE (lot_id, exit_ts_utc, quantity);


--
-- Name: executed_trade executed_trade_v2_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.executed_trade
    ADD CONSTRAINT executed_trade_v2_pkey PRIMARY KEY (trade_id);


--
-- Name: meta_learner_component meta_learner_component_v2_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.meta_learner_component
    ADD CONSTRAINT meta_learner_component_v2_pkey PRIMARY KEY (run_id, asset_id, horizon, meta_model_version_id, base_model_version_id, hour_ts_utc);


--
-- Name: model_prediction model_prediction_v2_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_prediction
    ADD CONSTRAINT model_prediction_v2_pkey PRIMARY KEY (run_id, asset_id, horizon, model_version_id, hour_ts_utc);


--
-- Name: order_fill order_fill_v2_fill_id_run_id_run_mode_account_id_asset_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_fill
    ADD CONSTRAINT order_fill_v2_fill_id_run_id_run_mode_account_id_asset_id_key UNIQUE (fill_id, run_id, run_mode, account_id, asset_id);


--
-- Name: order_fill order_fill_v2_order_id_exchange_trade_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_fill
    ADD CONSTRAINT order_fill_v2_order_id_exchange_trade_id_key UNIQUE (order_id, exchange_trade_id);


--
-- Name: order_fill order_fill_v2_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_fill
    ADD CONSTRAINT order_fill_v2_pkey PRIMARY KEY (fill_id);


--
-- Name: order_request order_request_v2_client_order_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_request
    ADD CONSTRAINT order_request_v2_client_order_id_key UNIQUE (client_order_id);


--
-- Name: order_request order_request_v2_order_id_run_id_run_mode_account_id_asset__key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_request
    ADD CONSTRAINT order_request_v2_order_id_run_id_run_mode_account_id_asset__key UNIQUE (order_id, run_id, run_mode, account_id, asset_id);


--
-- Name: order_request order_request_v2_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_request
    ADD CONSTRAINT order_request_v2_pkey PRIMARY KEY (order_id);


--
-- Name: account pk_account; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account
    ADD CONSTRAINT pk_account PRIMARY KEY (account_id);


--
-- Name: asset pk_asset; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asset
    ADD CONSTRAINT pk_asset PRIMARY KEY (asset_id);


--
-- Name: asset_cluster_membership pk_asset_cluster_membership; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asset_cluster_membership
    ADD CONSTRAINT pk_asset_cluster_membership PRIMARY KEY (membership_id);


--
-- Name: backtest_fold_result pk_backtest_fold_result; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backtest_fold_result
    ADD CONSTRAINT pk_backtest_fold_result PRIMARY KEY (backtest_run_id, fold_index);


--
-- Name: backtest_run pk_backtest_run; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backtest_run
    ADD CONSTRAINT pk_backtest_run PRIMARY KEY (backtest_run_id);


--
-- Name: cash_ledger_phase1a_archive pk_cash_ledger; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cash_ledger_phase1a_archive
    ADD CONSTRAINT pk_cash_ledger PRIMARY KEY (ledger_id);


--
-- Name: cluster_exposure_hourly_state pk_cluster_exposure_hourly_state; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cluster_exposure_hourly_state
    ADD CONSTRAINT pk_cluster_exposure_hourly_state PRIMARY KEY (run_mode, account_id, cluster_id, hour_ts_utc);


--
-- Name: correlation_cluster pk_correlation_cluster; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.correlation_cluster
    ADD CONSTRAINT pk_correlation_cluster PRIMARY KEY (cluster_id);


--
-- Name: cost_profile pk_cost_profile; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cost_profile
    ADD CONSTRAINT pk_cost_profile PRIMARY KEY (cost_profile_id);


--
-- Name: executed_trade_phase1a_archive pk_executed_trade; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.executed_trade_phase1a_archive
    ADD CONSTRAINT pk_executed_trade PRIMARY KEY (trade_id);


--
-- Name: feature_definition pk_feature_definition; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feature_definition
    ADD CONSTRAINT pk_feature_definition PRIMARY KEY (feature_id);


--
-- Name: feature_snapshot pk_feature_snapshot; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feature_snapshot
    ADD CONSTRAINT pk_feature_snapshot PRIMARY KEY (run_id, asset_id, feature_id, hour_ts_utc);


--
-- Name: market_ohlcv_hourly pk_market_ohlcv_hourly; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.market_ohlcv_hourly
    ADD CONSTRAINT pk_market_ohlcv_hourly PRIMARY KEY (asset_id, hour_ts_utc, source_venue);


--
-- Name: meta_learner_component_phase1a_archive pk_meta_learner_component; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.meta_learner_component_phase1a_archive
    ADD CONSTRAINT pk_meta_learner_component PRIMARY KEY (run_id, asset_id, horizon, meta_model_version_id, base_model_version_id, hour_ts_utc);


--
-- Name: model_activation_gate pk_model_activation_gate; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_activation_gate
    ADD CONSTRAINT pk_model_activation_gate PRIMARY KEY (activation_id);


--
-- Name: model_prediction_phase1a_archive pk_model_prediction; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_prediction_phase1a_archive
    ADD CONSTRAINT pk_model_prediction PRIMARY KEY (run_id, asset_id, horizon, model_version_id, hour_ts_utc);


--
-- Name: model_training_window pk_model_training_window; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_training_window
    ADD CONSTRAINT pk_model_training_window PRIMARY KEY (training_window_id);


--
-- Name: model_version pk_model_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_version
    ADD CONSTRAINT pk_model_version PRIMARY KEY (model_version_id);


--
-- Name: order_book_snapshot pk_order_book_snapshot; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_book_snapshot
    ADD CONSTRAINT pk_order_book_snapshot PRIMARY KEY (asset_id, snapshot_ts_utc, source_venue);


--
-- Name: order_fill_phase1a_archive pk_order_fill; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_fill_phase1a_archive
    ADD CONSTRAINT pk_order_fill PRIMARY KEY (fill_id);


--
-- Name: order_request_phase1a_archive pk_order_request; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_request_phase1a_archive
    ADD CONSTRAINT pk_order_request PRIMARY KEY (order_id);


--
-- Name: portfolio_hourly_state pk_portfolio_hourly_state; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.portfolio_hourly_state
    ADD CONSTRAINT pk_portfolio_hourly_state PRIMARY KEY (run_mode, account_id, hour_ts_utc);


--
-- Name: portfolio_hourly_state_identity pk_portfolio_hourly_state_identity; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.portfolio_hourly_state_identity
    ADD CONSTRAINT pk_portfolio_hourly_state_identity PRIMARY KEY (run_mode, account_id, hour_ts_utc);


--
-- Name: position_hourly_state pk_position_hourly_state; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.position_hourly_state
    ADD CONSTRAINT pk_position_hourly_state PRIMARY KEY (run_mode, account_id, asset_id, hour_ts_utc);


--
-- Name: position_lot_phase1a_archive pk_position_lot; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.position_lot_phase1a_archive
    ADD CONSTRAINT pk_position_lot PRIMARY KEY (lot_id);


--
-- Name: regime_output_phase1a_archive pk_regime_output; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.regime_output_phase1a_archive
    ADD CONSTRAINT pk_regime_output PRIMARY KEY (run_id, asset_id, hour_ts_utc);


--
-- Name: replay_manifest pk_replay_manifest; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.replay_manifest
    ADD CONSTRAINT pk_replay_manifest PRIMARY KEY (run_id);


--
-- Name: risk_event_phase1a_archive pk_risk_event; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_event_phase1a_archive
    ADD CONSTRAINT pk_risk_event PRIMARY KEY (risk_event_id);


--
-- Name: risk_hourly_state pk_risk_hourly_state; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_hourly_state
    ADD CONSTRAINT pk_risk_hourly_state PRIMARY KEY (run_mode, account_id, hour_ts_utc);


--
-- Name: risk_hourly_state_identity pk_risk_hourly_state_identity; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_hourly_state_identity
    ADD CONSTRAINT pk_risk_hourly_state_identity PRIMARY KEY (run_mode, account_id, hour_ts_utc, source_run_id);


--
-- Name: run_context pk_run_context; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_context
    ADD CONSTRAINT pk_run_context PRIMARY KEY (run_id);


--
-- Name: trade_signal_phase1a_archive pk_trade_signal; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_signal_phase1a_archive
    ADD CONSTRAINT pk_trade_signal PRIMARY KEY (signal_id);


--
-- Name: position_lot position_lot_v2_lot_id_run_id_run_mode_account_id_asset_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.position_lot
    ADD CONSTRAINT position_lot_v2_lot_id_run_id_run_mode_account_id_asset_id_key UNIQUE (lot_id, run_id, run_mode, account_id, asset_id);


--
-- Name: position_lot position_lot_v2_open_fill_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.position_lot
    ADD CONSTRAINT position_lot_v2_open_fill_id_key UNIQUE (open_fill_id);


--
-- Name: position_lot position_lot_v2_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.position_lot
    ADD CONSTRAINT position_lot_v2_pkey PRIMARY KEY (lot_id);


--
-- Name: regime_output regime_output_v2_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.regime_output
    ADD CONSTRAINT regime_output_v2_pkey PRIMARY KEY (run_id, asset_id, hour_ts_utc);


--
-- Name: risk_event risk_event_v2_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_event
    ADD CONSTRAINT risk_event_v2_pkey PRIMARY KEY (risk_event_id);


--
-- Name: schema_migration_control schema_migration_control_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migration_control
    ADD CONSTRAINT schema_migration_control_pkey PRIMARY KEY (migration_name);


--
-- Name: trade_signal trade_signal_v2_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_signal
    ADD CONSTRAINT trade_signal_v2_pkey PRIMARY KEY (signal_id);


--
-- Name: trade_signal trade_signal_v2_run_id_account_id_asset_id_horizon_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_signal
    ADD CONSTRAINT trade_signal_v2_run_id_account_id_asset_id_horizon_key UNIQUE (run_id, account_id, asset_id, horizon);


--
-- Name: trade_signal trade_signal_v2_signal_id_run_id_run_mode_account_id_asset__key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_signal
    ADD CONSTRAINT trade_signal_v2_signal_id_run_id_run_mode_account_id_asset__key UNIQUE (signal_id, run_id, run_mode, account_id, asset_id);


--
-- Name: account uq_account_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.account
    ADD CONSTRAINT uq_account_code UNIQUE (account_code);


--
-- Name: asset_cluster_membership uq_asset_cluster_membership_asset_effective_from; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asset_cluster_membership
    ADD CONSTRAINT uq_asset_cluster_membership_asset_effective_from UNIQUE (asset_id, effective_from_utc);


--
-- Name: asset uq_asset_venue_symbol; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asset
    ADD CONSTRAINT uq_asset_venue_symbol UNIQUE (venue, symbol);


--
-- Name: cash_ledger_phase1a_archive uq_cash_ledger_idempotency; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cash_ledger_phase1a_archive
    ADD CONSTRAINT uq_cash_ledger_idempotency UNIQUE (account_id, run_mode, event_ts_utc, ref_type, ref_id, event_type);


--
-- Name: cash_ledger uq_cash_ledger_v2_account_mode_seq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cash_ledger
    ADD CONSTRAINT uq_cash_ledger_v2_account_mode_seq UNIQUE (account_id, run_mode, ledger_seq);


--
-- Name: correlation_cluster uq_correlation_cluster_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.correlation_cluster
    ADD CONSTRAINT uq_correlation_cluster_code UNIQUE (cluster_code);


--
-- Name: cost_profile uq_cost_profile_venue_effective_from; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cost_profile
    ADD CONSTRAINT uq_cost_profile_venue_effective_from UNIQUE (venue, effective_from_utc);


--
-- Name: executed_trade_phase1a_archive uq_executed_trade_lot_exit_qty; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.executed_trade_phase1a_archive
    ADD CONSTRAINT uq_executed_trade_lot_exit_qty UNIQUE (lot_id, exit_ts_utc, quantity);


--
-- Name: feature_definition uq_feature_definition_name_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feature_definition
    ADD CONSTRAINT uq_feature_definition_name_version UNIQUE (feature_name, feature_version);


--
-- Name: meta_learner_component uq_meta_learner_component_identity_run_account_mode_hour; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.meta_learner_component
    ADD CONSTRAINT uq_meta_learner_component_identity_run_account_mode_hour UNIQUE (run_id, account_id, run_mode, asset_id, horizon, meta_model_version_id, base_model_version_id, hour_ts_utc);


--
-- Name: model_activation_gate uq_model_activation_gate_activation_model_mode; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_activation_gate
    ADD CONSTRAINT uq_model_activation_gate_activation_model_mode UNIQUE (activation_id, model_version_id, run_mode);


--
-- Name: model_prediction uq_model_prediction_identity_run_account_mode_hour; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_prediction
    ADD CONSTRAINT uq_model_prediction_identity_run_account_mode_hour UNIQUE (run_id, account_id, run_mode, asset_id, horizon, model_version_id, hour_ts_utc);


--
-- Name: model_training_window uq_model_training_window_run_model_fold_horizon; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_training_window
    ADD CONSTRAINT uq_model_training_window_run_model_fold_horizon UNIQUE (backtest_run_id, model_version_id, fold_index, horizon);


--
-- Name: model_version uq_model_version_name_label; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_version
    ADD CONSTRAINT uq_model_version_name_label UNIQUE (model_name, version_label);


--
-- Name: order_fill_phase1a_archive uq_order_fill_identity; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_fill_phase1a_archive
    ADD CONSTRAINT uq_order_fill_identity UNIQUE (fill_id, run_id, run_mode, account_id, asset_id);


--
-- Name: order_fill_phase1a_archive uq_order_fill_order_exchange_trade; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_fill_phase1a_archive
    ADD CONSTRAINT uq_order_fill_order_exchange_trade UNIQUE (order_id, exchange_trade_id);


--
-- Name: order_request_phase1a_archive uq_order_request_client_order_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_request_phase1a_archive
    ADD CONSTRAINT uq_order_request_client_order_id UNIQUE (client_order_id);


--
-- Name: order_request_phase1a_archive uq_order_request_identity; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_request_phase1a_archive
    ADD CONSTRAINT uq_order_request_identity UNIQUE (order_id, run_id, run_mode, account_id, asset_id);


--
-- Name: position_lot_phase1a_archive uq_position_lot_identity; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.position_lot_phase1a_archive
    ADD CONSTRAINT uq_position_lot_identity UNIQUE (lot_id, run_id, run_mode, account_id, asset_id);


--
-- Name: position_lot_phase1a_archive uq_position_lot_open_fill; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.position_lot_phase1a_archive
    ADD CONSTRAINT uq_position_lot_open_fill UNIQUE (open_fill_id);


--
-- Name: regime_output uq_regime_output_identity_run_account_mode_hour; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.regime_output
    ADD CONSTRAINT uq_regime_output_identity_run_account_mode_hour UNIQUE (run_id, account_id, run_mode, asset_id, model_version_id, hour_ts_utc);


--
-- Name: risk_hourly_state_identity uq_risk_hourly_state_identity_hour; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_hourly_state_identity
    ADD CONSTRAINT uq_risk_hourly_state_identity_hour UNIQUE (run_mode, account_id, hour_ts_utc);


--
-- Name: risk_hourly_state uq_risk_hourly_state_with_source; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_hourly_state
    ADD CONSTRAINT uq_risk_hourly_state_with_source UNIQUE (run_mode, account_id, hour_ts_utc, source_run_id);


--
-- Name: run_context uq_run_context_account_mode_hour; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_context
    ADD CONSTRAINT uq_run_context_account_mode_hour UNIQUE (account_id, run_mode, hour_ts_utc);


--
-- Name: run_context uq_run_context_run_account_mode_hour; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_context
    ADD CONSTRAINT uq_run_context_run_account_mode_hour UNIQUE (run_id, account_id, run_mode, hour_ts_utc);


--
-- Name: run_context uq_run_context_run_account_mode_origin_hour; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_context
    ADD CONSTRAINT uq_run_context_run_account_mode_origin_hour UNIQUE (run_id, account_id, run_mode, origin_hour_ts_utc);


--
-- Name: run_context uq_run_context_run_mode_hour; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_context
    ADD CONSTRAINT uq_run_context_run_mode_hour UNIQUE (run_id, run_mode, hour_ts_utc);


--
-- Name: trade_signal_phase1a_archive uq_trade_signal_identity; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_signal_phase1a_archive
    ADD CONSTRAINT uq_trade_signal_identity UNIQUE (signal_id, run_id, run_mode, account_id, asset_id);


--
-- Name: trade_signal_phase1a_archive uq_trade_signal_run_account_asset_horizon; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_signal_phase1a_archive
    ADD CONSTRAINT uq_trade_signal_run_account_asset_horizon UNIQUE (run_id, account_id, asset_id, horizon);


--
-- Name: trade_signal uq_trade_signal_v2_signal_cluster; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_signal
    ADD CONSTRAINT uq_trade_signal_v2_signal_cluster UNIQUE (signal_id, cluster_membership_id);


--
-- Name: trade_signal uq_trade_signal_v2_signal_riskrun; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_signal
    ADD CONSTRAINT uq_trade_signal_v2_signal_riskrun UNIQUE (signal_id, risk_state_run_id);


--
-- Name: cash_ledger_v2_account_id_event_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX cash_ledger_v2_account_id_event_ts_utc_idx ON public.cash_ledger USING btree (account_id, event_ts_utc DESC);


--
-- Name: cash_ledger_v2_hour_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX cash_ledger_v2_hour_ts_utc_idx ON public.cash_ledger USING btree (hour_ts_utc DESC);


--
-- Name: cash_ledger_v2_run_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX cash_ledger_v2_run_id_idx ON public.cash_ledger USING btree (run_id);


--
-- Name: executed_trade_v2_account_id_exit_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX executed_trade_v2_account_id_exit_ts_utc_idx ON public.executed_trade USING btree (account_id, exit_ts_utc DESC);


--
-- Name: executed_trade_v2_asset_id_exit_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX executed_trade_v2_asset_id_exit_ts_utc_idx ON public.executed_trade USING btree (asset_id, exit_ts_utc DESC);


--
-- Name: executed_trade_v2_lot_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX executed_trade_v2_lot_id_idx ON public.executed_trade USING btree (lot_id);


--
-- Name: feature_snapshot_hour_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX feature_snapshot_hour_ts_utc_idx ON public.feature_snapshot USING btree (hour_ts_utc DESC);


--
-- Name: idx_asset_cluster_membership_asset_effective; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_asset_cluster_membership_asset_effective ON public.asset_cluster_membership USING btree (asset_id, effective_from_utc DESC);


--
-- Name: idx_asset_is_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_asset_is_active ON public.asset USING btree (is_active);


--
-- Name: idx_backtest_fold_result_valid_range; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_backtest_fold_result_valid_range ON public.backtest_fold_result USING btree (valid_start_utc, valid_end_utc);


--
-- Name: idx_backtest_run_config_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_backtest_run_config_hash ON public.backtest_run USING btree (config_hash);


--
-- Name: idx_backtest_run_status_started_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_backtest_run_status_started_desc ON public.backtest_run USING btree (status, started_at_utc DESC);


--
-- Name: idx_cash_ledger_account_event_ts_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cash_ledger_account_event_ts_desc ON public.cash_ledger_phase1a_archive USING btree (account_id, event_ts_utc DESC);


--
-- Name: idx_cash_ledger_hour_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cash_ledger_hour_desc ON public.cash_ledger_phase1a_archive USING btree (hour_ts_utc DESC);


--
-- Name: idx_cash_ledger_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cash_ledger_run_id ON public.cash_ledger_phase1a_archive USING btree (run_id);


--
-- Name: idx_cash_ledger_v2_account_mode_event_seq; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cash_ledger_v2_account_mode_event_seq ON public.cash_ledger USING btree (account_id, run_mode, event_ts_utc, ledger_seq);


--
-- Name: idx_cluster_exposure_hourly_account_hour; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cluster_exposure_hourly_account_hour ON public.cluster_exposure_hourly_state USING btree (account_id, hour_ts_utc DESC);


--
-- Name: idx_cluster_exposure_hourly_cluster_hour; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cluster_exposure_hourly_cluster_hour ON public.cluster_exposure_hourly_state USING btree (cluster_id, hour_ts_utc DESC);


--
-- Name: idx_cost_profile_venue_effective_from_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cost_profile_venue_effective_from_desc ON public.cost_profile USING btree (venue, effective_from_utc DESC);


--
-- Name: idx_executed_trade_account_exit_ts_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_executed_trade_account_exit_ts_desc ON public.executed_trade_phase1a_archive USING btree (account_id, exit_ts_utc DESC);


--
-- Name: idx_executed_trade_asset_exit_ts_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_executed_trade_asset_exit_ts_desc ON public.executed_trade_phase1a_archive USING btree (asset_id, exit_ts_utc DESC);


--
-- Name: idx_executed_trade_lot_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_executed_trade_lot_id ON public.executed_trade_phase1a_archive USING btree (lot_id);


--
-- Name: idx_feature_snapshot_asset_hour_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_feature_snapshot_asset_hour_desc ON public.feature_snapshot USING btree (asset_id, hour_ts_utc DESC);


--
-- Name: idx_feature_snapshot_feature_hour_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_feature_snapshot_feature_hour_desc ON public.feature_snapshot USING btree (feature_id, hour_ts_utc DESC);


--
-- Name: idx_feature_snapshot_mode_hour_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_feature_snapshot_mode_hour_desc ON public.feature_snapshot USING btree (run_mode, hour_ts_utc DESC);


--
-- Name: idx_market_ohlcv_hour_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_market_ohlcv_hour_desc ON public.market_ohlcv_hourly USING btree (hour_ts_utc DESC);


--
-- Name: idx_meta_component_asset_hour_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_meta_component_asset_hour_desc ON public.meta_learner_component_phase1a_archive USING btree (asset_id, hour_ts_utc DESC);


--
-- Name: idx_meta_component_meta_model_hour_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_meta_component_meta_model_hour_desc ON public.meta_learner_component_phase1a_archive USING btree (meta_model_version_id, hour_ts_utc DESC);


--
-- Name: idx_model_prediction_asset_hour_horizon; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_model_prediction_asset_hour_horizon ON public.model_prediction_phase1a_archive USING btree (asset_id, hour_ts_utc DESC, horizon);


--
-- Name: idx_model_prediction_role_hour_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_model_prediction_role_hour_desc ON public.model_prediction_phase1a_archive USING btree (model_role, hour_ts_utc DESC);


--
-- Name: idx_model_training_window_valid_range; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_model_training_window_valid_range ON public.model_training_window USING btree (valid_start_utc, valid_end_utc);


--
-- Name: idx_model_version_role_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_model_version_role_active ON public.model_version USING btree (model_role, is_active);


--
-- Name: idx_order_book_asset_hour_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_order_book_asset_hour_desc ON public.order_book_snapshot USING btree (asset_id, hour_ts_utc DESC);


--
-- Name: idx_order_book_hour_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_order_book_hour_desc ON public.order_book_snapshot USING btree (hour_ts_utc DESC);


--
-- Name: idx_order_fill_account_fill_ts_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_order_fill_account_fill_ts_desc ON public.order_fill_phase1a_archive USING btree (account_id, fill_ts_utc DESC);


--
-- Name: idx_order_fill_asset_hour_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_order_fill_asset_hour_desc ON public.order_fill_phase1a_archive USING btree (asset_id, hour_ts_utc DESC);


--
-- Name: idx_order_fill_order_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_order_fill_order_id ON public.order_fill_phase1a_archive USING btree (order_id);


--
-- Name: idx_order_request_account_request_ts_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_order_request_account_request_ts_desc ON public.order_request_phase1a_archive USING btree (account_id, request_ts_utc DESC);


--
-- Name: idx_order_request_status_request_ts_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_order_request_status_request_ts_desc ON public.order_request_phase1a_archive USING btree (status, request_ts_utc DESC);


--
-- Name: idx_portfolio_hourly_account_hour_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_portfolio_hourly_account_hour_desc ON public.portfolio_hourly_state USING btree (account_id, hour_ts_utc DESC);


--
-- Name: idx_portfolio_hourly_halted_true_hour_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_portfolio_hourly_halted_true_hour_desc ON public.portfolio_hourly_state USING btree (hour_ts_utc DESC) WHERE (halted = true);


--
-- Name: idx_portfolio_hourly_source_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_portfolio_hourly_source_run_id ON public.portfolio_hourly_state USING btree (source_run_id);


--
-- Name: idx_position_hourly_account_hour_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_position_hourly_account_hour_desc ON public.position_hourly_state USING btree (account_id, hour_ts_utc DESC);


--
-- Name: idx_position_hourly_asset_hour_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_position_hourly_asset_hour_desc ON public.position_hourly_state USING btree (asset_id, hour_ts_utc DESC);


--
-- Name: idx_position_hourly_source_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_position_hourly_source_run_id ON public.position_hourly_state USING btree (source_run_id);


--
-- Name: idx_position_lot_account_asset_open_ts_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_position_lot_account_asset_open_ts_desc ON public.position_lot_phase1a_archive USING btree (account_id, asset_id, open_ts_utc DESC);


--
-- Name: idx_position_lot_remaining_qty; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_position_lot_remaining_qty ON public.position_lot_phase1a_archive USING btree (remaining_qty);


--
-- Name: idx_regime_output_asset_hour_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_regime_output_asset_hour_desc ON public.regime_output_phase1a_archive USING btree (asset_id, hour_ts_utc DESC);


--
-- Name: idx_regime_output_label_hour_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_regime_output_label_hour_desc ON public.regime_output_phase1a_archive USING btree (regime_label, hour_ts_utc DESC);


--
-- Name: idx_risk_event_account_event_ts_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_risk_event_account_event_ts_desc ON public.risk_event_phase1a_archive USING btree (account_id, event_ts_utc DESC);


--
-- Name: idx_risk_event_severity_event_ts_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_risk_event_severity_event_ts_desc ON public.risk_event_phase1a_archive USING btree (severity, event_ts_utc DESC);


--
-- Name: idx_risk_event_type_event_ts_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_risk_event_type_event_ts_desc ON public.risk_event_phase1a_archive USING btree (event_type, event_ts_utc DESC);


--
-- Name: idx_risk_hourly_halt_true_hour_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_risk_hourly_halt_true_hour_desc ON public.risk_hourly_state USING btree (hour_ts_utc DESC) WHERE (halt_new_entries = true);


--
-- Name: idx_risk_hourly_source_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_risk_hourly_source_run_id ON public.risk_hourly_state USING btree (source_run_id);


--
-- Name: idx_risk_hourly_tier_hour_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_risk_hourly_tier_hour_desc ON public.risk_hourly_state USING btree (drawdown_tier, hour_ts_utc DESC);


--
-- Name: idx_run_context_account_mode_hour_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_run_context_account_mode_hour_desc ON public.run_context USING btree (account_id, run_mode, hour_ts_utc DESC);


--
-- Name: idx_run_context_mode_hour_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_run_context_mode_hour_desc ON public.run_context USING btree (run_mode, hour_ts_utc DESC);


--
-- Name: idx_trade_signal_account_hour_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trade_signal_account_hour_desc ON public.trade_signal_phase1a_archive USING btree (account_id, hour_ts_utc DESC);


--
-- Name: idx_trade_signal_action_hour_desc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trade_signal_action_hour_desc ON public.trade_signal_phase1a_archive USING btree (action, hour_ts_utc DESC);


--
-- Name: market_ohlcv_hourly_asset_id_hour_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX market_ohlcv_hourly_asset_id_hour_ts_utc_idx ON public.market_ohlcv_hourly USING btree (asset_id, hour_ts_utc DESC);


--
-- Name: meta_learner_component_hour_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX meta_learner_component_hour_ts_utc_idx ON public.meta_learner_component_phase1a_archive USING btree (hour_ts_utc DESC);


--
-- Name: meta_learner_component_v2_asset_id_hour_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX meta_learner_component_v2_asset_id_hour_ts_utc_idx ON public.meta_learner_component USING btree (asset_id, hour_ts_utc DESC);


--
-- Name: meta_learner_component_v2_hour_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX meta_learner_component_v2_hour_ts_utc_idx ON public.meta_learner_component USING btree (hour_ts_utc DESC);


--
-- Name: meta_learner_component_v2_meta_model_version_id_hour_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX meta_learner_component_v2_meta_model_version_id_hour_ts_utc_idx ON public.meta_learner_component USING btree (meta_model_version_id, hour_ts_utc DESC);


--
-- Name: model_prediction_asset_id_hour_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX model_prediction_asset_id_hour_ts_utc_idx ON public.model_prediction_phase1a_archive USING btree (asset_id, hour_ts_utc DESC);


--
-- Name: model_prediction_hour_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX model_prediction_hour_ts_utc_idx ON public.model_prediction_phase1a_archive USING btree (hour_ts_utc DESC);


--
-- Name: model_prediction_v2_asset_id_hour_ts_utc_horizon_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX model_prediction_v2_asset_id_hour_ts_utc_horizon_idx ON public.model_prediction USING btree (asset_id, hour_ts_utc DESC, horizon);


--
-- Name: model_prediction_v2_asset_id_hour_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX model_prediction_v2_asset_id_hour_ts_utc_idx ON public.model_prediction USING btree (asset_id, hour_ts_utc DESC);


--
-- Name: model_prediction_v2_hour_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX model_prediction_v2_hour_ts_utc_idx ON public.model_prediction USING btree (hour_ts_utc DESC);


--
-- Name: model_prediction_v2_model_role_hour_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX model_prediction_v2_model_role_hour_ts_utc_idx ON public.model_prediction USING btree (model_role, hour_ts_utc DESC);


--
-- Name: model_prediction_v2_run_id_asset_id_horizon_hour_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX model_prediction_v2_run_id_asset_id_horizon_hour_ts_utc_idx ON public.model_prediction USING btree (run_id, asset_id, horizon, hour_ts_utc) WHERE (model_role = 'META'::public.model_role_enum);


--
-- Name: order_book_snapshot_asset_id_snapshot_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX order_book_snapshot_asset_id_snapshot_ts_utc_idx ON public.order_book_snapshot USING btree (asset_id, snapshot_ts_utc DESC);


--
-- Name: order_book_snapshot_snapshot_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX order_book_snapshot_snapshot_ts_utc_idx ON public.order_book_snapshot USING btree (snapshot_ts_utc DESC);


--
-- Name: order_fill_v2_account_id_fill_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX order_fill_v2_account_id_fill_ts_utc_idx ON public.order_fill USING btree (account_id, fill_ts_utc DESC);


--
-- Name: order_fill_v2_asset_id_hour_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX order_fill_v2_asset_id_hour_ts_utc_idx ON public.order_fill USING btree (asset_id, hour_ts_utc DESC);


--
-- Name: order_fill_v2_order_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX order_fill_v2_order_id_idx ON public.order_fill USING btree (order_id);


--
-- Name: order_request_v2_account_id_request_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX order_request_v2_account_id_request_ts_utc_idx ON public.order_request USING btree (account_id, request_ts_utc DESC);


--
-- Name: order_request_v2_status_request_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX order_request_v2_status_request_ts_utc_idx ON public.order_request USING btree (status, request_ts_utc DESC);


--
-- Name: position_hourly_state_hour_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX position_hourly_state_hour_ts_utc_idx ON public.position_hourly_state USING btree (hour_ts_utc DESC);


--
-- Name: position_lot_v2_account_id_asset_id_open_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX position_lot_v2_account_id_asset_id_open_ts_utc_idx ON public.position_lot USING btree (account_id, asset_id, open_ts_utc DESC);


--
-- Name: position_lot_v2_remaining_qty_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX position_lot_v2_remaining_qty_idx ON public.position_lot USING btree (remaining_qty);


--
-- Name: regime_output_hour_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX regime_output_hour_ts_utc_idx ON public.regime_output_phase1a_archive USING btree (hour_ts_utc DESC);


--
-- Name: regime_output_v2_asset_id_hour_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX regime_output_v2_asset_id_hour_ts_utc_idx ON public.regime_output USING btree (asset_id, hour_ts_utc DESC);


--
-- Name: regime_output_v2_hour_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX regime_output_v2_hour_ts_utc_idx ON public.regime_output USING btree (hour_ts_utc DESC);


--
-- Name: regime_output_v2_regime_label_hour_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX regime_output_v2_regime_label_hour_ts_utc_idx ON public.regime_output USING btree (regime_label, hour_ts_utc DESC);


--
-- Name: risk_event_v2_account_id_event_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX risk_event_v2_account_id_event_ts_utc_idx ON public.risk_event USING btree (account_id, event_ts_utc DESC);


--
-- Name: risk_event_v2_event_type_event_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX risk_event_v2_event_type_event_ts_utc_idx ON public.risk_event USING btree (event_type, event_ts_utc DESC);


--
-- Name: risk_event_v2_severity_event_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX risk_event_v2_severity_event_ts_utc_idx ON public.risk_event USING btree (severity, event_ts_utc DESC);


--
-- Name: risk_hourly_state_account_id_hour_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX risk_hourly_state_account_id_hour_ts_utc_idx ON public.risk_hourly_state USING btree (account_id, hour_ts_utc DESC);


--
-- Name: trade_signal_v2_account_id_hour_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trade_signal_v2_account_id_hour_ts_utc_idx ON public.trade_signal USING btree (account_id, hour_ts_utc DESC);


--
-- Name: trade_signal_v2_action_hour_ts_utc_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trade_signal_v2_action_hour_ts_utc_idx ON public.trade_signal USING btree (action, hour_ts_utc DESC);


--
-- Name: uqix_cost_profile_one_active_per_venue; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uqix_cost_profile_one_active_per_venue ON public.cost_profile USING btree (venue) WHERE (is_active = true);


--
-- Name: uqix_model_activation_gate_one_approved; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uqix_model_activation_gate_one_approved ON public.model_activation_gate USING btree (model_version_id, run_mode) WHERE (status = 'APPROVED'::text);


--
-- Name: uqix_model_prediction_meta_per_run_asset_horizon_hour; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uqix_model_prediction_meta_per_run_asset_horizon_hour ON public.model_prediction_phase1a_archive USING btree (run_id, asset_id, horizon, hour_ts_utc) WHERE (model_role = 'META'::public.model_role_enum);


--
-- Name: uqix_model_version_one_active_per_name_role; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uqix_model_version_one_active_per_name_role ON public.model_version USING btree (model_name, model_role) WHERE (is_active = true);


--
-- Name: cash_ledger ctrg_cash_ledger_chain; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER ctrg_cash_ledger_chain AFTER INSERT ON public.cash_ledger DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.fn_validate_cash_ledger_chain();


--
-- Name: cluster_exposure_hourly_state ctrg_cluster_exposure_parent_risk_hash; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER ctrg_cluster_exposure_parent_risk_hash AFTER INSERT ON public.cluster_exposure_hourly_state DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.fn_validate_cluster_exposure_parent_risk_hash();


--
-- Name: executed_trade ctrg_executed_trade_fee_rollup; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER ctrg_executed_trade_fee_rollup AFTER INSERT ON public.executed_trade DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.fn_validate_trade_fee_rollup();


--
-- Name: model_prediction ctrg_model_prediction_walk_forward; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER ctrg_model_prediction_walk_forward AFTER INSERT ON public.model_prediction DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.fn_enforce_model_prediction_walk_forward();


--
-- Name: order_fill ctrg_order_fill_causality; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER ctrg_order_fill_causality AFTER INSERT ON public.order_fill DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.fn_validate_execution_causality();


--
-- Name: order_request ctrg_order_request_cluster_cap; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER ctrg_order_request_cluster_cap AFTER INSERT ON public.order_request DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.fn_enforce_cluster_cap_on_admission();


--
-- Name: order_request ctrg_order_request_risk_gate; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER ctrg_order_request_risk_gate AFTER INSERT ON public.order_request DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.fn_enforce_runtime_risk_gate();


--
-- Name: portfolio_hourly_state_identity ctrg_portfolio_identity_source_exists; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER ctrg_portfolio_identity_source_exists AFTER INSERT ON public.portfolio_hourly_state_identity DEFERRABLE INITIALLY IMMEDIATE FOR EACH ROW EXECUTE FUNCTION public.fn_validate_portfolio_identity_source_exists();


--
-- Name: regime_output ctrg_regime_output_walk_forward; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER ctrg_regime_output_walk_forward AFTER INSERT ON public.regime_output DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.fn_enforce_regime_output_walk_forward();


--
-- Name: risk_event ctrg_risk_event_parent_state_hash; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER ctrg_risk_event_parent_state_hash AFTER INSERT ON public.risk_event DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.fn_validate_risk_event_parent_state_hash();


--
-- Name: risk_hourly_state_identity ctrg_risk_identity_source_exists; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER ctrg_risk_identity_source_exists AFTER INSERT ON public.risk_hourly_state_identity DEFERRABLE INITIALLY IMMEDIATE FOR EACH ROW EXECUTE FUNCTION public.fn_validate_risk_identity_source_exists();


--
-- Name: backtest_fold_result trg_backtest_fold_result_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_backtest_fold_result_append_only BEFORE DELETE OR UPDATE ON public.backtest_fold_result FOR EACH ROW EXECUTE FUNCTION public.fn_enforce_append_only();


--
-- Name: cash_ledger trg_cash_ledger_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_cash_ledger_append_only BEFORE DELETE OR UPDATE ON public.cash_ledger FOR EACH ROW EXECUTE FUNCTION public.fn_enforce_append_only();


--
-- Name: cash_ledger_phase1a_archive trg_cash_ledger_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_cash_ledger_append_only BEFORE DELETE OR UPDATE ON public.cash_ledger_phase1a_archive FOR EACH ROW EXECUTE FUNCTION public.fn_enforce_append_only();


--
-- Name: cash_ledger_phase1a_archive trg_cash_ledger_phase_1b_lock; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_cash_ledger_phase_1b_lock BEFORE INSERT ON public.cash_ledger_phase1a_archive FOR EACH ROW EXECUTE FUNCTION public.fn_reject_writes_when_phase_1b_locked();


--
-- Name: executed_trade trg_executed_trade_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_executed_trade_append_only BEFORE DELETE OR UPDATE ON public.executed_trade FOR EACH ROW EXECUTE FUNCTION public.fn_enforce_append_only();


--
-- Name: executed_trade_phase1a_archive trg_executed_trade_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_executed_trade_append_only BEFORE DELETE OR UPDATE ON public.executed_trade_phase1a_archive FOR EACH ROW EXECUTE FUNCTION public.fn_enforce_append_only();


--
-- Name: feature_snapshot trg_feature_snapshot_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_feature_snapshot_append_only BEFORE DELETE OR UPDATE ON public.feature_snapshot FOR EACH ROW EXECUTE FUNCTION public.fn_enforce_append_only();


--
-- Name: portfolio_hourly_state trg_guard_portfolio_hourly_state_identity_key_mutation; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_guard_portfolio_hourly_state_identity_key_mutation BEFORE DELETE OR UPDATE ON public.portfolio_hourly_state FOR EACH ROW EXECUTE FUNCTION public.fn_guard_portfolio_hourly_state_identity_key_mutation();


--
-- Name: risk_hourly_state trg_guard_risk_hourly_state_identity_key_mutation; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_guard_risk_hourly_state_identity_key_mutation BEFORE DELETE OR UPDATE ON public.risk_hourly_state FOR EACH ROW EXECUTE FUNCTION public.fn_guard_risk_hourly_state_identity_key_mutation();


--
-- Name: market_ohlcv_hourly trg_market_ohlcv_hourly_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_market_ohlcv_hourly_append_only BEFORE DELETE OR UPDATE ON public.market_ohlcv_hourly FOR EACH ROW EXECUTE FUNCTION public.fn_enforce_append_only();


--
-- Name: meta_learner_component_phase1a_archive trg_meta_learner_component_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_meta_learner_component_append_only BEFORE DELETE OR UPDATE ON public.meta_learner_component_phase1a_archive FOR EACH ROW EXECUTE FUNCTION public.fn_enforce_append_only();


--
-- Name: model_prediction_phase1a_archive trg_model_prediction_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_model_prediction_append_only BEFORE DELETE OR UPDATE ON public.model_prediction_phase1a_archive FOR EACH ROW EXECUTE FUNCTION public.fn_enforce_append_only();


--
-- Name: order_book_snapshot trg_order_book_snapshot_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_order_book_snapshot_append_only BEFORE DELETE OR UPDATE ON public.order_book_snapshot FOR EACH ROW EXECUTE FUNCTION public.fn_enforce_append_only();


--
-- Name: order_fill trg_order_fill_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_order_fill_append_only BEFORE DELETE OR UPDATE ON public.order_fill FOR EACH ROW EXECUTE FUNCTION public.fn_enforce_append_only();


--
-- Name: order_fill_phase1a_archive trg_order_fill_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_order_fill_append_only BEFORE DELETE OR UPDATE ON public.order_fill_phase1a_archive FOR EACH ROW EXECUTE FUNCTION public.fn_enforce_append_only();


--
-- Name: order_fill_phase1a_archive trg_order_fill_phase_1b_lock; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_order_fill_phase_1b_lock BEFORE INSERT ON public.order_fill_phase1a_archive FOR EACH ROW EXECUTE FUNCTION public.fn_reject_writes_when_phase_1b_locked();


--
-- Name: order_request trg_order_request_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_order_request_append_only BEFORE DELETE OR UPDATE ON public.order_request FOR EACH ROW EXECUTE FUNCTION public.fn_enforce_append_only();


--
-- Name: order_request_phase1a_archive trg_order_request_phase_1b_lock; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_order_request_phase_1b_lock BEFORE INSERT ON public.order_request_phase1a_archive FOR EACH ROW EXECUTE FUNCTION public.fn_reject_writes_when_phase_1b_locked();


--
-- Name: portfolio_hourly_state_identity trg_portfolio_hourly_state_identity_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_portfolio_hourly_state_identity_append_only BEFORE DELETE OR UPDATE ON public.portfolio_hourly_state_identity FOR EACH ROW EXECUTE FUNCTION public.fn_enforce_append_only();


--
-- Name: portfolio_hourly_state trg_portfolio_hourly_state_identity_sync_ins; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_portfolio_hourly_state_identity_sync_ins AFTER INSERT ON public.portfolio_hourly_state FOR EACH ROW EXECUTE FUNCTION public.fn_sync_portfolio_hourly_state_identity_ins();


--
-- Name: position_lot trg_position_lot_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_position_lot_append_only BEFORE DELETE OR UPDATE ON public.position_lot FOR EACH ROW EXECUTE FUNCTION public.fn_enforce_append_only();


--
-- Name: regime_output_phase1a_archive trg_regime_output_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_regime_output_append_only BEFORE DELETE OR UPDATE ON public.regime_output_phase1a_archive FOR EACH ROW EXECUTE FUNCTION public.fn_enforce_append_only();


--
-- Name: risk_event trg_risk_event_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_risk_event_append_only BEFORE DELETE OR UPDATE ON public.risk_event FOR EACH ROW EXECUTE FUNCTION public.fn_enforce_append_only();


--
-- Name: risk_event_phase1a_archive trg_risk_event_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_risk_event_append_only BEFORE DELETE OR UPDATE ON public.risk_event_phase1a_archive FOR EACH ROW EXECUTE FUNCTION public.fn_enforce_append_only();


--
-- Name: risk_hourly_state_identity trg_risk_hourly_state_identity_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_risk_hourly_state_identity_append_only BEFORE DELETE OR UPDATE ON public.risk_hourly_state_identity FOR EACH ROW EXECUTE FUNCTION public.fn_enforce_append_only();


--
-- Name: risk_hourly_state trg_risk_hourly_state_identity_sync_ins; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_risk_hourly_state_identity_sync_ins AFTER INSERT ON public.risk_hourly_state FOR EACH ROW EXECUTE FUNCTION public.fn_sync_risk_hourly_state_identity_ins();


--
-- Name: run_context trg_run_context_phase_1b_lock; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_run_context_phase_1b_lock BEFORE INSERT ON public.run_context FOR EACH ROW EXECUTE FUNCTION public.fn_reject_writes_when_phase_1b_locked();


--
-- Name: trade_signal trg_trade_signal_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_trade_signal_append_only BEFORE DELETE OR UPDATE ON public.trade_signal FOR EACH ROW EXECUTE FUNCTION public.fn_enforce_append_only();


--
-- Name: trade_signal_phase1a_archive trg_trade_signal_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_trade_signal_append_only BEFORE DELETE OR UPDATE ON public.trade_signal_phase1a_archive FOR EACH ROW EXECUTE FUNCTION public.fn_enforce_append_only();


--
-- Name: feature_snapshot ts_insert_blocker; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER ts_insert_blocker BEFORE INSERT ON public.feature_snapshot FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.insert_blocker();


--
-- Name: market_ohlcv_hourly ts_insert_blocker; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER ts_insert_blocker BEFORE INSERT ON public.market_ohlcv_hourly FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.insert_blocker();


--
-- Name: meta_learner_component_phase1a_archive ts_insert_blocker; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER ts_insert_blocker BEFORE INSERT ON public.meta_learner_component_phase1a_archive FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.insert_blocker();


--
-- Name: model_prediction_phase1a_archive ts_insert_blocker; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER ts_insert_blocker BEFORE INSERT ON public.model_prediction_phase1a_archive FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.insert_blocker();


--
-- Name: order_book_snapshot ts_insert_blocker; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER ts_insert_blocker BEFORE INSERT ON public.order_book_snapshot FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.insert_blocker();


--
-- Name: portfolio_hourly_state ts_insert_blocker; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER ts_insert_blocker BEFORE INSERT ON public.portfolio_hourly_state FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.insert_blocker();


--
-- Name: position_hourly_state ts_insert_blocker; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER ts_insert_blocker BEFORE INSERT ON public.position_hourly_state FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.insert_blocker();


--
-- Name: regime_output_phase1a_archive ts_insert_blocker; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER ts_insert_blocker BEFORE INSERT ON public.regime_output_phase1a_archive FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.insert_blocker();


--
-- Name: risk_hourly_state ts_insert_blocker; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER ts_insert_blocker BEFORE INSERT ON public.risk_hourly_state FOR EACH ROW EXECUTE FUNCTION _timescaledb_functions.insert_blocker();


--
-- Name: asset_cluster_membership fk_asset_cluster_membership_asset; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asset_cluster_membership
    ADD CONSTRAINT fk_asset_cluster_membership_asset FOREIGN KEY (asset_id) REFERENCES public.asset(asset_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: asset_cluster_membership fk_asset_cluster_membership_cluster; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asset_cluster_membership
    ADD CONSTRAINT fk_asset_cluster_membership_cluster FOREIGN KEY (cluster_id) REFERENCES public.correlation_cluster(cluster_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: backtest_fold_result fk_backtest_fold_result_backtest_run; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backtest_fold_result
    ADD CONSTRAINT fk_backtest_fold_result_backtest_run FOREIGN KEY (backtest_run_id) REFERENCES public.backtest_run(backtest_run_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: backtest_run fk_backtest_run_account; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backtest_run
    ADD CONSTRAINT fk_backtest_run_account FOREIGN KEY (account_id) REFERENCES public.account(account_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: backtest_run fk_backtest_run_cost_profile; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backtest_run
    ADD CONSTRAINT fk_backtest_run_cost_profile FOREIGN KEY (cost_profile_id) REFERENCES public.cost_profile(cost_profile_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: cash_ledger_phase1a_archive fk_cash_ledger_account; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cash_ledger_phase1a_archive
    ADD CONSTRAINT fk_cash_ledger_account FOREIGN KEY (account_id) REFERENCES public.account(account_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: cash_ledger_phase1a_archive fk_cash_ledger_run_context; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cash_ledger_phase1a_archive
    ADD CONSTRAINT fk_cash_ledger_run_context FOREIGN KEY (run_id, run_mode, hour_ts_utc) REFERENCES public.run_context(run_id, run_mode, hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: cash_ledger_phase1a_archive fk_cash_ledger_run_context_account_hour; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cash_ledger_phase1a_archive
    ADD CONSTRAINT fk_cash_ledger_run_context_account_hour FOREIGN KEY (run_id, account_id, run_mode, hour_ts_utc) REFERENCES public.run_context(run_id, account_id, run_mode, hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT NOT VALID;


--
-- Name: cash_ledger fk_cash_ledger_v2_run_context_origin; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cash_ledger
    ADD CONSTRAINT fk_cash_ledger_v2_run_context_origin FOREIGN KEY (run_id, account_id, run_mode, origin_hour_ts_utc) REFERENCES public.run_context(run_id, account_id, run_mode, origin_hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: cluster_exposure_hourly_state fk_cluster_exposure_hourly_state_cluster; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cluster_exposure_hourly_state
    ADD CONSTRAINT fk_cluster_exposure_hourly_state_cluster FOREIGN KEY (cluster_id) REFERENCES public.correlation_cluster(cluster_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: cluster_exposure_hourly_state fk_cluster_exposure_hourly_state_risk_identity; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cluster_exposure_hourly_state
    ADD CONSTRAINT fk_cluster_exposure_hourly_state_risk_identity FOREIGN KEY (run_mode, account_id, hour_ts_utc, source_run_id) REFERENCES public.risk_hourly_state_identity(run_mode, account_id, hour_ts_utc, source_run_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: executed_trade_phase1a_archive fk_executed_trade_account; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.executed_trade_phase1a_archive
    ADD CONSTRAINT fk_executed_trade_account FOREIGN KEY (account_id) REFERENCES public.account(account_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: executed_trade_phase1a_archive fk_executed_trade_asset; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.executed_trade_phase1a_archive
    ADD CONSTRAINT fk_executed_trade_asset FOREIGN KEY (asset_id) REFERENCES public.asset(asset_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: executed_trade_phase1a_archive fk_executed_trade_lot_identity; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.executed_trade_phase1a_archive
    ADD CONSTRAINT fk_executed_trade_lot_identity FOREIGN KEY (lot_id, run_id, run_mode, account_id, asset_id) REFERENCES public.position_lot_phase1a_archive(lot_id, run_id, run_mode, account_id, asset_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: executed_trade_phase1a_archive fk_executed_trade_run_context; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.executed_trade_phase1a_archive
    ADD CONSTRAINT fk_executed_trade_run_context FOREIGN KEY (run_id, run_mode, hour_ts_utc) REFERENCES public.run_context(run_id, run_mode, hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: executed_trade_phase1a_archive fk_executed_trade_run_context_account_hour; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.executed_trade_phase1a_archive
    ADD CONSTRAINT fk_executed_trade_run_context_account_hour FOREIGN KEY (run_id, account_id, run_mode, hour_ts_utc) REFERENCES public.run_context(run_id, account_id, run_mode, hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT NOT VALID;


--
-- Name: executed_trade fk_executed_trade_v2_run_context_origin; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.executed_trade
    ADD CONSTRAINT fk_executed_trade_v2_run_context_origin FOREIGN KEY (run_id, account_id, run_mode, origin_hour_ts_utc) REFERENCES public.run_context(run_id, account_id, run_mode, origin_hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: feature_snapshot fk_feature_snapshot_asset; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feature_snapshot
    ADD CONSTRAINT fk_feature_snapshot_asset FOREIGN KEY (asset_id) REFERENCES public.asset(asset_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: feature_snapshot fk_feature_snapshot_feature_definition; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feature_snapshot
    ADD CONSTRAINT fk_feature_snapshot_feature_definition FOREIGN KEY (feature_id) REFERENCES public.feature_definition(feature_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: feature_snapshot fk_feature_snapshot_run_context; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feature_snapshot
    ADD CONSTRAINT fk_feature_snapshot_run_context FOREIGN KEY (run_id, run_mode, hour_ts_utc) REFERENCES public.run_context(run_id, run_mode, hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: market_ohlcv_hourly fk_market_ohlcv_hourly_asset; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.market_ohlcv_hourly
    ADD CONSTRAINT fk_market_ohlcv_hourly_asset FOREIGN KEY (asset_id) REFERENCES public.asset(asset_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: market_ohlcv_hourly fk_market_ohlcv_hourly_run_context; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.market_ohlcv_hourly
    ADD CONSTRAINT fk_market_ohlcv_hourly_run_context FOREIGN KEY (ingest_run_id) REFERENCES public.run_context(run_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: meta_learner_component_phase1a_archive fk_meta_component_asset; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.meta_learner_component_phase1a_archive
    ADD CONSTRAINT fk_meta_component_asset FOREIGN KEY (asset_id) REFERENCES public.asset(asset_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: meta_learner_component_phase1a_archive fk_meta_component_base_model; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.meta_learner_component_phase1a_archive
    ADD CONSTRAINT fk_meta_component_base_model FOREIGN KEY (base_model_version_id) REFERENCES public.model_version(model_version_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: meta_learner_component_phase1a_archive fk_meta_component_meta_model; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.meta_learner_component_phase1a_archive
    ADD CONSTRAINT fk_meta_component_meta_model FOREIGN KEY (meta_model_version_id) REFERENCES public.model_version(model_version_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: meta_learner_component_phase1a_archive fk_meta_component_run_context; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.meta_learner_component_phase1a_archive
    ADD CONSTRAINT fk_meta_component_run_context FOREIGN KEY (run_id, run_mode, hour_ts_utc) REFERENCES public.run_context(run_id, run_mode, hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: meta_learner_component fk_meta_learner_component_account; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.meta_learner_component
    ADD CONSTRAINT fk_meta_learner_component_account FOREIGN KEY (account_id) REFERENCES public.account(account_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: meta_learner_component fk_meta_learner_component_run_context_run_account_mode_hour; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.meta_learner_component
    ADD CONSTRAINT fk_meta_learner_component_run_context_run_account_mode_hour FOREIGN KEY (run_id, account_id, run_mode, hour_ts_utc) REFERENCES public.run_context(run_id, account_id, run_mode, hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: model_activation_gate fk_model_activation_gate_backtest; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_activation_gate
    ADD CONSTRAINT fk_model_activation_gate_backtest FOREIGN KEY (validation_backtest_run_id) REFERENCES public.backtest_run(backtest_run_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: model_activation_gate fk_model_activation_gate_model; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_activation_gate
    ADD CONSTRAINT fk_model_activation_gate_model FOREIGN KEY (model_version_id) REFERENCES public.model_version(model_version_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: model_prediction fk_model_prediction_account; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_prediction
    ADD CONSTRAINT fk_model_prediction_account FOREIGN KEY (account_id) REFERENCES public.account(account_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: model_prediction fk_model_prediction_activation; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_prediction
    ADD CONSTRAINT fk_model_prediction_activation FOREIGN KEY (activation_id, model_version_id, run_mode) REFERENCES public.model_activation_gate(activation_id, model_version_id, run_mode) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: model_prediction_phase1a_archive fk_model_prediction_asset; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_prediction_phase1a_archive
    ADD CONSTRAINT fk_model_prediction_asset FOREIGN KEY (asset_id) REFERENCES public.asset(asset_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: model_prediction fk_model_prediction_lineage_fold; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_prediction
    ADD CONSTRAINT fk_model_prediction_lineage_fold FOREIGN KEY (lineage_backtest_run_id, lineage_fold_index) REFERENCES public.backtest_fold_result(backtest_run_id, fold_index) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: model_prediction fk_model_prediction_lineage_fold_horizon; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_prediction
    ADD CONSTRAINT fk_model_prediction_lineage_fold_horizon FOREIGN KEY (lineage_backtest_run_id, model_version_id, lineage_fold_index, lineage_horizon) REFERENCES public.model_training_window(backtest_run_id, model_version_id, fold_index, horizon) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: model_prediction_phase1a_archive fk_model_prediction_model_version; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_prediction_phase1a_archive
    ADD CONSTRAINT fk_model_prediction_model_version FOREIGN KEY (model_version_id) REFERENCES public.model_version(model_version_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: model_prediction_phase1a_archive fk_model_prediction_run_context; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_prediction_phase1a_archive
    ADD CONSTRAINT fk_model_prediction_run_context FOREIGN KEY (run_id, run_mode, hour_ts_utc) REFERENCES public.run_context(run_id, run_mode, hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: model_prediction fk_model_prediction_run_context_run_account_mode_hour; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_prediction
    ADD CONSTRAINT fk_model_prediction_run_context_run_account_mode_hour FOREIGN KEY (run_id, account_id, run_mode, hour_ts_utc) REFERENCES public.run_context(run_id, account_id, run_mode, hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: model_prediction fk_model_prediction_training_window; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_prediction
    ADD CONSTRAINT fk_model_prediction_training_window FOREIGN KEY (training_window_id) REFERENCES public.model_training_window(training_window_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: model_training_window fk_model_training_window_backtest_fold; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_training_window
    ADD CONSTRAINT fk_model_training_window_backtest_fold FOREIGN KEY (backtest_run_id, fold_index) REFERENCES public.backtest_fold_result(backtest_run_id, fold_index) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: model_training_window fk_model_training_window_model_version; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_training_window
    ADD CONSTRAINT fk_model_training_window_model_version FOREIGN KEY (model_version_id) REFERENCES public.model_version(model_version_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: order_book_snapshot fk_order_book_snapshot_asset; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_book_snapshot
    ADD CONSTRAINT fk_order_book_snapshot_asset FOREIGN KEY (asset_id) REFERENCES public.asset(asset_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: order_book_snapshot fk_order_book_snapshot_run_context; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_book_snapshot
    ADD CONSTRAINT fk_order_book_snapshot_run_context FOREIGN KEY (ingest_run_id) REFERENCES public.run_context(run_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: order_fill_phase1a_archive fk_order_fill_account; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_fill_phase1a_archive
    ADD CONSTRAINT fk_order_fill_account FOREIGN KEY (account_id) REFERENCES public.account(account_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: order_fill_phase1a_archive fk_order_fill_asset; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_fill_phase1a_archive
    ADD CONSTRAINT fk_order_fill_asset FOREIGN KEY (asset_id) REFERENCES public.asset(asset_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: order_fill_phase1a_archive fk_order_fill_order_request_identity; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_fill_phase1a_archive
    ADD CONSTRAINT fk_order_fill_order_request_identity FOREIGN KEY (order_id, run_id, run_mode, account_id, asset_id) REFERENCES public.order_request_phase1a_archive(order_id, run_id, run_mode, account_id, asset_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: order_fill_phase1a_archive fk_order_fill_run_context; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_fill_phase1a_archive
    ADD CONSTRAINT fk_order_fill_run_context FOREIGN KEY (run_id, run_mode, hour_ts_utc) REFERENCES public.run_context(run_id, run_mode, hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: order_fill_phase1a_archive fk_order_fill_run_context_account_hour; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_fill_phase1a_archive
    ADD CONSTRAINT fk_order_fill_run_context_account_hour FOREIGN KEY (run_id, account_id, run_mode, hour_ts_utc) REFERENCES public.run_context(run_id, account_id, run_mode, hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT NOT VALID;


--
-- Name: order_fill fk_order_fill_v2_run_context_origin; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_fill
    ADD CONSTRAINT fk_order_fill_v2_run_context_origin FOREIGN KEY (run_id, account_id, run_mode, origin_hour_ts_utc) REFERENCES public.run_context(run_id, account_id, run_mode, origin_hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: order_request_phase1a_archive fk_order_request_account; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_request_phase1a_archive
    ADD CONSTRAINT fk_order_request_account FOREIGN KEY (account_id) REFERENCES public.account(account_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: order_request_phase1a_archive fk_order_request_asset; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_request_phase1a_archive
    ADD CONSTRAINT fk_order_request_asset FOREIGN KEY (asset_id) REFERENCES public.asset(asset_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: order_request_phase1a_archive fk_order_request_cost_profile; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_request_phase1a_archive
    ADD CONSTRAINT fk_order_request_cost_profile FOREIGN KEY (cost_profile_id) REFERENCES public.cost_profile(cost_profile_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: order_request_phase1a_archive fk_order_request_run_context; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_request_phase1a_archive
    ADD CONSTRAINT fk_order_request_run_context FOREIGN KEY (run_id, run_mode, hour_ts_utc) REFERENCES public.run_context(run_id, run_mode, hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: order_request_phase1a_archive fk_order_request_run_context_account_hour; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_request_phase1a_archive
    ADD CONSTRAINT fk_order_request_run_context_account_hour FOREIGN KEY (run_id, account_id, run_mode, hour_ts_utc) REFERENCES public.run_context(run_id, account_id, run_mode, hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT NOT VALID;


--
-- Name: order_request_phase1a_archive fk_order_request_signal_identity; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_request_phase1a_archive
    ADD CONSTRAINT fk_order_request_signal_identity FOREIGN KEY (signal_id) REFERENCES public.trade_signal_phase1a_archive(signal_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: order_request fk_order_request_v2_run_context_origin; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_request
    ADD CONSTRAINT fk_order_request_v2_run_context_origin FOREIGN KEY (run_id, account_id, run_mode, origin_hour_ts_utc) REFERENCES public.run_context(run_id, account_id, run_mode, origin_hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: order_request fk_order_request_v2_signal_cluster; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_request
    ADD CONSTRAINT fk_order_request_v2_signal_cluster FOREIGN KEY (signal_id, cluster_membership_id) REFERENCES public.trade_signal(signal_id, cluster_membership_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: order_request fk_order_request_v2_signal_riskrun; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.order_request
    ADD CONSTRAINT fk_order_request_v2_signal_riskrun FOREIGN KEY (signal_id, risk_state_run_id) REFERENCES public.trade_signal(signal_id, risk_state_run_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: portfolio_hourly_state fk_portfolio_hourly_state_account; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.portfolio_hourly_state
    ADD CONSTRAINT fk_portfolio_hourly_state_account FOREIGN KEY (account_id) REFERENCES public.account(account_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: portfolio_hourly_state fk_portfolio_hourly_state_run_context; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.portfolio_hourly_state
    ADD CONSTRAINT fk_portfolio_hourly_state_run_context FOREIGN KEY (source_run_id, run_mode, hour_ts_utc) REFERENCES public.run_context(run_id, run_mode, hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: portfolio_hourly_state fk_portfolio_hourly_state_run_context_account_hour; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.portfolio_hourly_state
    ADD CONSTRAINT fk_portfolio_hourly_state_run_context_account_hour FOREIGN KEY (source_run_id, account_id, run_mode, hour_ts_utc) REFERENCES public.run_context(run_id, account_id, run_mode, hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT NOT VALID;


--
-- Name: position_hourly_state fk_position_hourly_state_account; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.position_hourly_state
    ADD CONSTRAINT fk_position_hourly_state_account FOREIGN KEY (account_id) REFERENCES public.account(account_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: position_hourly_state fk_position_hourly_state_asset; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.position_hourly_state
    ADD CONSTRAINT fk_position_hourly_state_asset FOREIGN KEY (asset_id) REFERENCES public.asset(asset_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: position_hourly_state fk_position_hourly_state_run_context; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.position_hourly_state
    ADD CONSTRAINT fk_position_hourly_state_run_context FOREIGN KEY (source_run_id, run_mode, hour_ts_utc) REFERENCES public.run_context(run_id, run_mode, hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: position_hourly_state fk_position_hourly_state_run_context_account_hour; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.position_hourly_state
    ADD CONSTRAINT fk_position_hourly_state_run_context_account_hour FOREIGN KEY (source_run_id, account_id, run_mode, hour_ts_utc) REFERENCES public.run_context(run_id, account_id, run_mode, hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT NOT VALID;


--
-- Name: position_lot_phase1a_archive fk_position_lot_account; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.position_lot_phase1a_archive
    ADD CONSTRAINT fk_position_lot_account FOREIGN KEY (account_id) REFERENCES public.account(account_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: position_lot_phase1a_archive fk_position_lot_asset; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.position_lot_phase1a_archive
    ADD CONSTRAINT fk_position_lot_asset FOREIGN KEY (asset_id) REFERENCES public.asset(asset_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: position_lot_phase1a_archive fk_position_lot_order_fill_identity; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.position_lot_phase1a_archive
    ADD CONSTRAINT fk_position_lot_order_fill_identity FOREIGN KEY (open_fill_id, run_id, run_mode, account_id, asset_id) REFERENCES public.order_fill_phase1a_archive(fill_id, run_id, run_mode, account_id, asset_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: position_lot_phase1a_archive fk_position_lot_run_context; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.position_lot_phase1a_archive
    ADD CONSTRAINT fk_position_lot_run_context FOREIGN KEY (run_id, run_mode, hour_ts_utc) REFERENCES public.run_context(run_id, run_mode, hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: position_lot_phase1a_archive fk_position_lot_run_context_account_hour; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.position_lot_phase1a_archive
    ADD CONSTRAINT fk_position_lot_run_context_account_hour FOREIGN KEY (run_id, account_id, run_mode, hour_ts_utc) REFERENCES public.run_context(run_id, account_id, run_mode, hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT NOT VALID;


--
-- Name: position_lot fk_position_lot_v2_run_context_origin; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.position_lot
    ADD CONSTRAINT fk_position_lot_v2_run_context_origin FOREIGN KEY (run_id, account_id, run_mode, origin_hour_ts_utc) REFERENCES public.run_context(run_id, account_id, run_mode, origin_hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: regime_output fk_regime_output_account; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.regime_output
    ADD CONSTRAINT fk_regime_output_account FOREIGN KEY (account_id) REFERENCES public.account(account_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: regime_output fk_regime_output_activation; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.regime_output
    ADD CONSTRAINT fk_regime_output_activation FOREIGN KEY (activation_id, model_version_id, run_mode) REFERENCES public.model_activation_gate(activation_id, model_version_id, run_mode) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: regime_output_phase1a_archive fk_regime_output_asset; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.regime_output_phase1a_archive
    ADD CONSTRAINT fk_regime_output_asset FOREIGN KEY (asset_id) REFERENCES public.asset(asset_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: regime_output fk_regime_output_lineage_fold; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.regime_output
    ADD CONSTRAINT fk_regime_output_lineage_fold FOREIGN KEY (lineage_backtest_run_id, lineage_fold_index) REFERENCES public.backtest_fold_result(backtest_run_id, fold_index) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: regime_output fk_regime_output_lineage_fold_horizon; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.regime_output
    ADD CONSTRAINT fk_regime_output_lineage_fold_horizon FOREIGN KEY (lineage_backtest_run_id, model_version_id, lineage_fold_index, lineage_horizon) REFERENCES public.model_training_window(backtest_run_id, model_version_id, fold_index, horizon) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: regime_output_phase1a_archive fk_regime_output_model_version; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.regime_output_phase1a_archive
    ADD CONSTRAINT fk_regime_output_model_version FOREIGN KEY (model_version_id) REFERENCES public.model_version(model_version_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: regime_output_phase1a_archive fk_regime_output_run_context; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.regime_output_phase1a_archive
    ADD CONSTRAINT fk_regime_output_run_context FOREIGN KEY (run_id, run_mode, hour_ts_utc) REFERENCES public.run_context(run_id, run_mode, hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: regime_output fk_regime_output_run_context_run_account_mode_hour; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.regime_output
    ADD CONSTRAINT fk_regime_output_run_context_run_account_mode_hour FOREIGN KEY (run_id, account_id, run_mode, hour_ts_utc) REFERENCES public.run_context(run_id, account_id, run_mode, hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: regime_output fk_regime_output_training_window; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.regime_output
    ADD CONSTRAINT fk_regime_output_training_window FOREIGN KEY (training_window_id) REFERENCES public.model_training_window(training_window_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: replay_manifest fk_replay_manifest_run_context; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.replay_manifest
    ADD CONSTRAINT fk_replay_manifest_run_context FOREIGN KEY (run_id, account_id, run_mode, origin_hour_ts_utc) REFERENCES public.run_context(run_id, account_id, run_mode, origin_hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: risk_event_phase1a_archive fk_risk_event_account; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_event_phase1a_archive
    ADD CONSTRAINT fk_risk_event_account FOREIGN KEY (account_id) REFERENCES public.account(account_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: risk_event_phase1a_archive fk_risk_event_risk_state_identity; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_event_phase1a_archive
    ADD CONSTRAINT fk_risk_event_risk_state_identity FOREIGN KEY (run_mode, account_id, related_state_hour_ts_utc) REFERENCES public.risk_hourly_state_identity(run_mode, account_id, hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: risk_event_phase1a_archive fk_risk_event_run_context; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_event_phase1a_archive
    ADD CONSTRAINT fk_risk_event_run_context FOREIGN KEY (run_id, run_mode, hour_ts_utc) REFERENCES public.run_context(run_id, run_mode, hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: risk_event_phase1a_archive fk_risk_event_run_context_account_hour; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_event_phase1a_archive
    ADD CONSTRAINT fk_risk_event_run_context_account_hour FOREIGN KEY (run_id, account_id, run_mode, hour_ts_utc) REFERENCES public.run_context(run_id, account_id, run_mode, hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT NOT VALID;


--
-- Name: risk_event fk_risk_event_v2_risk_state_identity; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_event
    ADD CONSTRAINT fk_risk_event_v2_risk_state_identity FOREIGN KEY (run_mode, account_id, related_state_hour_ts_utc) REFERENCES public.risk_hourly_state_identity(run_mode, account_id, hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: risk_event fk_risk_event_v2_run_context_origin; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_event
    ADD CONSTRAINT fk_risk_event_v2_run_context_origin FOREIGN KEY (run_id, account_id, run_mode, origin_hour_ts_utc) REFERENCES public.run_context(run_id, account_id, run_mode, origin_hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: risk_hourly_state_identity fk_risk_hourly_state_identity_run_context; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_hourly_state_identity
    ADD CONSTRAINT fk_risk_hourly_state_identity_run_context FOREIGN KEY (source_run_id, account_id, run_mode, hour_ts_utc) REFERENCES public.run_context(run_id, account_id, run_mode, hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: risk_hourly_state fk_risk_hourly_state_portfolio_identity; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_hourly_state
    ADD CONSTRAINT fk_risk_hourly_state_portfolio_identity FOREIGN KEY (run_mode, account_id, hour_ts_utc) REFERENCES public.portfolio_hourly_state_identity(run_mode, account_id, hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: risk_hourly_state fk_risk_hourly_state_run_context; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_hourly_state
    ADD CONSTRAINT fk_risk_hourly_state_run_context FOREIGN KEY (source_run_id, run_mode, hour_ts_utc) REFERENCES public.run_context(run_id, run_mode, hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: risk_hourly_state fk_risk_hourly_state_run_context_account_hour; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_hourly_state
    ADD CONSTRAINT fk_risk_hourly_state_run_context_account_hour FOREIGN KEY (source_run_id, account_id, run_mode, hour_ts_utc) REFERENCES public.run_context(run_id, account_id, run_mode, hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT NOT VALID;


--
-- Name: run_context fk_run_context_account; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_context
    ADD CONSTRAINT fk_run_context_account FOREIGN KEY (account_id) REFERENCES public.account(account_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: run_context fk_run_context_backtest_run; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_context
    ADD CONSTRAINT fk_run_context_backtest_run FOREIGN KEY (backtest_run_id) REFERENCES public.backtest_run(backtest_run_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: trade_signal_phase1a_archive fk_trade_signal_account; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_signal_phase1a_archive
    ADD CONSTRAINT fk_trade_signal_account FOREIGN KEY (account_id) REFERENCES public.account(account_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: trade_signal_phase1a_archive fk_trade_signal_asset; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_signal_phase1a_archive
    ADD CONSTRAINT fk_trade_signal_asset FOREIGN KEY (asset_id) REFERENCES public.asset(asset_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: trade_signal_phase1a_archive fk_trade_signal_risk_state_identity; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_signal_phase1a_archive
    ADD CONSTRAINT fk_trade_signal_risk_state_identity FOREIGN KEY (run_mode, account_id, risk_state_hour_ts_utc) REFERENCES public.risk_hourly_state_identity(run_mode, account_id, hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: trade_signal_phase1a_archive fk_trade_signal_run_context; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_signal_phase1a_archive
    ADD CONSTRAINT fk_trade_signal_run_context FOREIGN KEY (run_id, run_mode, hour_ts_utc) REFERENCES public.run_context(run_id, run_mode, hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: trade_signal_phase1a_archive fk_trade_signal_run_context_account_hour; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_signal_phase1a_archive
    ADD CONSTRAINT fk_trade_signal_run_context_account_hour FOREIGN KEY (run_id, account_id, run_mode, hour_ts_utc) REFERENCES public.run_context(run_id, account_id, run_mode, hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT NOT VALID;


--
-- Name: trade_signal fk_trade_signal_run_context_run_account_mode_hour; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_signal
    ADD CONSTRAINT fk_trade_signal_run_context_run_account_mode_hour FOREIGN KEY (run_id, account_id, run_mode, hour_ts_utc) REFERENCES public.run_context(run_id, account_id, run_mode, hour_ts_utc) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: trade_signal fk_trade_signal_v2_cluster_membership; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_signal
    ADD CONSTRAINT fk_trade_signal_v2_cluster_membership FOREIGN KEY (cluster_membership_id) REFERENCES public.asset_cluster_membership(membership_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- Name: trade_signal fk_trade_signal_v2_risk_state_exact_identity; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_signal
    ADD CONSTRAINT fk_trade_signal_v2_risk_state_exact_identity FOREIGN KEY (run_mode, account_id, risk_state_hour_ts_utc, risk_state_run_id) REFERENCES public.risk_hourly_state_identity(run_mode, account_id, hour_ts_utc, source_run_id) ON UPDATE RESTRICT ON DELETE RESTRICT;


--
-- PostgreSQL database dump complete
--

