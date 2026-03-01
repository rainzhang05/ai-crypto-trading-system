# Governance Directory Layout

This directory is organized by artifact type to keep deterministic governance assets easy to locate and maintain.

## Structure

- `specs/`
  - Authoritative project contracts and acceptance criteria.
  - Includes `MASTER_SPEC.md`, `PROJECT_ROADMAP.md`, `PROJECT_GOVERNANCE.md`, `ARCHITECT_DECISIONS.md`, `RISK_RULES.md`, `MODEL_ASSUMPTIONS.md`, `SCHEMA_DDL_MASTER.md`.
- `validations/`
  - Executable SQL validation gates used by test/rebuild flows.
  - Includes `PHASE_1C_VALIDATION.sql`, `PHASE_1D_RUNTIME_VALIDATION.sql`, `TEST_RUNTIME_INSERT_ENABLE.sql`.
- `repairs/`
  - Revision repair SQL artifacts kept at governance root scope.
  - Includes `PHASE_1C_REVISION_C_SCHEMA_REPAIR_BLUEPRINT.sql`, `PHASE_1C_REVISION_C_TRIGGER_REPAIR.sql`.
- `reports/`
  - QA planning and execution reports.
  - Includes `TEST_PLAN.md`, `TEST_REPORT.md`.
- `prompts/`
  - Governance prompts used during architect/auditor/implementation workflows.
- `phases/`
  - Phase-specific implementation logs and historical migration artifacts.
- `test_logs/`
  - Generated logs from `make test` / `scripts/test_all.sh` clean-room runs.

## Runtime/Test References

- Full deterministic test command: `make test`
- Test harness script: `scripts/test_all.sh`
- Replay CLI: `scripts/replay_cli.py`
- Validation SQL paths consumed by harness/tests:
  - `governance/validations/PHASE_1C_VALIDATION.sql`
  - `governance/validations/PHASE_1D_RUNTIME_VALIDATION.sql`
  - `governance/validations/TEST_RUNTIME_INSERT_ENABLE.sql`
