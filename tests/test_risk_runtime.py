"""Unit tests for runtime risk enforcement checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from execution.risk_runtime import (
    enforce_capital_preservation,
    enforce_cluster_cap,
    enforce_cross_account_isolation,
    enforce_runtime_risk_gate,
)


@dataclass(frozen=True)
class _RiskState:
    account_id: int
    hour_ts_utc: datetime
    source_run_id: UUID
    halt_new_entries: bool
    kill_switch_active: bool
    max_total_exposure_pct: Decimal
    row_hash: str


@dataclass(frozen=True)
class _CapitalState:
    account_id: int
    portfolio_value: Decimal
    cash_balance: Decimal
    total_exposure_pct: Decimal


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
            halt_new_entries=False,
            kill_switch_active=False,
            max_total_exposure_pct=Decimal("0.2000000000"),
            row_hash="r" * 64,
        )
        self.capital_state = _CapitalState(
            account_id=1,
            portfolio_value=Decimal("10000"),
            cash_balance=Decimal("1000"),
            total_exposure_pct=Decimal("0.0100000000"),
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
        halt_new_entries=True,
        kill_switch_active=False,
        max_total_exposure_pct=Decimal("0.2"),
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
        halt_new_entries=False,
        kill_switch_active=True,
        max_total_exposure_pct=Decimal("0.2"),
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


def test_capital_preservation_detects_non_positive_portfolio_value() -> None:
    context = _Context()
    context.capital_state = _CapitalState(
        account_id=1,
        portfolio_value=Decimal("0"),
        cash_balance=Decimal("1000"),
        total_exposure_pct=Decimal("0.01"),
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
    )
    violations = enforce_cross_account_isolation(context)
    assert any(v.reason_code == "CROSS_ACCOUNT_CAPITAL_STATE" for v in violations)


def test_cross_account_isolation_detects_risk_and_cluster_mismatch() -> None:
    context = _Context()
    context.risk_state = _RiskState(
        account_id=2,
        hour_ts_utc=context.risk_state.hour_ts_utc,
        source_run_id=context.risk_state.source_run_id,
        halt_new_entries=False,
        kill_switch_active=False,
        max_total_exposure_pct=Decimal("0.2"),
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
