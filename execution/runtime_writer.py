"""Append-only deterministic runtime writer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import json
from typing import Any, Mapping, Optional, Protocol, Sequence
from uuid import UUID

from execution.decision_engine import (
    NUMERIC_10,
    NUMERIC_18,
    DecisionResult,
    normalize_decimal,
    stable_hash,
    stable_uuid,
)
from execution.deterministic_context import (
    DeterministicAbortError,
    ExecutionContext,
    PredictionState,
    RegimeState,
)


class DeterministicWriterDatabase(Protocol):
    """Minimal write-capable DB protocol for deterministic runtime persistence."""

    def fetch_one(self, sql: str, params: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
        """Fetch one row."""

    def fetch_all(self, sql: str, params: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        """Fetch all rows."""

    def execute(self, sql: str, params: Mapping[str, Any]) -> None:
        """Execute INSERT-only SQL statements."""


@dataclass(frozen=True)
class TradeSignalRow:
    signal_id: UUID
    run_id: UUID
    run_mode: str
    account_id: int
    asset_id: int
    hour_ts_utc: datetime
    horizon: str
    action: str
    direction: str
    confidence: Decimal
    expected_return: Decimal
    assumed_fee_rate: Decimal
    assumed_slippage_rate: Decimal
    net_edge: Decimal
    target_position_notional: Decimal
    position_size_fraction: Decimal
    risk_state_hour_ts_utc: datetime
    decision_hash: str
    risk_state_run_id: UUID
    cluster_membership_id: int
    upstream_hash: str
    row_hash: str


@dataclass(frozen=True)
class OrderRequestRow:
    order_id: UUID
    signal_id: UUID
    run_id: UUID
    run_mode: str
    account_id: int
    asset_id: int
    client_order_id: str
    request_ts_utc: datetime
    hour_ts_utc: datetime
    side: str
    order_type: str
    tif: str
    limit_price: Optional[Decimal]
    requested_qty: Decimal
    requested_notional: Decimal
    pre_order_cash_available: Decimal
    risk_check_passed: bool
    status: str
    cost_profile_id: int
    origin_hour_ts_utc: datetime
    risk_state_run_id: UUID
    cluster_membership_id: int
    parent_signal_hash: str
    row_hash: str


@dataclass(frozen=True)
class OrderFillRow:
    fill_id: UUID
    order_id: UUID
    run_id: UUID
    run_mode: str
    account_id: int
    asset_id: int
    exchange_trade_id: str
    fill_ts_utc: datetime
    hour_ts_utc: datetime
    fill_price: Decimal
    fill_qty: Decimal
    fill_notional: Decimal
    fee_paid: Decimal
    fee_rate: Decimal
    realized_slippage_rate: Decimal
    origin_hour_ts_utc: datetime
    slippage_cost: Decimal
    parent_order_hash: str
    row_hash: str
    liquidity_flag: str


@dataclass(frozen=True)
class PositionLotRow:
    lot_id: UUID
    open_fill_id: UUID
    run_id: UUID
    run_mode: str
    account_id: int
    asset_id: int
    hour_ts_utc: datetime
    open_ts_utc: datetime
    open_price: Decimal
    open_qty: Decimal
    open_notional: Decimal
    open_fee: Decimal
    remaining_qty: Decimal
    origin_hour_ts_utc: datetime
    parent_fill_hash: str
    row_hash: str


@dataclass(frozen=True)
class ExecutedTradeRow:
    trade_id: UUID
    lot_id: UUID
    run_id: UUID
    run_mode: str
    account_id: int
    asset_id: int
    hour_ts_utc: datetime
    entry_ts_utc: datetime
    exit_ts_utc: datetime
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    gross_pnl: Decimal
    net_pnl: Decimal
    total_fee: Decimal
    total_slippage_cost: Decimal
    holding_hours: int
    origin_hour_ts_utc: datetime
    parent_lot_hash: str
    row_hash: str


@dataclass(frozen=True)
class RiskEventRow:
    risk_event_id: UUID
    run_id: UUID
    run_mode: str
    account_id: int
    event_ts_utc: datetime
    hour_ts_utc: datetime
    event_type: str
    severity: str
    reason_code: str
    details: str
    related_state_hour_ts_utc: datetime
    origin_hour_ts_utc: datetime
    parent_state_hash: str
    row_hash: str


@dataclass(frozen=True)
class RuntimeWriteResult:
    trade_signals: tuple[TradeSignalRow, ...]
    order_requests: tuple[OrderRequestRow, ...]
    order_fills: tuple[OrderFillRow, ...]
    position_lots: tuple[PositionLotRow, ...]
    executed_trades: tuple[ExecutedTradeRow, ...]
    risk_events: tuple[RiskEventRow, ...]


class AppendOnlyRuntimeWriter:
    """Insert-only writer for deterministic runtime artifacts."""

    def __init__(self, db: DeterministicWriterDatabase) -> None:
        self._db = db

    def assert_ledger_continuity(self, account_id: int, run_mode: str) -> None:
        """Fail fast if cash ledger continuity invariant is broken."""
        row = self._db.fetch_one(
            """
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
                    LAG(balance_after) OVER (
                        PARTITION BY account_id, run_mode
                        ORDER BY ledger_seq
                    ) AS expected_before,
                    LAG(ledger_hash) OVER (
                        PARTITION BY account_id, run_mode
                        ORDER BY ledger_seq
                    ) AS expected_prev_hash
                FROM cash_ledger
                WHERE account_id = :account_id
                  AND run_mode = :run_mode
            )
            SELECT COUNT(*) AS violations
            FROM ordered
            WHERE balance_after <> balance_before + delta_cash
               OR (ledger_seq > 1 AND balance_before <> expected_before)
               OR (ledger_seq > 1 AND prev_ledger_hash <> expected_prev_hash)
            """,
            {"account_id": account_id, "run_mode": run_mode},
        )
        violations = int(row["violations"]) if row is not None else 0
        if violations != 0:
            raise DeterministicAbortError(
                f"Cash ledger continuity invariant violated (violations={violations})."
            )

    def build_trade_signal_row(
        self,
        context: ExecutionContext,
        prediction: PredictionState,
        regime: RegimeState,
        decision: DecisionResult,
        action_override: Optional[str] = None,
    ) -> TradeSignalRow:
        action = action_override or decision.action
        if action not in {"ENTER", "HOLD", "EXIT"}:
            raise DeterministicAbortError(f"Invalid signal action={action}.")
        direction = "LONG" if action == "ENTER" else "FLAT"

        expected_return = normalize_decimal(prediction.expected_return, NUMERIC_18)
        assumed_fee_rate = normalize_decimal(context.cost_profile.fee_rate, Decimal("0.000001"))
        assumed_slippage_rate = self._derive_slippage_rate(context.cost_profile.slippage_param_hash)
        cost_rate = normalize_decimal(assumed_fee_rate + assumed_slippage_rate, Decimal("0.000001"))
        net_edge = normalize_decimal(expected_return - cost_rate, NUMERIC_18)

        position_size_fraction = (
            normalize_decimal(decision.position_size_fraction, NUMERIC_10)
            if action == "ENTER"
            else Decimal("0").quantize(NUMERIC_10)
        )
        target_notional = (
            normalize_decimal(context.capital_state.portfolio_value * position_size_fraction, NUMERIC_18)
            if action == "ENTER"
            else Decimal("0").quantize(NUMERIC_18)
        )
        if target_notional > context.capital_state.cash_balance:
            target_notional = normalize_decimal(context.capital_state.cash_balance, NUMERIC_18)

        membership = context.find_membership(prediction.asset_id)
        if membership is None:
            raise DeterministicAbortError(
                f"Missing cluster membership for asset_id={prediction.asset_id}."
            )
        cluster_state = context.find_cluster_state(membership.cluster_id)
        if cluster_state is None:
            raise DeterministicAbortError(
                f"Missing cluster state for cluster_id={membership.cluster_id}."
            )

        upstream_hash = stable_hash(
            (
                context.run_context.run_seed_hash,
                prediction.upstream_hash,
                regime.upstream_hash,
                context.capital_state.row_hash,
                context.risk_state.row_hash,
                cluster_state.row_hash,
            )
        )
        signal_id = stable_uuid(
            "trade_signal",
            (
                context.run_context.run_seed_hash,
                prediction.asset_id,
                prediction.horizon,
                action,
                decision.decision_hash,
                upstream_hash,
            ),
        )
        row_hash = stable_hash(
            (
                context.run_context.run_seed_hash,
                str(signal_id),
                str(context.run_context.run_id),
                context.run_context.run_mode,
                context.run_context.account_id,
                prediction.asset_id,
                context.run_context.origin_hour_ts_utc,
                prediction.horizon,
                action,
                direction,
                decision.confidence,
                expected_return,
                assumed_fee_rate,
                assumed_slippage_rate,
                net_edge,
                target_notional,
                position_size_fraction,
                context.risk_state.hour_ts_utc,
                decision.decision_hash,
                str(context.risk_state.source_run_id),
                membership.membership_id,
                upstream_hash,
            )
        )

        return TradeSignalRow(
            signal_id=signal_id,
            run_id=context.run_context.run_id,
            run_mode=context.run_context.run_mode,
            account_id=context.run_context.account_id,
            asset_id=prediction.asset_id,
            hour_ts_utc=context.run_context.origin_hour_ts_utc,
            horizon=prediction.horizon,
            action=action,
            direction=direction,
            confidence=decision.confidence,
            expected_return=expected_return,
            assumed_fee_rate=assumed_fee_rate,
            assumed_slippage_rate=assumed_slippage_rate,
            net_edge=net_edge,
            target_position_notional=target_notional,
            position_size_fraction=position_size_fraction,
            risk_state_hour_ts_utc=context.risk_state.hour_ts_utc,
            decision_hash=decision.decision_hash,
            risk_state_run_id=context.risk_state.source_run_id,
            cluster_membership_id=membership.membership_id,
            upstream_hash=upstream_hash,
            row_hash=row_hash,
        )

    def insert_trade_signal(self, signal: TradeSignalRow) -> None:
        self._db.execute(
            """
            INSERT INTO trade_signal (
                signal_id, run_id, run_mode, account_id, asset_id, hour_ts_utc, horizon,
                action, direction, confidence, expected_return, assumed_fee_rate,
                assumed_slippage_rate, net_edge, target_position_notional,
                position_size_fraction, risk_state_hour_ts_utc, decision_hash,
                risk_state_run_id, cluster_membership_id, upstream_hash, row_hash
            ) VALUES (
                :signal_id, :run_id, :run_mode, :account_id, :asset_id, :hour_ts_utc, :horizon,
                :action, :direction, :confidence, :expected_return, :assumed_fee_rate,
                :assumed_slippage_rate, :net_edge, :target_position_notional,
                :position_size_fraction, :risk_state_hour_ts_utc, :decision_hash,
                :risk_state_run_id, :cluster_membership_id, :upstream_hash, :row_hash
            )
            """,
            {
                "signal_id": str(signal.signal_id),
                "run_id": str(signal.run_id),
                "run_mode": signal.run_mode,
                "account_id": signal.account_id,
                "asset_id": signal.asset_id,
                "hour_ts_utc": signal.hour_ts_utc,
                "horizon": signal.horizon,
                "action": signal.action,
                "direction": signal.direction,
                "confidence": signal.confidence,
                "expected_return": signal.expected_return,
                "assumed_fee_rate": signal.assumed_fee_rate,
                "assumed_slippage_rate": signal.assumed_slippage_rate,
                "net_edge": signal.net_edge,
                "target_position_notional": signal.target_position_notional,
                "position_size_fraction": signal.position_size_fraction,
                "risk_state_hour_ts_utc": signal.risk_state_hour_ts_utc,
                "decision_hash": signal.decision_hash,
                "risk_state_run_id": str(signal.risk_state_run_id),
                "cluster_membership_id": signal.cluster_membership_id,
                "upstream_hash": signal.upstream_hash,
                "row_hash": signal.row_hash,
            },
        )

    def build_order_request_row(
        self,
        context: ExecutionContext,
        signal: TradeSignalRow,
    ) -> Optional[OrderRequestRow]:
        if signal.action != "ENTER":
            return None
        if signal.target_position_notional <= 0:
            return None

        requested_qty = normalize_decimal(signal.target_position_notional, NUMERIC_18)
        requested_notional = normalize_decimal(signal.target_position_notional, NUMERIC_18)
        return self.build_order_request_attempt_row(
            context=context,
            signal=signal,
            side="BUY",
            request_ts_utc=context.run_context.origin_hour_ts_utc,
            requested_qty=requested_qty,
            requested_notional=requested_notional,
            status="NEW",
            attempt_seq=0,
        )

    def build_order_request_attempt_row(
        self,
        context: ExecutionContext,
        signal: TradeSignalRow,
        side: str,
        request_ts_utc: datetime,
        requested_qty: Decimal,
        requested_notional: Decimal,
        status: str,
        attempt_seq: int,
    ) -> OrderRequestRow:
        if side not in {"BUY", "SELL"}:
            raise DeterministicAbortError(f"Invalid order side={side}.")
        if status not in {"NEW", "ACK", "PARTIAL", "FILLED", "CANCELLED", "REJECTED"}:
            raise DeterministicAbortError(f"Invalid order status={status}.")
        if requested_qty <= 0:
            raise DeterministicAbortError("requested_qty must be positive.")
        if requested_notional <= 0:
            raise DeterministicAbortError("requested_notional must be positive.")
        if attempt_seq < 0:
            raise DeterministicAbortError("attempt_seq must be non-negative.")

        order_id = stable_uuid(
            "order_request",
            (
                context.run_context.run_seed_hash,
                str(signal.signal_id),
                signal.row_hash,
                side,
                attempt_seq,
                request_ts_utc,
                requested_qty,
                requested_notional,
            ),
        )
        client_order_id = f"det-{order_id.hex[:24]}"
        row_hash = stable_hash(
            (
                context.run_context.run_seed_hash,
                str(order_id),
                str(signal.signal_id),
                str(signal.run_id),
                signal.run_mode,
                signal.account_id,
                signal.asset_id,
                client_order_id,
                request_ts_utc,
                context.run_context.origin_hour_ts_utc,
                side,
                "MARKET",
                "IOC",
                requested_qty,
                requested_notional,
                context.capital_state.cash_balance,
                1,
                status,
                context.cost_profile.cost_profile_id,
                context.run_context.origin_hour_ts_utc,
                str(context.risk_state.source_run_id),
                signal.cluster_membership_id,
                signal.row_hash,
            )
        )
        return OrderRequestRow(
            order_id=order_id,
            signal_id=signal.signal_id,
            run_id=signal.run_id,
            run_mode=signal.run_mode,
            account_id=signal.account_id,
            asset_id=signal.asset_id,
            client_order_id=client_order_id,
            request_ts_utc=request_ts_utc,
            hour_ts_utc=context.run_context.origin_hour_ts_utc,
            side=side,
            order_type="MARKET",
            tif="IOC",
            limit_price=None,
            requested_qty=normalize_decimal(requested_qty, NUMERIC_18),
            requested_notional=normalize_decimal(requested_notional, NUMERIC_18),
            pre_order_cash_available=normalize_decimal(context.capital_state.cash_balance, NUMERIC_18),
            risk_check_passed=True,
            status=status,
            cost_profile_id=context.cost_profile.cost_profile_id,
            origin_hour_ts_utc=context.run_context.origin_hour_ts_utc,
            risk_state_run_id=context.risk_state.source_run_id,
            cluster_membership_id=signal.cluster_membership_id,
            parent_signal_hash=signal.row_hash,
            row_hash=row_hash,
        )

    def insert_order_request(self, order: OrderRequestRow) -> None:
        self._db.execute(
            """
            INSERT INTO order_request (
                order_id, signal_id, run_id, run_mode, account_id, asset_id, client_order_id,
                request_ts_utc, hour_ts_utc, side, order_type, tif, limit_price, requested_qty,
                requested_notional, pre_order_cash_available, risk_check_passed, status,
                cost_profile_id, origin_hour_ts_utc, risk_state_run_id, cluster_membership_id,
                parent_signal_hash, row_hash
            ) VALUES (
                :order_id, :signal_id, :run_id, :run_mode, :account_id, :asset_id, :client_order_id,
                :request_ts_utc, :hour_ts_utc, :side, :order_type, :tif, :limit_price, :requested_qty,
                :requested_notional, :pre_order_cash_available, :risk_check_passed, :status,
                :cost_profile_id, :origin_hour_ts_utc, :risk_state_run_id, :cluster_membership_id,
                :parent_signal_hash, :row_hash
            )
            """,
            {
                "order_id": str(order.order_id),
                "signal_id": str(order.signal_id),
                "run_id": str(order.run_id),
                "run_mode": order.run_mode,
                "account_id": order.account_id,
                "asset_id": order.asset_id,
                "client_order_id": order.client_order_id,
                "request_ts_utc": order.request_ts_utc,
                "hour_ts_utc": order.hour_ts_utc,
                "side": order.side,
                "order_type": order.order_type,
                "tif": order.tif,
                "limit_price": order.limit_price,
                "requested_qty": order.requested_qty,
                "requested_notional": order.requested_notional,
                "pre_order_cash_available": order.pre_order_cash_available,
                "risk_check_passed": order.risk_check_passed,
                "status": order.status,
                "cost_profile_id": order.cost_profile_id,
                "origin_hour_ts_utc": order.origin_hour_ts_utc,
                "risk_state_run_id": str(order.risk_state_run_id),
                "cluster_membership_id": order.cluster_membership_id,
                "parent_signal_hash": order.parent_signal_hash,
                "row_hash": order.row_hash,
            },
        )

    def build_order_fill_row(
        self,
        context: ExecutionContext,
        order: OrderRequestRow,
        fill_ts_utc: datetime,
        fill_price: Decimal,
        fill_qty: Decimal,
        liquidity_flag: str,
        attempt_seq: int,
    ) -> OrderFillRow:
        if fill_qty <= 0:
            raise DeterministicAbortError("fill_qty must be positive for order_fill.")
        if fill_price <= 0:
            raise DeterministicAbortError("fill_price must be positive for order_fill.")
        if liquidity_flag not in {"MAKER", "TAKER", "UNKNOWN"}:
            raise DeterministicAbortError(f"Invalid liquidity_flag={liquidity_flag}.")

        fill_notional = normalize_decimal(fill_price * fill_qty, NUMERIC_18)
        fee_rate = normalize_decimal(context.cost_profile.fee_rate, Decimal("0.000001"))
        fee_paid = normalize_decimal(fill_notional * fee_rate, NUMERIC_18)
        realized_slippage_rate = self._derive_slippage_rate(context.cost_profile.slippage_param_hash)
        slippage_cost = normalize_decimal(fill_notional * realized_slippage_rate, NUMERIC_18)

        fill_id = stable_uuid(
            "order_fill",
            (
                context.run_context.run_seed_hash,
                str(order.order_id),
                attempt_seq,
                fill_ts_utc,
                fill_qty,
                fill_price,
            ),
        )
        exchange_trade_id = f"sim-{fill_id.hex[:28]}"
        row_hash = stable_hash(
            (
                context.run_context.run_seed_hash,
                str(fill_id),
                str(order.order_id),
                str(order.run_id),
                order.run_mode,
                order.account_id,
                order.asset_id,
                exchange_trade_id,
                fill_ts_utc,
                context.run_context.origin_hour_ts_utc,
                fill_price,
                fill_qty,
                fill_notional,
                fee_paid,
                fee_rate,
                realized_slippage_rate,
                liquidity_flag,
                context.run_context.origin_hour_ts_utc,
                slippage_cost,
                order.row_hash,
            )
        )
        return OrderFillRow(
            fill_id=fill_id,
            order_id=order.order_id,
            run_id=order.run_id,
            run_mode=order.run_mode,
            account_id=order.account_id,
            asset_id=order.asset_id,
            exchange_trade_id=exchange_trade_id,
            fill_ts_utc=fill_ts_utc,
            hour_ts_utc=context.run_context.origin_hour_ts_utc,
            fill_price=normalize_decimal(fill_price, NUMERIC_18),
            fill_qty=normalize_decimal(fill_qty, NUMERIC_18),
            fill_notional=fill_notional,
            fee_paid=fee_paid,
            fee_rate=fee_rate,
            realized_slippage_rate=realized_slippage_rate,
            origin_hour_ts_utc=context.run_context.origin_hour_ts_utc,
            slippage_cost=slippage_cost,
            parent_order_hash=order.row_hash,
            row_hash=row_hash,
            liquidity_flag=liquidity_flag,
        )

    def insert_order_fill(self, fill: OrderFillRow) -> None:
        self._db.execute(
            """
            INSERT INTO order_fill (
                fill_id, order_id, run_id, run_mode, account_id, asset_id, exchange_trade_id,
                fill_ts_utc, hour_ts_utc, fill_price, fill_qty, fill_notional, fee_paid,
                fee_rate, realized_slippage_rate, origin_hour_ts_utc, slippage_cost,
                parent_order_hash, row_hash, liquidity_flag
            ) VALUES (
                :fill_id, :order_id, :run_id, :run_mode, :account_id, :asset_id, :exchange_trade_id,
                :fill_ts_utc, :hour_ts_utc, :fill_price, :fill_qty, :fill_notional, :fee_paid,
                :fee_rate, :realized_slippage_rate, :origin_hour_ts_utc, :slippage_cost,
                :parent_order_hash, :row_hash, :liquidity_flag
            )
            """,
            {
                "fill_id": str(fill.fill_id),
                "order_id": str(fill.order_id),
                "run_id": str(fill.run_id),
                "run_mode": fill.run_mode,
                "account_id": fill.account_id,
                "asset_id": fill.asset_id,
                "exchange_trade_id": fill.exchange_trade_id,
                "fill_ts_utc": fill.fill_ts_utc,
                "hour_ts_utc": fill.hour_ts_utc,
                "fill_price": fill.fill_price,
                "fill_qty": fill.fill_qty,
                "fill_notional": fill.fill_notional,
                "fee_paid": fill.fee_paid,
                "fee_rate": fill.fee_rate,
                "realized_slippage_rate": fill.realized_slippage_rate,
                "origin_hour_ts_utc": fill.origin_hour_ts_utc,
                "slippage_cost": fill.slippage_cost,
                "parent_order_hash": fill.parent_order_hash,
                "row_hash": fill.row_hash,
                "liquidity_flag": fill.liquidity_flag,
            },
        )

    def build_position_lot_row(
        self,
        context: ExecutionContext,
        fill: OrderFillRow,
    ) -> PositionLotRow:
        if fill.fill_qty <= 0:
            raise DeterministicAbortError("Cannot create position lot with non-positive fill_qty.")
        lot_id = stable_uuid(
            "position_lot",
            (
                context.run_context.run_seed_hash,
                str(fill.fill_id),
                fill.fill_qty,
                fill.fill_price,
            ),
        )
        open_notional = normalize_decimal(fill.fill_notional, NUMERIC_18)
        row_hash = stable_hash(
            (
                context.run_context.run_seed_hash,
                str(lot_id),
                str(fill.fill_id),
                str(fill.run_id),
                fill.run_mode,
                fill.account_id,
                fill.asset_id,
                fill.hour_ts_utc,
                fill.fill_ts_utc,
                fill.fill_price,
                fill.fill_qty,
                open_notional,
                fill.fee_paid,
                fill.fill_qty,
                context.run_context.origin_hour_ts_utc,
                fill.row_hash,
            )
        )
        return PositionLotRow(
            lot_id=lot_id,
            open_fill_id=fill.fill_id,
            run_id=fill.run_id,
            run_mode=fill.run_mode,
            account_id=fill.account_id,
            asset_id=fill.asset_id,
            hour_ts_utc=fill.hour_ts_utc,
            open_ts_utc=fill.fill_ts_utc,
            open_price=fill.fill_price,
            open_qty=fill.fill_qty,
            open_notional=open_notional,
            open_fee=fill.fee_paid,
            remaining_qty=fill.fill_qty,
            origin_hour_ts_utc=context.run_context.origin_hour_ts_utc,
            parent_fill_hash=fill.row_hash,
            row_hash=row_hash,
        )

    def insert_position_lot(self, lot: PositionLotRow) -> None:
        self._db.execute(
            """
            INSERT INTO position_lot (
                lot_id, open_fill_id, run_id, run_mode, account_id, asset_id, hour_ts_utc,
                open_ts_utc, open_price, open_qty, open_notional, open_fee, remaining_qty,
                origin_hour_ts_utc, parent_fill_hash, row_hash
            ) VALUES (
                :lot_id, :open_fill_id, :run_id, :run_mode, :account_id, :asset_id, :hour_ts_utc,
                :open_ts_utc, :open_price, :open_qty, :open_notional, :open_fee, :remaining_qty,
                :origin_hour_ts_utc, :parent_fill_hash, :row_hash
            )
            """,
            {
                "lot_id": str(lot.lot_id),
                "open_fill_id": str(lot.open_fill_id),
                "run_id": str(lot.run_id),
                "run_mode": lot.run_mode,
                "account_id": lot.account_id,
                "asset_id": lot.asset_id,
                "hour_ts_utc": lot.hour_ts_utc,
                "open_ts_utc": lot.open_ts_utc,
                "open_price": lot.open_price,
                "open_qty": lot.open_qty,
                "open_notional": lot.open_notional,
                "open_fee": lot.open_fee,
                "remaining_qty": lot.remaining_qty,
                "origin_hour_ts_utc": lot.origin_hour_ts_utc,
                "parent_fill_hash": lot.parent_fill_hash,
                "row_hash": lot.row_hash,
            },
        )

    def build_executed_trade_row(
        self,
        context: ExecutionContext,
        lot_id: UUID,
        lot_asset_id: int,
        entry_ts_utc: datetime,
        entry_price: Decimal,
        lot_open_qty: Decimal,
        lot_open_fee: Decimal,
        entry_fill_slippage_cost: Decimal,
        parent_lot_hash: str,
        exit_fill: OrderFillRow,
        quantity: Decimal,
    ) -> ExecutedTradeRow:
        if quantity <= 0:
            raise DeterministicAbortError("Executed trade quantity must be positive.")
        if lot_open_qty <= 0:
            raise DeterministicAbortError("Lot open quantity must be positive.")

        entry_weight = normalize_decimal(quantity / lot_open_qty, NUMERIC_18)
        entry_fee = normalize_decimal(lot_open_fee * entry_weight, NUMERIC_18)
        entry_slippage = normalize_decimal(entry_fill_slippage_cost * entry_weight, NUMERIC_18)

        exit_weight = normalize_decimal(quantity / exit_fill.fill_qty, NUMERIC_18)
        exit_fee = normalize_decimal(exit_fill.fee_paid * exit_weight, NUMERIC_18)
        exit_slippage = normalize_decimal(exit_fill.slippage_cost * exit_weight, NUMERIC_18)

        total_fee = normalize_decimal(entry_fee + exit_fee, NUMERIC_18)
        total_slippage_cost = normalize_decimal(entry_slippage + exit_slippage, NUMERIC_18)
        gross_pnl = normalize_decimal((exit_fill.fill_price - entry_price) * quantity, NUMERIC_18)
        net_pnl = normalize_decimal(gross_pnl - total_fee - total_slippage_cost, NUMERIC_18)
        holding_hours = max(0, int((exit_fill.fill_ts_utc - entry_ts_utc).total_seconds() // 3600))

        trade_id = stable_uuid(
            "executed_trade",
            (
                context.run_context.run_seed_hash,
                str(lot_id),
                str(exit_fill.fill_id),
                quantity,
                exit_fill.fill_ts_utc,
            ),
        )
        row_hash = stable_hash(
            (
                context.run_context.run_seed_hash,
                str(trade_id),
                str(lot_id),
                str(exit_fill.run_id),
                exit_fill.run_mode,
                exit_fill.account_id,
                lot_asset_id,
                exit_fill.hour_ts_utc,
                entry_ts_utc,
                exit_fill.fill_ts_utc,
                entry_price,
                exit_fill.fill_price,
                quantity,
                gross_pnl,
                net_pnl,
                total_fee,
                total_slippage_cost,
                holding_hours,
                context.run_context.origin_hour_ts_utc,
                parent_lot_hash,
            )
        )
        return ExecutedTradeRow(
            trade_id=trade_id,
            lot_id=lot_id,
            run_id=exit_fill.run_id,
            run_mode=exit_fill.run_mode,
            account_id=exit_fill.account_id,
            asset_id=lot_asset_id,
            hour_ts_utc=exit_fill.hour_ts_utc,
            entry_ts_utc=entry_ts_utc,
            exit_ts_utc=exit_fill.fill_ts_utc,
            entry_price=normalize_decimal(entry_price, NUMERIC_18),
            exit_price=normalize_decimal(exit_fill.fill_price, NUMERIC_18),
            quantity=normalize_decimal(quantity, NUMERIC_18),
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            total_fee=total_fee,
            total_slippage_cost=total_slippage_cost,
            holding_hours=holding_hours,
            origin_hour_ts_utc=context.run_context.origin_hour_ts_utc,
            parent_lot_hash=parent_lot_hash,
            row_hash=row_hash,
        )

    def insert_executed_trade(self, trade: ExecutedTradeRow) -> None:
        self._db.execute(
            """
            INSERT INTO executed_trade (
                trade_id, lot_id, run_id, run_mode, account_id, asset_id, hour_ts_utc,
                entry_ts_utc, exit_ts_utc, entry_price, exit_price, quantity, gross_pnl,
                net_pnl, total_fee, total_slippage_cost, holding_hours, origin_hour_ts_utc,
                parent_lot_hash, row_hash
            ) VALUES (
                :trade_id, :lot_id, :run_id, :run_mode, :account_id, :asset_id, :hour_ts_utc,
                :entry_ts_utc, :exit_ts_utc, :entry_price, :exit_price, :quantity, :gross_pnl,
                :net_pnl, :total_fee, :total_slippage_cost, :holding_hours, :origin_hour_ts_utc,
                :parent_lot_hash, :row_hash
            )
            """,
            {
                "trade_id": str(trade.trade_id),
                "lot_id": str(trade.lot_id),
                "run_id": str(trade.run_id),
                "run_mode": trade.run_mode,
                "account_id": trade.account_id,
                "asset_id": trade.asset_id,
                "hour_ts_utc": trade.hour_ts_utc,
                "entry_ts_utc": trade.entry_ts_utc,
                "exit_ts_utc": trade.exit_ts_utc,
                "entry_price": trade.entry_price,
                "exit_price": trade.exit_price,
                "quantity": trade.quantity,
                "gross_pnl": trade.gross_pnl,
                "net_pnl": trade.net_pnl,
                "total_fee": trade.total_fee,
                "total_slippage_cost": trade.total_slippage_cost,
                "holding_hours": trade.holding_hours,
                "origin_hour_ts_utc": trade.origin_hour_ts_utc,
                "parent_lot_hash": trade.parent_lot_hash,
                "row_hash": trade.row_hash,
            },
        )

    def build_risk_event_row(
        self,
        context: ExecutionContext,
        event_type: str,
        severity: str,
        reason_code: str,
        detail: str,
        details: Optional[Mapping[str, Any]] = None,
    ) -> RiskEventRow:
        event_details: dict[str, Any] = {"detail": detail}
        if details is not None:
            event_details.update(dict(details))
        details_payload = json.dumps(
            event_details,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        risk_event_id = stable_uuid(
            "risk_event",
            (
                context.run_context.run_seed_hash,
                event_type,
                severity,
                reason_code,
                detail,
                context.run_context.origin_hour_ts_utc,
            ),
        )
        row_hash = stable_hash(
            (
                context.run_context.run_seed_hash,
                str(risk_event_id),
                str(context.run_context.run_id),
                context.run_context.run_mode,
                context.run_context.account_id,
                context.run_context.origin_hour_ts_utc,
                context.run_context.origin_hour_ts_utc,
                event_type,
                severity,
                reason_code,
                details_payload,
                context.risk_state.hour_ts_utc,
                context.run_context.origin_hour_ts_utc,
                context.risk_state.row_hash,
            )
        )
        return RiskEventRow(
            risk_event_id=risk_event_id,
            run_id=context.run_context.run_id,
            run_mode=context.run_context.run_mode,
            account_id=context.run_context.account_id,
            event_ts_utc=context.run_context.origin_hour_ts_utc,
            hour_ts_utc=context.run_context.origin_hour_ts_utc,
            event_type=event_type,
            severity=severity,
            reason_code=reason_code,
            details=details_payload,
            related_state_hour_ts_utc=context.risk_state.hour_ts_utc,
            origin_hour_ts_utc=context.run_context.origin_hour_ts_utc,
            parent_state_hash=context.risk_state.row_hash,
            row_hash=row_hash,
        )

    def insert_risk_event(self, risk_event: RiskEventRow) -> None:
        self._db.execute(
            """
            INSERT INTO risk_event (
                risk_event_id, run_id, run_mode, account_id, event_ts_utc, hour_ts_utc,
                event_type, severity, reason_code, details, related_state_hour_ts_utc,
                origin_hour_ts_utc, parent_state_hash, row_hash
            ) VALUES (
                :risk_event_id, :run_id, :run_mode, :account_id, :event_ts_utc, :hour_ts_utc,
                :event_type, :severity, :reason_code, CAST(:details AS jsonb), :related_state_hour_ts_utc,
                :origin_hour_ts_utc, :parent_state_hash, :row_hash
            )
            """,
            {
                "risk_event_id": str(risk_event.risk_event_id),
                "run_id": str(risk_event.run_id),
                "run_mode": risk_event.run_mode,
                "account_id": risk_event.account_id,
                "event_ts_utc": risk_event.event_ts_utc,
                "hour_ts_utc": risk_event.hour_ts_utc,
                "event_type": risk_event.event_type,
                "severity": risk_event.severity,
                "reason_code": risk_event.reason_code,
                "details": risk_event.details,
                "related_state_hour_ts_utc": risk_event.related_state_hour_ts_utc,
                "origin_hour_ts_utc": risk_event.origin_hour_ts_utc,
                "parent_state_hash": risk_event.parent_state_hash,
                "row_hash": risk_event.row_hash,
            },
        )

    def _derive_slippage_rate(self, slippage_param_hash: str) -> Decimal:
        """
        Derive a deterministic slippage rate from slippage_param_hash.

        This keeps runtime deterministic while sourcing all state from DB values.
        """
        basis_points = int(slippage_param_hash[:8], 16) % 1000
        rate = Decimal(basis_points) / Decimal(1_000_000)
        return normalize_decimal(rate, Decimal("0.000001"))
