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


@dataclass(frozen=True)
class FixtureIds:
    run_id: UUID
    account_id: int
    asset_id: int
    model_version_id: int
    cluster_membership_id: int
    hour_ts_utc: datetime


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
        ORDER BY effective_from_utc DESC, cost_profile_id DESC
        LIMIT 1
        """,
        {},
    )
    if cost_profile_row is None:
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
            raise RuntimeError("Failed to insert cost profile fixture.")
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

    db.conn.commit()

    return FixtureIds(
        run_id=run_id,
        account_id=account_id,
        asset_id=asset_id,
        model_version_id=model_version_id,
        cluster_membership_id=membership_id,
        hour_ts_utc=hour,
    )
