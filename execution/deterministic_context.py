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
    prob_up: Decimal
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
    drawdown_pct: Decimal
    drawdown_tier: str
    base_risk_fraction: Decimal
    max_concurrent_positions: int
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
class RiskProfileState:
    profile_version: str
    total_exposure_mode: str
    max_total_exposure_pct: Optional[Decimal]
    max_total_exposure_amount: Optional[Decimal]
    cluster_exposure_mode: str
    max_cluster_exposure_pct: Optional[Decimal]
    max_cluster_exposure_amount: Optional[Decimal]
    max_concurrent_positions: int
    severe_loss_drawdown_trigger: Decimal
    volatility_feature_id: int
    volatility_target: Decimal
    volatility_scale_floor: Decimal
    volatility_scale_ceiling: Decimal
    hold_min_expected_return: Decimal
    exit_expected_return_threshold: Decimal
    recovery_hold_prob_up_threshold: Decimal
    recovery_exit_prob_up_threshold: Decimal
    derisk_fraction: Decimal
    signal_persistence_required: int
    row_hash: str


@dataclass(frozen=True)
class VolatilityFeatureState:
    asset_id: int
    feature_id: int
    feature_value: Decimal
    row_hash: str


@dataclass(frozen=True)
class PositionState:
    run_mode: str
    account_id: int
    asset_id: int
    hour_ts_utc: datetime
    source_run_id: UUID
    quantity: Decimal
    exposure_pct: Decimal
    unrealized_pnl: Decimal
    row_hash: str


@dataclass(frozen=True)
class AssetPrecisionState:
    asset_id: int
    tick_size: Decimal
    lot_size: Decimal


@dataclass(frozen=True)
class OrderBookSnapshotState:
    asset_id: int
    snapshot_ts_utc: datetime
    hour_ts_utc: datetime
    best_bid_price: Decimal
    best_ask_price: Decimal
    best_bid_size: Decimal
    best_ask_size: Decimal
    row_hash: str


@dataclass(frozen=True)
class OhlcvState:
    asset_id: int
    hour_ts_utc: datetime
    close_price: Decimal
    row_hash: str


@dataclass(frozen=True)
class ExistingOrderFillState:
    fill_id: UUID
    order_id: UUID
    run_id: UUID
    run_mode: str
    account_id: int
    asset_id: int
    fill_ts_utc: datetime
    fill_price: Decimal
    fill_qty: Decimal
    fill_notional: Decimal
    fee_paid: Decimal
    realized_slippage_rate: Decimal
    slippage_cost: Decimal
    row_hash: str


@dataclass(frozen=True)
class ExistingPositionLotState:
    lot_id: UUID
    open_fill_id: UUID
    run_id: UUID
    run_mode: str
    account_id: int
    asset_id: int
    open_ts_utc: datetime
    open_price: Decimal
    open_qty: Decimal
    open_fee: Decimal
    remaining_qty: Decimal
    row_hash: str


