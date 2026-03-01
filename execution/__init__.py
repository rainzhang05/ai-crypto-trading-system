"""Deterministic execution runtime and replay harness package."""

from execution.activation_gate import ActivationGateResult, ActivationRecord, enforce_activation_gate
from execution.decision_engine import DecisionResult, deterministic_decision
from execution.deterministic_context import (
    DeterministicAbortError,
    DeterministicContextBuilder,
    ExecutionContext,
)
from execution.replay_harness import ReplayComparisonReport, replay_manifest_parity
from execution.replay_engine import ReplayReport, execute_hour, replay_hour
from execution.runtime_writer import AppendOnlyRuntimeWriter, RuntimeWriteResult

__all__ = [
    "ActivationGateResult",
    "ActivationRecord",
    "AppendOnlyRuntimeWriter",
    "DecisionResult",
    "DeterministicAbortError",
    "DeterministicContextBuilder",
    "ExecutionContext",
    "ReplayComparisonReport",
    "ReplayReport",
    "RuntimeWriteResult",
    "deterministic_decision",
    "enforce_activation_gate",
    "execute_hour",
    "replay_manifest_parity",
    "replay_hour",
]
