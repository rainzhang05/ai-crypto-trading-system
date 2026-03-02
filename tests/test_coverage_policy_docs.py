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
    assert "Core trading operation must be local-first" in text
    assert "signed release bundles" in text


def test_project_roadmap_contains_phase_closure_coverage_gate_language() -> None:
    text = _read("docs/specs/PROJECT_ROADMAP.md")
    assert "phase coverage closure" in text.lower()
    assert "every phase implementation is incomplete until coverage closure is achieved" in text.lower()
    assert "100% line and 100% branch" in text
    assert "PHASE 8B — LOCAL RUNTIME SERVICE AND CONTROL API" in text
    assert "PHASE 9B — macOS APP PACKAGING, INSTALLER, AND FIRST-RUN UX" in text
    assert "PHASE 9C — BUDGET AND LIMIT EXTENSIONS" in text
    assert "PHASE 10A — MODEL BUNDLE RELEASE AND ONE-CLICK UPDATER" in text
    assert "PHASE 10B — VERSION COMPATIBILITY GOVERNANCE" in text
    assert "PHASE 10G — ARTIFACT TRUST POLICY AND KEY ROTATION" in text


def test_test_plan_contains_repository_executable_artifact_coverage_gates() -> None:
    text = _read("docs/reports/TEST_PLAN.md")
    assert "repository executable-artifact coverage closure" in text.lower()
    assert "SQL artifacts are fully covered by execution/equivalence policy" in text
    normalized = text.replace("`", "")
    assert "Coverage across backend/*, execution/*, and scripts/* is 100% line + branch" in normalized
    assert "Per-currency budget cap enforcement for CAD, USD, USDC." in normalized


def test_local_first_and_model_bundle_specs_are_authoritative_and_referenced() -> None:
    privacy_text = _read("docs/specs/LOCAL_FIRST_RUNTIME_AND_PRIVACY_SPEC.md")
    model_text = _read("docs/specs/MODEL_BUNDLE_DISTRIBUTION_AND_UPDATE_SPEC.md")
    ops_text = _read("docs/specs/PRODUCTION_OPERATIONS_AND_RELIABILITY_SPEC.md")
    roadmap_text = _read("docs/specs/PROJECT_ROADMAP.md")

    assert "Status: AUTHORITATIVE" in privacy_text
    assert "Status: AUTHORITATIVE" in model_text
    assert "Status: AUTHORITATIVE" in ops_text
    assert "LOCAL_FIRST_RUNTIME_AND_PRIVACY_SPEC.md" in roadmap_text
    assert "MODEL_BUNDLE_DISTRIBUTION_AND_UPDATE_SPEC.md" in roadmap_text
    assert "PRODUCTION_OPERATIONS_AND_RELIABILITY_SPEC.md" in roadmap_text
