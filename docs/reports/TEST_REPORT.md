# Global Codespace Test Report (Phase 0 -> 1A -> 1B -> 1C -> 1D) [Historical]

Current Phase 2 status and closure evidence are documented in:
- `docs/reports/PHASE_2_TEST_REPORT.md`
- `docs/phases/phase_2_replay_harness/PHASE_2_COMPLETION_REPORT.md`

## Final Decision

**PASS**

All required gates for this review run passed in a clean-room ephemeral DB run, with deterministic test coverage expansion completed.

## 1) Repository Inventory and Structure Check

### Migration/DDL artifacts for Phase 0/1A/1B/1C

- Canonical schema bootstrap:
  - `schema_bootstrap.sql`
- Authoritative schema/governance specs:
  - `docs/specs/SCHEMA_DDL_MASTER.md`
  - `docs/specs/MASTER_SPEC.md`
  - `docs/specs/PROJECT_ROADMAP.md`
  - `docs/specs/PROJECT_GOVERNANCE.md`
  - `docs/specs/ARCHITECT_DECISIONS.md`
  - `docs/specs/RISK_RULES.md`
  - `docs/specs/MODEL_ASSUMPTIONS.md`
- Phase 1B/1C migration artifacts:
  - `docs/phases/phase_1_deterministic_contract/SCHEMA_MIGRATION_PHASE_1B.md`
  - `docs/phases/phase_1_deterministic_contract/PHASE_1C_REVISION_A_SCHEMA_MIGRATION.md`
  - `docs/phases/phase_1_deterministic_contract/PHASE_1C_REVISION_B_SCHEMA_MIGRATION.md`
  - `docs/phases/phase_1_deterministic_contract/PHASE_1C_REVISION_C_SCHEMA_REPAIR_BLUEPRINT.sql`
  - `docs/phases/phase_1_deterministic_contract/PHASE_1C_REVISION_C_TRIGGER_REPAIR.sql`

### Canonical schema bootstrap location

- `schema_bootstrap.sql`

### Phase 1D runtime modules

- `execution/deterministic_context.py`
- `execution/decision_engine.py`
- `execution/runtime_writer.py`
- `execution/activation_gate.py`
- `execution/risk_runtime.py`
- `execution/replay_engine.py`

### Governance logs/blueprints present

- `docs/phases/phase_0_data_layer_foundation/IMPLEMENTATION_LOG_PHASE_0.md`
- `docs/phases/phase_1_deterministic_contract/IMPLEMENTATION_LOG_PHASE_1A.md`
- `docs/phases/phase_1_deterministic_contract/IMPLEMENTATION_LOG_PHASE_1B.md`
- `docs/phases/phase_1_deterministic_contract/IMPLEMENTATION_LOG_PHASE_1C.md`
- `docs/phases/phase_1_deterministic_contract/IMPLEMENTATION_LOG_PHASE_1D.md`
- `docs/repairs/PHASE_1C_REVISION_C_SCHEMA_REPAIR_BLUEPRINT.sql`
- `docs/repairs/PHASE_1C_REVISION_C_TRIGGER_REPAIR.sql`

## 2) Governance Artifact Completeness Check

- `docs/repairs/PHASE_1C_REVISION_C_SCHEMA_REPAIR_BLUEPRINT.sql`: **present**.
- Matched against phase artifact copy (`cmp` exit 0): **match**.
- `docs/validations/PHASE_1D_RUNTIME_VALIDATION.sql`: **present**.
- Required phase implementation logs (0/1A/1B/1C/1D): **present**.

## 3) Clean-Room Rebuild Proof

### Exact commands executed

```bash
./scripts/test_all.sh
make test
```

### Key rebuild commands executed by script

```bash
docker run -d --name crypto-timescale-test ... timescale/timescaledb:2.13.1-pg15 ...
docker exec -i crypto-timescale-test psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS crypto_db_test;"
docker exec -i crypto-timescale-test psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE crypto_db_test;"
docker exec -i crypto-timescale-test psql -U postgres -d crypto_db_test -v ON_ERROR_STOP=1 < schema_bootstrap.sql
```

### Log evidence

- Container/bootstrap logs:
  - `docs/test_logs/container_start.log`
  - `docs/test_logs/db_create.log`
  - `docs/test_logs/schema_bootstrap_apply.log`

## 4) Canonical Schema Equivalence Check

### Commands

```bash
docker exec crypto-timescale-test pg_dump -U postgres -d crypto_db_test --schema-only --no-owner --no-privileges > docs/test_logs/live_schema.sql
shasum -a 256 docs/test_logs/live_schema.sql schema_bootstrap.sql
cmp -s docs/test_logs/live_schema.sql schema_bootstrap.sql
```

### Result

- SHA-256 (live schema): `875eec6c382fc93b19c4a97a3e0442103acdb9487df6b1ca1511f79aef18fea2`
- SHA-256 (canonical): `875eec6c382fc93b19c4a97a3e0442103acdb9487df6b1ca1511f79aef18fea2`
- Exact byte-compare (`cmp`): **match**
- Evidence: `docs/test_logs/schema_sha256.log`, `docs/test_logs/live_schema.sql`

