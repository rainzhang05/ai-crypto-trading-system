"""Policy tests for phase-level coverage closure governance language."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_project_governance_contains_phase_coverage_closure_policy() -> None:
    text = _read("docs/specs/PROJECT_GOVERNANCE.md")
    assert "Every phase implementation is incomplete until coverage closure is achieved" in text
    assert "Python implementation coverage must remain 100% line and 100% branch" in text
    assert "Non-Python executable artifacts must be 100% classified and validated" in text


def test_project_roadmap_contains_phase_closure_coverage_gate_language() -> None:
    text = _read("docs/specs/PROJECT_ROADMAP.md")
    assert "phase coverage closure" in text.lower()
    assert "every phase implementation is incomplete until coverage closure is achieved" in text.lower()
    assert "100% line and 100% branch" in text


def test_test_plan_contains_repository_executable_artifact_coverage_gates() -> None:
    text = _read("docs/reports/TEST_PLAN.md")
    assert "repository executable-artifact coverage closure" in text.lower()
    assert "SQL artifacts are fully covered by execution/equivalence policy" in text
    normalized = text.replace("`", "")
    assert "Coverage across backend/*, execution/*, and scripts/* is 100% line + branch" in normalized
