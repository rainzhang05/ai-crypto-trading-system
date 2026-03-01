"""Deterministic execution runtime and replay harness package."""

from execution.activation_gate import ActivationGateResult, ActivationRecord, enforce_activation_gate
from execution.decision_engine import DecisionResult, deterministic_decision
from execution.deterministic_context import (
    DeterministicAbortError,
    DeterministicContextBuilder,
    ExecutionContext,
)
from execution.replay_harness import (
    ReplayComparisonReport,
    ReplayWindowReport,
    discover_replay_targets,
    list_replay_targets,
    replay_manifest_parity,
    replay_manifest_tool_parity,
    replay_manifest_window_parity,
)
from execution.replay_engine import ReplayReport, execute_hour, replay_hour
from execution.risk_runtime import (
    RiskStateEvaluation,
    RuntimeRiskProfile,
    evaluate_risk_state_machine,
)
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
    "ReplayWindowReport",
    "ReplayReport",
    "RiskStateEvaluation",
    "RuntimeRiskProfile",
    "RuntimeWriteResult",
    "discover_replay_targets",
    "deterministic_decision",
    "enforce_activation_gate",
    "execute_hour",
    "evaluate_risk_state_machine",
    "list_replay_targets",
    "replay_manifest_parity",
    "replay_manifest_tool_parity",
    "replay_manifest_window_parity",
    "replay_hour",
]
