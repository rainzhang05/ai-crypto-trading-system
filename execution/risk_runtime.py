"""Deterministic runtime risk enforcement checks."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from execution.decision_engine import normalize_decimal

if TYPE_CHECKING:
    from execution.deterministic_context import ExecutionContext


@dataclass(frozen=True)
class RiskViolation:
    """Deterministic risk enforcement violation payload."""

    event_type: str
    severity: str
    reason_code: str
    detail: str


def enforce_cross_account_isolation(context: "ExecutionContext") -> tuple[RiskViolation, ...]:
    """Validate account isolation across runtime state surfaces."""
    account_id = context.run_context.account_id
    violations: list[RiskViolation] = []
    if context.risk_state.account_id != account_id:
        violations.append(
            RiskViolation(
                event_type="RISK_GATE",
                severity="CRITICAL",
                reason_code="CROSS_ACCOUNT_RISK_STATE",
                detail="risk_hourly_state account_id does not match run_context account_id.",
            )
        )
    if context.capital_state.account_id != account_id:
        violations.append(
            RiskViolation(
                event_type="RISK_GATE",
                severity="CRITICAL",
                reason_code="CROSS_ACCOUNT_CAPITAL_STATE",
                detail="portfolio_hourly_state account_id does not match run_context account_id.",
            )
        )
    for cluster_state in context.cluster_states:
        if cluster_state.account_id != account_id:
            violations.append(
                RiskViolation(
                    event_type="RISK_GATE",
                    severity="CRITICAL",
                    reason_code="CROSS_ACCOUNT_CLUSTER_STATE",
                    detail="cluster_exposure_hourly_state account_id mismatch.",
                )
            )
            break
    return tuple(violations)


def enforce_runtime_risk_gate(action: str, context: "ExecutionContext") -> tuple[RiskViolation, ...]:
    """Enforce halt/kill-switch runtime admission rules."""
    if action != "ENTER":
        return tuple()
    if context.risk_state.halt_new_entries:
        return (
            RiskViolation(
                event_type="RISK_GATE",
                severity="HIGH",
                reason_code="HALT_NEW_ENTRIES_ACTIVE",
                detail="halt_new_entries is TRUE; new entries are blocked.",
            ),
        )
    if context.risk_state.kill_switch_active:
        return (
            RiskViolation(
                event_type="RISK_GATE",
                severity="CRITICAL",
                reason_code="KILL_SWITCH_ACTIVE",
                detail="kill_switch_active is TRUE; new entries are blocked.",
            ),
        )
    return tuple()


def enforce_capital_preservation(
    action: str,
    target_position_notional: Decimal,
    context: "ExecutionContext",
) -> tuple[RiskViolation, ...]:
    """Enforce deterministic capital and exposure preservation rules."""
    if action != "ENTER":
        return tuple()

    violations: list[RiskViolation] = []
    if target_position_notional > context.capital_state.cash_balance:
        violations.append(
            RiskViolation(
                event_type="CAPITAL_RULE",
                severity="HIGH",
                reason_code="INSUFFICIENT_AVAILABLE_CASH",
                detail="target_position_notional exceeds cash_balance.",
            )
        )

    if context.capital_state.portfolio_value <= 0:
        violations.append(
            RiskViolation(
                event_type="CAPITAL_RULE",
                severity="HIGH",
                reason_code="NON_POSITIVE_PORTFOLIO_VALUE",
                detail="portfolio_value is non-positive; order admission is blocked.",
            )
        )
        return tuple(violations)

    projected_exposure_pct = normalize_decimal(
        context.capital_state.total_exposure_pct
        + (target_position_notional / context.capital_state.portfolio_value)
    )
    if projected_exposure_pct > context.risk_state.max_total_exposure_pct:
        violations.append(
            RiskViolation(
                event_type="CAPITAL_RULE",
                severity="HIGH",
                reason_code="TOTAL_EXPOSURE_CAP_EXCEEDED",
                detail="Projected total exposure exceeds max_total_exposure_pct.",
            )
        )
    return tuple(violations)


def enforce_cluster_cap(
    action: str,
    asset_id: int,
    target_position_notional: Decimal,
    context: "ExecutionContext",
) -> tuple[RiskViolation, ...]:
    """Enforce deterministic cluster-cap admission rule."""
    if action != "ENTER":
        return tuple()

    membership = context.find_membership(asset_id)
    if membership is None:
        return (
            RiskViolation(
                event_type="CLUSTER_CAP",
                severity="HIGH",
                reason_code="MISSING_CLUSTER_MEMBERSHIP",
                detail=f"No active cluster membership for asset_id={asset_id}.",
            ),
        )
    cluster_state = context.find_cluster_state(membership.cluster_id)
    if cluster_state is None:
        return (
            RiskViolation(
                event_type="CLUSTER_CAP",
                severity="HIGH",
                reason_code="MISSING_CLUSTER_STATE",
                detail=f"No cluster exposure state for cluster_id={membership.cluster_id}.",
            ),
        )

    if context.capital_state.portfolio_value <= 0:
        return (
            RiskViolation(
                event_type="CLUSTER_CAP",
                severity="HIGH",
                reason_code="NON_POSITIVE_PORTFOLIO_VALUE",
                detail="portfolio_value is non-positive; cannot compute cluster cap projection.",
            ),
        )

    projected_cluster_pct = normalize_decimal(
        cluster_state.exposure_pct + (target_position_notional / context.capital_state.portfolio_value)
    )
    if projected_cluster_pct > cluster_state.max_cluster_exposure_pct:
        return (
            RiskViolation(
                event_type="CLUSTER_CAP",
                severity="HIGH",
                reason_code="CLUSTER_CAP_EXCEEDED",
                detail="Projected cluster exposure exceeds max_cluster_exposure_pct.",
            ),
        )
    return tuple()
