"""Runtime DB adapter and fixture loaders for integration tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import re
from typing import Any, Mapping, Optional, Sequence
from uuid import UUID, uuid5, NAMESPACE_URL

from psycopg import Connection
from psycopg.rows import dict_row


_NAMED_PARAM_RE = re.compile(r"(?<!:):([a-zA-Z_][a-zA-Z0-9_]*)")


def _convert_named_params(sql: str) -> str:
    """Convert :named params to psycopg %(named)s format."""
    return _NAMED_PARAM_RE.sub(r"%(\1)s", sql)


class PsycopgRuntimeDB:
    """Adapter implementing execution runtime read/write protocol on psycopg."""

    def __init__(self, conn: Connection[Any]) -> None:
        self.conn = conn
        self._tx_started = False

    def begin(self) -> None:
        if self._tx_started:
            return
        with self.conn.cursor() as cur:
            cur.execute("BEGIN")
        self._tx_started = True

    def commit(self) -> None:
        self.conn.commit()
        self._tx_started = False

    def rollback(self) -> None:
        self.conn.rollback()
        self._tx_started = False

    def fetch_one(self, sql: str, params: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
        rows = self.fetch_all(sql, params)
        return rows[0] if rows else None

    def fetch_all(self, sql: str, params: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        converted = _convert_named_params(sql)
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(converted, dict(params))
            return [dict(row) for row in cur.fetchall()]

    def execute(self, sql: str, params: Mapping[str, Any]) -> None:
        converted = _convert_named_params(sql)
        with self.conn.cursor() as cur:
            cur.execute(converted, dict(params))


def deterministic_uuid(seed: str) -> UUID:
    """Generate deterministic UUID for test fixtures."""
    return uuid5(NAMESPACE_URL, f"phase-test::{seed}")


def _align_hour_with_cost_profile_window(
    hour: datetime,
    effective_from_utc: datetime,
    effective_to_utc: Optional[datetime],
) -> datetime:
    """Return an hour-aligned timestamp that falls within a cost-profile window."""
    if hour < effective_from_utc:
        aligned = effective_from_utc.replace(minute=0, second=0, microsecond=0)
        if aligned < effective_from_utc:
            aligned += timedelta(hours=1)
        hour = aligned
    if effective_to_utc is not None and hour >= effective_to_utc:
        candidate = (effective_to_utc - timedelta(hours=1)).replace(
            minute=0,
            second=0,
            microsecond=0,
        )
        if candidate < effective_from_utc:
            raise RuntimeError("No hour-aligned timestamp fits active KRAKEN cost_profile window.")
        hour = candidate
    return hour


@dataclass(frozen=True)
class FixtureIds:
    run_id: UUID
    account_id: int
    asset_id: int
    model_version_id: int
    cluster_membership_id: int
    hour_ts_utc: datetime


@dataclass(frozen=True)
class PreloadedLotIds:
    signal_id: UUID
    order_id: UUID
    fill_id: UUID
    lot_id: UUID


def insert_runtime_fixture(
    db: PsycopgRuntimeDB,
    *,
    seed: str,
    run_mode: str = "LIVE",
    activation_status: str = "APPROVED",
    activation_window_end_utc: Optional[datetime] = None,
    halt_new_entries: bool = False,
    kill_switch_active: bool = False,
    cluster_exposure_pct: Decimal = Decimal("0.0100000000"),
    cluster_parent_hash: str = "r" * 64,
    risk_row_hash: str = "r" * 64,
    prediction_row_hash: str = "5" * 64,
    expected_return: Decimal = Decimal("0.020000000000000000"),
    order_book_best_bid_price: Decimal = Decimal("99.000000000000000000"),
    order_book_best_ask_price: Decimal = Decimal("100.000000000000000000"),
    order_book_best_bid_size: Decimal = Decimal("1000000.000000000000000000"),
    order_book_best_ask_size: Decimal = Decimal("1000000.000000000000000000"),
    ohlcv_close_price: Decimal = Decimal("100.000000000000000000"),
) -> FixtureIds:
    """
    Insert deterministic minimal fixture rows required by Phase 1D runtime.

    The inserted data is deterministic and self-contained for one run/account/hour.
    """
    run_id = deterministic_uuid(f"run-{seed}")
    backtest_run_id = deterministic_uuid(f"backtest-{seed}")
    hour_offset = deterministic_uuid(f"hour-{seed}").int % 5000
    hour = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc) + timedelta(hours=hour_offset)
    seed_suffix = deterministic_uuid(f"suffix-{seed}").hex[:8].upper()

    account_code = f"ACC_{seed.upper()}"
    asset_symbol = f"AS{seed_suffix}"
    model_name = f"META_{seed.upper()}"
    model_label = f"v_{seed}"

    account_row = db.fetch_one(
        """
        INSERT INTO account (account_code, base_currency, is_active)
        VALUES (:account_code, 'USD', TRUE)
        RETURNING account_id
        """,
        {"account_code": account_code},
    )
    if account_row is None:
        raise RuntimeError("Failed to insert account fixture.")
    account_id = int(account_row["account_id"])

    asset_row = db.fetch_one(
        """
        INSERT INTO asset (
            venue, symbol, base_asset, quote_asset, tick_size, lot_size,
            is_active, listed_at_utc
        ) VALUES (
            'KRAKEN', :symbol, :base_asset, 'USD', 0.000000010000000000,
            0.000000010000000000, TRUE, :listed_at_utc
        )
        RETURNING asset_id
        """,
        {
            "symbol": asset_symbol,
            "base_asset": asset_symbol,
            "listed_at_utc": hour - timedelta(days=365),
        },
    )
    if asset_row is None:
        raise RuntimeError("Failed to insert asset fixture.")
    asset_id = int(asset_row["asset_id"])

    cost_profile_row = db.fetch_one(
        """
        SELECT cost_profile_id
        FROM cost_profile
        WHERE venue = 'KRAKEN'
          AND is_active = TRUE
          AND effective_from_utc <= :hour_ts_utc
          AND (effective_to_utc IS NULL OR effective_to_utc > :hour_ts_utc)
        ORDER BY effective_from_utc DESC, cost_profile_id DESC
        LIMIT 1
        """,
        {"hour_ts_utc": hour},
    )
    if cost_profile_row is None:
        existing_active_row = db.fetch_one(
            """
            SELECT cost_profile_id, effective_from_utc, effective_to_utc
            FROM cost_profile
            WHERE venue = 'KRAKEN'
              AND is_active = TRUE
            ORDER BY effective_from_utc DESC, cost_profile_id DESC
            LIMIT 1
            """,
            {},
        )
        if existing_active_row is not None:
            hour = _align_hour_with_cost_profile_window(
                hour=hour,
                effective_from_utc=existing_active_row["effective_from_utc"],
                effective_to_utc=existing_active_row["effective_to_utc"],
            )
            cost_profile_row = {"cost_profile_id": int(existing_active_row["cost_profile_id"])}
        else:
            cost_profile_row = db.fetch_one(
                """
                INSERT INTO cost_profile (
                    venue, fee_rate, slippage_model_name, slippage_param_hash,
                    effective_from_utc, effective_to_utc, is_active
                ) VALUES (
                    'KRAKEN', 0.004000, 'DET_TEST', :slippage_param_hash,
                    :effective_from_utc, NULL, TRUE
                )
                RETURNING cost_profile_id
                """,
                {
                    "slippage_param_hash": "a" * 64,
                    "effective_from_utc": hour - timedelta(days=30),
                },
            )
        if cost_profile_row is None:
            raise RuntimeError("Failed to resolve active cost profile fixture.")
    cost_profile_id = int(cost_profile_row["cost_profile_id"])

    db.execute(
        """
        INSERT INTO backtest_run (
            backtest_run_id, account_id, started_at_utc, completed_at_utc, status,
            strategy_code_sha, config_hash, universe_hash, initial_capital,
            cost_profile_id, random_seed, row_hash
        ) VALUES (
            :backtest_run_id, :account_id, :started_at_utc, :completed_at_utc, 'COMPLETED',
            :strategy_code_sha, :config_hash, :universe_hash, 10000.000000000000000000,
            :cost_profile_id, 7, :row_hash
        )
        """,
        {
            "backtest_run_id": str(backtest_run_id),
            "account_id": account_id,
            "started_at_utc": hour - timedelta(days=7),
            "completed_at_utc": hour - timedelta(days=6),
            "strategy_code_sha": "1" * 40,
            "config_hash": "2" * 64,
            "universe_hash": "3" * 64,
            "cost_profile_id": cost_profile_id,
            "row_hash": "4" * 64,
        },
    )

    model_row = db.fetch_one(
        """
        INSERT INTO model_version (
            model_name, model_role, version_label, mlflow_model_uri, mlflow_run_id,
            feature_set_version, hyperparams_hash, training_data_hash, is_active
        ) VALUES (
            :model_name, 'META', :version_label, :model_uri, :run_id,
            'feature_v1', :hyperparams_hash, :training_data_hash, TRUE
        )
        RETURNING model_version_id
        """,
        {
            "model_name": model_name,
            "version_label": model_label,
            "model_uri": f"models:/{model_name}/{model_label}",
            "run_id": f"mlflow-{seed}",
            "hyperparams_hash": "5" * 64,
            "training_data_hash": "6" * 64,
        },
    )
    if model_row is None:
        raise RuntimeError("Failed to insert model_version fixture.")
    model_version_id = int(model_row["model_version_id"])

    db.execute(
        """
        INSERT INTO run_context (
            run_id, account_id, run_mode, hour_ts_utc, cycle_seq, code_version_sha,
            config_hash, data_snapshot_hash, random_seed, backtest_run_id,
            started_at_utc, completed_at_utc, status, origin_hour_ts_utc,
            run_seed_hash, context_hash, replay_root_hash
        ) VALUES (
            :run_id, :account_id, :run_mode, :hour_ts_utc, 1, :code_version_sha,
            :config_hash, :data_snapshot_hash, 7, NULL,
            :started_at_utc, :completed_at_utc, 'COMPLETED', :origin_hour_ts_utc,
            :run_seed_hash, :context_hash, :replay_root_hash
        )
        """,
        {
            "run_id": str(run_id),
            "account_id": account_id,
            "run_mode": run_mode,
            "hour_ts_utc": hour,
            "code_version_sha": "a" * 40,
            "config_hash": "b" * 64,
            "data_snapshot_hash": "c" * 64,
            "started_at_utc": hour - timedelta(minutes=5),
            "completed_at_utc": hour,
            "origin_hour_ts_utc": hour,
            "run_seed_hash": "d" * 64,
            "context_hash": "e" * 64,
            "replay_root_hash": "f" * 64,
        },
    )

    feature_definition_row = db.fetch_one(
        """
        INSERT INTO feature_definition (
            feature_name, feature_group, lookback_hours, value_dtype, feature_version
        ) VALUES (
            :feature_name, 'RISK_VOLATILITY', 24, 'NUMERIC', 'phase3_v1'
        )
        RETURNING feature_id
        """,
        {"feature_name": f"REALIZED_VOL_{seed.upper()}"},
    )
    if feature_definition_row is None:
        raise RuntimeError("Failed to insert feature_definition fixture.")
    volatility_feature_id = int(feature_definition_row["feature_id"])

    profile_version = f"profile_{seed.lower()}"
    db.execute(
        """
        INSERT INTO risk_profile (
            profile_version, total_exposure_mode, max_total_exposure_pct, max_total_exposure_amount,
            cluster_exposure_mode, max_cluster_exposure_pct, max_cluster_exposure_amount,
            max_concurrent_positions, severe_loss_drawdown_trigger, volatility_feature_id,
            volatility_target, volatility_scale_floor, volatility_scale_ceiling,
            hold_min_expected_return, exit_expected_return_threshold,
            recovery_hold_prob_up_threshold, recovery_exit_prob_up_threshold,
            derisk_fraction, signal_persistence_required, row_hash
        ) VALUES (
            :profile_version, 'PERCENT_OF_PV', 0.2000000000, NULL,
            'PERCENT_OF_PV', 0.0800000000, NULL,
            10, 0.2000000000, :volatility_feature_id,
            0.0200000000, 0.5000000000, 1.5000000000,
            0.000000000000000000, -0.005000000000000000,
            0.6000000000, 0.3500000000,
            0.5000000000, 1, :row_hash
        )
        """,
        {
            "profile_version": profile_version,
            "volatility_feature_id": volatility_feature_id,
            "row_hash": "z" * 64,
        },
    )
    db.execute(
        """
        INSERT INTO account_risk_profile_assignment (
            account_id, profile_version, effective_from_utc, effective_to_utc, row_hash
        ) VALUES (
            :account_id, :profile_version, :effective_from_utc, NULL, :row_hash
        )
        """,
        {
            "account_id": account_id,
            "profile_version": profile_version,
            "effective_from_utc": hour - timedelta(days=1),
            "row_hash": "y" * 64,
        },
    )

    db.execute(
        """
        INSERT INTO replay_manifest (
            run_id, account_id, run_mode, origin_hour_ts_utc,
            run_seed_hash, replay_root_hash, authoritative_row_count, generated_at_utc
        ) VALUES (
            :run_id, :account_id, :run_mode, :origin_hour_ts_utc,
            :run_seed_hash, :replay_root_hash, :authoritative_row_count, :generated_at_utc
        )
        """,
        {
            "run_id": str(run_id),
            "account_id": account_id,
            "run_mode": run_mode,
            "origin_hour_ts_utc": hour,
            "run_seed_hash": "d" * 64,
            "replay_root_hash": "f" * 64,
            "authoritative_row_count": 0,
            "generated_at_utc": hour,
        },
    )

    db.execute(
        """
        INSERT INTO portfolio_hourly_state (
            run_mode, account_id, hour_ts_utc, cash_balance, market_value, portfolio_value,
            peak_portfolio_value, drawdown_pct, total_exposure_pct, open_position_count,
            halted, source_run_id, reconciliation_hash, row_hash
        ) VALUES (
            :run_mode, :account_id, :hour_ts_utc, 10000.000000000000000000,
            0.000000000000000000, 10000.000000000000000000, 10000.000000000000000000,
            0.0000000000, 0.0100000000, 1, FALSE, :source_run_id, :reconciliation_hash, :row_hash
        )
        """,
        {
            "run_mode": run_mode,
            "account_id": account_id,
            "hour_ts_utc": hour,
            "source_run_id": str(run_id),
            "reconciliation_hash": "g" * 64,
            "row_hash": "h" * 64,
        },
    )

    db.execute(
        """
        INSERT INTO position_hourly_state (
            run_mode, account_id, asset_id, hour_ts_utc, quantity, avg_cost, mark_price,
            market_value, unrealized_pnl, realized_pnl_cum, exposure_pct, source_run_id, row_hash
        ) VALUES (
            :run_mode, :account_id, :asset_id, :hour_ts_utc, 1.000000000000000000, 100.000000000000000000,
            100.000000000000000000, 100.000000000000000000, 0.000000000000000000,
            0.000000000000000000, 0.0100000000, :source_run_id, :row_hash
        )
        """,
        {
            "run_mode": run_mode,
            "account_id": account_id,
            "asset_id": asset_id,
            "hour_ts_utc": hour,
            "source_run_id": str(run_id),
            "row_hash": "x" * 64,
        },
    )

    db.execute(
        """
        INSERT INTO risk_hourly_state (
            run_mode, account_id, hour_ts_utc, portfolio_value, peak_portfolio_value,
            drawdown_pct, drawdown_tier, base_risk_fraction, max_concurrent_positions,
            max_total_exposure_pct, max_cluster_exposure_pct, halt_new_entries,
            kill_switch_active, kill_switch_reason, requires_manual_review,
            evaluated_at_utc, source_run_id, state_hash, row_hash
        ) VALUES (
            :run_mode, :account_id, :hour_ts_utc, 10000.000000000000000000,
            10000.000000000000000000, 0.0000000000, 'NORMAL', 0.0200000000, 10,
            0.2000000000, 0.0800000000, :halt_new_entries, :kill_switch_active,
            :kill_switch_reason, FALSE, :evaluated_at_utc, :source_run_id, :state_hash, :row_hash
        )
        """,
        {
            "run_mode": run_mode,
            "account_id": account_id,
            "hour_ts_utc": hour,
            "halt_new_entries": halt_new_entries,
            "kill_switch_active": kill_switch_active,
            "kill_switch_reason": "TEST_KILL" if kill_switch_active else None,
            "evaluated_at_utc": hour,
            "source_run_id": str(run_id),
            "state_hash": "i" * 64,
            "row_hash": risk_row_hash,
        },
    )

    cluster_row = db.fetch_one(
        """
        INSERT INTO correlation_cluster (cluster_code, description, is_active)
        VALUES (:cluster_code, :description, TRUE)
        RETURNING cluster_id
        """,
        {
            "cluster_code": f"CL_{seed.upper()}",
            "description": f"Cluster {seed}",
        },
    )
    if cluster_row is None:
        raise RuntimeError("Failed to insert correlation_cluster fixture.")
    cluster_id = int(cluster_row["cluster_id"])

    membership_row = db.fetch_one(
        """
        INSERT INTO asset_cluster_membership (
            asset_id, cluster_id, effective_from_utc, effective_to_utc, membership_hash
        ) VALUES (
            :asset_id, :cluster_id, :effective_from_utc, NULL, :membership_hash
        )
        RETURNING membership_id
        """,
        {
            "asset_id": asset_id,
            "cluster_id": cluster_id,
            "effective_from_utc": hour - timedelta(days=10),
            "membership_hash": "j" * 64,
        },
    )
    if membership_row is None:
        raise RuntimeError("Failed to insert asset_cluster_membership fixture.")
    membership_id = int(membership_row["membership_id"])

    db.execute(
        """
        INSERT INTO cluster_exposure_hourly_state (
            run_mode, account_id, cluster_id, hour_ts_utc, source_run_id,
            gross_exposure_notional, exposure_pct, max_cluster_exposure_pct,
            state_hash, parent_risk_hash, row_hash
        ) VALUES (
            :run_mode, :account_id, :cluster_id, :hour_ts_utc, :source_run_id,
            100.000000000000000000, :exposure_pct, 0.0800000000, :state_hash,
            :parent_risk_hash, :row_hash
        )
        """,
        {
            "run_mode": run_mode,
            "account_id": account_id,
            "cluster_id": cluster_id,
            "hour_ts_utc": hour,
            "source_run_id": str(run_id),
            "exposure_pct": cluster_exposure_pct,
            "state_hash": "k" * 64,
            "parent_risk_hash": cluster_parent_hash,
            "row_hash": "l" * 64,
        },
    )

    activation_row = db.fetch_one(
        """
        INSERT INTO model_activation_gate (
            model_version_id, run_mode, validation_backtest_run_id, validation_window_end_utc,
            approved_at_utc, status, approval_hash
        ) VALUES (
            :model_version_id, :run_mode, :validation_backtest_run_id, :validation_window_end_utc,
            :approved_at_utc, :status, :approval_hash
        )
        RETURNING activation_id
        """,
        {
            "model_version_id": model_version_id,
            "run_mode": run_mode,
            "validation_backtest_run_id": str(backtest_run_id),
            "validation_window_end_utc": activation_window_end_utc or (hour - timedelta(hours=1)),
            "approved_at_utc": hour - timedelta(minutes=10),
            "status": activation_status,
            "approval_hash": "m" * 64,
        },
    )
    if activation_row is None:
        raise RuntimeError("Failed to insert model_activation_gate fixture.")
    activation_id = int(activation_row["activation_id"])

    db.execute(
        """
        INSERT INTO model_prediction (
            run_id, run_mode, asset_id, hour_ts_utc, horizon, model_version_id, model_role,
            prob_up, expected_return, input_feature_hash, upstream_hash, row_hash, account_id,
            training_window_id, lineage_backtest_run_id, lineage_fold_index, lineage_horizon, activation_id
        ) VALUES (
            :run_id, :run_mode, :asset_id, :hour_ts_utc, 'H1', :model_version_id, 'META',
            0.6500000000, :expected_return, :input_feature_hash, :upstream_hash, :row_hash, :account_id,
            NULL, NULL, NULL, NULL, :activation_id
        )
        """,
        {
            "run_id": str(run_id),
            "run_mode": run_mode,
            "asset_id": asset_id,
            "hour_ts_utc": hour,
            "model_version_id": model_version_id,
            "expected_return": expected_return,
            "input_feature_hash": "n" * 64,
            "upstream_hash": "o" * 64,
            "row_hash": prediction_row_hash,
            "account_id": account_id,
            "activation_id": activation_id,
        },
    )

    db.execute(
        """
        INSERT INTO regime_output (
            run_id, run_mode, asset_id, hour_ts_utc, model_version_id, regime_label,
            regime_probability, input_feature_hash, upstream_hash, row_hash, account_id,
            training_window_id, lineage_backtest_run_id, lineage_fold_index, lineage_horizon, activation_id
        ) VALUES (
            :run_id, :run_mode, :asset_id, :hour_ts_utc, :model_version_id, 'TRENDING',
            0.7100000000, :input_feature_hash, :upstream_hash, :row_hash, :account_id,
            NULL, NULL, NULL, NULL, :activation_id
        )
        """,
        {
            "run_id": str(run_id),
            "run_mode": run_mode,
            "asset_id": asset_id,
            "hour_ts_utc": hour,
            "model_version_id": model_version_id,
            "input_feature_hash": "p" * 64,
            "upstream_hash": "q" * 64,
            "row_hash": "1" * 64,
            "account_id": account_id,
            "activation_id": activation_id,
        },
    )

    db.execute(
        """
        INSERT INTO feature_snapshot (
            run_id, run_mode, asset_id, hour_ts_utc, feature_id, feature_value,
            source_window_start_utc, source_window_end_utc, input_data_hash, row_hash
        ) VALUES (
            :run_id, :run_mode, :asset_id, :hour_ts_utc, :feature_id, 0.0200000000,
            :source_window_start_utc, :source_window_end_utc, :input_data_hash, :row_hash
        )
        """,
        {
            "run_id": str(run_id),
            "run_mode": run_mode,
            "asset_id": asset_id,
            "hour_ts_utc": hour,
            "feature_id": volatility_feature_id,
            "source_window_start_utc": hour - timedelta(hours=24),
            "source_window_end_utc": hour,
            "input_data_hash": "w" * 64,
            "row_hash": "v" * 64,
        },
    )

    ingest_run_id = run_id
    db.execute(
        """
        INSERT INTO order_book_snapshot (
            asset_id, snapshot_ts_utc, hour_ts_utc, best_bid_price, best_ask_price,
            best_bid_size, best_ask_size, source_venue, ingest_run_id, row_hash
        ) VALUES (
            :asset_id, :snapshot_ts_utc, :hour_ts_utc, :best_bid_price, :best_ask_price,
            :best_bid_size, :best_ask_size, 'KRAKEN', :ingest_run_id, :row_hash
        )
        """,
        {
            "asset_id": asset_id,
            "snapshot_ts_utc": hour,
            "hour_ts_utc": hour,
            "best_bid_price": order_book_best_bid_price,
            "best_ask_price": order_book_best_ask_price,
            "best_bid_size": order_book_best_bid_size,
            "best_ask_size": order_book_best_ask_size,
            "ingest_run_id": str(ingest_run_id),
            "row_hash": "1" * 64,
        },
    )

    db.execute(
        """
        INSERT INTO market_ohlcv_hourly (
            asset_id, hour_ts_utc, open_price, high_price, low_price, close_price,
            volume_base, volume_quote, trade_count, source_venue, ingest_run_id, row_hash
        ) VALUES (
            :asset_id, :hour_ts_utc, :open_price, :high_price, :low_price, :close_price,
            :volume_base, :volume_quote, :trade_count, 'KRAKEN', :ingest_run_id, :row_hash
        )
        """,
        {
            "asset_id": asset_id,
            "hour_ts_utc": hour,
            "open_price": ohlcv_close_price,
            "high_price": ohlcv_close_price,
            "low_price": ohlcv_close_price,
            "close_price": ohlcv_close_price,
            "volume_base": Decimal("0"),
            "volume_quote": Decimal("0"),
            "trade_count": 0,
            "ingest_run_id": str(ingest_run_id),
            "row_hash": "2" * 64,
        },
    )

    db.conn.commit()

    return FixtureIds(
        run_id=run_id,
        account_id=account_id,
        asset_id=asset_id,
        model_version_id=model_version_id,
        cluster_membership_id=membership_id,
        hour_ts_utc=hour,
    )


def preload_open_lot_for_sell_path(
    db: PsycopgRuntimeDB,
    fixture: FixtureIds,
    *,
    seed: str,
    quantity: Decimal = Decimal("1.000000000000000000"),
    price: Decimal = Decimal("100.000000000000000000"),
) -> PreloadedLotIds:
    """Insert deterministic BUY signal/order/fill/lot rows for SELL-path integration tests."""
    signal_id = deterministic_uuid(f"preload-signal-{seed}")
    order_id = deterministic_uuid(f"preload-order-{seed}")
    fill_id = deterministic_uuid(f"preload-fill-{seed}")
    lot_id = deterministic_uuid(f"preload-lot-{seed}")

    row_hash_signal = "3" * 64
    row_hash_order = "4" * 64
    row_hash_fill = "5" * 64
    row_hash_lot = "6" * 64

    notional = quantity * price
    fee_rate = Decimal("0.004000")
    slippage_rate = Decimal("0.000170")
    fee_paid = notional * fee_rate
    slippage_cost = notional * slippage_rate

    cost_profile_row = db.fetch_one(
        """
        SELECT cost_profile_id
        FROM cost_profile
        WHERE venue = 'KRAKEN'
          AND is_active = TRUE
          AND effective_from_utc <= :hour_ts_utc
          AND (effective_to_utc IS NULL OR effective_to_utc > :hour_ts_utc)
        ORDER BY effective_from_utc DESC, cost_profile_id DESC
        LIMIT 1
        """,
        {"hour_ts_utc": fixture.hour_ts_utc},
    )
    if cost_profile_row is None:
        raise RuntimeError("No active cost_profile found for lot preloading.")
    cost_profile_id = int(cost_profile_row["cost_profile_id"])

    db.execute(
        """
        INSERT INTO trade_signal (
            signal_id, run_id, run_mode, account_id, asset_id, hour_ts_utc, horizon,
            action, direction, confidence, expected_return, assumed_fee_rate,
            assumed_slippage_rate, net_edge, target_position_notional, position_size_fraction,
            risk_state_hour_ts_utc, decision_hash, risk_state_run_id, cluster_membership_id,
            upstream_hash, row_hash
        ) VALUES (
            :signal_id, :run_id, 'LIVE', :account_id, :asset_id, :hour_ts_utc, 'H4',
            'ENTER', 'LONG', 0.5000000000, 0.010000000000000000, :assumed_fee_rate,
            :assumed_slippage_rate, 0.005830000000000000, :target_position_notional, 0.0100000000,
            :risk_state_hour_ts_utc, :decision_hash, :risk_state_run_id, :cluster_membership_id,
            :upstream_hash, :row_hash
        )
        """,
        {
            "signal_id": str(signal_id),
            "run_id": str(fixture.run_id),
            "account_id": fixture.account_id,
            "asset_id": fixture.asset_id,
            "hour_ts_utc": fixture.hour_ts_utc,
            "assumed_fee_rate": fee_rate,
            "assumed_slippage_rate": slippage_rate,
            "target_position_notional": notional,
            "risk_state_hour_ts_utc": fixture.hour_ts_utc,
            "decision_hash": "7" * 64,
            "risk_state_run_id": str(fixture.run_id),
            "cluster_membership_id": fixture.cluster_membership_id,
            "upstream_hash": "8" * 64,
            "row_hash": row_hash_signal,
        },
    )

    db.execute(
        """
        INSERT INTO order_request (
            order_id, signal_id, run_id, run_mode, account_id, asset_id, client_order_id,
            request_ts_utc, hour_ts_utc, side, order_type, tif, limit_price, requested_qty,
            requested_notional, pre_order_cash_available, risk_check_passed, status,
            cost_profile_id, origin_hour_ts_utc, risk_state_run_id, cluster_membership_id,
            parent_signal_hash, row_hash
        ) VALUES (
            :order_id, :signal_id, :run_id, 'LIVE', :account_id, :asset_id, :client_order_id,
            :request_ts_utc, :hour_ts_utc, 'BUY', 'MARKET', 'IOC', NULL, :requested_qty,
            :requested_notional, 10000.000000000000000000, TRUE, 'FILLED',
            :cost_profile_id, :origin_hour_ts_utc, :risk_state_run_id, :cluster_membership_id,
            :parent_signal_hash, :row_hash
        )
        """,
        {
            "order_id": str(order_id),
            "signal_id": str(signal_id),
            "run_id": str(fixture.run_id),
            "account_id": fixture.account_id,
            "asset_id": fixture.asset_id,
            "client_order_id": f"preload-{order_id.hex[:16]}",
            "request_ts_utc": fixture.hour_ts_utc,
            "hour_ts_utc": fixture.hour_ts_utc,
            "requested_qty": quantity,
            "requested_notional": notional,
            "cost_profile_id": cost_profile_id,
            "origin_hour_ts_utc": fixture.hour_ts_utc,
            "risk_state_run_id": str(fixture.run_id),
            "cluster_membership_id": fixture.cluster_membership_id,
            "parent_signal_hash": row_hash_signal,
            "row_hash": row_hash_order,
        },
    )

    db.execute(
        """
        INSERT INTO order_fill (
            fill_id, order_id, run_id, run_mode, account_id, asset_id, exchange_trade_id,
            fill_ts_utc, hour_ts_utc, fill_price, fill_qty, fill_notional, fee_paid,
            fee_rate, realized_slippage_rate, origin_hour_ts_utc, slippage_cost,
            parent_order_hash, row_hash, liquidity_flag
        ) VALUES (
            :fill_id, :order_id, :run_id, 'LIVE', :account_id, :asset_id, :exchange_trade_id,
            :fill_ts_utc, :hour_ts_utc, :fill_price, :fill_qty, :fill_notional, :fee_paid,
            :fee_rate, :realized_slippage_rate, :origin_hour_ts_utc, :slippage_cost,
            :parent_order_hash, :row_hash, 'TAKER'
        )
        """,
        {
            "fill_id": str(fill_id),
            "order_id": str(order_id),
            "run_id": str(fixture.run_id),
            "account_id": fixture.account_id,
            "asset_id": fixture.asset_id,
            "exchange_trade_id": f"preload-{fill_id.hex[:20]}",
            "fill_ts_utc": fixture.hour_ts_utc,
            "hour_ts_utc": fixture.hour_ts_utc,
            "fill_price": price,
            "fill_qty": quantity,
            "fill_notional": notional,
            "fee_paid": fee_paid,
            "fee_rate": fee_rate,
            "realized_slippage_rate": slippage_rate,
            "origin_hour_ts_utc": fixture.hour_ts_utc,
            "slippage_cost": slippage_cost,
            "parent_order_hash": row_hash_order,
            "row_hash": row_hash_fill,
        },
    )

    db.execute(
        """
        INSERT INTO position_lot (
            lot_id, open_fill_id, run_id, run_mode, account_id, asset_id, hour_ts_utc,
            open_ts_utc, open_price, open_qty, open_notional, open_fee, remaining_qty,
            origin_hour_ts_utc, parent_fill_hash, row_hash
        ) VALUES (
            :lot_id, :open_fill_id, :run_id, 'LIVE', :account_id, :asset_id, :hour_ts_utc,
            :open_ts_utc, :open_price, :open_qty, :open_notional, :open_fee, :remaining_qty,
            :origin_hour_ts_utc, :parent_fill_hash, :row_hash
        )
        """,
        {
            "lot_id": str(lot_id),
            "open_fill_id": str(fill_id),
            "run_id": str(fixture.run_id),
            "account_id": fixture.account_id,
            "asset_id": fixture.asset_id,
            "hour_ts_utc": fixture.hour_ts_utc,
            "open_ts_utc": fixture.hour_ts_utc,
            "open_price": price,
            "open_qty": quantity,
            "open_notional": notional,
            "open_fee": fee_paid,
            "remaining_qty": quantity,
            "origin_hour_ts_utc": fixture.hour_ts_utc,
            "parent_fill_hash": row_hash_fill,
            "row_hash": row_hash_lot,
        },
    )

    risk_state_row = db.fetch_one(
        """
        SELECT row_hash
        FROM risk_hourly_state
        WHERE run_mode = 'LIVE'
          AND account_id = :account_id
          AND hour_ts_utc = :hour_ts_utc
          AND source_run_id = :source_run_id
        """,
        {
            "account_id": fixture.account_id,
            "hour_ts_utc": fixture.hour_ts_utc,
            "source_run_id": str(fixture.run_id),
        },
    )
    if risk_state_row is None:
        raise RuntimeError("Missing risk_hourly_state row for preloaded lot decision trace.")

    risk_event_id = deterministic_uuid(f"preload-trace-{seed}")
    db.execute(
        """
        INSERT INTO risk_event (
            risk_event_id, run_id, run_mode, account_id, event_ts_utc, hour_ts_utc,
            event_type, severity, reason_code, details, related_state_hour_ts_utc,
            origin_hour_ts_utc, parent_state_hash, row_hash
        ) VALUES (
            :risk_event_id, :run_id, 'LIVE', :account_id, :event_ts_utc, :hour_ts_utc,
            'DECISION_TRACE', 'LOW', 'VOLATILITY_SIZED', CAST(:details AS jsonb),
            :related_state_hour_ts_utc, :origin_hour_ts_utc, :parent_state_hash, :row_hash
        )
        """,
        {
            "risk_event_id": str(risk_event_id),
            "run_id": str(fixture.run_id),
            "account_id": fixture.account_id,
            "event_ts_utc": fixture.hour_ts_utc,
            "hour_ts_utc": fixture.hour_ts_utc,
            "details": '{"detail":"preloaded decision trace"}',
            "related_state_hour_ts_utc": fixture.hour_ts_utc,
            "origin_hour_ts_utc": fixture.hour_ts_utc,
            "parent_state_hash": str(risk_state_row["row_hash"]),
            "row_hash": "7" * 64,
        },
    )

    db.conn.commit()
    return PreloadedLotIds(
        signal_id=signal_id,
        order_id=order_id,
        fill_id=fill_id,
        lot_id=lot_id,
    )
