"""Unit tests for runtime risk enforcement checks."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from execution.risk_runtime import (
    ABSOLUTE_AMOUNT,
    RuntimeRiskProfile,
    compute_volatility_adjusted_fraction,
    enforce_capital_preservation,
    enforce_cluster_cap,
    enforce_cross_account_isolation,
    enforce_position_count_cap,
    enforce_runtime_risk_gate,
    enforce_severe_loss_entry_gate,
    evaluate_adaptive_horizon_action,
    evaluate_risk_state_machine,
    evaluate_severe_loss_recovery_action,
)


@dataclass(frozen=True)
class _RiskState:
    account_id: int
    hour_ts_utc: datetime
    source_run_id: UUID
    drawdown_pct: Decimal
    drawdown_tier: str
    max_concurrent_positions: int
    halt_new_entries: bool
    kill_switch_active: bool
    max_total_exposure_pct: Decimal
    max_cluster_exposure_pct: Decimal
    row_hash: str
    base_risk_fraction: Decimal = Decimal("0.0200000000")


@dataclass(frozen=True)
class _CapitalState:
    account_id: int
    portfolio_value: Decimal
    cash_balance: Decimal
    total_exposure_pct: Decimal
    open_position_count: int


@dataclass(frozen=True)
class _Membership:
    asset_id: int
    cluster_id: int


@dataclass(frozen=True)
class _ClusterState:
    account_id: int
    cluster_id: int
    exposure_pct: Decimal
    max_cluster_exposure_pct: Decimal
    parent_risk_hash: str


@dataclass(frozen=True)
class _VolatilityFeatureState:
    asset_id: int
    feature_id: int
    feature_value: Decimal
    row_hash: str


@dataclass(frozen=True)
class _PositionState:
    asset_id: int
    quantity: Decimal
    exposure_pct: Decimal
    unrealized_pnl: Decimal


@dataclass(frozen=True)
class _RiskProfileState:
    profile_version: str
    total_exposure_mode: str
    max_total_exposure_pct: Decimal
    max_total_exposure_amount: Decimal | None
    cluster_exposure_mode: str
    max_cluster_exposure_pct: Decimal
    max_cluster_exposure_amount: Decimal | None
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


class _Context:
    def __init__(self) -> None:
        run_id = UUID("11111111-1111-4111-8111-111111111111")
        hour = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.run_context = type("RunCtx", (), {"account_id": 1})
        self.risk_state = _RiskState(
            account_id=1,
            hour_ts_utc=hour,
            source_run_id=run_id,
            drawdown_pct=Decimal("0.0100000000"),
            drawdown_tier="NORMAL",
            max_concurrent_positions=10,
            halt_new_entries=False,
            kill_switch_active=False,
            max_total_exposure_pct=Decimal("0.2000000000"),
            max_cluster_exposure_pct=Decimal("0.0800000000"),
            row_hash="r" * 64,
        )
        self.capital_state = _CapitalState(
            account_id=1,
            portfolio_value=Decimal("10000"),
            cash_balance=Decimal("1000"),
            total_exposure_pct=Decimal("0.0100000000"),
            open_position_count=1,
        )
        self.cluster_states = (
            _ClusterState(
                account_id=1,
                cluster_id=7,
                exposure_pct=Decimal("0.0200000000"),
                max_cluster_exposure_pct=Decimal("0.0800000000"),
                parent_risk_hash="r" * 64,
            ),
        )
        self._memberships = {1: _Membership(asset_id=1, cluster_id=7)}
        self._volatility_features = {
            1: _VolatilityFeatureState(
                asset_id=1,
                feature_id=9001,
                feature_value=Decimal("0.0200000000"),
                row_hash="v" * 64,
            )
        }
        self._positions = {
            1: _PositionState(
                asset_id=1,
                quantity=Decimal("1.000000000000000000"),
                exposure_pct=Decimal("0.0100000000"),
                unrealized_pnl=Decimal("0"),
            )
        }
        self.risk_profile = _RiskProfileState(
            profile_version="default_v1",
            total_exposure_mode="PERCENT_OF_PV",
            max_total_exposure_pct=Decimal("0.2000000000"),
            max_total_exposure_amount=None,
            cluster_exposure_mode="PERCENT_OF_PV",
            max_cluster_exposure_pct=Decimal("0.0800000000"),
            max_cluster_exposure_amount=None,
            max_concurrent_positions=10,
            severe_loss_drawdown_trigger=Decimal("0.2000000000"),
            volatility_feature_id=9001,
            volatility_target=Decimal("0.0200000000"),
            volatility_scale_floor=Decimal("0.5000000000"),
            volatility_scale_ceiling=Decimal("1.5000000000"),
            hold_min_expected_return=Decimal("0"),
            exit_expected_return_threshold=Decimal("-0.005000000000000000"),
            recovery_hold_prob_up_threshold=Decimal("0.6000000000"),
            recovery_exit_prob_up_threshold=Decimal("0.3500000000"),
            derisk_fraction=Decimal("0.5000000000"),
            signal_persistence_required=1,
        )

    def find_membership(self, asset_id: int) -> _Membership | None:
        return self._memberships.get(asset_id)

    def find_cluster_state(self, cluster_id: int) -> _ClusterState | None:
        for item in self.cluster_states:
            if item.cluster_id == cluster_id:
                return item
        return None

    def find_volatility_feature(self, asset_id: int) -> _VolatilityFeatureState | None:
        return self._volatility_features.get(asset_id)

    def find_position(self, asset_id: int) -> _PositionState | None:
        return self._positions.get(asset_id)


def test_runtime_risk_gate_blocks_enter_when_halt() -> None:
    context = _Context()
    context.risk_state = _RiskState(
        account_id=1,
        hour_ts_utc=context.risk_state.hour_ts_utc,
        source_run_id=context.risk_state.source_run_id,
        drawdown_pct=Decimal("0.0100000000"),
        drawdown_tier="NORMAL",
        max_concurrent_positions=10,
        halt_new_entries=True,
        kill_switch_active=False,
        max_total_exposure_pct=Decimal("0.2"),
        max_cluster_exposure_pct=Decimal("0.08"),
        row_hash="r" * 64,
    )
    violations = enforce_runtime_risk_gate("ENTER", context)
    assert len(violations) == 1
    assert violations[0].reason_code == "HALT_NEW_ENTRIES_ACTIVE"


def test_runtime_risk_gate_blocks_enter_when_kill_switch() -> None:
    context = _Context()
    context.risk_state = _RiskState(
        account_id=1,
        hour_ts_utc=context.risk_state.hour_ts_utc,
        source_run_id=context.risk_state.source_run_id,
        drawdown_pct=Decimal("0.0100000000"),
        drawdown_tier="NORMAL",
        max_concurrent_positions=10,
        halt_new_entries=False,
        kill_switch_active=True,
        max_total_exposure_pct=Decimal("0.2"),
        max_cluster_exposure_pct=Decimal("0.08"),
        row_hash="r" * 64,
    )
    violations = enforce_runtime_risk_gate("ENTER", context)
    assert len(violations) == 1
    assert violations[0].reason_code == "KILL_SWITCH_ACTIVE"


def test_runtime_risk_gate_dual_halt_and_kill_prefers_kill_switch() -> None:
    context = _Context()
    context.risk_state = _RiskState(
        account_id=1,
        hour_ts_utc=context.risk_state.hour_ts_utc,
        source_run_id=context.risk_state.source_run_id,
        drawdown_pct=Decimal("0.0100000000"),
        drawdown_tier="NORMAL",
        max_concurrent_positions=10,
        halt_new_entries=True,
        kill_switch_active=True,
        max_total_exposure_pct=Decimal("0.2"),
        max_cluster_exposure_pct=Decimal("0.08"),
        row_hash="r" * 64,
    )
    violations = enforce_runtime_risk_gate("ENTER", context)
    assert len(violations) == 1
    assert violations[0].reason_code == "KILL_SWITCH_ACTIVE"
    assert violations[0].severity == "CRITICAL"


def test_runtime_risk_gate_non_enter_action_has_no_violation() -> None:
    context = _Context()
    assert enforce_runtime_risk_gate("HOLD", context) == tuple()


def test_capital_preservation_detects_insufficient_cash() -> None:
    context = _Context()
    violations = enforce_capital_preservation("ENTER", Decimal("1500"), context)
    assert any(v.reason_code == "INSUFFICIENT_AVAILABLE_CASH" for v in violations)


def test_capital_preservation_detects_total_exposure_cap() -> None:
    context = _Context()
    violations = enforce_capital_preservation("ENTER", Decimal("3000"), context)
    assert any(v.reason_code == "TOTAL_EXPOSURE_CAP_EXCEEDED" for v in violations)


def test_capital_preservation_percent_mode_passes_when_within_cap() -> None:
    context = _Context()
    assert enforce_capital_preservation("ENTER", Decimal("100"), context) == tuple()


def test_capital_preservation_detects_non_positive_portfolio_value() -> None:
    context = _Context()
    context.capital_state = _CapitalState(
        account_id=1,
        portfolio_value=Decimal("0"),
        cash_balance=Decimal("1000"),
        total_exposure_pct=Decimal("0.01"),
        open_position_count=1,
    )
    violations = enforce_capital_preservation("ENTER", Decimal("10"), context)
    assert any(v.reason_code == "NON_POSITIVE_PORTFOLIO_VALUE" for v in violations)


def test_capital_preservation_non_enter_action_has_no_violation() -> None:
    context = _Context()
    assert enforce_capital_preservation("EXIT", Decimal("100"), context) == tuple()


def test_cluster_cap_violation_detected() -> None:
    context = _Context()
    violations = enforce_cluster_cap("ENTER", 1, Decimal("700"), context)
    assert any(v.reason_code == "CLUSTER_CAP_EXCEEDED" for v in violations)


def test_cluster_cap_percent_mode_passes_when_within_cap() -> None:
    context = _Context()
    assert enforce_cluster_cap("ENTER", 1, Decimal("100"), context) == tuple()


def test_cluster_cap_missing_membership_detected() -> None:
    context = _Context()
    context._memberships = {}
    violations = enforce_cluster_cap("ENTER", 1, Decimal("100"), context)
    assert len(violations) == 1
    assert violations[0].reason_code == "MISSING_CLUSTER_MEMBERSHIP"


def test_cluster_cap_missing_cluster_state_detected() -> None:
    context = _Context()
    context.cluster_states = tuple()
    violations = enforce_cluster_cap("ENTER", 1, Decimal("100"), context)
    assert len(violations) == 1
    assert violations[0].reason_code == "MISSING_CLUSTER_STATE"


def test_cluster_cap_non_positive_portfolio_value_detected() -> None:
    context = _Context()
    context.capital_state = _CapitalState(
        account_id=1,
        portfolio_value=Decimal("-1"),
        cash_balance=Decimal("1000"),
        total_exposure_pct=Decimal("0.01"),
        open_position_count=1,
    )
    violations = enforce_cluster_cap("ENTER", 1, Decimal("100"), context)
    assert len(violations) == 1
    assert violations[0].reason_code == "NON_POSITIVE_PORTFOLIO_VALUE"


def test_cluster_cap_non_enter_action_has_no_violation() -> None:
    context = _Context()
    assert enforce_cluster_cap("HOLD", 1, Decimal("100"), context) == tuple()


def test_cross_account_isolation_detects_mismatch() -> None:
    context = _Context()
    context.capital_state = _CapitalState(
        account_id=2,
        portfolio_value=Decimal("10000"),
        cash_balance=Decimal("1000"),
        total_exposure_pct=Decimal("0.01"),
        open_position_count=1,
    )
    violations = enforce_cross_account_isolation(context)
    assert any(v.reason_code == "CROSS_ACCOUNT_CAPITAL_STATE" for v in violations)


def test_cross_account_isolation_detects_risk_and_cluster_mismatch() -> None:
    context = _Context()
    context.risk_state = _RiskState(
        account_id=2,
        hour_ts_utc=context.risk_state.hour_ts_utc,
        source_run_id=context.risk_state.source_run_id,
        drawdown_pct=Decimal("0.0100000000"),
        drawdown_tier="NORMAL",
        max_concurrent_positions=10,
        halt_new_entries=False,
        kill_switch_active=False,
        max_total_exposure_pct=Decimal("0.2"),
        max_cluster_exposure_pct=Decimal("0.08"),
        row_hash="r" * 64,
    )
    context.cluster_states = (
        _ClusterState(
            account_id=2,
            cluster_id=7,
            exposure_pct=Decimal("0.0200000000"),
            max_cluster_exposure_pct=Decimal("0.0800000000"),
            parent_risk_hash="r" * 64,
        ),
    )
    violations = enforce_cross_account_isolation(context)
    reason_codes = {v.reason_code for v in violations}
    assert "CROSS_ACCOUNT_RISK_STATE" in reason_codes
    assert "CROSS_ACCOUNT_CLUSTER_STATE" in reason_codes


def test_risk_state_machine_normal_halt_kill_and_severe_modes() -> None:
    context = _Context()
    assert evaluate_risk_state_machine(context).state == "NORMAL"

    context.risk_state = _RiskState(
        account_id=1,
        hour_ts_utc=context.risk_state.hour_ts_utc,
        source_run_id=context.risk_state.source_run_id,
        drawdown_pct=Decimal("0.0100000000"),
        drawdown_tier="NORMAL",
        max_concurrent_positions=10,
        halt_new_entries=True,
        kill_switch_active=False,
        max_total_exposure_pct=Decimal("0.2"),
        max_cluster_exposure_pct=Decimal("0.08"),
        row_hash="r" * 64,
    )
    assert evaluate_risk_state_machine(context).state == "ENTRY_HALT"

    context.risk_state = _RiskState(
        account_id=1,
        hour_ts_utc=context.risk_state.hour_ts_utc,
        source_run_id=context.risk_state.source_run_id,
        drawdown_pct=Decimal("0.0100000000"),
        drawdown_tier="NORMAL",
        max_concurrent_positions=10,
        halt_new_entries=False,
        kill_switch_active=True,
        max_total_exposure_pct=Decimal("0.2"),
        max_cluster_exposure_pct=Decimal("0.08"),
        row_hash="r" * 64,
    )
    assert evaluate_risk_state_machine(context).state == "KILL_SWITCH_LOCKDOWN"

    context.risk_state = _RiskState(
        account_id=1,
        hour_ts_utc=context.risk_state.hour_ts_utc,
        source_run_id=context.risk_state.source_run_id,
        drawdown_pct=Decimal("0.1700000000"),
        drawdown_tier="DD15",
        max_concurrent_positions=10,
        halt_new_entries=False,
        kill_switch_active=False,
        max_total_exposure_pct=Decimal("0.2"),
        max_cluster_exposure_pct=Decimal("0.08"),
        row_hash="r" * 64,
    )
    profile = RuntimeRiskProfile(severe_loss_drawdown_trigger=Decimal("0.1500000000"))
    assert evaluate_risk_state_machine(context, profile).state == "SEVERE_LOSS_RECOVERY"


def test_position_count_cap_blocks_when_open_positions_exceed_limit() -> None:
    context = _Context()
    context.capital_state = _CapitalState(
        account_id=1,
        portfolio_value=Decimal("10000"),
        cash_balance=Decimal("1000"),
        total_exposure_pct=Decimal("0.01"),
        open_position_count=10,
    )
    violations = enforce_position_count_cap("ENTER", context)
    assert len(violations) == 1
    assert violations[0].reason_code == "MAX_CONCURRENT_POSITIONS_EXCEEDED"


def test_position_count_cap_invalid_profile_config_is_rejected() -> None:
    context = _Context()
    profile = RuntimeRiskProfile(max_concurrent_positions=-1)
    violations = enforce_position_count_cap("ENTER", context, profile)
    assert len(violations) == 1
    assert violations[0].reason_code == "INVALID_MAX_CONCURRENT_POSITIONS_CONFIG"


def test_position_count_cap_non_enter_action_has_no_violation() -> None:
    context = _Context()
    assert enforce_position_count_cap("EXIT", context) == tuple()


def test_severe_loss_entry_gate_blocks_new_entries_in_recovery_mode() -> None:
    context = _Context()
    context.risk_state = _RiskState(
        account_id=1,
        hour_ts_utc=context.risk_state.hour_ts_utc,
        source_run_id=context.risk_state.source_run_id,
        drawdown_pct=Decimal("0.1700000000"),
        drawdown_tier="DD15",
        max_concurrent_positions=10,
        halt_new_entries=False,
        kill_switch_active=False,
        max_total_exposure_pct=Decimal("0.2"),
        max_cluster_exposure_pct=Decimal("0.08"),
        row_hash="r" * 64,
    )
    profile = RuntimeRiskProfile(severe_loss_drawdown_trigger=Decimal("0.1500000000"))
    violations = enforce_severe_loss_entry_gate("ENTER", context, profile)
    assert len(violations) == 1
    assert violations[0].reason_code == "SEVERE_LOSS_RECOVERY_ENTRY_BLOCKED"


def test_severe_loss_entry_gate_non_enter_and_non_severe_paths() -> None:
    context = _Context()
    assert enforce_severe_loss_entry_gate("HOLD", context) == tuple()
    assert enforce_severe_loss_entry_gate("ENTER", context) == tuple()


def test_capital_preservation_absolute_amount_mode_paths() -> None:
    context = _Context()
    profile = RuntimeRiskProfile(
        total_exposure_mode=ABSOLUTE_AMOUNT,
        max_total_exposure_amount=Decimal("1500"),
    )
    violations = enforce_capital_preservation("ENTER", Decimal("1501"), context, profile)
    assert any(v.reason_code == "TOTAL_EXPOSURE_AMOUNT_CAP_EXCEEDED" for v in violations)

    bad_amount_profile = RuntimeRiskProfile(total_exposure_mode=ABSOLUTE_AMOUNT, max_total_exposure_amount=None)
    violations = enforce_capital_preservation("ENTER", Decimal("100"), context, bad_amount_profile)
    assert any(v.reason_code == "INVALID_TOTAL_EXPOSURE_ABSOLUTE_CAP" for v in violations)

    invalid_mode_profile = RuntimeRiskProfile(total_exposure_mode="UNKNOWN")
    violations = enforce_capital_preservation("ENTER", Decimal("100"), context, invalid_mode_profile)
    assert any(v.reason_code == "INVALID_TOTAL_EXPOSURE_MODE" for v in violations)


def test_cluster_cap_absolute_amount_and_mode_paths() -> None:
    context = _Context()
    profile = RuntimeRiskProfile(
        cluster_exposure_mode=ABSOLUTE_AMOUNT,
        max_cluster_exposure_amount=Decimal("300"),
    )
    assert enforce_cluster_cap("ENTER", 1, Decimal("50"), context, profile) == tuple()

    violations = enforce_cluster_cap("ENTER", 1, Decimal("200"), context, profile)
    assert len(violations) == 1
    assert violations[0].reason_code == "CLUSTER_CAP_AMOUNT_EXCEEDED"

    bad_amount_profile = RuntimeRiskProfile(
        cluster_exposure_mode=ABSOLUTE_AMOUNT,
        max_cluster_exposure_amount=None,
    )
    violations = enforce_cluster_cap("ENTER", 1, Decimal("50"), context, bad_amount_profile)
    assert len(violations) == 1
    assert violations[0].reason_code == "INVALID_CLUSTER_EXPOSURE_ABSOLUTE_CAP"

    invalid_mode_profile = RuntimeRiskProfile(cluster_exposure_mode="UNKNOWN")
    violations = enforce_cluster_cap("ENTER", 1, Decimal("50"), context, invalid_mode_profile)
    assert len(violations) == 1
    assert violations[0].reason_code == "INVALID_CLUSTER_EXPOSURE_MODE"


def test_compute_volatility_adjusted_fraction_paths() -> None:
    context = _Context()

    sized = compute_volatility_adjusted_fraction(
        action="ENTER",
        candidate_fraction=Decimal("0.0300000000"),
        asset_id=1,
        context=context,
    )
    assert sized.reason_code == "VOLATILITY_SIZED"
    assert sized.adjusted_fraction == Decimal("0.0200000000")
    assert sized.volatility_scale == Decimal("1.0000000000")

    context._volatility_features = {}
    fallback = compute_volatility_adjusted_fraction(
        action="ENTER",
        candidate_fraction=Decimal("0.0100000000"),
        asset_id=1,
        context=context,
    )
    assert fallback.reason_code == "VOLATILITY_FALLBACK_BASE"
    assert fallback.adjusted_fraction == Decimal("0.0100000000")

    non_enter = compute_volatility_adjusted_fraction(
        action="HOLD",
        candidate_fraction=Decimal("0.0100000000"),
        asset_id=1,
        context=context,
    )
    assert non_enter.reason_code == "VOLATILITY_SIZING_NOT_APPLICABLE"
    assert non_enter.adjusted_fraction == Decimal("0.0000000000")


def test_evaluate_adaptive_horizon_action_paths() -> None:
    context = _Context()
    prediction = type(
        "Prediction",
        (),
        {
            "asset_id": 1,
            "expected_return": Decimal("0.010000000000000000"),
            "prob_up": Decimal("0.6500000000"),
        },
    )()
    hold_eval = evaluate_adaptive_horizon_action("EXIT", prediction, context)
    assert hold_eval.action == "HOLD"
    assert hold_eval.reason_code == "ADAPTIVE_HORIZON_HOLD_EXTENDED"

    prediction.expected_return = Decimal("-0.020000000000000000")
    exit_eval = evaluate_adaptive_horizon_action("HOLD", prediction, context)
    assert exit_eval.action == "EXIT"
    assert exit_eval.reason_code == "ADAPTIVE_HORIZON_EXIT_PERSISTENT_NEGATIVE"

    context.risk_profile = replace(context.risk_profile, signal_persistence_required=2)
    pending_eval = evaluate_adaptive_horizon_action("HOLD", prediction, context)
    assert pending_eval.action == "HOLD"
    assert pending_eval.reason_code == "ADAPTIVE_HORIZON_PERSISTENCE_PENDING"

    context._positions = {}
    no_position_eval = evaluate_adaptive_horizon_action("HOLD", prediction, context)
    assert no_position_eval.reason_code == "ADAPTIVE_HORIZON_NO_OPEN_POSITION"

    context._positions = {
        1: _PositionState(
            asset_id=1,
            quantity=Decimal("1.000000000000000000"),
            exposure_pct=Decimal("0.0100000000"),
            unrealized_pnl=Decimal("0"),
        )
    }
    prediction.expected_return = Decimal("-0.001000000000000000")
    context.risk_profile = replace(
        context.risk_profile,
        hold_min_expected_return=Decimal("0.005000000000000000"),
        exit_expected_return_threshold=Decimal("-0.005000000000000000"),
        signal_persistence_required=1,
    )
    no_override_eval = evaluate_adaptive_horizon_action("HOLD", prediction, context)
    assert no_override_eval.reason_code == "ADAPTIVE_HORIZON_NO_OVERRIDE"


def test_evaluate_adaptive_horizon_action_persistence_pending_forces_hold_from_exit() -> None:
    context = _Context()
    prediction = type(
        "Prediction",
        (),
        {
            "asset_id": 1,
            "expected_return": Decimal("-0.020000000000000000"),
            "prob_up": Decimal("0.2000000000"),
        },
    )()
    context.risk_profile = replace(context.risk_profile, signal_persistence_required=2)

    pending_eval = evaluate_adaptive_horizon_action("EXIT", prediction, context)
    assert pending_eval.action == "HOLD"
    assert pending_eval.reason_code == "ADAPTIVE_HORIZON_PERSISTENCE_PENDING"


def test_evaluate_adaptive_horizon_action_persistence_pending_forces_hold_from_enter() -> None:
    context = _Context()
    prediction = type(
        "Prediction",
        (),
        {
            "asset_id": 1,
            "expected_return": Decimal("-0.020000000000000000"),
            "prob_up": Decimal("0.2000000000"),
        },
    )()
    context.risk_profile = replace(context.risk_profile, signal_persistence_required=3)

    pending_eval = evaluate_adaptive_horizon_action("ENTER", prediction, context)
    assert pending_eval.action == "HOLD"
    assert pending_eval.reason_code == "ADAPTIVE_HORIZON_PERSISTENCE_PENDING"

def test_evaluate_severe_loss_recovery_action_paths() -> None:
    context = _Context()
    context.risk_state = replace(context.risk_state, drawdown_pct=Decimal("0.2100000000"))
    prediction = type(
        "Prediction",
        (),
        {
            "asset_id": 1,
            "expected_return": Decimal("0.001000000000000000"),
            "prob_up": Decimal("0.7000000000"),
        },
    )()
    entry_eval = evaluate_severe_loss_recovery_action("ENTER", prediction, context)
    assert entry_eval.reason_code == "SEVERE_RECOVERY_ENTRY_PENDING_GATE"
    assert entry_eval.action == "ENTER"

    hold_eval = evaluate_severe_loss_recovery_action("HOLD", prediction, context)
    assert hold_eval.reason_code == "SEVERE_RECOVERY_HOLD"
    assert hold_eval.action == "HOLD"

    prediction.prob_up = Decimal("0.1000000000")
    exit_eval = evaluate_severe_loss_recovery_action("HOLD", prediction, context)
    assert exit_eval.reason_code == "SEVERE_RECOVERY_EXIT"
    assert exit_eval.action == "EXIT"

    prediction.prob_up = Decimal("0.5000000000")
    prediction.expected_return = Decimal("0.000100000000000000")
    derisk_eval = evaluate_severe_loss_recovery_action("HOLD", prediction, context)
    assert derisk_eval.reason_code == "SEVERE_RECOVERY_DERISK_INTENT"
    assert derisk_eval.action == "HOLD"


def test_runtime_profile_fallback_path_without_context_profile() -> None:
    context = _Context()
    delattr(context, "risk_profile")
    violations = enforce_position_count_cap("ENTER", context, risk_profile=None)
    assert violations == tuple()
