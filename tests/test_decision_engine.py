"""Unit tests for deterministic decision engine primitives."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from execution.decision_engine import (
    NUMERIC_10,
    deterministic_decision,
    normalize_decimal,
    stable_hash,
    stable_uuid,
)


def test_stable_hash_is_deterministic_for_identical_inputs() -> None:
    tokens = ("a", "b", Decimal("1.234500000000000000"), datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert stable_hash(tokens) == stable_hash(tokens)


def test_stable_hash_changes_when_order_changes() -> None:
    assert stable_hash(("x", "y", "z")) != stable_hash(("z", "y", "x"))


def test_stable_uuid_is_deterministic() -> None:
    uuid_a = stable_uuid("ns", ("r", "s", "t"))
    uuid_b = stable_uuid("ns", ("r", "s", "t"))
    assert uuid_a == uuid_b


def test_normalize_decimal_quantizes_with_half_even() -> None:
    value = Decimal("0.12345678906")
    assert normalize_decimal(value, NUMERIC_10) == Decimal("0.1234567891")


def test_deterministic_decision_is_pure_function() -> None:
    result_a = deterministic_decision("1" * 64, "2" * 64, "3" * 64, "4" * 64, "5" * 64)
    result_b = deterministic_decision("1" * 64, "2" * 64, "3" * 64, "4" * 64, "5" * 64)
    assert result_a == result_b


def test_deterministic_decision_changes_with_input_hashes() -> None:
    result_a = deterministic_decision("1" * 64, "2" * 64, "3" * 64, "4" * 64, "5" * 64)
    result_b = deterministic_decision("9" * 64, "2" * 64, "3" * 64, "4" * 64, "5" * 64)
    assert result_a.decision_hash != result_b.decision_hash