## 5) Validation Gate Outputs (All Zero)

### Phase 1C gate output

From `docs/test_logs/phase_1c_validation.log`:

- triggers_with_v2_refs_action_statement=0
- functions_with_v2_refs_blueprint_scope=0
- functions_named_with_v2_suffix=0
- residual_v2_relations=0
- no_fk_targets_on_hypertables=0
- nullable_replay_critical_hash_columns=0
- walk_forward_contamination_exclusion=0
- cross_account_isolation=0
- ledger_arithmetic_continuity=0
- cluster_cap_enforcement=0
- deterministic_replay_parity_mismatch_pairs=0

### Phase 1D gate output

From `docs/test_logs/phase_1d_validation.log`:

- append_only_trigger_gaps=0
- replay_sample_hour_shortfall=0
- replay_manifest_root_mismatch=0
- cross_account_isolation=0
- ledger_arithmetic_continuity=0
- walk_forward_contamination_exclusion=0
- activation_gate_enforcement=0
- runtime_risk_gate_violation=0
- runtime_risk_gate_logging_gap=0
- cluster_cap_violation=0
- cluster_cap_logging_gap=0
- quantity_overflow_violation=0
- deterministic_replay_parity_mismatch_pairs=0

## 6) Automated Test Execution and Coverage

### Command

```bash
pytest
```

(Executed inside `./scripts/test_all.sh` after clean-room bootstrap and validations.)

### Result

- `86 passed`
- Coverage safety target for `execution/*` passed at `100.00%`
- Total coverage: `100.00%`

Per-module coverage (`execution/*`):

- `execution/activation_gate.py`: 100%
- `execution/decision_engine.py`: 100%
- `execution/deterministic_context.py`: 100%
- `execution/replay_engine.py`: 100%
- `execution/risk_runtime.py`: 100%
- `execution/runtime_writer.py`: 100%

Evidence: `docs/test_logs/pytest.log`

## 7) Failures Encountered and Fixes Applied

The following blocking failures were found during this review cycle and fixed deterministically:

1. Integration fixture key collisions (asset symbol / active cost profile uniqueness).
   - Fix: deterministic unique asset symbols; reuse existing active KRAKEN cost profile in fixtures.
2. Activation negative-path integration test violated strict context pre-validation.
   - Fix: test now uses `APPROVED` activation with future `validation_window_end_utc` to trigger deterministic activation-gate rejection in runtime planning.
3. Parent-hash mismatch integration setup conflicted with DB invariant trigger.
   - Fix: converted to explicit insert-abort test proving mismatch rejection with zero partial writes.
4. Validation SQL test parser incorrectly split semicolons inside comments.
   - Fix: strip comment lines before statement splitting.
5. Replay validation test drift after runtime fixture inserts (`replay_manifest_root_mismatch`).
   - Fix: fixture loader now inserts deterministic `replay_manifest` row aligned with `run_context`.
6. Unit test slippage hash used non-hex token (`"l"`).
   - Fix: replaced with valid hex hash.
7. Ephemeral DB startup flakiness.
   - Fix: hardened startup readiness checks (consecutive healthy checks + post-ready stability check) in `scripts/test_all.sh`.
8. Remaining uncovered execution branches during safety hardening.
   - Fix: added exhaustive branch tests across context constructor, replay diffing, and append-only writer guards to reach 100% execution-module coverage.

## 8) Governance Layout Cleanup

- Governance root was reorganized into typed subfolders for maintainability:
  - `docs/specs/`
  - `docs/validations/`
  - `docs/repairs/`
  - `docs/reports/`
  - `docs/prompts/`
- Updated all script/test/document references to new paths.
- Added `docs/README.md` as a directory map and usage guide.

## 9) Determinism/Replay Evidence

- Runtime DB integration test executes one-hour deterministic runtime and verifies:
  - append-only behavior on runtime tables,
  - required artifact inserts,
  - replay parity with `replay_hour(...)` mismatch count = 0.
- Governance replay parity gates all returned zero.

## 10) Schema/Governance Safety Confirmation

- No schema redesign introduced.
- No constraints relaxed.
- No new phases added.
- No acceptance criteria changed.
- No contract expansion performed.

## 11) Phase 1D Closure Addendum (2026-03-01 UTC)

- Added deterministic replay CLI entrypoint:
  - `scripts/replay_cli.py` (`execute-hour`, `replay-hour`).
- Fixed potential duplicate `risk_event_id` collisions when repeated asset-level violations occur in a single run-hour:
  - Runtime plan now de-duplicates semantically identical risk events per run-hour before insert.
- Added explicit quantity overflow validation gate in:
  - `docs/validations/PHASE_1D_RUNTIME_VALIDATION.sql`
  - Check name: `quantity_overflow_violation`