@dataclass(frozen=True)
class ExistingExecutedTradeState:
    trade_id: UUID
    lot_id: UUID
    run_id: UUID
    run_mode: str
    account_id: int
    asset_id: int
    quantity: Decimal
    row_hash: str


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
    risk_profile: RiskProfileState
    volatility_features: tuple[VolatilityFeatureState, ...]
    positions: tuple[PositionState, ...]
    asset_precisions: tuple[AssetPrecisionState, ...]
    order_book_snapshots: tuple[OrderBookSnapshotState, ...]
    ohlcv_rows: tuple[OhlcvState, ...]
    existing_order_fills: tuple[ExistingOrderFillState, ...]
    existing_position_lots: tuple[ExistingPositionLotState, ...]
    existing_executed_trades: tuple[ExistingExecutedTradeState, ...]

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

    def find_volatility_feature(self, asset_id: int) -> Optional[VolatilityFeatureState]:
        for feature_state in self.volatility_features:
            if feature_state.asset_id == asset_id:
                return feature_state
        return None

    def find_position(self, asset_id: int) -> Optional[PositionState]:
        for position in self.positions:
            if position.asset_id == asset_id:
                return position
        return None

    def find_asset_precision(self, asset_id: int) -> Optional[AssetPrecisionState]:
        for asset in self.asset_precisions:
            if asset.asset_id == asset_id:
                return asset
        return None

    def find_latest_order_book_snapshot(
        self,
        asset_id: int,
        as_of_ts_utc: datetime,
    ) -> Optional[OrderBookSnapshotState]:
        selected: Optional[OrderBookSnapshotState] = None
        for snapshot in self.order_book_snapshots:
            if snapshot.asset_id != asset_id:
                continue
            if snapshot.snapshot_ts_utc > as_of_ts_utc:
                continue
            if selected is None or snapshot.snapshot_ts_utc > selected.snapshot_ts_utc:
                selected = snapshot
        return selected

    def find_ohlcv(self, asset_id: int) -> Optional[OhlcvState]:
        for row in self.ohlcv_rows:
            if row.asset_id == asset_id:
                return row
        return None

    def find_existing_fill(self, fill_id: UUID) -> Optional[ExistingOrderFillState]:
        for fill in self.existing_order_fills:
            if fill.fill_id == fill_id:
                return fill
        return None

    def lots_for_asset(self, asset_id: int) -> tuple[ExistingPositionLotState, ...]:
        return tuple(lot for lot in self.existing_position_lots if lot.asset_id == asset_id)

    def executed_qty_for_lot(self, lot_id: UUID) -> Decimal:
        total = Decimal("0")
        for trade in self.existing_executed_trades:
            if trade.lot_id == lot_id:
                total += trade.quantity
        return total


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
        risk_profile = self._load_risk_profile(account_id=account_id, hour_ts_utc=hour_ts_utc)
        volatility_features = self._load_volatility_features(
            run_id=run_id,
            run_mode=normalized_mode,
            hour_ts_utc=hour_ts_utc,
            predictions=predictions,
            volatility_feature_id=risk_profile.volatility_feature_id,
        )
        positions = self._load_positions(run_id, account_id, normalized_mode, hour_ts_utc)
        asset_precisions = self._load_asset_precisions(predictions)
        order_book_snapshots = self._load_order_book_snapshots(predictions, hour_ts_utc)
        ohlcv_rows = self._load_ohlcv_rows(predictions, hour_ts_utc)
        existing_order_fills = self._load_existing_order_fills(run_id, account_id, normalized_mode)
        existing_position_lots = self._load_existing_position_lots(run_id, account_id, normalized_mode)
        existing_executed_trades = self._load_existing_executed_trades(
            run_id,
            account_id,
            normalized_mode,
        )

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
            risk_profile=risk_profile,
            volatility_features=volatility_features,
            positions=positions,
            asset_precisions=asset_precisions,
            order_book_snapshots=order_book_snapshots,
            ohlcv_rows=ohlcv_rows,
            existing_order_fills=existing_order_fills,
            existing_position_lots=existing_position_lots,
            existing_executed_trades=existing_executed_trades,
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
            if context.find_asset_precision(prediction.asset_id) is None:
                raise DeterministicAbortError(
                    f"Missing asset precision metadata for asset_id={prediction.asset_id}."
                )

        if context.prior_economic_state is not None and context.prior_economic_state.ledger_seq > 1:
            if not context.prior_economic_state.prev_ledger_hash:
                raise DeterministicAbortError("Prior economic state has broken ledger hash continuity.")

        if context.risk_profile.total_exposure_mode not in {"PERCENT_OF_PV", "ABSOLUTE_AMOUNT"}:
            raise DeterministicAbortError("Unsupported total_exposure_mode in risk_profile.")
        if context.risk_profile.cluster_exposure_mode not in {"PERCENT_OF_PV", "ABSOLUTE_AMOUNT"}:
            raise DeterministicAbortError("Unsupported cluster_exposure_mode in risk_profile.")
        if context.risk_profile.signal_persistence_required < 1:
            raise DeterministicAbortError("risk_profile signal_persistence_required must be >= 1.")
        if context.risk_profile.volatility_scale_floor > context.risk_profile.volatility_scale_ceiling:
            raise DeterministicAbortError("risk_profile volatility scale floor/ceiling invalid.")

        for feature_state in context.volatility_features:
            if feature_state.feature_id != context.risk_profile.volatility_feature_id:
                raise DeterministicAbortError("Configured volatility_feature_id mismatch in feature_snapshot.")

        for lot in context.existing_position_lots:
            if context.find_existing_fill(lot.open_fill_id) is None:
                raise DeterministicAbortError(
                    f"position_lot open_fill_id={lot.open_fill_id} missing matching order_fill row."
                )

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
                   model_version_id, prob_up, expected_return, upstream_hash, row_hash,
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
                    prob_up=_as_decimal(row["prob_up"]),
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
                   drawdown_pct, drawdown_tier, base_risk_fraction, max_concurrent_positions,
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
            drawdown_pct=(
                _as_decimal(row["drawdown_pct"])
                if row.get("drawdown_pct") is not None
                else Decimal("0")
            ),
            drawdown_tier=str(row["drawdown_tier"]) if row.get("drawdown_tier") is not None else "NORMAL",
            base_risk_fraction=(
                _as_decimal(row["base_risk_fraction"])
                if row.get("base_risk_fraction") is not None
                else Decimal("0.0200000000")
            ),
            max_concurrent_positions=(
                int(row["max_concurrent_positions"])
                if row.get("max_concurrent_positions") is not None
                else 10
            ),
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

    def _load_risk_profile(
        self,
        account_id: int,
        hour_ts_utc: datetime,
    ) -> RiskProfileState:
        rows = self._db.fetch_all(
            """
            SELECT
                a.assignment_id,
                p.profile_version,
                p.total_exposure_mode,
                p.max_total_exposure_pct,
                p.max_total_exposure_amount,
                p.cluster_exposure_mode,
                p.max_cluster_exposure_pct,
                p.max_cluster_exposure_amount,
                p.max_concurrent_positions,
                p.severe_loss_drawdown_trigger,
                p.volatility_feature_id,
                p.volatility_target,
                p.volatility_scale_floor,
                p.volatility_scale_ceiling,
                p.hold_min_expected_return,
                p.exit_expected_return_threshold,
                p.recovery_hold_prob_up_threshold,
                p.recovery_exit_prob_up_threshold,
                p.derisk_fraction,
                p.signal_persistence_required,
                p.row_hash
            FROM account_risk_profile_assignment a
            JOIN risk_profile p
              ON p.profile_version = a.profile_version
            WHERE a.account_id = :account_id
              AND a.effective_from_utc <= :hour_ts_utc
              AND (a.effective_to_utc IS NULL OR a.effective_to_utc > :hour_ts_utc)
            ORDER BY a.effective_from_utc DESC, a.assignment_id DESC
            """,
            {"account_id": account_id, "hour_ts_utc": hour_ts_utc},
        )
        if not rows:
            raise DeterministicAbortError("No active risk_profile assignment for execution hour.")
        if len(rows) > 1:
            raise DeterministicAbortError("Multiple active risk_profile assignments for execution hour.")

        row = rows[0]
        return RiskProfileState(
            profile_version=str(row["profile_version"]),
            total_exposure_mode=str(row["total_exposure_mode"]),
            max_total_exposure_pct=(
                _as_decimal(row["max_total_exposure_pct"])
                if row["max_total_exposure_pct"] is not None
                else None
            ),
            max_total_exposure_amount=(
                _as_decimal(row["max_total_exposure_amount"])
                if row["max_total_exposure_amount"] is not None
                else None
            ),
            cluster_exposure_mode=str(row["cluster_exposure_mode"]),
            max_cluster_exposure_pct=(
                _as_decimal(row["max_cluster_exposure_pct"])
                if row["max_cluster_exposure_pct"] is not None
                else None
            ),
            max_cluster_exposure_amount=(
                _as_decimal(row["max_cluster_exposure_amount"])
                if row["max_cluster_exposure_amount"] is not None
                else None
            ),
            max_concurrent_positions=int(row["max_concurrent_positions"]),
            severe_loss_drawdown_trigger=_as_decimal(row["severe_loss_drawdown_trigger"]),
            volatility_feature_id=int(row["volatility_feature_id"]),
            volatility_target=_as_decimal(row["volatility_target"]),
            volatility_scale_floor=_as_decimal(row["volatility_scale_floor"]),
            volatility_scale_ceiling=_as_decimal(row["volatility_scale_ceiling"]),
            hold_min_expected_return=_as_decimal(row["hold_min_expected_return"]),
            exit_expected_return_threshold=_as_decimal(row["exit_expected_return_threshold"]),
            recovery_hold_prob_up_threshold=_as_decimal(row["recovery_hold_prob_up_threshold"]),
            recovery_exit_prob_up_threshold=_as_decimal(row["recovery_exit_prob_up_threshold"]),
            derisk_fraction=_as_decimal(row["derisk_fraction"]),
            signal_persistence_required=int(row["signal_persistence_required"]),
            row_hash=str(row["row_hash"]),
        )

    def _load_volatility_features(
        self,
        run_id: UUID,
        run_mode: str,
        hour_ts_utc: datetime,
        predictions: Sequence[PredictionState],
        volatility_feature_id: int,
    ) -> tuple[VolatilityFeatureState, ...]:
        rows = self._db.fetch_all(
            """
            SELECT asset_id, feature_id, feature_value, row_hash
            FROM feature_snapshot
            WHERE run_id = :run_id
              AND run_mode = :run_mode
              AND hour_ts_utc = :hour_ts_utc
              AND feature_id = :feature_id
            ORDER BY asset_id ASC
            """,
            {
                "run_id": str(run_id),
                "run_mode": run_mode,
                "hour_ts_utc": hour_ts_utc,
                "feature_id": volatility_feature_id,
            },
        )
        target_assets = {prediction.asset_id for prediction in predictions}
        result: list[VolatilityFeatureState] = []
        for row in rows:
            asset_id = int(row["asset_id"])
            if asset_id not in target_assets:
                continue
            result.append(
                VolatilityFeatureState(
                    asset_id=asset_id,
                    feature_id=int(row["feature_id"]),
                    feature_value=_as_decimal(row["feature_value"]),
                    row_hash=str(row["row_hash"]),
                )
            )
        return tuple(result)

    def _load_positions(
        self,
        run_id: UUID,
        account_id: int,
        run_mode: str,
        hour_ts_utc: datetime,
    ) -> tuple[PositionState, ...]:
        rows = self._db.fetch_all(
            """
            SELECT run_mode, account_id, asset_id, hour_ts_utc, source_run_id,
                   quantity, exposure_pct, unrealized_pnl, row_hash
            FROM position_hourly_state
            WHERE run_mode = :run_mode
              AND account_id = :account_id
              AND hour_ts_utc = :hour_ts_utc
              AND source_run_id = :source_run_id
            ORDER BY asset_id ASC
            """,
            {
                "run_mode": run_mode,
                "account_id": account_id,
                "hour_ts_utc": hour_ts_utc,
                "source_run_id": str(run_id),
            },
        )
        result: list[PositionState] = []
        for row in rows:
            result.append(
                PositionState(
                    run_mode=str(row["run_mode"]),
                    account_id=int(row["account_id"]),
                    asset_id=int(row["asset_id"]),
                    hour_ts_utc=_as_datetime(row["hour_ts_utc"]),
                    source_run_id=_as_uuid(row["source_run_id"]),
                    quantity=_as_decimal(row["quantity"]),
                    exposure_pct=_as_decimal(row["exposure_pct"]),
                    unrealized_pnl=_as_decimal(row["unrealized_pnl"]),
                    row_hash=str(row["row_hash"]),
                )
            )
        return tuple(result)

    def _load_asset_precisions(
        self,
        predictions: Sequence[PredictionState],
    ) -> tuple[AssetPrecisionState, ...]:
        asset_ids = {prediction.asset_id for prediction in predictions}
        rows = self._db.fetch_all(
            """
            SELECT asset_id, tick_size, lot_size
            FROM asset
            ORDER BY asset_id ASC
            """,
            {},
        )
        result: list[AssetPrecisionState] = []
        for row in rows:
            asset_id = int(row["asset_id"])
            if asset_id not in asset_ids:
                continue
            result.append(
                AssetPrecisionState(
                    asset_id=asset_id,
                    tick_size=_as_decimal(row["tick_size"]),
                    lot_size=_as_decimal(row["lot_size"]),
                )
            )
        return tuple(result)

    def _load_order_book_snapshots(
        self,
        predictions: Sequence[PredictionState],
        hour_ts_utc: datetime,
    ) -> tuple[OrderBookSnapshotState, ...]:
        target_assets = {prediction.asset_id for prediction in predictions}
        rows = self._db.fetch_all(
            """
            SELECT
                asset_id,
                snapshot_ts_utc,
                hour_ts_utc,
                best_bid_price,
                best_ask_price,
                best_bid_size,
                best_ask_size,
                row_hash
            FROM order_book_snapshot
            WHERE hour_ts_utc = :hour_ts_utc
            ORDER BY asset_id ASC, snapshot_ts_utc ASC, row_hash ASC
            """,
            {"hour_ts_utc": hour_ts_utc},
        )
        result: list[OrderBookSnapshotState] = []
        for row in rows:
            asset_id = int(row["asset_id"])
            if asset_id not in target_assets:
                continue
            result.append(
                OrderBookSnapshotState(
                    asset_id=asset_id,
                    snapshot_ts_utc=_as_datetime(row["snapshot_ts_utc"]),
                    hour_ts_utc=_as_datetime(row["hour_ts_utc"]),
                    best_bid_price=_as_decimal(row["best_bid_price"]),
                    best_ask_price=_as_decimal(row["best_ask_price"]),
                    best_bid_size=_as_decimal(row["best_bid_size"]),
                    best_ask_size=_as_decimal(row["best_ask_size"]),
                    row_hash=str(row["row_hash"]),
                )
            )
        return tuple(result)

    def _load_ohlcv_rows(
        self,
        predictions: Sequence[PredictionState],
        hour_ts_utc: datetime,
    ) -> tuple[OhlcvState, ...]:
        target_assets = {prediction.asset_id for prediction in predictions}
        rows = self._db.fetch_all(
            """
            SELECT asset_id, hour_ts_utc, close_price, row_hash, source_venue
            FROM market_ohlcv_hourly
            WHERE hour_ts_utc = :hour_ts_utc
            ORDER BY asset_id ASC, source_venue ASC, row_hash ASC
            """,
            {"hour_ts_utc": hour_ts_utc},
        )
        selected: dict[int, OhlcvState] = {}
        for row in rows:
            asset_id = int(row["asset_id"])
            if asset_id not in target_assets or asset_id in selected:
                continue
            selected[asset_id] = OhlcvState(
                asset_id=asset_id,
                hour_ts_utc=_as_datetime(row["hour_ts_utc"]),
                close_price=_as_decimal(row["close_price"]),
                row_hash=str(row["row_hash"]),
            )
        return tuple(selected[asset_id] for asset_id in sorted(selected))

    def _load_existing_order_fills(
        self,
        run_id: UUID,
        account_id: int,
        run_mode: str,
    ) -> tuple[ExistingOrderFillState, ...]:
        rows = self._db.fetch_all(
            """
            SELECT
                fill_id,
                order_id,
                run_id,
                run_mode,
                account_id,
                asset_id,
                fill_ts_utc,
                fill_price,
                fill_qty,
                fill_notional,
                fee_paid,
                realized_slippage_rate,
                slippage_cost,
                row_hash
            FROM order_fill
            WHERE run_id = :run_id
              AND account_id = :account_id
              AND run_mode = :run_mode
            ORDER BY fill_ts_utc ASC, fill_id ASC
            """,
            {
                "run_id": str(run_id),
                "account_id": account_id,
                "run_mode": run_mode,
            },
        )
        result: list[ExistingOrderFillState] = []
        for row in rows:
            result.append(
                ExistingOrderFillState(
                    fill_id=_as_uuid(row["fill_id"]),
                    order_id=_as_uuid(row["order_id"]),
                    run_id=_as_uuid(row["run_id"]),
                    run_mode=str(row["run_mode"]),
                    account_id=int(row["account_id"]),
                    asset_id=int(row["asset_id"]),
                    fill_ts_utc=_as_datetime(row["fill_ts_utc"]),
                    fill_price=_as_decimal(row["fill_price"]),
                    fill_qty=_as_decimal(row["fill_qty"]),
                    fill_notional=_as_decimal(row["fill_notional"]),
                    fee_paid=_as_decimal(row["fee_paid"]),
                    realized_slippage_rate=_as_decimal(row["realized_slippage_rate"]),
                    slippage_cost=_as_decimal(row["slippage_cost"]),
                    row_hash=str(row["row_hash"]),
                )
            )
        return tuple(result)

    def _load_existing_position_lots(
        self,
        run_id: UUID,
        account_id: int,
        run_mode: str,
    ) -> tuple[ExistingPositionLotState, ...]:
        rows = self._db.fetch_all(
            """
            SELECT
                lot_id,
                open_fill_id,
                run_id,
                run_mode,
                account_id,
                asset_id,
                open_ts_utc,
                open_price,
                open_qty,
                open_fee,
                remaining_qty,
                row_hash
            FROM position_lot
            WHERE run_id = :run_id
              AND account_id = :account_id
              AND run_mode = :run_mode
            ORDER BY open_ts_utc ASC, lot_id ASC
            """,
            {
                "run_id": str(run_id),
                "account_id": account_id,
                "run_mode": run_mode,
            },
        )
        result: list[ExistingPositionLotState] = []
        for row in rows:
            result.append(
                ExistingPositionLotState(
                    lot_id=_as_uuid(row["lot_id"]),
                    open_fill_id=_as_uuid(row["open_fill_id"]),
                    run_id=_as_uuid(row["run_id"]),
                    run_mode=str(row["run_mode"]),
                    account_id=int(row["account_id"]),
                    asset_id=int(row["asset_id"]),
                    open_ts_utc=_as_datetime(row["open_ts_utc"]),
                    open_price=_as_decimal(row["open_price"]),
                    open_qty=_as_decimal(row["open_qty"]),
                    open_fee=_as_decimal(row["open_fee"]),
                    remaining_qty=_as_decimal(row["remaining_qty"]),
                    row_hash=str(row["row_hash"]),
                )
            )
        return tuple(result)

    def _load_existing_executed_trades(
        self,
        run_id: UUID,
        account_id: int,
        run_mode: str,
    ) -> tuple[ExistingExecutedTradeState, ...]:
        rows = self._db.fetch_all(
            """
            SELECT
                trade_id,
                lot_id,
                run_id,
                run_mode,
                account_id,
                asset_id,
                quantity,
                row_hash
            FROM executed_trade
            WHERE run_id = :run_id
              AND account_id = :account_id
              AND run_mode = :run_mode
            ORDER BY exit_ts_utc ASC, trade_id ASC
            """,
            {
                "run_id": str(run_id),
                "account_id": account_id,
                "run_mode": run_mode,
            },
        )
        result: list[ExistingExecutedTradeState] = []
        for row in rows:
            result.append(
                ExistingExecutedTradeState(
                    trade_id=_as_uuid(row["trade_id"]),
                    lot_id=_as_uuid(row["lot_id"]),
                    run_id=_as_uuid(row["run_id"]),
                    run_mode=str(row["run_mode"]),
                    account_id=int(row["account_id"]),
                    asset_id=int(row["asset_id"]),
                    quantity=_as_decimal(row["quantity"]),
                    row_hash=str(row["row_hash"]),
                )
            )
        return tuple(result)
