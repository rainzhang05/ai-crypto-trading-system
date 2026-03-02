"""Contract tests for non-SQL executable artifacts."""

from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess

import pytest

from tests.utils.executable_artifact_manifest import ROOT


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_test_all_shell_syntax_is_valid() -> None:
    script_path = ROOT / "scripts" / "test_all.sh"
    completed = subprocess.run(
        ["bash", "-n", str(script_path)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, (
        "scripts/test_all.sh failed bash syntax validation.\n"
        f"stdout={completed.stdout}\nstderr={completed.stderr}"
    )


def test_makefile_contract_targets_are_present() -> None:
    makefile = _read("Makefile")
    assert re.search(r"^preflight:\s*$", makefile, flags=re.MULTILINE), "Missing Makefile preflight target."
    assert "python3 -m compileall -q backend execution scripts tests" in makefile
    assert "pytest -q" in makefile
    assert re.search(r"^test:\s*$", makefile, flags=re.MULTILINE), "Missing Makefile test target."
    assert "./scripts/test_all.sh" in makefile


def test_workflows_keep_clean_room_gate_invocation() -> None:
    ci = _read(".github/workflows/ci.yml")
    release = _read(".github/workflows/release.yml")
    deploy = _read(".github/workflows/deploy-cloud-run.yml")

    assert "name: CI" in ci
    assert "clean_room_validation" in ci
    assert "run: bash scripts/test_all.sh" in ci

    assert "name: Release" in release
    assert "Run clean-room validation pipeline" in release
    assert "run: bash scripts/test_all.sh" in release

    assert "name: Deploy Cloud Run" in deploy
    assert "clean_room_gate" in deploy
    assert "run: bash scripts/test_all.sh" in deploy


def test_docker_compose_file_parses_with_docker_compose_config() -> None:
    docker_bin = shutil.which("docker")
    if docker_bin is None:
        pytest.skip("docker command is unavailable.")

    compose_path = ROOT / "docker-compose.yml"
    completed = subprocess.run(
        [docker_bin, "compose", "-f", str(compose_path), "config"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, (
        "docker compose config failed for docker-compose.yml.\n"
        f"stdout={completed.stdout}\nstderr={completed.stderr}"
    )
    assert "services:" in completed.stdout
