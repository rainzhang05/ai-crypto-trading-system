"""Deterministic runtime execution orchestration and replay harness."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping, Optional, Protocol, Sequence
from uuid import UUID

from execution.activation_gate import enforce_activation_gate
from execution.decision_engine import deterministic_decision, stable_hash
from execution.deterministic_context import (
    DeterministicAbortError,
    DeterministicContextBuilder,
    ExecutionContext,
    PredictionState,
)
from execution.risk_runtime import (
    RiskViolation,
    enforce_capital_preservation,
    enforce_cluster_cap,
    enforce_cross_account_isolation,
    enforce_runtime_risk_gate,
)
from execution.runtime_writer import (
    AppendOnlyRuntimeWriter,
    OrderRequestRow,
    RiskEventRow,
    RuntimeWriteResult,
    TradeSignalRow,
)


class RuntimeDatabase(Protocol):
    """Combined read/write DB protocol needed by execute/replay functions."""

    def fetch_one(self, sql: str, params: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
        """Fetch one row."""

    def fetch_all(self, sql: str, params: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        """Fetch all rows."""

    def execute(self, sql: str, params: Mapping[str, Any]) -> None:
        """Execute SQL mutation."""


@dataclass(frozen=True)
class ReplayMismatch:
    table_name: str
    key: str
    field_name: str
    expected: str
    actual: str


@dataclass(frozen=True)
class ReplayReport:
    mismatch_count: int
    mismatches: tuple[ReplayMismatch, ...]


def execute_hour(
    db: RuntimeDatabase,
    run_id: UUID,
    account_id: int,
    run_mode: str,
    hour_ts_utc: datetime,
) -> RuntimeWriteResult:
    """Execute deterministic runtime writes for one run/account/hour key."""
    builder = DeterministicContextBuilder(db)
    context = builder.build_context(run_id, account_id, run_mode, hour_ts_utc)
    writer = AppendOnlyRuntimeWriter(db)

    begin = getattr(db, "begin", None)
    commit = getattr(db, "commit", None)
    rollback = getattr(db, "rollback", None)
    tx_started = False

    try:
        if callable(begin):
            begin()
            tx_started = True

        # Preserve and validate ledger continuity before writes.
        writer.assert_ledger_continuity(
            account_id=context.run_context.account_id,
            run_mode=context.run_context.run_mode,
        )
        planned = _plan_runtime_artifacts(context, writer)

        for signal in planned.trade_signals:
            writer.insert_trade_signal(signal)
        for order in planned.order_requests:
            writer.insert_order_request(order)
        for risk_event in planned.risk_events:
            writer.insert_risk_event(risk_event)

        # Preserve and validate ledger continuity after writes.
        writer.assert_ledger_continuity(
            account_id=context.run_context.account_id,
            run_mode=context.run_context.run_mode,
        )

        if tx_started and callable(commit):
            commit()
        return planned
    except Exception:
        if tx_started and callable(rollback):
            rollback()
        raise


def replay_hour(
    db: RuntimeDatabase,
    run_id: UUID,
    account_id: int,
    hour_ts_utc: datetime,
) -> ReplayReport:
    """Reconstruct, recompute, and compare deterministic runtime artifacts."""
    run_ctx = db.fetch_one(
        """
        SELECT run_mode
        FROM run_context
        WHERE run_id = :run_id
          AND account_id = :account_id
          AND origin_hour_ts_utc = :hour_ts_utc
        """,
        {"run_id": str(run_id), "account_id": account_id, "hour_ts_utc": hour_ts_utc},
    )
    if run_ctx is None:
        raise DeterministicAbortError("run_context not found for replay key.")

    run_mode = str(run_ctx["run_mode"])
    builder = DeterministicContextBuilder(db)
    context = builder.build_context(run_id, account_id, run_mode, hour_ts_utc)
    writer = AppendOnlyRuntimeWriter(db)
    expected = _plan_runtime_artifacts(context, writer)

    stored_signals = db.fetch_all(
        """
        SELECT signal_id, decision_hash, row_hash
        FROM trade_signal
        WHERE run_id = :run_id
          AND account_id = :account_id
          AND hour_ts_utc = :hour_ts_utc
        ORDER BY signal_id ASC
        """,
        {"run_id": str(run_id), "account_id": account_id, "hour_ts_utc": hour_ts_utc},
    )
    stored_orders = db.fetch_all(
        """
        SELECT order_id, row_hash
        FROM order_request
        WHERE run_id = :run_id
          AND account_id = :account_id
          AND origin_hour_ts_utc = :hour_ts_utc
        ORDER BY order_id ASC
        """,
        {"run_id": str(run_id), "account_id": account_id, "hour_ts_utc": hour_ts_utc},
    )
    stored_risk_events = db.fetch_all(
        """
        SELECT risk_event_id, row_hash
        FROM risk_event
        WHERE run_id = :run_id
          AND account_id = :account_id
          AND origin_hour_ts_utc = :hour_ts_utc
        ORDER BY risk_event_id ASC
        """,
        {"run_id": str(run_id), "account_id": account_id, "hour_ts_utc": hour_ts_utc},
    )

    mismatches: list[ReplayMismatch] = []
    mismatches.extend(_compare_signals(expected.trade_signals, stored_signals))
    mismatches.extend(_compare_orders(expected.order_requests, stored_orders))
    mismatches.extend(_compare_risk_events(expected.risk_events, stored_risk_events))

    return ReplayReport(mismatch_count=len(mismatches), mismatches=tuple(mismatches))


def _plan_runtime_artifacts(
    context: ExecutionContext,
    writer: AppendOnlyRuntimeWriter,
) -> RuntimeWriteResult:
    trade_signals: list[TradeSignalRow] = []
    order_requests: list[OrderRequestRow] = []
    risk_events: list[RiskEventRow] = []
    emitted_risk_events: set[tuple[str, str, str, str]] = set()

    for prediction in context.predictions:
        regime = context.find_regime(prediction.asset_id, prediction.model_version_id)
        if regime is None:
            raise DeterministicAbortError(
                f"Missing regime for asset_id={prediction.asset_id} "
                f"model_version_id={prediction.model_version_id}."
            )

        cluster_hash = _cluster_state_hash_for_prediction(context, prediction)
        decision = deterministic_decision(
            prediction_hash=prediction.row_hash,
            regime_hash=regime.row_hash,
            capital_state_hash=context.capital_state.row_hash,
            risk_state_hash=context.risk_state.row_hash,
            cluster_state_hash=cluster_hash,
        )

        activation = (
            context.find_activation(prediction.activation_id)
            if prediction.activation_id is not None
            else None
        )
        activation_result = enforce_activation_gate(
            run_mode=context.run_context.run_mode,
            hour_ts_utc=context.run_context.origin_hour_ts_utc,
            model_version_id=prediction.model_version_id,
            activation=activation,
        )

        preliminary_signal = writer.build_trade_signal_row(
            context=context,
            prediction=prediction,
            regime=regime,
            decision=decision,
            action_override=None,
        )

        violations: list[RiskViolation] = []
        violations.extend(enforce_cross_account_isolation(context))
        if not activation_result.allowed:
            violations.append(
                RiskViolation(
                    event_type="ACTIVATION_GATE",
                    severity="HIGH",
                    reason_code=activation_result.reason_code,
                    detail=activation_result.detail,
                )
            )
        violations.extend(enforce_runtime_risk_gate(preliminary_signal.action, context))
        if preliminary_signal.action == "ENTER" and preliminary_signal.net_edge <= Decimal("0"):
            violations.append(
                RiskViolation(
                    event_type="RISK_GATE",
                    severity="MEDIUM",
                    reason_code="ENTER_COST_GATE_FAILED",
                    detail="Expected return does not exceed deterministic transaction cost.",
                )
            )
        violations.extend(
            enforce_capital_preservation(
                preliminary_signal.action,
                preliminary_signal.target_position_notional,
                context,
            )
        )
        violations.extend(
            enforce_cluster_cap(
                preliminary_signal.action,
                prediction.asset_id,
                preliminary_signal.target_position_notional,
                context,
            )
        )

        action_override = "HOLD" if violations else None
        final_signal = writer.build_trade_signal_row(
            context=context,
            prediction=prediction,
            regime=regime,
            decision=decision,
            action_override=action_override,
        )
        trade_signals.append(final_signal)

        if not violations:
            order = writer.build_order_request_row(context=context, signal=final_signal)
            if order is not None:
                order_requests.append(order)
        else:
            for violation in violations:
                # De-duplicate semantically identical run-hour violations so
                # repeated asset-level blocks do not collide on deterministic IDs.
                event_key = (
                    violation.event_type,
                    violation.severity,
                    violation.reason_code,
                    violation.detail,
                )
                if event_key in emitted_risk_events:
                    continue
                emitted_risk_events.add(event_key)
                risk_events.append(
                    writer.build_risk_event_row(
                        context=context,
                        event_type=violation.event_type,
                        severity=violation.severity,
                        reason_code=violation.reason_code,
                        detail=violation.detail,
                    )
                )

    return RuntimeWriteResult(
        trade_signals=tuple(trade_signals),
        order_requests=tuple(order_requests),
        risk_events=tuple(risk_events),
    )


def _cluster_state_hash_for_prediction(context: ExecutionContext, prediction: PredictionState) -> str:
    membership = context.find_membership(prediction.asset_id)
    if membership is None:
        raise DeterministicAbortError(f"Missing cluster membership for asset_id={prediction.asset_id}.")
    cluster_state = context.find_cluster_state(membership.cluster_id)
    if cluster_state is None:
        raise DeterministicAbortError(f"Missing cluster state for cluster_id={membership.cluster_id}.")
    return stable_hash(
        (
            context.run_context.run_seed_hash,
            membership.membership_hash,
            cluster_state.state_hash,
            cluster_state.parent_risk_hash,
            cluster_state.row_hash,
        )
    )


def _compare_signals(
    expected: Sequence[TradeSignalRow],
    stored: Sequence[Mapping[str, Any]],
) -> list[ReplayMismatch]:
    mismatches: list[ReplayMismatch] = []
    expected_map = {str(row.signal_id): row for row in expected}
    stored_map = {str(row["signal_id"]): row for row in stored}

    all_keys = sorted(set(expected_map.keys()) | set(stored_map.keys()))
    for key in all_keys:
        if key not in expected_map:
            mismatches.append(
                ReplayMismatch("trade_signal", key, "presence", "expected_absent", "stored_present")
            )
            continue
        if key not in stored_map:
            mismatches.append(
                ReplayMismatch("trade_signal", key, "presence", "expected_present", "stored_absent")
            )
            continue
        expected_row = expected_map[key]
        stored_row = stored_map[key]
        if str(stored_row["decision_hash"]) != expected_row.decision_hash:
            mismatches.append(
                ReplayMismatch(
                    "trade_signal",
                    key,
                    "decision_hash",
                    expected_row.decision_hash,
                    str(stored_row["decision_hash"]),
                )
            )
        if str(stored_row["row_hash"]) != expected_row.row_hash:
            mismatches.append(
                ReplayMismatch(
                    "trade_signal",
                    key,
                    "row_hash",
                    expected_row.row_hash,
                    str(stored_row["row_hash"]),
                )
            )
    return mismatches


def _compare_orders(
    expected: Sequence[OrderRequestRow],
    stored: Sequence[Mapping[str, Any]],
) -> list[ReplayMismatch]:
    mismatches: list[ReplayMismatch] = []
    expected_map = {str(row.order_id): row for row in expected}
    stored_map = {str(row["order_id"]): row for row in stored}
    all_keys = sorted(set(expected_map.keys()) | set(stored_map.keys()))
    for key in all_keys:
        if key not in expected_map:
            mismatches.append(
                ReplayMismatch("order_request", key, "presence", "expected_absent", "stored_present")
            )
            continue
        if key not in stored_map:
            mismatches.append(
                ReplayMismatch("order_request", key, "presence", "expected_present", "stored_absent")
            )
            continue
        if str(stored_map[key]["row_hash"]) != expected_map[key].row_hash:
            mismatches.append(
                ReplayMismatch(
                    "order_request",
                    key,
                    "row_hash",
                    expected_map[key].row_hash,
                    str(stored_map[key]["row_hash"]),
                )
            )
    return mismatches


def _compare_risk_events(
    expected: Sequence[RiskEventRow],
    stored: Sequence[Mapping[str, Any]],
) -> list[ReplayMismatch]:
    mismatches: list[ReplayMismatch] = []
    expected_map = {str(row.risk_event_id): row for row in expected}
    stored_map = {str(row["risk_event_id"]): row for row in stored}
    all_keys = sorted(set(expected_map.keys()) | set(stored_map.keys()))
    for key in all_keys:
        if key not in expected_map:
            mismatches.append(
                ReplayMismatch("risk_event", key, "presence", "expected_absent", "stored_present")
            )
            continue
        if key not in stored_map:
            mismatches.append(
                ReplayMismatch("risk_event", key, "presence", "expected_present", "stored_absent")
            )
            continue
        if str(stored_map[key]["row_hash"]) != expected_map[key].row_hash:
            mismatches.append(
                ReplayMismatch(
                    "risk_event",
                    key,
                    "row_hash",
                    expected_map[key].row_hash,
                    str(stored_map[key]["row_hash"]),
                )
            )
    return mismatches
