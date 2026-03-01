"""Unit tests for deterministic activation gate logic."""

from __future__ import annotations

from datetime import datetime, timezone

from execution.activation_gate import ActivationRecord, enforce_activation_gate


def test_backtest_without_activation_is_allowed() -> None:
    result = enforce_activation_gate(
        run_mode="BACKTEST",
        hour_ts_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        model_version_id=11,
        activation=None,
    )
    assert result.allowed is True
    assert result.reason_code == "OK"


def test_backtest_with_activation_is_rejected() -> None:
    activation = ActivationRecord(
        activation_id=1,
        model_version_id=11,
        run_mode="BACKTEST",
        validation_window_end_utc=datetime(2025, 12, 31, tzinfo=timezone.utc),
        status="APPROVED",
        approval_hash="a" * 64,
    )
    result = enforce_activation_gate(
        run_mode="BACKTEST",
        hour_ts_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        model_version_id=11,
        activation=activation,
    )
    assert result.allowed is False
    assert result.reason_code == "BACKTEST_ACTIVATION_PRESENT"


def test_live_missing_activation_is_rejected() -> None:
    result = enforce_activation_gate(
        run_mode="LIVE",
        hour_ts_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        model_version_id=11,
        activation=None,
    )
    assert result.allowed is False
    assert result.reason_code == "MISSING_ACTIVATION"


def test_live_activation_requires_approved_status() -> None:
    activation = ActivationRecord(
        activation_id=1,
        model_version_id=11,
        run_mode="LIVE",
        validation_window_end_utc=datetime(2025, 12, 31, tzinfo=timezone.utc),
        status="REVOKED",
        approval_hash="a" * 64,
    )
    result = enforce_activation_gate(
        run_mode="LIVE",
        hour_ts_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        model_version_id=11,
        activation=activation,
    )
    assert result.allowed is False
    assert result.reason_code == "ACTIVATION_NOT_APPROVED"


def test_live_activation_model_mismatch_is_rejected() -> None:
    activation = ActivationRecord(
        activation_id=1,
        model_version_id=22,
        run_mode="LIVE",
        validation_window_end_utc=datetime(2025, 12, 31, tzinfo=timezone.utc),
        status="APPROVED",
        approval_hash="a" * 64,
    )
    result = enforce_activation_gate(
        run_mode="LIVE",
        hour_ts_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        model_version_id=11,
        activation=activation,
    )
    assert result.allowed is False
    assert result.reason_code == "ACTIVATION_MODEL_MISMATCH"


def test_live_activation_mode_mismatch_is_rejected() -> None:
    activation = ActivationRecord(
        activation_id=1,
        model_version_id=11,
        run_mode="PAPER",
        validation_window_end_utc=datetime(2025, 12, 31, tzinfo=timezone.utc),
        status="APPROVED",
        approval_hash="a" * 64,
    )
    result = enforce_activation_gate(
        run_mode="LIVE",
        hour_ts_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        model_version_id=11,
        activation=activation,
    )
    assert result.allowed is False
    assert result.reason_code == "ACTIVATION_MODE_MISMATCH"


def test_live_activation_window_not_reached_is_rejected() -> None:
    activation = ActivationRecord(
        activation_id=1,
        model_version_id=11,
        run_mode="LIVE",
        validation_window_end_utc=datetime(2026, 1, 2, tzinfo=timezone.utc),
        status="APPROVED",
        approval_hash="a" * 64,
    )
    result = enforce_activation_gate(
        run_mode="LIVE",
        hour_ts_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        model_version_id=11,
        activation=activation,
    )
    assert result.allowed is False
    assert result.reason_code == "ACTIVATION_WINDOW_NOT_REACHED"


def test_live_activation_happy_path_allowed() -> None:
    activation = ActivationRecord(
        activation_id=1,
        model_version_id=11,
        run_mode="LIVE",
        validation_window_end_utc=datetime(2025, 12, 31, tzinfo=timezone.utc),
        status="APPROVED",
        approval_hash="a" * 64,
    )
    result = enforce_activation_gate(
        run_mode="live",
        hour_ts_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        model_version_id=11,
        activation=activation,
    )
    assert result.allowed is True
    assert result.reason_code == "OK"
