"""Deterministic execution context constructor for Phase 1D runtime."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping, Optional, Protocol, Sequence
from uuid import UUID

from execution.activation_gate import ActivationRecord


class DeterministicAbortError(RuntimeError):
    """Raised when deterministic runtime preconditions fail."""


class DeterministicDatabase(Protocol):
    """Minimal database protocol required by Phase 1D runtime modules."""

    def fetch_one(
        self,
        sql: str,
        params: Mapping[str, Any],
    ) -> Optional[Mapping[str, Any]]:
        """Fetch one row."""

    def fetch_all(
        self,
        sql: str,
        params: Mapping[str, Any],
    ) -> Sequence[Mapping[str, Any]]:
        """Fetch all rows in deterministic query order."""


def _as_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _as_uuid(value: Any) -> UUID:
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


@dataclass(frozen=True)
class RunContextState:
    run_id: UUID
    account_id: int
    run_mode: str
    hour_ts_utc: datetime
    origin_hour_ts_utc: datetime
    run_seed_hash: str
    context_hash: str
    replay_root_hash: str


@dataclass(frozen=True)
class PredictionState:
    run_id: UUID
    account_id: int
    run_mode: str
    asset_id: int
    hour_ts_utc: datetime
    horizon: str
    model_version_id: int
    expected_return: Decimal
    upstream_hash: str
    row_hash: str
    training_window_id: Optional[int]
    lineage_backtest_run_id: Optional[UUID]
    lineage_fold_index: Optional[int]
    lineage_horizon: Optional[str]
    activation_id: Optional[int]


@dataclass(frozen=True)
class RegimeState:
    run_id: UUID
    account_id: int
    run_mode: str
    asset_id: int
    hour_ts_utc: datetime
    model_version_id: int
    regime_label: str
    upstream_hash: str
    row_hash: str
    training_window_id: Optional[int]
    lineage_backtest_run_id: Optional[UUID]
    lineage_fold_index: Optional[int]
    lineage_horizon: Optional[str]
    activation_id: Optional[int]


@dataclass(frozen=True)
class TrainingWindowState:
    training_window_id: int
    backtest_run_id: UUID
    model_version_id: int
    fold_index: int
    horizon: str
    train_end_utc: datetime
    valid_start_utc: datetime
    valid_end_utc: datetime
    training_window_hash: str
    row_hash: str


@dataclass(frozen=True)
class RiskState:
    run_mode: str
    account_id: int
    hour_ts_utc: datetime
    source_run_id: UUID
    portfolio_value: Decimal
    max_total_exposure_pct: Decimal
    max_cluster_exposure_pct: Decimal
    halt_new_entries: bool
    kill_switch_active: bool
    state_hash: str
    row_hash: str


@dataclass(frozen=True)
class CapitalState:
    run_mode: str
    account_id: int
    hour_ts_utc: datetime
    source_run_id: UUID
    cash_balance: Decimal
    portfolio_value: Decimal
    total_exposure_pct: Decimal
    open_position_count: int
    row_hash: str


@dataclass(frozen=True)
class ClusterState:
    run_mode: str
    account_id: int
    cluster_id: int
    hour_ts_utc: datetime
    source_run_id: UUID
    exposure_pct: Decimal
    max_cluster_exposure_pct: Decimal
    state_hash: str
    parent_risk_hash: str
    row_hash: str


@dataclass(frozen=True)
class PriorEconomicState:
    ledger_seq: int
    balance_before: Decimal
    balance_after: Decimal
    prev_ledger_hash: Optional[str]
    ledger_hash: str
    row_hash: str
    event_ts_utc: datetime


@dataclass(frozen=True)
class CostProfileState:
    cost_profile_id: int
    fee_rate: Decimal
    slippage_param_hash: str


@dataclass(frozen=True)
class ClusterMembershipState:
    membership_id: int
    asset_id: int
    cluster_id: int
    membership_hash: str


@dataclass(frozen=True)
class ExecutionContext:
    """Immutable context used by deterministic runtime execution."""

    run_context: RunContextState
    predictions: tuple[PredictionState, ...]
    regimes: tuple[RegimeState, ...]
    risk_state: RiskState
    capital_state: CapitalState
    cluster_states: tuple[ClusterState, ...]
    prior_economic_state: Optional[PriorEconomicState]
    training_windows: tuple[TrainingWindowState, ...]
    activation_records: tuple[ActivationRecord, ...]
    memberships: tuple[ClusterMembershipState, ...]
    cost_profile: CostProfileState

    def find_training_window(self, training_window_id: int) -> Optional[TrainingWindowState]:
        for window in self.training_windows:
            if window.training_window_id == training_window_id:
                return window
        return None

    def find_activation(self, activation_id: int) -> Optional[ActivationRecord]:
        for activation in self.activation_records:
            if activation.activation_id == activation_id:
                return activation
        return None

    def find_regime(self, asset_id: int, model_version_id: int) -> Optional[RegimeState]:
        for regime in self.regimes:
            if regime.asset_id == asset_id and regime.model_version_id == model_version_id:
                return regime
        return None

    def find_membership(self, asset_id: int) -> Optional[ClusterMembershipState]:
        for membership in self.memberships:
            if membership.asset_id == asset_id:
                return membership
        return None

    def find_cluster_state(self, cluster_id: int) -> Optional[ClusterState]:
        for cluster_state in self.cluster_states:
            if cluster_state.cluster_id == cluster_id:
                return cluster_state
        return None


class DeterministicContextBuilder:
    """Construct and validate deterministic runtime execution context."""

    def __init__(self, db: DeterministicDatabase) -> None:
        self._db = db

    def build_context(
        self,
        run_id: UUID,
        account_id: int,
        run_mode: str,
        hour_ts_utc: datetime,
    ) -> ExecutionContext:
        normalized_mode = run_mode.upper()
        run_ctx = self._load_run_context(run_id, account_id, normalized_mode, hour_ts_utc)
        predictions = self._load_predictions(run_id, account_id, normalized_mode, hour_ts_utc)
        regimes = self._load_regimes(run_id, account_id, normalized_mode, hour_ts_utc)
        risk_state = self._load_risk_state(run_id, account_id, normalized_mode, hour_ts_utc)
        capital_state = self._load_capital_state(run_id, account_id, normalized_mode, hour_ts_utc)
        cluster_states = self._load_cluster_states(run_id, account_id, normalized_mode, hour_ts_utc)
        prior_state = self._load_prior_economic_state(account_id, normalized_mode, hour_ts_utc)
        training_windows = self._load_training_windows(predictions, regimes)
        activations = self._load_activation_records(predictions, regimes)
        memberships = self._load_memberships(predictions, hour_ts_utc)
        cost_profile = self._load_cost_profile(hour_ts_utc)

        context = ExecutionContext(
            run_context=run_ctx,
            predictions=predictions,
            regimes=regimes,
            risk_state=risk_state,
            capital_state=capital_state,
            cluster_states=cluster_states,
            prior_economic_state=prior_state,
            training_windows=training_windows,
            activation_records=activations,
            memberships=memberships,
            cost_profile=cost_profile,
        )
        self._validate_context(context)
        return context

    def _validate_context(self, context: ExecutionContext) -> None:
        if not context.predictions:
            raise DeterministicAbortError("No model_prediction rows available for execution hour.")
        if not context.regimes:
            raise DeterministicAbortError("No regime_output rows available for execution hour.")

        run_id = context.run_context.run_id
        account_id = context.run_context.account_id
        run_mode = context.run_context.run_mode

        if context.risk_state.source_run_id != run_id:
            raise DeterministicAbortError("Risk state source_run_id mismatch.")
        if context.capital_state.source_run_id != run_id:
            raise DeterministicAbortError("Capital state source_run_id mismatch.")

        if context.risk_state.account_id != account_id or context.capital_state.account_id != account_id:
            raise DeterministicAbortError("Cross-account contamination on risk/capital state.")

        for cluster_state in context.cluster_states:
            if cluster_state.account_id != account_id:
                raise DeterministicAbortError("Cross-account contamination in cluster_exposure_hourly_state.")
            if cluster_state.parent_risk_hash != context.risk_state.row_hash:
                raise DeterministicAbortError("Cluster parent_risk_hash lineage mismatch.")

        for prediction in context.predictions:
            if prediction.account_id != account_id or prediction.run_id != run_id:
                raise DeterministicAbortError("Cross-account contamination in model_prediction.")
            if prediction.run_mode != run_mode:
                raise DeterministicAbortError("model_prediction run_mode mismatch.")
            self._validate_prediction_lineage(prediction, context)

        for regime in context.regimes:
            if regime.account_id != account_id or regime.run_id != run_id:
                raise DeterministicAbortError("Cross-account contamination in regime_output.")
            if regime.run_mode != run_mode:
                raise DeterministicAbortError("regime_output run_mode mismatch.")
            self._validate_regime_lineage(regime, context)

        for prediction in context.predictions:
            if context.find_regime(prediction.asset_id, prediction.model_version_id) is None:
                raise DeterministicAbortError(
                    f"Missing regime_output for asset_id={prediction.asset_id} "
                    f"model_version_id={prediction.model_version_id}."
                )
            if context.find_membership(prediction.asset_id) is None:
                raise DeterministicAbortError(
                    f"Missing asset_cluster_membership for asset_id={prediction.asset_id} at hour."
                )

        if context.prior_economic_state is not None and context.prior_economic_state.ledger_seq > 1:
            if not context.prior_economic_state.prev_ledger_hash:
                raise DeterministicAbortError("Prior economic state has broken ledger hash continuity.")

    def _validate_prediction_lineage(self, prediction: PredictionState, context: ExecutionContext) -> None:
        if context.run_context.run_mode == "BACKTEST":
            if prediction.training_window_id is None:
                raise DeterministicAbortError("BACKTEST prediction missing training_window_id.")
            window = context.find_training_window(prediction.training_window_id)
            if window is None:
                raise DeterministicAbortError("BACKTEST prediction training window not found.")
            if prediction.lineage_backtest_run_id != window.backtest_run_id:
                raise DeterministicAbortError("BACKTEST prediction lineage_backtest_run_id mismatch.")
            if prediction.lineage_fold_index != window.fold_index:
                raise DeterministicAbortError("BACKTEST prediction lineage_fold_index mismatch.")
            if prediction.lineage_horizon != window.horizon:
                raise DeterministicAbortError("BACKTEST prediction lineage_horizon mismatch.")
            if prediction.model_version_id != window.model_version_id:
                raise DeterministicAbortError("BACKTEST prediction model_version_id mismatch in lineage.")
            # No-forward-leakage guard.
            if prediction.hour_ts_utc <= window.train_end_utc:
                raise DeterministicAbortError("BACKTEST prediction leaks into training period.")
            if prediction.hour_ts_utc < window.valid_start_utc:
                raise DeterministicAbortError("BACKTEST prediction before validation window.")
            if prediction.hour_ts_utc >= window.valid_end_utc:
                raise DeterministicAbortError("BACKTEST prediction after validation window.")
            if prediction.activation_id is not None:
                raise DeterministicAbortError("BACKTEST prediction must not carry activation_id.")
            return

        if prediction.activation_id is None:
            raise DeterministicAbortError("LIVE/PAPER prediction missing activation_id.")
        activation = context.find_activation(prediction.activation_id)
        if activation is None:
            raise DeterministicAbortError("LIVE/PAPER prediction activation record missing.")
        if activation.status != "APPROVED":
            raise DeterministicAbortError("LIVE/PAPER prediction activation not APPROVED.")
        if activation.model_version_id != prediction.model_version_id:
            raise DeterministicAbortError("LIVE/PAPER prediction activation model_version mismatch.")
        if activation.run_mode != context.run_context.run_mode:
            raise DeterministicAbortError("LIVE/PAPER prediction activation run_mode mismatch.")

    def _validate_regime_lineage(self, regime: RegimeState, context: ExecutionContext) -> None:
        if context.run_context.run_mode == "BACKTEST":
            if regime.training_window_id is None:
                raise DeterministicAbortError("BACKTEST regime_output missing training_window_id.")
            window = context.find_training_window(regime.training_window_id)
            if window is None:
                raise DeterministicAbortError("BACKTEST regime_output training window not found.")
            if regime.lineage_backtest_run_id != window.backtest_run_id:
                raise DeterministicAbortError("BACKTEST regime_output lineage_backtest_run_id mismatch.")
            if regime.lineage_fold_index != window.fold_index:
                raise DeterministicAbortError("BACKTEST regime_output lineage_fold_index mismatch.")
            if regime.lineage_horizon != window.horizon:
                raise DeterministicAbortError("BACKTEST regime_output lineage_horizon mismatch.")
            if regime.model_version_id != window.model_version_id:
                raise DeterministicAbortError("BACKTEST regime_output model_version_id mismatch in lineage.")
            # No-forward-leakage guard.
            if regime.hour_ts_utc <= window.train_end_utc:
                raise DeterministicAbortError("BACKTEST regime_output leaks into training period.")
            if regime.hour_ts_utc < window.valid_start_utc:
                raise DeterministicAbortError("BACKTEST regime_output before validation window.")
            if regime.hour_ts_utc >= window.valid_end_utc:
                raise DeterministicAbortError("BACKTEST regime_output after validation window.")
            if regime.activation_id is not None:
                raise DeterministicAbortError("BACKTEST regime_output must not carry activation_id.")
            return

        if regime.activation_id is None:
            raise DeterministicAbortError("LIVE/PAPER regime_output missing activation_id.")
        activation = context.find_activation(regime.activation_id)
        if activation is None:
            raise DeterministicAbortError("LIVE/PAPER regime_output activation record missing.")
        if activation.status != "APPROVED":
            raise DeterministicAbortError("LIVE/PAPER regime_output activation not APPROVED.")
        if activation.model_version_id != regime.model_version_id:
            raise DeterministicAbortError("LIVE/PAPER regime_output activation model_version mismatch.")
        if activation.run_mode != context.run_context.run_mode:
            raise DeterministicAbortError("LIVE/PAPER regime_output activation run_mode mismatch.")

    def _load_run_context(
        self,
        run_id: UUID,
        account_id: int,
        run_mode: str,
        hour_ts_utc: datetime,
    ) -> RunContextState:
        row = self._db.fetch_one(
            """
            SELECT run_id, account_id, run_mode, hour_ts_utc, origin_hour_ts_utc,
                   run_seed_hash, context_hash, replay_root_hash
            FROM run_context
            WHERE run_id = :run_id
              AND account_id = :account_id
              AND run_mode = :run_mode
              AND origin_hour_ts_utc = :hour_ts_utc
            """,
            {
                "run_id": str(run_id),
                "account_id": account_id,
                "run_mode": run_mode,
                "hour_ts_utc": hour_ts_utc,
            },
        )
        if row is None:
            raise DeterministicAbortError("run_context row not found for deterministic execution key.")
        return RunContextState(
            run_id=_as_uuid(row["run_id"]),
            account_id=int(row["account_id"]),
            run_mode=str(row["run_mode"]),
            hour_ts_utc=_as_datetime(row["hour_ts_utc"]),
            origin_hour_ts_utc=_as_datetime(row["origin_hour_ts_utc"]),
            run_seed_hash=str(row["run_seed_hash"]),
            context_hash=str(row["context_hash"]),
            replay_root_hash=str(row["replay_root_hash"]),
        )

    def _load_predictions(
        self,
        run_id: UUID,
        account_id: int,
        run_mode: str,
        hour_ts_utc: datetime,
    ) -> tuple[PredictionState, ...]:
        rows = self._db.fetch_all(
            """
            SELECT run_id, account_id, run_mode, asset_id, hour_ts_utc, horizon,
                   model_version_id, expected_return, upstream_hash, row_hash,
                   training_window_id, lineage_backtest_run_id, lineage_fold_index,
                   lineage_horizon, activation_id
            FROM model_prediction
            WHERE run_id = :run_id
              AND account_id = :account_id
              AND run_mode = :run_mode
              AND hour_ts_utc = :hour_ts_utc
            ORDER BY asset_id ASC, horizon ASC, model_version_id ASC, row_hash ASC
            """,
            {
                "run_id": str(run_id),
                "account_id": account_id,
                "run_mode": run_mode,
                "hour_ts_utc": hour_ts_utc,
            },
        )
        result: list[PredictionState] = []
        for row in rows:
            result.append(
                PredictionState(
                    run_id=_as_uuid(row["run_id"]),
                    account_id=int(row["account_id"]),
                    run_mode=str(row["run_mode"]),
                    asset_id=int(row["asset_id"]),
                    hour_ts_utc=_as_datetime(row["hour_ts_utc"]),
                    horizon=str(row["horizon"]),
                    model_version_id=int(row["model_version_id"]),
                    expected_return=_as_decimal(row["expected_return"]),
                    upstream_hash=str(row["upstream_hash"]),
                    row_hash=str(row["row_hash"]),
                    training_window_id=(
                        int(row["training_window_id"]) if row["training_window_id"] is not None else None
                    ),
                    lineage_backtest_run_id=(
                        _as_uuid(row["lineage_backtest_run_id"])
                        if row["lineage_backtest_run_id"] is not None
                        else None
                    ),
                    lineage_fold_index=(
                        int(row["lineage_fold_index"]) if row["lineage_fold_index"] is not None else None
                    ),
                    lineage_horizon=str(row["lineage_horizon"]) if row["lineage_horizon"] is not None else None,
                    activation_id=int(row["activation_id"]) if row["activation_id"] is not None else None,
                )
            )
        return tuple(result)

    def _load_regimes(
        self,
        run_id: UUID,
        account_id: int,
        run_mode: str,
        hour_ts_utc: datetime,
    ) -> tuple[RegimeState, ...]:
        rows = self._db.fetch_all(
            """
            SELECT run_id, account_id, run_mode, asset_id, hour_ts_utc, model_version_id,
                   regime_label, upstream_hash, row_hash,
                   training_window_id, lineage_backtest_run_id, lineage_fold_index,
                   lineage_horizon, activation_id
            FROM regime_output
            WHERE run_id = :run_id
              AND account_id = :account_id
              AND run_mode = :run_mode
              AND hour_ts_utc = :hour_ts_utc
            ORDER BY asset_id ASC, model_version_id ASC, row_hash ASC
            """,
            {
                "run_id": str(run_id),
                "account_id": account_id,
                "run_mode": run_mode,
                "hour_ts_utc": hour_ts_utc,
            },
        )
        result: list[RegimeState] = []
        for row in rows:
            result.append(
                RegimeState(
                    run_id=_as_uuid(row["run_id"]),
                    account_id=int(row["account_id"]),
                    run_mode=str(row["run_mode"]),
                    asset_id=int(row["asset_id"]),
                    hour_ts_utc=_as_datetime(row["hour_ts_utc"]),
                    model_version_id=int(row["model_version_id"]),
                    regime_label=str(row["regime_label"]),
                    upstream_hash=str(row["upstream_hash"]),
                    row_hash=str(row["row_hash"]),
                    training_window_id=(
                        int(row["training_window_id"]) if row["training_window_id"] is not None else None
                    ),
                    lineage_backtest_run_id=(
                        _as_uuid(row["lineage_backtest_run_id"])
                        if row["lineage_backtest_run_id"] is not None
                        else None
                    ),
                    lineage_fold_index=(
                        int(row["lineage_fold_index"]) if row["lineage_fold_index"] is not None else None
                    ),
                    lineage_horizon=str(row["lineage_horizon"]) if row["lineage_horizon"] is not None else None,
                    activation_id=int(row["activation_id"]) if row["activation_id"] is not None else None,
                )
            )
        return tuple(result)

    def _load_risk_state(
        self,
        run_id: UUID,
        account_id: int,
        run_mode: str,
        hour_ts_utc: datetime,
    ) -> RiskState:
        row = self._db.fetch_one(
            """
            SELECT run_mode, account_id, hour_ts_utc, source_run_id, portfolio_value,
                   max_total_exposure_pct, max_cluster_exposure_pct, halt_new_entries,
                   kill_switch_active, state_hash, row_hash
            FROM risk_hourly_state
            WHERE run_mode = :run_mode
              AND account_id = :account_id
              AND hour_ts_utc = :hour_ts_utc
              AND source_run_id = :source_run_id
            """,
            {
                "run_mode": run_mode,
                "account_id": account_id,
                "hour_ts_utc": hour_ts_utc,
                "source_run_id": str(run_id),
            },
        )
        if row is None:
            raise DeterministicAbortError("risk_hourly_state row not found for execution key.")
        return RiskState(
            run_mode=str(row["run_mode"]),
            account_id=int(row["account_id"]),
            hour_ts_utc=_as_datetime(row["hour_ts_utc"]),
            source_run_id=_as_uuid(row["source_run_id"]),
            portfolio_value=_as_decimal(row["portfolio_value"]),
            max_total_exposure_pct=_as_decimal(row["max_total_exposure_pct"]),
            max_cluster_exposure_pct=_as_decimal(row["max_cluster_exposure_pct"]),
            halt_new_entries=bool(row["halt_new_entries"]),
            kill_switch_active=bool(row["kill_switch_active"]),
            state_hash=str(row["state_hash"]),
            row_hash=str(row["row_hash"]),
        )

    def _load_capital_state(
        self,
        run_id: UUID,
        account_id: int,
        run_mode: str,
        hour_ts_utc: datetime,
    ) -> CapitalState:
        row = self._db.fetch_one(
            """
            SELECT run_mode, account_id, hour_ts_utc, source_run_id, cash_balance,
                   portfolio_value, total_exposure_pct, open_position_count, row_hash
            FROM portfolio_hourly_state
            WHERE run_mode = :run_mode
              AND account_id = :account_id
              AND hour_ts_utc = :hour_ts_utc
              AND source_run_id = :source_run_id
            """,
            {
                "run_mode": run_mode,
                "account_id": account_id,
                "hour_ts_utc": hour_ts_utc,
                "source_run_id": str(run_id),
            },
        )
        if row is None:
            raise DeterministicAbortError("portfolio_hourly_state row not found for execution key.")
        return CapitalState(
            run_mode=str(row["run_mode"]),
            account_id=int(row["account_id"]),
            hour_ts_utc=_as_datetime(row["hour_ts_utc"]),
            source_run_id=_as_uuid(row["source_run_id"]),
            cash_balance=_as_decimal(row["cash_balance"]),
            portfolio_value=_as_decimal(row["portfolio_value"]),
            total_exposure_pct=_as_decimal(row["total_exposure_pct"]),
            open_position_count=int(row["open_position_count"]),
            row_hash=str(row["row_hash"]),
        )

    def _load_cluster_states(
        self,
        run_id: UUID,
        account_id: int,
        run_mode: str,
        hour_ts_utc: datetime,
    ) -> tuple[ClusterState, ...]:
        rows = self._db.fetch_all(
            """
            SELECT run_mode, account_id, cluster_id, hour_ts_utc, source_run_id,
                   exposure_pct, max_cluster_exposure_pct, state_hash, parent_risk_hash, row_hash
            FROM cluster_exposure_hourly_state
            WHERE run_mode = :run_mode
              AND account_id = :account_id
              AND hour_ts_utc = :hour_ts_utc
              AND source_run_id = :source_run_id
            ORDER BY cluster_id ASC
            """,
            {
                "run_mode": run_mode,
                "account_id": account_id,
                "hour_ts_utc": hour_ts_utc,
                "source_run_id": str(run_id),
            },
        )
        result: list[ClusterState] = []
        for row in rows:
            result.append(
                ClusterState(
                    run_mode=str(row["run_mode"]),
                    account_id=int(row["account_id"]),
                    cluster_id=int(row["cluster_id"]),
                    hour_ts_utc=_as_datetime(row["hour_ts_utc"]),
                    source_run_id=_as_uuid(row["source_run_id"]),
                    exposure_pct=_as_decimal(row["exposure_pct"]),
                    max_cluster_exposure_pct=_as_decimal(row["max_cluster_exposure_pct"]),
                    state_hash=str(row["state_hash"]),
                    parent_risk_hash=str(row["parent_risk_hash"]),
                    row_hash=str(row["row_hash"]),
                )
            )
        return tuple(result)

    def _load_prior_economic_state(
        self,
        account_id: int,
        run_mode: str,
        hour_ts_utc: datetime,
    ) -> Optional[PriorEconomicState]:
        row = self._db.fetch_one(
            """
            SELECT ledger_seq, balance_before, balance_after, prev_ledger_hash, ledger_hash,
                   row_hash, event_ts_utc
            FROM cash_ledger
            WHERE account_id = :account_id
              AND run_mode = :run_mode
              AND event_ts_utc < :hour_ts_utc
            ORDER BY ledger_seq DESC
            LIMIT 1
            """,
            {
                "account_id": account_id,
                "run_mode": run_mode,
                "hour_ts_utc": hour_ts_utc,
            },
        )
        if row is None:
            return None
        return PriorEconomicState(
            ledger_seq=int(row["ledger_seq"]),
            balance_before=_as_decimal(row["balance_before"]),
            balance_after=_as_decimal(row["balance_after"]),
            prev_ledger_hash=str(row["prev_ledger_hash"]) if row["prev_ledger_hash"] is not None else None,
            ledger_hash=str(row["ledger_hash"]),
            row_hash=str(row["row_hash"]),
            event_ts_utc=_as_datetime(row["event_ts_utc"]),
        )

    def _load_training_windows(
        self,
        predictions: Sequence[PredictionState],
        regimes: Sequence[RegimeState],
    ) -> tuple[TrainingWindowState, ...]:
        ids: list[int] = []
        for prediction in predictions:
            if prediction.training_window_id is not None and prediction.training_window_id not in ids:
                ids.append(prediction.training_window_id)
        for regime in regimes:
            if regime.training_window_id is not None and regime.training_window_id not in ids:
                ids.append(regime.training_window_id)

        result: list[TrainingWindowState] = []
        for training_window_id in sorted(ids):
            row = self._db.fetch_one(
                """
                SELECT training_window_id, backtest_run_id, model_version_id, fold_index, horizon,
                       train_end_utc, valid_start_utc, valid_end_utc,
                       training_window_hash, row_hash
                FROM model_training_window
                WHERE training_window_id = :training_window_id
                """,
                {"training_window_id": training_window_id},
            )
            if row is None:
                raise DeterministicAbortError(f"training_window_id={training_window_id} not found.")
            result.append(
                TrainingWindowState(
                    training_window_id=int(row["training_window_id"]),
                    backtest_run_id=_as_uuid(row["backtest_run_id"]),
                    model_version_id=int(row["model_version_id"]),
                    fold_index=int(row["fold_index"]),
                    horizon=str(row["horizon"]),
                    train_end_utc=_as_datetime(row["train_end_utc"]),
                    valid_start_utc=_as_datetime(row["valid_start_utc"]),
                    valid_end_utc=_as_datetime(row["valid_end_utc"]),
                    training_window_hash=str(row["training_window_hash"]),
                    row_hash=str(row["row_hash"]),
                )
            )
        return tuple(result)

    def _load_activation_records(
        self,
        predictions: Sequence[PredictionState],
        regimes: Sequence[RegimeState],
    ) -> tuple[ActivationRecord, ...]:
        ids: list[int] = []
        for prediction in predictions:
            if prediction.activation_id is not None and prediction.activation_id not in ids:
                ids.append(prediction.activation_id)
        for regime in regimes:
            if regime.activation_id is not None and regime.activation_id not in ids:
                ids.append(regime.activation_id)

        result: list[ActivationRecord] = []
        for activation_id in sorted(ids):
            row = self._db.fetch_one(
                """
                SELECT activation_id, model_version_id, run_mode, validation_window_end_utc,
                       status, approval_hash
                FROM model_activation_gate
                WHERE activation_id = :activation_id
                """,
                {"activation_id": activation_id},
            )
            if row is None:
                raise DeterministicAbortError(f"activation_id={activation_id} not found.")
            result.append(
                ActivationRecord(
                    activation_id=int(row["activation_id"]),
                    model_version_id=int(row["model_version_id"]),
                    run_mode=str(row["run_mode"]),
                    validation_window_end_utc=_as_datetime(row["validation_window_end_utc"]),
                    status=str(row["status"]),
                    approval_hash=str(row["approval_hash"]),
                )
            )
        return tuple(result)

    def _load_memberships(
        self,
        predictions: Sequence[PredictionState],
        hour_ts_utc: datetime,
    ) -> tuple[ClusterMembershipState, ...]:
        asset_ids = sorted({prediction.asset_id for prediction in predictions})
        if not asset_ids:
            return tuple()

        rows = self._db.fetch_all(
            """
            SELECT membership_id, asset_id, cluster_id, membership_hash, effective_from_utc
            FROM asset_cluster_membership
            WHERE effective_from_utc <= :hour_ts_utc
              AND (effective_to_utc IS NULL OR effective_to_utc > :hour_ts_utc)
            ORDER BY asset_id ASC, effective_from_utc DESC, membership_id DESC
            """,
            {"hour_ts_utc": hour_ts_utc},
        )

        selected_by_asset: dict[int, ClusterMembershipState] = {}
        for row in rows:
            asset_id = int(row["asset_id"])
            if asset_id not in asset_ids:
                continue
            if asset_id in selected_by_asset:
                continue
            selected_by_asset[asset_id] = ClusterMembershipState(
                membership_id=int(row["membership_id"]),
                asset_id=asset_id,
                cluster_id=int(row["cluster_id"]),
                membership_hash=str(row["membership_hash"]),
            )

        ordered = [selected_by_asset[asset_id] for asset_id in asset_ids if asset_id in selected_by_asset]
        return tuple(ordered)

    def _load_cost_profile(self, hour_ts_utc: datetime) -> CostProfileState:
        row = self._db.fetch_one(
            """
            SELECT cost_profile_id, fee_rate, slippage_param_hash
            FROM cost_profile
            WHERE venue = 'KRAKEN'
              AND is_active = TRUE
              AND effective_from_utc <= :hour_ts_utc
              AND (effective_to_utc IS NULL OR effective_to_utc > :hour_ts_utc)
            ORDER BY effective_from_utc DESC, cost_profile_id DESC
            LIMIT 1
            """,
            {"hour_ts_utc": hour_ts_utc},
        )
        if row is None:
            raise DeterministicAbortError("No active KRAKEN cost_profile for execution hour.")
        return CostProfileState(
            cost_profile_id=int(row["cost_profile_id"]),
            fee_rate=_as_decimal(row["fee_rate"]),
            slippage_param_hash=str(row["slippage_param_hash"]),
        )
