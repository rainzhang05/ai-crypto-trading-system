# Docs Directory Layout

This directory is organized by artifact type to keep deterministic governance assets easy to locate and maintain.

## Structure

- `specs/`
  - Authoritative project contracts and acceptance criteria.
  - Includes `MASTER_SPEC.md`, `PROJECT_ROADMAP.md`, `PROJECT_GOVERNANCE.md`, `ARCHITECT_DECISIONS.md`, `RISK_RULES.md`, `MODEL_ASSUMPTIONS.md`, `SCHEMA_DDL_MASTER.md`, `TRADING_LOGIC_EXECUTION_SPEC.md`, `OPERATOR_CONTROL_PLANE_AND_KRAKEN_ONBOARDING_SPEC.md`, `LOCAL_FIRST_RUNTIME_AND_PRIVACY_SPEC.md`, `MODEL_BUNDLE_DISTRIBUTION_AND_UPDATE_SPEC.md`, `PRODUCTION_OPERATIONS_AND_RELIABILITY_SPEC.md`.
  - Includes adaptive-horizon policy (no fixed global maximum holding window) and deterministic re-evaluation requirements.
  - Includes future-binding frontend/operator control plane, Kraken onboarding, local runtime/privacy, model-bundle update requirements, and production operations reliability requirements.
- `validations/`
  - Executable SQL validation gates used by test/rebuild flows.
  - Includes `PHASE_1C_VALIDATION.sql`, `PHASE_1D_RUNTIME_VALIDATION.sql`, `PHASE_2_REPLAY_HARNESS_VALIDATION.sql`, `PHASE_3_RUNTIME_VALIDATION.sql`, `PHASE_4_ORDER_LIFECYCLE_VALIDATION.sql`, `PHASE_5_PORTFOLIO_LEDGER_VALIDATION.sql`, `TEST_RUNTIME_INSERT_ENABLE.sql`.
- `repairs/`
  - Revision repair SQL artifacts kept at docs root scope.
  - Includes `PHASE_1C_REVISION_C_SCHEMA_REPAIR_BLUEPRINT.sql`, `PHASE_1C_REVISION_C_TRIGGER_REPAIR.sql`.
- `reports/`
  - QA planning and execution reports.
  - Includes `TEST_PLAN.md`, `TEST_REPORT.md`.
- `prompts/`
  - Governance prompts used during architect/auditor/implementation workflows.
- `phases/`
  - Phase-specific implementation logs and historical migration artifacts.
  - Historical snapshots may contain superseded assumptions; current trading-horizon policy is always defined in `docs/specs/*`.
  - See `docs/phases/README.md` for the interpretation policy used by implementers.
- `test_logs/`
  - Generated logs from `make test` / `scripts/test_all.sh` clean-room runs.

## Runtime/Test References

- Full deterministic test command: `make test`
- Test harness script: `scripts/test_all.sh`
- Replay CLI: `scripts/replay_cli.py`
- Validation SQL paths consumed by harness/tests:
  - `docs/validations/PHASE_1C_VALIDATION.sql`
  - `docs/validations/PHASE_1D_RUNTIME_VALIDATION.sql`
  - `docs/validations/PHASE_2_REPLAY_HARNESS_VALIDATION.sql`
  - `docs/validations/PHASE_3_RUNTIME_VALIDATION.sql`
  - `docs/validations/PHASE_4_ORDER_LIFECYCLE_VALIDATION.sql`
  - `docs/validations/PHASE_5_PORTFOLIO_LEDGER_VALIDATION.sql`
  - `docs/validations/TEST_RUNTIME_INSERT_ENABLE.sql`
