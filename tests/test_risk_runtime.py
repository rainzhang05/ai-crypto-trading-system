"""Unit tests for runtime risk enforcement checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from execution.risk_runtime import (
    ABSOLUTE_AMOUNT,
    RuntimeRiskProfile,
    enforce_capital_preservation,
    enforce_cluster_cap,
    enforce_cross_account_isolation,
    enforce_position_count_cap,
    enforce_runtime_risk_gate,
    enforce_severe_loss_entry_gate,
    evaluate_risk_state_machine,
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

    def find_membership(self, asset_id: int) -> _Membership | None:
        return self._memberships.get(asset_id)

    def find_cluster_state(self, cluster_id: int) -> _ClusterState | None:
        for item in self.cluster_states:
            if item.cluster_id == cluster_id:
                return item
        return None


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
