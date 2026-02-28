"""Initial production schema for the AI crypto trading system."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from alembic import op

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


ENUM_DDL: tuple[str, ...] = (
    "CREATE TYPE run_mode_enum AS ENUM ('BACKTEST', 'PAPER', 'LIVE');",
    "CREATE TYPE horizon_enum AS ENUM ('H1', 'H4', 'H24');",
    "CREATE TYPE model_role_enum AS ENUM ('BASE_TREE', 'BASE_DEEP', 'REGIME', 'META');",
    "CREATE TYPE signal_action_enum AS ENUM ('ENTER', 'EXIT', 'HOLD');",
    "CREATE TYPE order_side_enum AS ENUM ('BUY', 'SELL');",
    "CREATE TYPE order_type_enum AS ENUM ('LIMIT', 'MARKET');",
    "CREATE TYPE order_status_enum AS ENUM ('NEW', 'ACK', 'PARTIAL', 'FILLED', 'CANCELLED', 'REJECTED');",
    "CREATE TYPE drawdown_tier_enum AS ENUM ('NORMAL', 'DD10', 'DD15', 'HALT20');",
)

TABLE_DDL: tuple[str, ...] = (
    """
    CREATE TABLE asset (
        asset_id SMALLINT GENERATED ALWAYS AS IDENTITY,
        venue TEXT NOT NULL,
        symbol TEXT NOT NULL,
        base_asset TEXT NOT NULL,
        quote_asset TEXT NOT NULL,
        tick_size NUMERIC(38,18) NOT NULL,
        lot_size NUMERIC(38,18) NOT NULL,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        listed_at_utc TIMESTAMPTZ NOT NULL,
        delisted_at_utc TIMESTAMPTZ,
        CONSTRAINT pk_asset PRIMARY KEY (asset_id),
        CONSTRAINT uq_asset_venue_symbol UNIQUE (venue, symbol),
        CONSTRAINT ck_asset_venue_not_blank CHECK (length(btrim(venue)) > 0),
        CONSTRAINT ck_asset_symbol_not_blank CHECK (length(btrim(symbol)) > 0),
        CONSTRAINT ck_asset_symbol_upper CHECK (symbol = upper(symbol)),
        CONSTRAINT ck_asset_base_upper CHECK (base_asset = upper(base_asset)),
        CONSTRAINT ck_asset_quote_upper CHECK (quote_asset = upper(quote_asset)),
        CONSTRAINT ck_asset_tick_size_pos CHECK (tick_size > 0),
        CONSTRAINT ck_asset_lot_size_pos CHECK (lot_size > 0),
        CONSTRAINT ck_asset_delisted_after_listed CHECK (delisted_at_utc IS NULL OR delisted_at_utc > listed_at_utc)
    );
    """,
    """
    CREATE TABLE account (
        account_id SMALLINT GENERATED ALWAYS AS IDENTITY,
        account_code TEXT NOT NULL,
        base_currency TEXT NOT NULL,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at_utc TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT pk_account PRIMARY KEY (account_id),
        CONSTRAINT uq_account_code UNIQUE (account_code),
        CONSTRAINT ck_account_code_not_blank CHECK (length(btrim(account_code)) > 0),
        CONSTRAINT ck_account_base_currency_upper CHECK (base_currency = upper(base_currency))
    );
    """,
    """
    CREATE TABLE cost_profile (
        cost_profile_id SMALLINT GENERATED ALWAYS AS IDENTITY,
        venue TEXT NOT NULL,
        fee_rate NUMERIC(10,6) NOT NULL,
        slippage_model_name TEXT NOT NULL,
        slippage_param_hash CHAR(64) NOT NULL,
        effective_from_utc TIMESTAMPTZ NOT NULL,
        effective_to_utc TIMESTAMPTZ,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        CONSTRAINT pk_cost_profile PRIMARY KEY (cost_profile_id),
        CONSTRAINT uq_cost_profile_venue_effective_from UNIQUE (venue, effective_from_utc),
        CONSTRAINT ck_cost_profile_venue_upper CHECK (venue = upper(venue)),
        CONSTRAINT ck_cost_profile_venue_not_blank CHECK (length(btrim(venue)) > 0),
        CONSTRAINT ck_cost_profile_fee_rate_range CHECK (fee_rate >= 0 AND fee_rate <= 1),
        CONSTRAINT ck_cost_profile_slippage_model_not_blank CHECK (length(btrim(slippage_model_name)) > 0),
        CONSTRAINT ck_cost_profile_effective_window CHECK (effective_to_utc IS NULL OR effective_to_utc > effective_from_utc),
        CONSTRAINT ck_cost_profile_kraken_fee_fixed CHECK (venue <> 'KRAKEN' OR fee_rate = 0.004000)
    );
    """,
    """
    CREATE TABLE model_version (
        model_version_id BIGINT GENERATED ALWAYS AS IDENTITY,
        model_name TEXT NOT NULL,
        model_role model_role_enum NOT NULL,
        version_label TEXT NOT NULL,
        mlflow_model_uri TEXT NOT NULL,
        mlflow_run_id TEXT NOT NULL,
        feature_set_version TEXT NOT NULL,
        hyperparams_hash CHAR(64) NOT NULL,
        training_data_hash CHAR(64) NOT NULL,
        created_at_utc TIMESTAMPTZ NOT NULL DEFAULT now(),
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        CONSTRAINT pk_model_version PRIMARY KEY (model_version_id),
        CONSTRAINT uq_model_version_name_label UNIQUE (model_name, version_label),
        CONSTRAINT ck_model_version_model_name_not_blank CHECK (length(btrim(model_name)) > 0),
        CONSTRAINT ck_model_version_version_label_not_blank CHECK (length(btrim(version_label)) > 0),
        CONSTRAINT ck_model_version_mlflow_uri_not_blank CHECK (length(btrim(mlflow_model_uri)) > 0),
        CONSTRAINT ck_model_version_mlflow_run_id_not_blank CHECK (length(btrim(mlflow_run_id)) > 0)
    );
    """,
    """
    CREATE TABLE feature_definition (
        feature_id INTEGER GENERATED ALWAYS AS IDENTITY,
        feature_name TEXT NOT NULL,
        feature_group TEXT NOT NULL,
        lookback_hours INTEGER NOT NULL,
        value_dtype TEXT NOT NULL DEFAULT 'NUMERIC',
        feature_version TEXT NOT NULL,
        created_at_utc TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT pk_feature_definition PRIMARY KEY (feature_id),
        CONSTRAINT uq_feature_definition_name_version UNIQUE (feature_name, feature_version),
        CONSTRAINT ck_feature_definition_name_not_blank CHECK (length(btrim(feature_name)) > 0),
        CONSTRAINT ck_feature_definition_group_not_blank CHECK (length(btrim(feature_group)) > 0),
        CONSTRAINT ck_feature_definition_lookback_nonneg CHECK (lookback_hours >= 0),
        CONSTRAINT ck_feature_definition_dtype CHECK (value_dtype IN ('NUMERIC'))
    );
    """,
    """
    CREATE TABLE backtest_run (
        backtest_run_id UUID NOT NULL,
        account_id SMALLINT NOT NULL,
        started_at_utc TIMESTAMPTZ NOT NULL,
        completed_at_utc TIMESTAMPTZ,
        status TEXT NOT NULL,
        strategy_code_sha CHAR(40) NOT NULL,
        config_hash CHAR(64) NOT NULL,
        universe_hash CHAR(64) NOT NULL,
        initial_capital NUMERIC(38,18) NOT NULL,
        cost_profile_id SMALLINT NOT NULL,
        random_seed INTEGER NOT NULL,
        CONSTRAINT pk_backtest_run PRIMARY KEY (backtest_run_id),
        CONSTRAINT ck_backtest_run_status CHECK (status IN ('QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')),
        CONSTRAINT ck_backtest_run_completed_after_started CHECK (completed_at_utc IS NULL OR completed_at_utc >= started_at_utc),
        CONSTRAINT ck_backtest_run_initial_capital_pos CHECK (initial_capital > 0),
        CONSTRAINT fk_backtest_run_account FOREIGN KEY (account_id)
            REFERENCES account (account_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_backtest_run_cost_profile FOREIGN KEY (cost_profile_id)
            REFERENCES cost_profile (cost_profile_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT
    );
    """,
    """
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
        CONSTRAINT uq_run_context_account_mode_hour UNIQUE (account_id, run_mode, hour_ts_utc),
        CONSTRAINT uq_run_context_run_mode_hour UNIQUE (run_id, run_mode, hour_ts_utc),
        CONSTRAINT ck_run_context_hour_aligned CHECK (date_trunc('hour', hour_ts_utc) = hour_ts_utc),
        CONSTRAINT ck_run_context_cycle_seq_pos CHECK (cycle_seq >= 0),
        CONSTRAINT ck_run_context_status CHECK (status IN ('STARTED', 'COMPLETED', 'FAILED', 'SKIPPED')),
        CONSTRAINT ck_run_context_completed_after_started CHECK (completed_at_utc IS NULL OR completed_at_utc >= started_at_utc),
        CONSTRAINT ck_run_context_backtest_link CHECK (
            (run_mode = 'BACKTEST' AND backtest_run_id IS NOT NULL) OR
            (run_mode IN ('PAPER', 'LIVE') AND backtest_run_id IS NULL)
        ),
        CONSTRAINT fk_run_context_account FOREIGN KEY (account_id)
            REFERENCES account (account_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_run_context_backtest_run FOREIGN KEY (backtest_run_id)
            REFERENCES backtest_run (backtest_run_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT
    );
    """,
    """
    CREATE TABLE model_training_window (
        training_window_id BIGINT GENERATED ALWAYS AS IDENTITY,
        model_version_id BIGINT NOT NULL,
        fold_index INTEGER NOT NULL,
        horizon horizon_enum NOT NULL,
        train_start_utc TIMESTAMPTZ NOT NULL,
        train_end_utc TIMESTAMPTZ NOT NULL,
        valid_start_utc TIMESTAMPTZ NOT NULL,
        valid_end_utc TIMESTAMPTZ NOT NULL,
        CONSTRAINT pk_model_training_window PRIMARY KEY (training_window_id),
        CONSTRAINT uq_model_training_window_model_fold_horizon UNIQUE (model_version_id, fold_index, horizon),
        CONSTRAINT ck_model_training_window_fold_nonneg CHECK (fold_index >= 0),
        CONSTRAINT ck_model_training_window_ordering CHECK (
            train_start_utc < train_end_utc AND
            train_end_utc < valid_start_utc AND
            valid_start_utc < valid_end_utc
        ),
        CONSTRAINT fk_model_training_window_model_version FOREIGN KEY (model_version_id)
            REFERENCES model_version (model_version_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT
    );
    """,
    """
    CREATE TABLE market_ohlcv_hourly (
        asset_id SMALLINT NOT NULL,
        hour_ts_utc TIMESTAMPTZ NOT NULL,
        open_price NUMERIC(38,18) NOT NULL,
        high_price NUMERIC(38,18) NOT NULL,
        low_price NUMERIC(38,18) NOT NULL,
        close_price NUMERIC(38,18) NOT NULL,
        volume_base NUMERIC(38,18) NOT NULL,
        volume_quote NUMERIC(38,18) NOT NULL,
        trade_count BIGINT NOT NULL,
        source_venue TEXT NOT NULL,
        ingest_run_id UUID NOT NULL,
        CONSTRAINT pk_market_ohlcv_hourly PRIMARY KEY (asset_id, hour_ts_utc, source_venue),
        CONSTRAINT ck_market_ohlcv_hourly_hour_aligned CHECK (date_trunc('hour', hour_ts_utc) = hour_ts_utc),
        CONSTRAINT ck_market_ohlcv_hourly_open_pos CHECK (open_price > 0),
        CONSTRAINT ck_market_ohlcv_hourly_high_pos CHECK (high_price > 0),
        CONSTRAINT ck_market_ohlcv_hourly_low_pos CHECK (low_price > 0),
        CONSTRAINT ck_market_ohlcv_hourly_close_pos CHECK (close_price > 0),
        CONSTRAINT ck_market_ohlcv_hourly_high_low CHECK (high_price >= low_price),
        CONSTRAINT ck_market_ohlcv_hourly_high_bounds CHECK (high_price >= greatest(open_price, close_price, low_price)),
        CONSTRAINT ck_market_ohlcv_hourly_low_bounds CHECK (low_price <= least(open_price, close_price, high_price)),
        CONSTRAINT ck_market_ohlcv_hourly_volume_base_nonneg CHECK (volume_base >= 0),
        CONSTRAINT ck_market_ohlcv_hourly_volume_quote_nonneg CHECK (volume_quote >= 0),
        CONSTRAINT ck_market_ohlcv_hourly_trade_count_nonneg CHECK (trade_count >= 0),
        CONSTRAINT fk_market_ohlcv_hourly_asset FOREIGN KEY (asset_id)
            REFERENCES asset (asset_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_market_ohlcv_hourly_run_context FOREIGN KEY (ingest_run_id)
            REFERENCES run_context (run_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT
    );
    """,
    """
    CREATE TABLE order_book_snapshot (
        asset_id SMALLINT NOT NULL,
        snapshot_ts_utc TIMESTAMPTZ NOT NULL,
        hour_ts_utc TIMESTAMPTZ NOT NULL,
        best_bid_price NUMERIC(38,18) NOT NULL,
        best_ask_price NUMERIC(38,18) NOT NULL,
        best_bid_size NUMERIC(38,18) NOT NULL,
        best_ask_size NUMERIC(38,18) NOT NULL,
        spread_abs NUMERIC(38,18) GENERATED ALWAYS AS (best_ask_price - best_bid_price) STORED,
        spread_bps NUMERIC(12,8) GENERATED ALWAYS AS (((best_ask_price - best_bid_price) / NULLIF(best_bid_price, 0)) * 10000::numeric) STORED,
        source_venue TEXT NOT NULL,
        ingest_run_id UUID NOT NULL,
        CONSTRAINT pk_order_book_snapshot PRIMARY KEY (asset_id, snapshot_ts_utc, source_venue),
        CONSTRAINT ck_order_book_snapshot_hour_aligned CHECK (date_trunc('hour', hour_ts_utc) = hour_ts_utc),
        CONSTRAINT ck_order_book_snapshot_bucket_match CHECK (hour_ts_utc = date_trunc('hour', snapshot_ts_utc)),
        CONSTRAINT ck_order_book_snapshot_bid_pos CHECK (best_bid_price > 0),
        CONSTRAINT ck_order_book_snapshot_ask_pos CHECK (best_ask_price > 0),
        CONSTRAINT ck_order_book_snapshot_ask_ge_bid CHECK (best_ask_price >= best_bid_price),
        CONSTRAINT ck_order_book_snapshot_bid_size_nonneg CHECK (best_bid_size >= 0),
        CONSTRAINT ck_order_book_snapshot_ask_size_nonneg CHECK (best_ask_size >= 0),
        CONSTRAINT fk_order_book_snapshot_asset FOREIGN KEY (asset_id)
            REFERENCES asset (asset_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_order_book_snapshot_run_context FOREIGN KEY (ingest_run_id)
            REFERENCES run_context (run_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT
    );
    """,
    """
    CREATE TABLE feature_snapshot (
        run_id UUID NOT NULL,
        run_mode run_mode_enum NOT NULL,
        asset_id SMALLINT NOT NULL,
        hour_ts_utc TIMESTAMPTZ NOT NULL,
        feature_id INTEGER NOT NULL,
        feature_value NUMERIC(38,18) NOT NULL,
        source_window_start_utc TIMESTAMPTZ NOT NULL,
        source_window_end_utc TIMESTAMPTZ NOT NULL,
        input_data_hash CHAR(64) NOT NULL,
        CONSTRAINT pk_feature_snapshot PRIMARY KEY (run_id, asset_id, feature_id, hour_ts_utc),
        CONSTRAINT ck_feature_snapshot_hour_aligned CHECK (date_trunc('hour', hour_ts_utc) = hour_ts_utc),
        CONSTRAINT ck_feature_snapshot_source_window CHECK (
            source_window_start_utc <= source_window_end_utc AND
            source_window_end_utc <= hour_ts_utc
        ),
        CONSTRAINT fk_feature_snapshot_run_context FOREIGN KEY (run_id, run_mode, hour_ts_utc)
            REFERENCES run_context (run_id, run_mode, hour_ts_utc)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_feature_snapshot_asset FOREIGN KEY (asset_id)
            REFERENCES asset (asset_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_feature_snapshot_feature_definition FOREIGN KEY (feature_id)
            REFERENCES feature_definition (feature_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT
    );
    """,
    """
    CREATE TABLE regime_output (
        run_id UUID NOT NULL,
        run_mode run_mode_enum NOT NULL,
        asset_id SMALLINT NOT NULL,
        hour_ts_utc TIMESTAMPTZ NOT NULL,
        model_version_id BIGINT NOT NULL,
        regime_label TEXT NOT NULL,
        regime_probability NUMERIC(12,10) NOT NULL,
        input_feature_hash CHAR(64) NOT NULL,
        CONSTRAINT pk_regime_output PRIMARY KEY (run_id, asset_id, hour_ts_utc),
        CONSTRAINT ck_regime_output_hour_aligned CHECK (date_trunc('hour', hour_ts_utc) = hour_ts_utc),
        CONSTRAINT ck_regime_output_label_not_blank CHECK (length(btrim(regime_label)) > 0),
        CONSTRAINT ck_regime_output_probability_range CHECK (regime_probability >= 0 AND regime_probability <= 1),
        CONSTRAINT fk_regime_output_run_context FOREIGN KEY (run_id, run_mode, hour_ts_utc)
            REFERENCES run_context (run_id, run_mode, hour_ts_utc)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_regime_output_asset FOREIGN KEY (asset_id)
            REFERENCES asset (asset_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_regime_output_model_version FOREIGN KEY (model_version_id)
            REFERENCES model_version (model_version_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT
    );
    """,
    """
    CREATE TABLE model_prediction (
        run_id UUID NOT NULL,
        run_mode run_mode_enum NOT NULL,
        asset_id SMALLINT NOT NULL,
        hour_ts_utc TIMESTAMPTZ NOT NULL,
        horizon horizon_enum NOT NULL,
        model_version_id BIGINT NOT NULL,
        model_role model_role_enum NOT NULL,
        prob_up NUMERIC(12,10) NOT NULL,
        expected_return NUMERIC(38,18) NOT NULL,
        input_feature_hash CHAR(64) NOT NULL,
        CONSTRAINT pk_model_prediction PRIMARY KEY (run_id, asset_id, horizon, model_version_id, hour_ts_utc),
        CONSTRAINT ck_model_prediction_hour_aligned CHECK (date_trunc('hour', hour_ts_utc) = hour_ts_utc),
        CONSTRAINT ck_model_prediction_prob_range CHECK (prob_up >= 0 AND prob_up <= 1),
        CONSTRAINT fk_model_prediction_run_context FOREIGN KEY (run_id, run_mode, hour_ts_utc)
            REFERENCES run_context (run_id, run_mode, hour_ts_utc)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_model_prediction_asset FOREIGN KEY (asset_id)
            REFERENCES asset (asset_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_model_prediction_model_version FOREIGN KEY (model_version_id)
            REFERENCES model_version (model_version_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT
    );
    """,
    """
    CREATE TABLE meta_learner_component (
        run_id UUID NOT NULL,
        run_mode run_mode_enum NOT NULL,
        asset_id SMALLINT NOT NULL,
        hour_ts_utc TIMESTAMPTZ NOT NULL,
        horizon horizon_enum NOT NULL,
        meta_model_version_id BIGINT NOT NULL,
        base_model_version_id BIGINT NOT NULL,
        base_prob_up NUMERIC(12,10) NOT NULL,
        base_expected_return NUMERIC(38,18) NOT NULL,
        component_weight NUMERIC(38,18) NOT NULL,
        CONSTRAINT pk_meta_learner_component PRIMARY KEY (
            run_id, asset_id, horizon, meta_model_version_id, base_model_version_id, hour_ts_utc
        ),
        CONSTRAINT ck_meta_learner_component_hour_aligned CHECK (date_trunc('hour', hour_ts_utc) = hour_ts_utc),
        CONSTRAINT ck_meta_learner_component_prob_range CHECK (base_prob_up >= 0 AND base_prob_up <= 1),
        CONSTRAINT ck_meta_learner_component_distinct_models CHECK (meta_model_version_id <> base_model_version_id),
        CONSTRAINT fk_meta_component_run_context FOREIGN KEY (run_id, run_mode, hour_ts_utc)
            REFERENCES run_context (run_id, run_mode, hour_ts_utc)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_meta_component_asset FOREIGN KEY (asset_id)
            REFERENCES asset (asset_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_meta_component_meta_model FOREIGN KEY (meta_model_version_id)
            REFERENCES model_version (model_version_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_meta_component_base_model FOREIGN KEY (base_model_version_id)
            REFERENCES model_version (model_version_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT
    );
    """,
    """
    CREATE TABLE portfolio_hourly_state (
        run_mode run_mode_enum NOT NULL,
        account_id SMALLINT NOT NULL,
        hour_ts_utc TIMESTAMPTZ NOT NULL,
        cash_balance NUMERIC(38,18) NOT NULL,
        market_value NUMERIC(38,18) NOT NULL,
        portfolio_value NUMERIC(38,18) NOT NULL,
        peak_portfolio_value NUMERIC(38,18) NOT NULL,
        drawdown_pct NUMERIC(12,10) NOT NULL,
        total_exposure_pct NUMERIC(12,10) NOT NULL,
        open_position_count INTEGER NOT NULL,
        halted BOOLEAN NOT NULL DEFAULT FALSE,
        source_run_id UUID NOT NULL,
        reconciliation_hash CHAR(64) NOT NULL,
        CONSTRAINT pk_portfolio_hourly_state PRIMARY KEY (run_mode, account_id, hour_ts_utc),
        CONSTRAINT ck_portfolio_hourly_state_hour_aligned CHECK (date_trunc('hour', hour_ts_utc) = hour_ts_utc),
        CONSTRAINT ck_portfolio_hourly_state_cash_nonneg CHECK (cash_balance >= 0),
        CONSTRAINT ck_portfolio_hourly_state_market_nonneg CHECK (market_value >= 0),
        CONSTRAINT ck_portfolio_hourly_state_value_nonneg CHECK (portfolio_value >= 0),
        CONSTRAINT ck_portfolio_hourly_state_peak_nonneg CHECK (peak_portfolio_value >= 0),
        CONSTRAINT ck_portfolio_hourly_state_drawdown_range CHECK (drawdown_pct >= 0 AND drawdown_pct <= 1),
        CONSTRAINT ck_portfolio_hourly_state_exposure_range CHECK (total_exposure_pct >= 0 AND total_exposure_pct <= 1),
        CONSTRAINT ck_portfolio_hourly_state_pos_count_range CHECK (open_position_count >= 0 AND open_position_count <= 10),
        CONSTRAINT ck_portfolio_hourly_state_value_reconcile CHECK (portfolio_value = cash_balance + market_value),
        CONSTRAINT ck_portfolio_hourly_state_peak_ge_value CHECK (peak_portfolio_value >= portfolio_value),
        CONSTRAINT fk_portfolio_hourly_state_account FOREIGN KEY (account_id)
            REFERENCES account (account_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_portfolio_hourly_state_run_context FOREIGN KEY (source_run_id, run_mode, hour_ts_utc)
            REFERENCES run_context (run_id, run_mode, hour_ts_utc)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT
    );
    """,
    """
    CREATE TABLE risk_hourly_state (
        run_mode run_mode_enum NOT NULL,
        account_id SMALLINT NOT NULL,
        hour_ts_utc TIMESTAMPTZ NOT NULL,
        portfolio_value NUMERIC(38,18) NOT NULL,
        peak_portfolio_value NUMERIC(38,18) NOT NULL,
        drawdown_pct NUMERIC(12,10) NOT NULL,
        drawdown_tier drawdown_tier_enum NOT NULL,
        base_risk_fraction NUMERIC(12,10) NOT NULL,
        max_concurrent_positions INTEGER NOT NULL,
        max_total_exposure_pct NUMERIC(12,10) NOT NULL,
        max_cluster_exposure_pct NUMERIC(12,10) NOT NULL,
        halt_new_entries BOOLEAN NOT NULL DEFAULT FALSE,
        kill_switch_active BOOLEAN NOT NULL DEFAULT FALSE,
        kill_switch_reason TEXT,
        requires_manual_review BOOLEAN NOT NULL DEFAULT FALSE,
        evaluated_at_utc TIMESTAMPTZ NOT NULL DEFAULT now(),
        source_run_id UUID NOT NULL,
        state_hash CHAR(64) NOT NULL,
        CONSTRAINT pk_risk_hourly_state PRIMARY KEY (run_mode, account_id, hour_ts_utc),
        CONSTRAINT ck_risk_hourly_state_hour_aligned CHECK (date_trunc('hour', hour_ts_utc) = hour_ts_utc),
        CONSTRAINT ck_risk_hourly_state_drawdown_range CHECK (drawdown_pct >= 0 AND drawdown_pct <= 1),
        CONSTRAINT ck_risk_hourly_state_base_risk_range CHECK (base_risk_fraction >= 0 AND base_risk_fraction <= 0.02),
        CONSTRAINT ck_risk_hourly_state_max_pos_range CHECK (max_concurrent_positions >= 0 AND max_concurrent_positions <= 10),
        CONSTRAINT ck_risk_hourly_state_total_exposure_cap CHECK (max_total_exposure_pct > 0 AND max_total_exposure_pct <= 0.20),
        CONSTRAINT ck_risk_hourly_state_cluster_exposure_cap CHECK (max_cluster_exposure_pct > 0 AND max_cluster_exposure_pct <= 0.08),
        CONSTRAINT ck_risk_hourly_state_peak_ge_value CHECK (peak_portfolio_value >= portfolio_value),
        CONSTRAINT ck_risk_hourly_state_tier_mapping CHECK (
            (drawdown_pct < 0.10 AND drawdown_tier = 'NORMAL') OR
            (drawdown_pct >= 0.10 AND drawdown_pct < 0.15 AND drawdown_tier = 'DD10') OR
            (drawdown_pct >= 0.15 AND drawdown_pct < 0.20 AND drawdown_tier = 'DD15') OR
            (drawdown_pct >= 0.20 AND drawdown_tier = 'HALT20')
        ),
        CONSTRAINT ck_risk_hourly_state_dd10_controls CHECK (
            drawdown_pct < 0.10 OR base_risk_fraction <= 0.015
        ),
        CONSTRAINT ck_risk_hourly_state_dd15_controls CHECK (
            drawdown_pct < 0.15 OR (base_risk_fraction <= 0.01 AND max_concurrent_positions <= 5)
        ),
        CONSTRAINT ck_risk_hourly_state_dd20_halt CHECK (
            drawdown_pct < 0.20 OR (
                halt_new_entries = TRUE AND
                requires_manual_review = TRUE AND
                base_risk_fraction = 0 AND
                drawdown_tier = 'HALT20'
            )
        ),
        CONSTRAINT ck_risk_hourly_state_kill_switch_reason CHECK (
            kill_switch_active = FALSE OR length(btrim(coalesce(kill_switch_reason, ''))) > 0
        ),
        CONSTRAINT fk_risk_hourly_state_portfolio FOREIGN KEY (run_mode, account_id, hour_ts_utc)
            REFERENCES portfolio_hourly_state (run_mode, account_id, hour_ts_utc)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_risk_hourly_state_run_context FOREIGN KEY (source_run_id, run_mode, hour_ts_utc)
            REFERENCES run_context (run_id, run_mode, hour_ts_utc)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT
    );
    """,
    """
    CREATE TABLE trade_signal (
        signal_id UUID NOT NULL,
        run_id UUID NOT NULL,
        run_mode run_mode_enum NOT NULL,
        account_id SMALLINT NOT NULL,
        asset_id SMALLINT NOT NULL,
        hour_ts_utc TIMESTAMPTZ NOT NULL,
        horizon horizon_enum NOT NULL,
        action signal_action_enum NOT NULL,
        direction TEXT NOT NULL,
        confidence NUMERIC(12,10) NOT NULL,
        expected_return NUMERIC(38,18) NOT NULL,
        assumed_fee_rate NUMERIC(10,6) NOT NULL,
        assumed_slippage_rate NUMERIC(10,6) NOT NULL,
        net_edge NUMERIC(38,18) NOT NULL,
        target_position_notional NUMERIC(38,18) NOT NULL,
        position_size_fraction NUMERIC(12,10) NOT NULL,
        risk_state_hour_ts_utc TIMESTAMPTZ NOT NULL,
        decision_hash CHAR(64) NOT NULL,
        CONSTRAINT pk_trade_signal PRIMARY KEY (signal_id),
        CONSTRAINT uq_trade_signal_run_account_asset_horizon UNIQUE (run_id, account_id, asset_id, horizon),
        CONSTRAINT uq_trade_signal_identity UNIQUE (signal_id, run_id, run_mode, account_id, asset_id),
        CONSTRAINT ck_trade_signal_hour_aligned CHECK (date_trunc('hour', hour_ts_utc) = hour_ts_utc),
        CONSTRAINT ck_trade_signal_risk_hour_aligned CHECK (date_trunc('hour', risk_state_hour_ts_utc) = risk_state_hour_ts_utc),
        CONSTRAINT ck_trade_signal_risk_hour_match CHECK (risk_state_hour_ts_utc = hour_ts_utc),
        CONSTRAINT ck_trade_signal_direction CHECK (direction IN ('LONG', 'FLAT')),
        CONSTRAINT ck_trade_signal_confidence_range CHECK (confidence >= 0 AND confidence <= 1),
        CONSTRAINT ck_trade_signal_fee_rate_range CHECK (assumed_fee_rate >= 0 AND assumed_fee_rate <= 1),
        CONSTRAINT ck_trade_signal_slippage_rate_range CHECK (assumed_slippage_rate >= 0 AND assumed_slippage_rate <= 1),
        CONSTRAINT ck_trade_signal_position_fraction_range CHECK (position_size_fraction >= 0 AND position_size_fraction <= 1),
        CONSTRAINT ck_trade_signal_target_notional_nonneg CHECK (target_position_notional >= 0),
        CONSTRAINT ck_trade_signal_enter_edge CHECK (action <> 'ENTER' OR net_edge > 0),
        CONSTRAINT ck_trade_signal_enter_return_gt_cost CHECK (
            action <> 'ENTER' OR expected_return > (assumed_fee_rate + assumed_slippage_rate)
        ),
        CONSTRAINT ck_trade_signal_enter_direction CHECK (action <> 'ENTER' OR direction = 'LONG'),
        CONSTRAINT ck_trade_signal_exit_direction CHECK (action <> 'EXIT' OR direction = 'FLAT'),
        CONSTRAINT fk_trade_signal_run_context FOREIGN KEY (run_id, run_mode, hour_ts_utc)
            REFERENCES run_context (run_id, run_mode, hour_ts_utc)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_trade_signal_account FOREIGN KEY (account_id)
            REFERENCES account (account_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_trade_signal_asset FOREIGN KEY (asset_id)
            REFERENCES asset (asset_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_trade_signal_risk_hourly_state FOREIGN KEY (run_mode, account_id, risk_state_hour_ts_utc)
            REFERENCES risk_hourly_state (run_mode, account_id, hour_ts_utc)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT
    );
    """,
    """
    CREATE TABLE order_request (
        order_id UUID NOT NULL,
        signal_id UUID NOT NULL,
        run_id UUID NOT NULL,
        run_mode run_mode_enum NOT NULL,
        account_id SMALLINT NOT NULL,
        asset_id SMALLINT NOT NULL,
        client_order_id TEXT NOT NULL,
        request_ts_utc TIMESTAMPTZ NOT NULL,
        hour_ts_utc TIMESTAMPTZ NOT NULL,
        side order_side_enum NOT NULL,
        order_type order_type_enum NOT NULL,
        tif TEXT NOT NULL,
        limit_price NUMERIC(38,18),
        requested_qty NUMERIC(38,18) NOT NULL,
        requested_notional NUMERIC(38,18) NOT NULL,
        pre_order_cash_available NUMERIC(38,18) NOT NULL,
        risk_check_passed BOOLEAN NOT NULL,
        status order_status_enum NOT NULL,
        cost_profile_id SMALLINT NOT NULL,
        CONSTRAINT pk_order_request PRIMARY KEY (order_id),
        CONSTRAINT uq_order_request_client_order_id UNIQUE (client_order_id),
        CONSTRAINT uq_order_request_identity UNIQUE (order_id, run_id, run_mode, account_id, asset_id),
        CONSTRAINT ck_order_request_client_order_id_not_blank CHECK (length(btrim(client_order_id)) > 0),
        CONSTRAINT ck_order_request_hour_aligned CHECK (date_trunc('hour', hour_ts_utc) = hour_ts_utc),
        CONSTRAINT ck_order_request_request_in_hour CHECK (
            request_ts_utc >= hour_ts_utc AND request_ts_utc < hour_ts_utc + interval '1 hour'
        ),
        CONSTRAINT ck_order_request_tif CHECK (tif IN ('GTC', 'IOC', 'FOK')),
        CONSTRAINT ck_order_request_limit_price_rule CHECK (
            (order_type = 'LIMIT' AND limit_price IS NOT NULL AND limit_price > 0) OR
            (order_type = 'MARKET' AND limit_price IS NULL)
        ),
        CONSTRAINT ck_order_request_qty_pos CHECK (requested_qty > 0),
        CONSTRAINT ck_order_request_notional_pos CHECK (requested_notional > 0),
        CONSTRAINT ck_order_request_cash_nonneg CHECK (pre_order_cash_available >= 0),
        CONSTRAINT ck_order_request_no_leverage_buy CHECK (
            side <> 'BUY' OR requested_notional <= pre_order_cash_available
        ),
        CONSTRAINT ck_order_request_risk_gate CHECK (
            risk_check_passed = TRUE OR status = 'REJECTED'
        ),
        CONSTRAINT fk_order_request_signal_identity FOREIGN KEY (signal_id)
            REFERENCES trade_signal (signal_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_order_request_run_context FOREIGN KEY (run_id, run_mode, hour_ts_utc)
            REFERENCES run_context (run_id, run_mode, hour_ts_utc)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_order_request_account FOREIGN KEY (account_id)
            REFERENCES account (account_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_order_request_asset FOREIGN KEY (asset_id)
            REFERENCES asset (asset_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_order_request_cost_profile FOREIGN KEY (cost_profile_id)
            REFERENCES cost_profile (cost_profile_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT
    );
    """,
    """
    CREATE TABLE order_fill (
        fill_id UUID NOT NULL,
        order_id UUID NOT NULL,
        run_id UUID NOT NULL,
        run_mode run_mode_enum NOT NULL,
        account_id SMALLINT NOT NULL,
        asset_id SMALLINT NOT NULL,
        exchange_trade_id TEXT NOT NULL,
        fill_ts_utc TIMESTAMPTZ NOT NULL,
        hour_ts_utc TIMESTAMPTZ NOT NULL,
        fill_price NUMERIC(38,18) NOT NULL,
        fill_qty NUMERIC(38,18) NOT NULL,
        fill_notional NUMERIC(38,18) NOT NULL,
        fee_paid NUMERIC(38,18) NOT NULL,
        fee_rate NUMERIC(10,6) NOT NULL,
        realized_slippage_rate NUMERIC(10,6) NOT NULL,
        liquidity_flag TEXT NOT NULL DEFAULT 'UNKNOWN',
        CONSTRAINT pk_order_fill PRIMARY KEY (fill_id),
        CONSTRAINT uq_order_fill_order_exchange_trade UNIQUE (order_id, exchange_trade_id),
        CONSTRAINT uq_order_fill_identity UNIQUE (fill_id, run_id, run_mode, account_id, asset_id),
        CONSTRAINT ck_order_fill_exchange_trade_id_not_blank CHECK (length(btrim(exchange_trade_id)) > 0),
        CONSTRAINT ck_order_fill_hour_aligned CHECK (date_trunc('hour', hour_ts_utc) = hour_ts_utc),
        CONSTRAINT ck_order_fill_bucket_match CHECK (hour_ts_utc = date_trunc('hour', fill_ts_utc)),
        CONSTRAINT ck_order_fill_price_pos CHECK (fill_price > 0),
        CONSTRAINT ck_order_fill_qty_pos CHECK (fill_qty > 0),
        CONSTRAINT ck_order_fill_notional_pos CHECK (fill_notional > 0),
        CONSTRAINT ck_order_fill_notional_formula CHECK (fill_notional = fill_price * fill_qty),
        CONSTRAINT ck_order_fill_fee_nonneg CHECK (fee_paid >= 0),
        CONSTRAINT ck_order_fill_fee_rate_range CHECK (fee_rate >= 0 AND fee_rate <= 1),
        CONSTRAINT ck_order_fill_slippage_nonneg CHECK (realized_slippage_rate >= 0),
        CONSTRAINT ck_order_fill_liquidity_flag CHECK (liquidity_flag IN ('MAKER', 'TAKER', 'UNKNOWN')),
        CONSTRAINT fk_order_fill_order_request_identity FOREIGN KEY (order_id, run_id, run_mode, account_id, asset_id)
            REFERENCES order_request (order_id, run_id, run_mode, account_id, asset_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_order_fill_run_context FOREIGN KEY (run_id, run_mode, hour_ts_utc)
            REFERENCES run_context (run_id, run_mode, hour_ts_utc)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_order_fill_account FOREIGN KEY (account_id)
            REFERENCES account (account_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_order_fill_asset FOREIGN KEY (asset_id)
            REFERENCES asset (asset_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT
    );
    """,
    """
    CREATE TABLE position_lot (
        lot_id UUID NOT NULL,
        open_fill_id UUID NOT NULL,
        run_id UUID NOT NULL,
        run_mode run_mode_enum NOT NULL,
        account_id SMALLINT NOT NULL,
        asset_id SMALLINT NOT NULL,
        hour_ts_utc TIMESTAMPTZ NOT NULL,
        open_ts_utc TIMESTAMPTZ NOT NULL,
        open_price NUMERIC(38,18) NOT NULL,
        open_qty NUMERIC(38,18) NOT NULL,
        open_notional NUMERIC(38,18) NOT NULL,
        open_fee NUMERIC(38,18) NOT NULL,
        remaining_qty NUMERIC(38,18) NOT NULL,
        CONSTRAINT pk_position_lot PRIMARY KEY (lot_id),
        CONSTRAINT uq_position_lot_open_fill UNIQUE (open_fill_id),
        CONSTRAINT uq_position_lot_identity UNIQUE (lot_id, run_id, run_mode, account_id, asset_id),
        CONSTRAINT ck_position_lot_hour_aligned CHECK (date_trunc('hour', hour_ts_utc) = hour_ts_utc),
        CONSTRAINT ck_position_lot_bucket_match CHECK (hour_ts_utc = date_trunc('hour', open_ts_utc)),
        CONSTRAINT ck_position_lot_open_price_pos CHECK (open_price > 0),
        CONSTRAINT ck_position_lot_open_qty_pos CHECK (open_qty > 0),
        CONSTRAINT ck_position_lot_open_notional_pos CHECK (open_notional > 0),
        CONSTRAINT ck_position_lot_notional_formula CHECK (open_notional = open_price * open_qty),
        CONSTRAINT ck_position_lot_open_fee_nonneg CHECK (open_fee >= 0),
        CONSTRAINT ck_position_lot_remaining_range CHECK (remaining_qty >= 0 AND remaining_qty <= open_qty),
        CONSTRAINT fk_position_lot_order_fill_identity FOREIGN KEY (open_fill_id, run_id, run_mode, account_id, asset_id)
            REFERENCES order_fill (fill_id, run_id, run_mode, account_id, asset_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_position_lot_run_context FOREIGN KEY (run_id, run_mode, hour_ts_utc)
            REFERENCES run_context (run_id, run_mode, hour_ts_utc)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_position_lot_account FOREIGN KEY (account_id)
            REFERENCES account (account_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_position_lot_asset FOREIGN KEY (asset_id)
            REFERENCES asset (asset_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT
    );
    """,
    """
    CREATE TABLE executed_trade (
        trade_id UUID NOT NULL,
        lot_id UUID NOT NULL,
        run_id UUID NOT NULL,
        run_mode run_mode_enum NOT NULL,
        account_id SMALLINT NOT NULL,
        asset_id SMALLINT NOT NULL,
        hour_ts_utc TIMESTAMPTZ NOT NULL,
        entry_ts_utc TIMESTAMPTZ NOT NULL,
        exit_ts_utc TIMESTAMPTZ NOT NULL,
        entry_price NUMERIC(38,18) NOT NULL,
        exit_price NUMERIC(38,18) NOT NULL,
        quantity NUMERIC(38,18) NOT NULL,
        gross_pnl NUMERIC(38,18) NOT NULL,
        net_pnl NUMERIC(38,18) NOT NULL,
        total_fee NUMERIC(38,18) NOT NULL,
        total_slippage_cost NUMERIC(38,18) NOT NULL,
        holding_hours INTEGER NOT NULL,
        CONSTRAINT pk_executed_trade PRIMARY KEY (trade_id),
        CONSTRAINT uq_executed_trade_lot_exit_qty UNIQUE (lot_id, exit_ts_utc, quantity),
        CONSTRAINT ck_executed_trade_hour_aligned CHECK (date_trunc('hour', hour_ts_utc) = hour_ts_utc),
        CONSTRAINT ck_executed_trade_bucket_match CHECK (hour_ts_utc = date_trunc('hour', exit_ts_utc)),
        CONSTRAINT ck_executed_trade_time_order CHECK (exit_ts_utc >= entry_ts_utc),
        CONSTRAINT ck_executed_trade_entry_price_pos CHECK (entry_price > 0),
        CONSTRAINT ck_executed_trade_exit_price_pos CHECK (exit_price > 0),
        CONSTRAINT ck_executed_trade_qty_pos CHECK (quantity > 0),
        CONSTRAINT ck_executed_trade_fee_nonneg CHECK (total_fee >= 0),
        CONSTRAINT ck_executed_trade_slippage_nonneg CHECK (total_slippage_cost >= 0),
        CONSTRAINT ck_executed_trade_holding_nonneg CHECK (holding_hours >= 0),
        CONSTRAINT ck_executed_trade_net_pnl_formula CHECK (net_pnl = gross_pnl - total_fee - total_slippage_cost),
        CONSTRAINT fk_executed_trade_lot_identity FOREIGN KEY (lot_id, run_id, run_mode, account_id, asset_id)
            REFERENCES position_lot (lot_id, run_id, run_mode, account_id, asset_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_executed_trade_run_context FOREIGN KEY (run_id, run_mode, hour_ts_utc)
            REFERENCES run_context (run_id, run_mode, hour_ts_utc)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_executed_trade_account FOREIGN KEY (account_id)
            REFERENCES account (account_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_executed_trade_asset FOREIGN KEY (asset_id)
            REFERENCES asset (asset_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT
    );
    """,
    """
    CREATE TABLE cash_ledger (
        ledger_id BIGINT GENERATED ALWAYS AS IDENTITY,
        run_id UUID NOT NULL,
        run_mode run_mode_enum NOT NULL,
        account_id SMALLINT NOT NULL,
        event_ts_utc TIMESTAMPTZ NOT NULL,
        hour_ts_utc TIMESTAMPTZ NOT NULL,
        event_type TEXT NOT NULL,
        ref_type TEXT NOT NULL,
        ref_id UUID NOT NULL,
        delta_cash NUMERIC(38,18) NOT NULL,
        balance_after NUMERIC(38,18) NOT NULL,
        CONSTRAINT pk_cash_ledger PRIMARY KEY (ledger_id),
        CONSTRAINT uq_cash_ledger_idempotency UNIQUE (account_id, run_mode, event_ts_utc, ref_type, ref_id, event_type),
        CONSTRAINT ck_cash_ledger_hour_aligned CHECK (date_trunc('hour', hour_ts_utc) = hour_ts_utc),
        CONSTRAINT ck_cash_ledger_bucket_match CHECK (hour_ts_utc = date_trunc('hour', event_ts_utc)),
        CONSTRAINT ck_cash_ledger_event_type_not_blank CHECK (length(btrim(event_type)) > 0),
        CONSTRAINT ck_cash_ledger_ref_type_not_blank CHECK (length(btrim(ref_type)) > 0),
        CONSTRAINT ck_cash_ledger_balance_nonneg CHECK (balance_after >= 0),
        CONSTRAINT fk_cash_ledger_run_context FOREIGN KEY (run_id, run_mode, hour_ts_utc)
            REFERENCES run_context (run_id, run_mode, hour_ts_utc)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_cash_ledger_account FOREIGN KEY (account_id)
            REFERENCES account (account_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT
    );
    """,
    """
    CREATE TABLE position_hourly_state (
        run_mode run_mode_enum NOT NULL,
        account_id SMALLINT NOT NULL,
        asset_id SMALLINT NOT NULL,
        hour_ts_utc TIMESTAMPTZ NOT NULL,
        quantity NUMERIC(38,18) NOT NULL,
        avg_cost NUMERIC(38,18) NOT NULL,
        mark_price NUMERIC(38,18) NOT NULL,
        market_value NUMERIC(38,18) NOT NULL,
        unrealized_pnl NUMERIC(38,18) NOT NULL,
        realized_pnl_cum NUMERIC(38,18) NOT NULL,
        exposure_pct NUMERIC(12,10) NOT NULL,
        source_run_id UUID NOT NULL,
        CONSTRAINT pk_position_hourly_state PRIMARY KEY (run_mode, account_id, asset_id, hour_ts_utc),
        CONSTRAINT ck_position_hourly_state_hour_aligned CHECK (date_trunc('hour', hour_ts_utc) = hour_ts_utc),
        CONSTRAINT ck_position_hourly_state_qty_nonneg CHECK (quantity >= 0),
        CONSTRAINT ck_position_hourly_state_avg_cost_nonneg CHECK (avg_cost >= 0),
        CONSTRAINT ck_position_hourly_state_mark_price_pos CHECK (mark_price > 0),
        CONSTRAINT ck_position_hourly_state_market_value_nonneg CHECK (market_value >= 0),
        CONSTRAINT ck_position_hourly_state_market_value_formula CHECK (market_value = quantity * mark_price),
        CONSTRAINT ck_position_hourly_state_exposure_range CHECK (exposure_pct >= 0 AND exposure_pct <= 1),
        CONSTRAINT fk_position_hourly_state_account FOREIGN KEY (account_id)
            REFERENCES account (account_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_position_hourly_state_asset FOREIGN KEY (asset_id)
            REFERENCES asset (asset_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_position_hourly_state_run_context FOREIGN KEY (source_run_id, run_mode, hour_ts_utc)
            REFERENCES run_context (run_id, run_mode, hour_ts_utc)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT
    );
    """,
    """
    CREATE TABLE risk_event (
        risk_event_id UUID NOT NULL,
        run_id UUID NOT NULL,
        run_mode run_mode_enum NOT NULL,
        account_id SMALLINT NOT NULL,
        event_ts_utc TIMESTAMPTZ NOT NULL,
        hour_ts_utc TIMESTAMPTZ NOT NULL,
        event_type TEXT NOT NULL,
        severity TEXT NOT NULL,
        reason_code TEXT NOT NULL,
        details JSONB NOT NULL DEFAULT '{}'::jsonb,
        related_state_hour_ts_utc TIMESTAMPTZ NOT NULL,
        CONSTRAINT pk_risk_event PRIMARY KEY (risk_event_id),
        CONSTRAINT ck_risk_event_hour_aligned CHECK (date_trunc('hour', hour_ts_utc) = hour_ts_utc),
        CONSTRAINT ck_risk_event_bucket_match CHECK (hour_ts_utc = date_trunc('hour', event_ts_utc)),
        CONSTRAINT ck_risk_event_event_type_not_blank CHECK (length(btrim(event_type)) > 0),
        CONSTRAINT ck_risk_event_reason_not_blank CHECK (length(btrim(reason_code)) > 0),
        CONSTRAINT ck_risk_event_severity CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
        CONSTRAINT ck_risk_event_related_state_not_future CHECK (related_state_hour_ts_utc <= hour_ts_utc),
        CONSTRAINT fk_risk_event_run_context FOREIGN KEY (run_id, run_mode, hour_ts_utc)
            REFERENCES run_context (run_id, run_mode, hour_ts_utc)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_risk_event_account FOREIGN KEY (account_id)
            REFERENCES account (account_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT,
        CONSTRAINT fk_risk_event_risk_hourly_state FOREIGN KEY (run_mode, account_id, related_state_hour_ts_utc)
            REFERENCES risk_hourly_state (run_mode, account_id, hour_ts_utc)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT
    );
    """,
    """
    CREATE TABLE backtest_fold_result (
        backtest_run_id UUID NOT NULL,
        fold_index INTEGER NOT NULL,
        train_start_utc TIMESTAMPTZ NOT NULL,
        train_end_utc TIMESTAMPTZ NOT NULL,
        valid_start_utc TIMESTAMPTZ NOT NULL,
        valid_end_utc TIMESTAMPTZ NOT NULL,
        trades_count INTEGER NOT NULL,
        sharpe NUMERIC(20,10) NOT NULL,
        max_drawdown_pct NUMERIC(12,10) NOT NULL,
        net_return_pct NUMERIC(38,18) NOT NULL,
        win_rate NUMERIC(12,10) NOT NULL,
        CONSTRAINT pk_backtest_fold_result PRIMARY KEY (backtest_run_id, fold_index),
        CONSTRAINT ck_backtest_fold_result_fold_nonneg CHECK (fold_index >= 0),
        CONSTRAINT ck_backtest_fold_result_window_order CHECK (
            train_start_utc < train_end_utc AND
            train_end_utc < valid_start_utc AND
            valid_start_utc < valid_end_utc
        ),
        CONSTRAINT ck_backtest_fold_result_trades_nonneg CHECK (trades_count >= 0),
        CONSTRAINT ck_backtest_fold_result_drawdown_range CHECK (max_drawdown_pct >= 0 AND max_drawdown_pct <= 1),
        CONSTRAINT ck_backtest_fold_result_win_rate_range CHECK (win_rate >= 0 AND win_rate <= 1),
        CONSTRAINT fk_backtest_fold_result_backtest_run FOREIGN KEY (backtest_run_id)
            REFERENCES backtest_run (backtest_run_id)
            ON UPDATE RESTRICT
            ON DELETE RESTRICT
    );
    """,
)

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX idx_asset_is_active ON asset USING btree (is_active);",
    "CREATE INDEX idx_cost_profile_venue_effective_from_desc ON cost_profile USING btree (venue, effective_from_utc DESC);",
    "CREATE UNIQUE INDEX uqix_cost_profile_one_active_per_venue ON cost_profile USING btree (venue) WHERE is_active = TRUE;",
    "CREATE INDEX idx_model_version_role_active ON model_version USING btree (model_role, is_active);",
    "CREATE UNIQUE INDEX uqix_model_version_one_active_per_name_role ON model_version USING btree (model_name, model_role) WHERE is_active = TRUE;",
    "CREATE INDEX idx_model_training_window_valid_range ON model_training_window USING btree (valid_start_utc, valid_end_utc);",
    "CREATE INDEX idx_backtest_run_status_started_desc ON backtest_run USING btree (status, started_at_utc DESC);",
    "CREATE INDEX idx_backtest_run_config_hash ON backtest_run USING btree (config_hash);",
    "CREATE INDEX idx_run_context_mode_hour_desc ON run_context USING btree (run_mode, hour_ts_utc DESC);",
    "CREATE INDEX idx_run_context_account_mode_hour_desc ON run_context USING btree (account_id, run_mode, hour_ts_utc DESC);",
    "CREATE INDEX idx_market_ohlcv_hour_desc ON market_ohlcv_hourly USING btree (hour_ts_utc DESC);",
    "CREATE INDEX idx_order_book_asset_hour_desc ON order_book_snapshot USING btree (asset_id, hour_ts_utc DESC);",
    "CREATE INDEX idx_order_book_hour_desc ON order_book_snapshot USING btree (hour_ts_utc DESC);",
    "CREATE INDEX idx_feature_snapshot_asset_hour_desc ON feature_snapshot USING btree (asset_id, hour_ts_utc DESC);",
    "CREATE INDEX idx_feature_snapshot_feature_hour_desc ON feature_snapshot USING btree (feature_id, hour_ts_utc DESC);",
    "CREATE INDEX idx_feature_snapshot_mode_hour_desc ON feature_snapshot USING btree (run_mode, hour_ts_utc DESC);",
    "CREATE INDEX idx_regime_output_label_hour_desc ON regime_output USING btree (regime_label, hour_ts_utc DESC);",
    "CREATE INDEX idx_regime_output_asset_hour_desc ON regime_output USING btree (asset_id, hour_ts_utc DESC);",
    "CREATE INDEX idx_model_prediction_asset_hour_horizon ON model_prediction USING btree (asset_id, hour_ts_utc DESC, horizon);",
    "CREATE INDEX idx_model_prediction_role_hour_desc ON model_prediction USING btree (model_role, hour_ts_utc DESC);",
    """
    CREATE UNIQUE INDEX uqix_model_prediction_meta_per_run_asset_horizon_hour
        ON model_prediction USING btree (run_id, asset_id, horizon, hour_ts_utc)
        WHERE model_role = 'META';
    """,
    "CREATE INDEX idx_meta_component_meta_model_hour_desc ON meta_learner_component USING btree (meta_model_version_id, hour_ts_utc DESC);",
    "CREATE INDEX idx_meta_component_asset_hour_desc ON meta_learner_component USING btree (asset_id, hour_ts_utc DESC);",
    "CREATE INDEX idx_portfolio_hourly_account_hour_desc ON portfolio_hourly_state USING btree (account_id, hour_ts_utc DESC);",
    """
    CREATE INDEX idx_portfolio_hourly_halted_true_hour_desc ON portfolio_hourly_state USING btree (hour_ts_utc DESC)
        WHERE halted = TRUE;
    """,
    "CREATE INDEX idx_portfolio_hourly_source_run_id ON portfolio_hourly_state USING btree (source_run_id);",
    "CREATE INDEX idx_risk_hourly_tier_hour_desc ON risk_hourly_state USING btree (drawdown_tier, hour_ts_utc DESC);",
    """
    CREATE INDEX idx_risk_hourly_halt_true_hour_desc ON risk_hourly_state USING btree (hour_ts_utc DESC)
        WHERE halt_new_entries = TRUE;
    """,
    "CREATE INDEX idx_risk_hourly_source_run_id ON risk_hourly_state USING btree (source_run_id);",
    "CREATE INDEX idx_trade_signal_action_hour_desc ON trade_signal USING btree (action, hour_ts_utc DESC);",
    "CREATE INDEX idx_trade_signal_account_hour_desc ON trade_signal USING btree (account_id, hour_ts_utc DESC);",
    "CREATE INDEX idx_order_request_account_request_ts_desc ON order_request USING btree (account_id, request_ts_utc DESC);",
    "CREATE INDEX idx_order_request_status_request_ts_desc ON order_request USING btree (status, request_ts_utc DESC);",
    "CREATE INDEX idx_order_fill_account_fill_ts_desc ON order_fill USING btree (account_id, fill_ts_utc DESC);",
    "CREATE INDEX idx_order_fill_asset_hour_desc ON order_fill USING btree (asset_id, hour_ts_utc DESC);",
    "CREATE INDEX idx_order_fill_order_id ON order_fill USING btree (order_id);",
    "CREATE INDEX idx_position_lot_account_asset_open_ts_desc ON position_lot USING btree (account_id, asset_id, open_ts_utc DESC);",
    "CREATE INDEX idx_position_lot_remaining_qty ON position_lot USING btree (remaining_qty);",
    "CREATE INDEX idx_executed_trade_account_exit_ts_desc ON executed_trade USING btree (account_id, exit_ts_utc DESC);",
    "CREATE INDEX idx_executed_trade_asset_exit_ts_desc ON executed_trade USING btree (asset_id, exit_ts_utc DESC);",
    "CREATE INDEX idx_executed_trade_lot_id ON executed_trade USING btree (lot_id);",
    "CREATE INDEX idx_cash_ledger_account_event_ts_desc ON cash_ledger USING btree (account_id, event_ts_utc DESC);",
    "CREATE INDEX idx_cash_ledger_hour_desc ON cash_ledger USING btree (hour_ts_utc DESC);",
    "CREATE INDEX idx_cash_ledger_run_id ON cash_ledger USING btree (run_id);",
    "CREATE INDEX idx_position_hourly_account_hour_desc ON position_hourly_state USING btree (account_id, hour_ts_utc DESC);",
    "CREATE INDEX idx_position_hourly_asset_hour_desc ON position_hourly_state USING btree (asset_id, hour_ts_utc DESC);",
    "CREATE INDEX idx_position_hourly_source_run_id ON position_hourly_state USING btree (source_run_id);",
    "CREATE INDEX idx_risk_event_type_event_ts_desc ON risk_event USING btree (event_type, event_ts_utc DESC);",
    "CREATE INDEX idx_risk_event_severity_event_ts_desc ON risk_event USING btree (severity, event_ts_utc DESC);",
    "CREATE INDEX idx_risk_event_account_event_ts_desc ON risk_event USING btree (account_id, event_ts_utc DESC);",
    "CREATE INDEX idx_backtest_fold_result_valid_range ON backtest_fold_result USING btree (valid_start_utc, valid_end_utc);",
)

TIMESCALE_HYPERTABLE_DDL: tuple[str, ...] = (
    """
    SELECT create_hypertable(
        'market_ohlcv_hourly',
        'hour_ts_utc',
        'asset_id',
        8,
        chunk_time_interval => INTERVAL '30 days',
        if_not_exists => TRUE
    );
    """,
    """
    SELECT create_hypertable(
        'order_book_snapshot',
        'snapshot_ts_utc',
        'asset_id',
        8,
        chunk_time_interval => INTERVAL '7 days',
        if_not_exists => TRUE
    );
    """,
    """
    SELECT create_hypertable(
        'feature_snapshot',
        'hour_ts_utc',
        'asset_id',
        8,
        chunk_time_interval => INTERVAL '14 days',
        if_not_exists => TRUE
    );
    """,
    """
    SELECT create_hypertable(
        'regime_output',
        'hour_ts_utc',
        'asset_id',
        8,
        chunk_time_interval => INTERVAL '14 days',
        if_not_exists => TRUE
    );
    """,
    """
    SELECT create_hypertable(
        'model_prediction',
        'hour_ts_utc',
        'asset_id',
        8,
        chunk_time_interval => INTERVAL '14 days',
        if_not_exists => TRUE
    );
    """,
    """
    SELECT create_hypertable(
        'meta_learner_component',
        'hour_ts_utc',
        'asset_id',
        8,
        chunk_time_interval => INTERVAL '14 days',
        if_not_exists => TRUE
    );
    """,
    """
    SELECT create_hypertable(
        'position_hourly_state',
        'hour_ts_utc',
        'account_id',
        4,
        chunk_time_interval => INTERVAL '30 days',
        if_not_exists => TRUE
    );
    """,
    """
    SELECT create_hypertable(
        'portfolio_hourly_state',
        'hour_ts_utc',
        'account_id',
        4,
        chunk_time_interval => INTERVAL '30 days',
        if_not_exists => TRUE
    );
    """,
    """
    SELECT create_hypertable(
        'risk_hourly_state',
        'hour_ts_utc',
        'account_id',
        4,
        chunk_time_interval => INTERVAL '30 days',
        if_not_exists => TRUE
    );
    """,
)

TIMESCALE_COMPRESSION_DDL: tuple[str, ...] = (
    """
    ALTER TABLE market_ohlcv_hourly
    SET (timescaledb.compress, timescaledb.compress_segmentby = 'asset_id,source_venue', timescaledb.compress_orderby = 'hour_ts_utc DESC');
    """,
    "SELECT add_compression_policy('market_ohlcv_hourly', INTERVAL '14 days', if_not_exists => TRUE);",
    """
    ALTER TABLE order_book_snapshot
    SET (timescaledb.compress, timescaledb.compress_segmentby = 'asset_id,source_venue', timescaledb.compress_orderby = 'snapshot_ts_utc DESC');
    """,
    "SELECT add_compression_policy('order_book_snapshot', INTERVAL '7 days', if_not_exists => TRUE);",
    """
    ALTER TABLE feature_snapshot
    SET (timescaledb.compress, timescaledb.compress_segmentby = 'asset_id,feature_id,run_mode', timescaledb.compress_orderby = 'hour_ts_utc DESC');
    """,
    "SELECT add_compression_policy('feature_snapshot', INTERVAL '14 days', if_not_exists => TRUE);",
    """
    ALTER TABLE model_prediction
    SET (timescaledb.compress, timescaledb.compress_segmentby = 'asset_id,horizon,run_mode,model_role', timescaledb.compress_orderby = 'hour_ts_utc DESC');
    """,
    "SELECT add_compression_policy('model_prediction', INTERVAL '14 days', if_not_exists => TRUE);",
    """
    ALTER TABLE meta_learner_component
    SET (timescaledb.compress, timescaledb.compress_segmentby = 'asset_id,horizon,run_mode', timescaledb.compress_orderby = 'hour_ts_utc DESC');
    """,
    "SELECT add_compression_policy('meta_learner_component', INTERVAL '14 days', if_not_exists => TRUE);",
    """
    ALTER TABLE position_hourly_state
    SET (timescaledb.compress, timescaledb.compress_segmentby = 'account_id,asset_id,run_mode', timescaledb.compress_orderby = 'hour_ts_utc DESC');
    """,
    "SELECT add_compression_policy('position_hourly_state', INTERVAL '30 days', if_not_exists => TRUE);",
    """
    ALTER TABLE portfolio_hourly_state
    SET (timescaledb.compress, timescaledb.compress_segmentby = 'account_id,run_mode', timescaledb.compress_orderby = 'hour_ts_utc DESC');
    """,
    "SELECT add_compression_policy('portfolio_hourly_state', INTERVAL '30 days', if_not_exists => TRUE);",
    """
    ALTER TABLE risk_hourly_state
    SET (timescaledb.compress, timescaledb.compress_segmentby = 'account_id,run_mode,drawdown_tier', timescaledb.compress_orderby = 'hour_ts_utc DESC');
    """,
    "SELECT add_compression_policy('risk_hourly_state', INTERVAL '30 days', if_not_exists => TRUE);",
)

APPEND_ONLY_DDL: tuple[str, ...] = (
    """
    CREATE OR REPLACE FUNCTION fn_enforce_append_only()
    RETURNS TRIGGER
    LANGUAGE plpgsql
    AS $$
    BEGIN
        RAISE EXCEPTION 'append-only violation on table %, operation % is not allowed', TG_TABLE_NAME, TG_OP;
    END;
    $$;
    """,
    """
    CREATE TRIGGER trg_market_ohlcv_hourly_append_only
    BEFORE UPDATE OR DELETE ON market_ohlcv_hourly
    FOR EACH ROW EXECUTE FUNCTION fn_enforce_append_only();
    """,
    """
    CREATE TRIGGER trg_order_book_snapshot_append_only
    BEFORE UPDATE OR DELETE ON order_book_snapshot
    FOR EACH ROW EXECUTE FUNCTION fn_enforce_append_only();
    """,
    """
    CREATE TRIGGER trg_feature_snapshot_append_only
    BEFORE UPDATE OR DELETE ON feature_snapshot
    FOR EACH ROW EXECUTE FUNCTION fn_enforce_append_only();
    """,
    """
    CREATE TRIGGER trg_regime_output_append_only
    BEFORE UPDATE OR DELETE ON regime_output
    FOR EACH ROW EXECUTE FUNCTION fn_enforce_append_only();
    """,
    """
    CREATE TRIGGER trg_model_prediction_append_only
    BEFORE UPDATE OR DELETE ON model_prediction
    FOR EACH ROW EXECUTE FUNCTION fn_enforce_append_only();
    """,
    """
    CREATE TRIGGER trg_meta_learner_component_append_only
    BEFORE UPDATE OR DELETE ON meta_learner_component
    FOR EACH ROW EXECUTE FUNCTION fn_enforce_append_only();
    """,
    """
    CREATE TRIGGER trg_trade_signal_append_only
    BEFORE UPDATE OR DELETE ON trade_signal
    FOR EACH ROW EXECUTE FUNCTION fn_enforce_append_only();
    """,
    """
    CREATE TRIGGER trg_order_fill_append_only
    BEFORE UPDATE OR DELETE ON order_fill
    FOR EACH ROW EXECUTE FUNCTION fn_enforce_append_only();
    """,
    """
    CREATE TRIGGER trg_executed_trade_append_only
    BEFORE UPDATE OR DELETE ON executed_trade
    FOR EACH ROW EXECUTE FUNCTION fn_enforce_append_only();
    """,
    """
    CREATE TRIGGER trg_cash_ledger_append_only
    BEFORE UPDATE OR DELETE ON cash_ledger
    FOR EACH ROW EXECUTE FUNCTION fn_enforce_append_only();
    """,
    """
    CREATE TRIGGER trg_risk_event_append_only
    BEFORE UPDATE OR DELETE ON risk_event
    FOR EACH ROW EXECUTE FUNCTION fn_enforce_append_only();
    """,
    """
    CREATE TRIGGER trg_backtest_fold_result_append_only
    BEFORE UPDATE OR DELETE ON backtest_fold_result
    FOR EACH ROW EXECUTE FUNCTION fn_enforce_append_only();
    """,
)


def _execute_all(statements: Sequence[str]) -> None:
    """Execute an ordered sequence of SQL statements."""

    for statement in statements:
        try:
            op.execute(statement)
        except Exception:
            logger.exception("Migration statement failed.")
            raise


def upgrade() -> None:
    """Apply the initial schema migration."""

    logger.info("Starting initial schema migration upgrade.")
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")
    _execute_all(ENUM_DDL)
    _execute_all(TABLE_DDL)
    _execute_all(INDEX_DDL)
    _execute_all(TIMESCALE_HYPERTABLE_DDL)
    _execute_all(TIMESCALE_COMPRESSION_DDL)
    _execute_all(APPEND_ONLY_DDL)
    logger.info("Completed initial schema migration upgrade.")


def downgrade() -> None:
    """Revert the initial schema migration."""

    logger.info("Starting initial schema migration downgrade.")
    _execute_all(
        (
            "DROP TRIGGER IF EXISTS trg_backtest_fold_result_append_only ON backtest_fold_result;",
            "DROP TRIGGER IF EXISTS trg_risk_event_append_only ON risk_event;",
            "DROP TRIGGER IF EXISTS trg_cash_ledger_append_only ON cash_ledger;",
            "DROP TRIGGER IF EXISTS trg_executed_trade_append_only ON executed_trade;",
            "DROP TRIGGER IF EXISTS trg_order_fill_append_only ON order_fill;",
            "DROP TRIGGER IF EXISTS trg_trade_signal_append_only ON trade_signal;",
            "DROP TRIGGER IF EXISTS trg_meta_learner_component_append_only ON meta_learner_component;",
            "DROP TRIGGER IF EXISTS trg_model_prediction_append_only ON model_prediction;",
            "DROP TRIGGER IF EXISTS trg_regime_output_append_only ON regime_output;",
            "DROP TRIGGER IF EXISTS trg_feature_snapshot_append_only ON feature_snapshot;",
            "DROP TRIGGER IF EXISTS trg_order_book_snapshot_append_only ON order_book_snapshot;",
            "DROP TRIGGER IF EXISTS trg_market_ohlcv_hourly_append_only ON market_ohlcv_hourly;",
            "DROP FUNCTION IF EXISTS fn_enforce_append_only();",
            "SELECT remove_compression_policy('risk_hourly_state', if_exists => TRUE);",
            "SELECT remove_compression_policy('portfolio_hourly_state', if_exists => TRUE);",
            "SELECT remove_compression_policy('position_hourly_state', if_exists => TRUE);",
            "SELECT remove_compression_policy('meta_learner_component', if_exists => TRUE);",
            "SELECT remove_compression_policy('model_prediction', if_exists => TRUE);",
            "SELECT remove_compression_policy('feature_snapshot', if_exists => TRUE);",
            "SELECT remove_compression_policy('order_book_snapshot', if_exists => TRUE);",
            "SELECT remove_compression_policy('market_ohlcv_hourly', if_exists => TRUE);",
            "DROP TABLE IF EXISTS backtest_fold_result;",
            "DROP TABLE IF EXISTS risk_event;",
            "DROP TABLE IF EXISTS position_hourly_state;",
            "DROP TABLE IF EXISTS cash_ledger;",
            "DROP TABLE IF EXISTS executed_trade;",
            "DROP TABLE IF EXISTS position_lot;",
            "DROP TABLE IF EXISTS order_fill;",
            "DROP TABLE IF EXISTS order_request;",
            "DROP TABLE IF EXISTS trade_signal;",
            "DROP TABLE IF EXISTS risk_hourly_state;",
            "DROP TABLE IF EXISTS portfolio_hourly_state;",
            "DROP TABLE IF EXISTS meta_learner_component;",
            "DROP TABLE IF EXISTS model_prediction;",
            "DROP TABLE IF EXISTS regime_output;",
            "DROP TABLE IF EXISTS feature_snapshot;",
            "DROP TABLE IF EXISTS order_book_snapshot;",
            "DROP TABLE IF EXISTS market_ohlcv_hourly;",
            "DROP TABLE IF EXISTS model_training_window;",
            "DROP TABLE IF EXISTS run_context;",
            "DROP TABLE IF EXISTS backtest_run;",
            "DROP TABLE IF EXISTS feature_definition;",
            "DROP TABLE IF EXISTS model_version;",
            "DROP TABLE IF EXISTS cost_profile;",
            "DROP TABLE IF EXISTS account;",
            "DROP TABLE IF EXISTS asset;",
            "DROP TYPE IF EXISTS drawdown_tier_enum;",
            "DROP TYPE IF EXISTS order_status_enum;",
            "DROP TYPE IF EXISTS order_type_enum;",
            "DROP TYPE IF EXISTS order_side_enum;",
            "DROP TYPE IF EXISTS signal_action_enum;",
            "DROP TYPE IF EXISTS model_role_enum;",
            "DROP TYPE IF EXISTS horizon_enum;",
            "DROP TYPE IF EXISTS run_mode_enum;",
        )
    )
    logger.info("Completed initial schema migration downgrade.")
