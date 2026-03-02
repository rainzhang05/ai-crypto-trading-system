"""Deterministic model artifact packaging and local-branch publication helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from typing import Iterable, Sequence

from execution.decision_engine import stable_hash


@dataclass(frozen=True)
class PackagedArtifact:
    """Packaged artifact file metadata."""

    path: Path
    sha256: str


@dataclass(frozen=True)
class PackagingResult:
    """Result of artifact packaging and report generation."""

    bundle_dir: Path
    manifest_path: Path
    report_path: Path
    artifact_hash: str



def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _gather_files(paths: Iterable[Path]) -> tuple[PackagedArtifact, ...]:
    artifacts: list[PackagedArtifact] = []
    for path in sorted(paths):
        if not path.exists() or path.is_dir():
            continue
        artifacts.append(PackagedArtifact(path=path, sha256=_sha256_file(path)))
    if not artifacts:
        raise RuntimeError("No artifact files found to package")
    return tuple(artifacts)


def package_promoted_artifacts(
    *,
    promotion_id: str,
    output_root: Path,
    model_files: Sequence[Path],
    compatibility_range: str,
    source_ref: str,
) -> PackagingResult:
    """Package promoted artifacts into deterministic bundle manifest/report."""
    bundle_dir = output_root / promotion_id
    bundle_dir.mkdir(parents=True, exist_ok=True)

    gathered = _gather_files(model_files)
    inventory = [
        {
            "path": str(item.path),
            "sha256": item.sha256,
        }
        for item in gathered
    ]
    artifact_hash = stable_hash(tuple(token for row in inventory for token in (row["path"], row["sha256"])))

    manifest = {
        "bundle_version": promotion_id,
        "generated_at_utc": datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z"),
        "compatibility_range": compatibility_range,
        "source_ref": source_ref,
        "artifact_hash": artifact_hash,
        "artifacts": inventory,
    }
    manifest_path = bundle_dir / "bundle_manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2), encoding="utf-8")

    report = {
        "promotion_id": promotion_id,
        "artifact_hash": artifact_hash,
        "artifact_count": len(inventory),
        "status": "PACKAGED",
    }
    report_path = bundle_dir / "promotion_report.json"
    report_path.write_text(json.dumps(report, sort_keys=True, indent=2), encoding="utf-8")

    return PackagingResult(
        bundle_dir=bundle_dir,
        manifest_path=manifest_path,
        report_path=report_path,
        artifact_hash=artifact_hash,
    )


def commit_packaged_artifacts(
    *,
    repo_root: Path,
    branch_name: str,
    files_to_commit: Sequence[Path],
    commit_message: str,
) -> None:
    """Commit packaged artifacts to deterministic local automation branch."""
    subprocess.run(["git", "checkout", "-B", branch_name], cwd=repo_root, check=True)
    relative_files = [str(path.relative_to(repo_root)) for path in files_to_commit]
    subprocess.run(["git", "add", *relative_files], cwd=repo_root, check=True)
    subprocess.run(["git", "commit", "-m", commit_message], cwd=repo_root, check=True)
