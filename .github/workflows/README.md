# GitHub Actions Workflows

This repository uses three workflows:

1. `ci.yml`
- Triggers on pull requests, branch pushes, manual runs, and nightly schedule.
- Runs Python preflight checks (`compileall`, `pytest`) and then the authoritative clean-room gate via `scripts/test_all.sh`.
- Uploads `docs/test_logs` artifacts for audit evidence.

2. `release.yml`
- Triggers on tags matching `v*`.
- Re-runs `scripts/test_all.sh`.
- Publishes a GitHub release with a governance evidence bundle.

3. `deploy-cloud-run.yml`
- Manual (`workflow_dispatch`) deployment pipeline for Cloud Run.
- Optional clean-room gate before deployment.
- Uses Workload Identity Federation (OIDC) and pushes container images to Artifact Registry.
- Supports dry-run mode (build/push only, no `gcloud run deploy`).

## Required Secrets for Cloud Run Deploy

Configure these repository or environment secrets:

- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_SERVICE_ACCOUNT`
- `GCP_PROJECT_ID`
- `GCP_REGION`
- `GAR_REPOSITORY`
- `CLOUD_RUN_SERVICE`

## Notes

- `scripts/test_all.sh` is the canonical deterministic validation path and should remain green before any merge or deployment.
- Cloud Run deployment expects a Dockerfile in the repository (default path: `Dockerfile`, configurable at dispatch time).
