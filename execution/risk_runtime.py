"""Deterministic runtime risk enforcement checks."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from execution.decision_engine import normalize_decimal

if TYPE_CHECKING:
    from execution.deterministic_context import ExecutionContext, PredictionState


PERCENT_OF_PV = "PERCENT_OF_PV"
ABSOLUTE_AMOUNT = "ABSOLUTE_AMOUNT"


@dataclass(frozen=True)
class RiskViolation:
    """Deterministic risk enforcement violation payload."""

    event_type: str
    severity: str
    reason_code: str
    detail: str


@dataclass(frozen=True)
class RuntimeRiskProfile:
    """Phase 3 runtime risk profile surface for configurable exposure controls."""

    profile_version: str = "schema_baseline_v1"
    max_concurrent_positions: Optional[int] = None
    total_exposure_mode: str = PERCENT_OF_PV
    max_total_exposure_pct: Optional[Decimal] = None
    max_total_exposure_amount: Optional[Decimal] = None
    cluster_exposure_mode: str = PERCENT_OF_PV
    max_cluster_exposure_pct: Optional[Decimal] = None
    max_cluster_exposure_amount: Optional[Decimal] = None
    severe_loss_drawdown_trigger: Decimal = Decimal("0.2000000000")
    volatility_feature_id: Optional[int] = None
    volatility_target: Decimal = Decimal("0.0200000000")
    volatility_scale_floor: Decimal = Decimal("0.5000000000")
    volatility_scale_ceiling: Decimal = Decimal("1.5000000000")
    hold_min_expected_return: Decimal = Decimal("0.000000000000000000")
    exit_expected_return_threshold: Decimal = Decimal("-0.005000000000000000")
    recovery_hold_prob_up_threshold: Decimal = Decimal("0.6000000000")
    recovery_exit_prob_up_threshold: Decimal = Decimal("0.3500000000")
    derisk_fraction: Decimal = Decimal("0.5000000000")
    signal_persistence_required: int = 1


@dataclass(frozen=True)
class RiskStateEvaluation:
    """Risk-state state machine evaluation result for the active context/profile."""

    state: str
    reason_code: str
    detail: str


@dataclass(frozen=True)
class VolatilitySizingEvaluation:
    adjusted_fraction: Decimal
    reason_code: str
    detail: str
    base_fraction: Decimal
    observed_volatility: Optional[Decimal]
    volatility_scale: Decimal


@dataclass(frozen=True)
class ActionEvaluation:
    action: str
    reason_code: str
    detail: str


def _resolve_runtime_profile(
    context: "ExecutionContext",
    risk_profile: Optional[RuntimeRiskProfile],
) -> RuntimeRiskProfile:
    if risk_profile is not None:
        return risk_profile
    context_profile = getattr(context, "risk_profile", None)
    if context_profile is not None:
        return RuntimeRiskProfile(
            profile_version=context_profile.profile_version,
            max_concurrent_positions=context_profile.max_concurrent_positions,
            total_exposure_mode=context_profile.total_exposure_mode,
            max_total_exposure_pct=context_profile.max_total_exposure_pct,
            max_total_exposure_amount=context_profile.max_total_exposure_amount,
            cluster_exposure_mode=context_profile.cluster_exposure_mode,
            max_cluster_exposure_pct=context_profile.max_cluster_exposure_pct,
            max_cluster_exposure_amount=context_profile.max_cluster_exposure_amount,
            severe_loss_drawdown_trigger=context_profile.severe_loss_drawdown_trigger,
            volatility_feature_id=context_profile.volatility_feature_id,
            volatility_target=context_profile.volatility_target,
            volatility_scale_floor=context_profile.volatility_scale_floor,
            volatility_scale_ceiling=context_profile.volatility_scale_ceiling,
            hold_min_expected_return=context_profile.hold_min_expected_return,
            exit_expected_return_threshold=context_profile.exit_expected_return_threshold,
            recovery_hold_prob_up_threshold=context_profile.recovery_hold_prob_up_threshold,
            recovery_exit_prob_up_threshold=context_profile.recovery_exit_prob_up_threshold,
            derisk_fraction=context_profile.derisk_fraction,
            signal_persistence_required=context_profile.signal_persistence_required,
        )
    return RuntimeRiskProfile(
        max_concurrent_positions=getattr(context.risk_state, "max_concurrent_positions", 10),
        total_exposure_mode=PERCENT_OF_PV,
        max_total_exposure_pct=context.risk_state.max_total_exposure_pct,
        cluster_exposure_mode=PERCENT_OF_PV,
        max_cluster_exposure_pct=context.risk_state.max_cluster_exposure_pct,
    )


def compute_volatility_adjusted_fraction(
    action: str,
    candidate_fraction: Decimal,
    asset_id: int,
    context: "ExecutionContext",
    risk_profile: Optional[RuntimeRiskProfile] = None,
) -> VolatilitySizingEvaluation:
    """
    Deterministically scale entry size by profile volatility controls.

    Non-entry actions always result in zero target fraction.
    """
    if action != "ENTER":
        zero_fraction = Decimal("0.0000000000")
        return VolatilitySizingEvaluation(
            adjusted_fraction=zero_fraction,
            reason_code="VOLATILITY_SIZING_NOT_APPLICABLE",
            detail="Volatility sizing is only applied to ENTER actions.",
            base_fraction=zero_fraction,
            observed_volatility=None,
            volatility_scale=Decimal("0.0000000000"),
        )

    profile = _resolve_runtime_profile(context, risk_profile)
    capped_candidate = min(candidate_fraction, context.risk_state.base_risk_fraction)
    base_fraction = normalize_decimal(max(Decimal("0"), capped_candidate), Decimal("0.0000000001"))

    volatility_state = context.find_volatility_feature(asset_id)
    if volatility_state is None or volatility_state.feature_value <= 0:
        return VolatilitySizingEvaluation(
            adjusted_fraction=base_fraction,
            reason_code="VOLATILITY_FALLBACK_BASE",
            detail="Missing or non-positive volatility input; using base fraction without scaling.",
            base_fraction=base_fraction,
            observed_volatility=None if volatility_state is None else volatility_state.feature_value,
            volatility_scale=Decimal("1.0000000000"),
        )

    epsilon = Decimal("0.0000000001")
    observed_volatility = volatility_state.feature_value
    raw_scale = profile.volatility_target / max(observed_volatility, epsilon)
    clipped_scale = min(profile.volatility_scale_ceiling, max(profile.volatility_scale_floor, raw_scale))
    volatility_scale = normalize_decimal(clipped_scale, Decimal("0.0000000001"))
    adjusted = normalize_decimal(base_fraction * volatility_scale, Decimal("0.0000000001"))
    adjusted_fraction = min(Decimal("1.0000000000"), max(Decimal("0"), adjusted))

    return VolatilitySizingEvaluation(
        adjusted_fraction=adjusted_fraction,
        reason_code="VOLATILITY_SIZED",
        detail="Applied deterministic volatility-adjusted sizing.",
        base_fraction=base_fraction,
        observed_volatility=observed_volatility,
        volatility_scale=volatility_scale,
    )


def evaluate_risk_state_machine(
    context: "ExecutionContext",
    risk_profile: Optional[RuntimeRiskProfile] = None,
) -> RiskStateEvaluation:
    """Evaluate deterministic risk-state mode for admission and management behavior."""
    profile = _resolve_runtime_profile(context, risk_profile)
    if context.risk_state.kill_switch_active:
        return RiskStateEvaluation(
            state="KILL_SWITCH_LOCKDOWN",
            reason_code="KILL_SWITCH_ACTIVE",
            detail="Kill switch is active; new entries are blocked.",
        )
    if context.risk_state.halt_new_entries:
        return RiskStateEvaluation(
            state="ENTRY_HALT",
            reason_code="HALT_NEW_ENTRIES_ACTIVE",
            detail="Drawdown/risk halt is active; new entries are blocked.",
        )

    drawdown_pct = getattr(context.risk_state, "drawdown_pct", Decimal("0"))
    if drawdown_pct >= profile.severe_loss_drawdown_trigger:
        return RiskStateEvaluation(
            state="SEVERE_LOSS_RECOVERY",
            reason_code="SEVERE_LOSS_RECOVERY_MODE",
            detail="Severe-loss recovery mode active; prioritize de-risking over new exposure.",
        )

    return RiskStateEvaluation(
        state="NORMAL",
        reason_code="NORMAL",
        detail="Risk state within normal admission bounds.",
    )


def evaluate_adaptive_horizon_action(
    candidate_action: str,
    prediction: "PredictionState",
    context: "ExecutionContext",
    risk_profile: Optional[RuntimeRiskProfile] = None,
) -> ActionEvaluation:
    """
    Deterministically apply adaptive horizon action overrides for open positions.

    Persistence policy is safety-biased for open positions: when a negative
    signal is detected but persistence confirmations are still pending, EXIT-like
    intent is deferred to HOLD.
    """
    profile = _resolve_runtime_profile(context, risk_profile)
    position = context.find_position(prediction.asset_id)
    if position is None or position.quantity <= 0:
        return ActionEvaluation(
            action=candidate_action,
            reason_code="ADAPTIVE_HORIZON_NO_OPEN_POSITION",
            detail="No open position exists for adaptive horizon override.",
        )

    if candidate_action == "ENTER":
        if (
            prediction.expected_return <= profile.exit_expected_return_threshold
            and profile.signal_persistence_required > 1
        ):
            return ActionEvaluation(
                action="HOLD",
                reason_code="ADAPTIVE_HORIZON_PERSISTENCE_PENDING",
                detail=(
                    "Negative signal detected but persistence window requires additional confirmations; "
                    "forcing HOLD until persistence is satisfied."
                ),
            )
        return ActionEvaluation(
            action=candidate_action,
            reason_code="ADAPTIVE_HORIZON_NO_OVERRIDE",
            detail="Entry candidates are governed by admission gates, not horizon extension logic.",
        )

    if prediction.expected_return >= profile.hold_min_expected_return:
        return ActionEvaluation(
            action="HOLD",
            reason_code="ADAPTIVE_HORIZON_HOLD_EXTENDED",
            detail="Expected return remains above hold threshold; extending hold horizon.",
        )

    if prediction.expected_return <= profile.exit_expected_return_threshold:
        if profile.signal_persistence_required <= 1:
            return ActionEvaluation(
                action="EXIT",
                reason_code="ADAPTIVE_HORIZON_EXIT_PERSISTENT_NEGATIVE",
                detail="Negative expectation threshold breached with satisfied persistence policy.",
            )
        return ActionEvaluation(
            action="HOLD",
            reason_code="ADAPTIVE_HORIZON_PERSISTENCE_PENDING",
            detail=(
                "Negative signal detected but persistence window requires additional confirmations; "
                "forcing HOLD until persistence is satisfied."
            ),
        )

    return ActionEvaluation(
        action=candidate_action,
        reason_code="ADAPTIVE_HORIZON_NO_OVERRIDE",
        detail="Adaptive horizon thresholds did not require action override.",
    )


def evaluate_severe_loss_recovery_action(
    candidate_action: str,
    prediction: "PredictionState",
    context: "ExecutionContext",
    risk_profile: Optional[RuntimeRiskProfile] = None,
) -> ActionEvaluation:
    """
    Determine severe-loss recovery branch action in prediction-led mode.
    """
    profile = _resolve_runtime_profile(context, risk_profile)
    state = evaluate_risk_state_machine(context, risk_profile)
    if state.state != "SEVERE_LOSS_RECOVERY":
        return ActionEvaluation(
            action=candidate_action,
            reason_code="NO_SEVERE_LOSS_RECOVERY",
            detail="Risk state is not in severe-loss recovery mode.",
        )

    if candidate_action == "ENTER":
        return ActionEvaluation(
            action=candidate_action,
            reason_code="SEVERE_RECOVERY_ENTRY_PENDING_GATE",
            detail="Entry candidate is deferred to severe-loss entry gate enforcement.",
        )

    if prediction.prob_up >= profile.recovery_hold_prob_up_threshold:
        return ActionEvaluation(
            action="HOLD",
            reason_code="SEVERE_RECOVERY_HOLD",
            detail="Recovery probability is credible; continue holding.",
        )

    if (
        prediction.prob_up <= profile.recovery_exit_prob_up_threshold
        or prediction.expected_return <= profile.exit_expected_return_threshold
    ):
        return ActionEvaluation(
            action="EXIT",
            reason_code="SEVERE_RECOVERY_EXIT",
            detail="Recovery outlook is weak; full exit is required.",
        )

    return ActionEvaluation(
        action="HOLD",
        reason_code="SEVERE_RECOVERY_DERISK_INTENT",
        detail=(
            "Mixed recovery outlook; emit deterministic de-risk intent "
            f"with derisk_fraction={profile.derisk_fraction}."
        ),
    )


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
    """
    Enforce halt/kill-switch runtime admission rules.

    Kill-switch precedence is strict: when both halt and kill switch are active,
    the emitted gating reason is KILL_SWITCH_ACTIVE.
    """
    if action != "ENTER":
        return tuple()
    if context.risk_state.kill_switch_active:
        return (
            RiskViolation(
                event_type="RISK_GATE",
                severity="CRITICAL",
                reason_code="KILL_SWITCH_ACTIVE",
                detail="kill_switch_active is TRUE; new entries are blocked.",
            ),
        )
    if context.risk_state.halt_new_entries:
        return (
            RiskViolation(
                event_type="RISK_GATE",
                severity="HIGH",
                reason_code="HALT_NEW_ENTRIES_ACTIVE",
                detail="halt_new_entries is TRUE; new entries are blocked.",
            ),
        )
    return tuple()


def enforce_position_count_cap(
    action: str,
    context: "ExecutionContext",
    risk_profile: Optional[RuntimeRiskProfile] = None,
) -> tuple[RiskViolation, ...]:
    """Enforce max concurrent position admission cap from active profile."""
    if action != "ENTER":
        return tuple()

    profile = _resolve_runtime_profile(context, risk_profile)
    max_positions = profile.max_concurrent_positions
    if max_positions is None:
        max_positions = getattr(context.risk_state, "max_concurrent_positions", 10)

    if max_positions < 0:
        return (
            RiskViolation(
                event_type="CAPITAL_RULE",
                severity="CRITICAL",
                reason_code="INVALID_MAX_CONCURRENT_POSITIONS_CONFIG",
                detail="max_concurrent_positions must be >= 0.",
            ),
        )

    if context.capital_state.open_position_count >= max_positions:
        return (
            RiskViolation(
                event_type="CAPITAL_RULE",
                severity="HIGH",
                reason_code="MAX_CONCURRENT_POSITIONS_EXCEEDED",
                detail="open_position_count exceeds max_concurrent_positions.",
            ),
        )

    return tuple()


def enforce_severe_loss_entry_gate(
    action: str,
    context: "ExecutionContext",
    risk_profile: Optional[RuntimeRiskProfile] = None,
) -> tuple[RiskViolation, ...]:
    """
    Block new risk admission in severe-loss recovery mode.

    This preserves adaptive management of existing positions while restricting
    additional exposure when the active profile marks drawdown as severe.
    """
    if action != "ENTER":
        return tuple()

    evaluation = evaluate_risk_state_machine(context, risk_profile)
    if evaluation.state != "SEVERE_LOSS_RECOVERY":
        return tuple()

    return (
        RiskViolation(
            event_type="RISK_GATE",
            severity="HIGH",
            reason_code="SEVERE_LOSS_RECOVERY_ENTRY_BLOCKED",
            detail="Severe-loss recovery mode is active; new entries are blocked.",
        ),
    )


def enforce_capital_preservation(
    action: str,
    target_position_notional: Decimal,
    context: "ExecutionContext",
    risk_profile: Optional[RuntimeRiskProfile] = None,
) -> tuple[RiskViolation, ...]:
    """Enforce deterministic capital and exposure preservation rules."""
    if action != "ENTER":
        return tuple()

    profile = _resolve_runtime_profile(context, risk_profile)
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

    total_mode = profile.total_exposure_mode.upper()
    if total_mode == PERCENT_OF_PV:
        cap_pct = profile.max_total_exposure_pct or context.risk_state.max_total_exposure_pct
        projected_exposure_pct = normalize_decimal(
            context.capital_state.total_exposure_pct
            + (target_position_notional / context.capital_state.portfolio_value)
        )
        if projected_exposure_pct > cap_pct:
            violations.append(
                RiskViolation(
                    event_type="CAPITAL_RULE",
                    severity="HIGH",
                    reason_code="TOTAL_EXPOSURE_CAP_EXCEEDED",
                    detail="Projected total exposure exceeds max_total_exposure_pct.",
                )
            )
        return tuple(violations)

    if total_mode == ABSOLUTE_AMOUNT:
        cap_amount = profile.max_total_exposure_amount
        if cap_amount is None or cap_amount <= 0:
            violations.append(
                RiskViolation(
                    event_type="CAPITAL_RULE",
                    severity="CRITICAL",
                    reason_code="INVALID_TOTAL_EXPOSURE_ABSOLUTE_CAP",
                    detail="ABSOLUTE_AMOUNT mode requires max_total_exposure_amount > 0.",
                )
            )
            return tuple(violations)

        current_exposure_notional = normalize_decimal(
            context.capital_state.total_exposure_pct * context.capital_state.portfolio_value
        )
        projected_exposure_notional = normalize_decimal(
            current_exposure_notional + target_position_notional
        )
        if projected_exposure_notional > cap_amount:
            violations.append(
                RiskViolation(
                    event_type="CAPITAL_RULE",
                    severity="HIGH",
                    reason_code="TOTAL_EXPOSURE_AMOUNT_CAP_EXCEEDED",
                    detail="Projected total exposure exceeds max_total_exposure_amount.",
                )
            )
        return tuple(violations)

    violations.append(
        RiskViolation(
            event_type="CAPITAL_RULE",
            severity="CRITICAL",
            reason_code="INVALID_TOTAL_EXPOSURE_MODE",
            detail=f"Unsupported total exposure mode: {profile.total_exposure_mode}.",
        )
    )
    return tuple(violations)


def enforce_cluster_cap(
    action: str,
    asset_id: int,
    target_position_notional: Decimal,
    context: "ExecutionContext",
    risk_profile: Optional[RuntimeRiskProfile] = None,
) -> tuple[RiskViolation, ...]:
    """Enforce deterministic cluster-cap admission rule."""
    if action != "ENTER":
        return tuple()

    profile = _resolve_runtime_profile(context, risk_profile)
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

    cluster_mode = profile.cluster_exposure_mode.upper()
    if cluster_mode == PERCENT_OF_PV:
        cap_pct = profile.max_cluster_exposure_pct or cluster_state.max_cluster_exposure_pct
        projected_cluster_pct = normalize_decimal(
            cluster_state.exposure_pct + (target_position_notional / context.capital_state.portfolio_value)
        )
        if projected_cluster_pct > cap_pct:
            return (
                RiskViolation(
                    event_type="CLUSTER_CAP",
                    severity="HIGH",
                    reason_code="CLUSTER_CAP_EXCEEDED",
                    detail="Projected cluster exposure exceeds max_cluster_exposure_pct.",
                ),
            )
        return tuple()

    if cluster_mode == ABSOLUTE_AMOUNT:
        cap_amount = profile.max_cluster_exposure_amount
        if cap_amount is None or cap_amount <= 0:
            return (
                RiskViolation(
                    event_type="CLUSTER_CAP",
                    severity="CRITICAL",
                    reason_code="INVALID_CLUSTER_EXPOSURE_ABSOLUTE_CAP",
                    detail="ABSOLUTE_AMOUNT mode requires max_cluster_exposure_amount > 0.",
                ),
            )

        current_cluster_notional = normalize_decimal(
            cluster_state.exposure_pct * context.capital_state.portfolio_value
        )
        projected_cluster_notional = normalize_decimal(
            current_cluster_notional + target_position_notional
        )
        if projected_cluster_notional > cap_amount:
            return (
                RiskViolation(
                    event_type="CLUSTER_CAP",
                    severity="HIGH",
                    reason_code="CLUSTER_CAP_AMOUNT_EXCEEDED",
                    detail="Projected cluster exposure exceeds max_cluster_exposure_amount.",
                ),
            )
        return tuple()

    return (
        RiskViolation(
            event_type="CLUSTER_CAP",
            severity="CRITICAL",
            reason_code="INVALID_CLUSTER_EXPOSURE_MODE",
            detail=f"Unsupported cluster exposure mode: {profile.cluster_exposure_mode}.",
        ),
    )
