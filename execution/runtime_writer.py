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
        order_id = stable_uuid(
            "order_request",
            (
                context.run_context.run_seed_hash,
                str(signal.signal_id),
                signal.row_hash,
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
                context.run_context.origin_hour_ts_utc,
                "BUY",
                "MARKET",
                "IOC",
                requested_qty,
                requested_notional,
                context.capital_state.cash_balance,
                1,
                "NEW",
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
            request_ts_utc=context.run_context.origin_hour_ts_utc,
            hour_ts_utc=context.run_context.origin_hour_ts_utc,
            side="BUY",
            order_type="MARKET",
            tif="IOC",
            limit_price=None,
            requested_qty=requested_qty,
            requested_notional=requested_notional,
            pre_order_cash_available=normalize_decimal(context.capital_state.cash_balance, NUMERIC_18),
            risk_check_passed=True,
            status="NEW",
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

    def build_risk_event_row(
        self,
        context: ExecutionContext,
        event_type: str,
        severity: str,
        reason_code: str,
        detail: str,
    ) -> RiskEventRow:
        details_payload = json.dumps({"detail": detail}, sort_keys=True, separators=(",", ":"))
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
