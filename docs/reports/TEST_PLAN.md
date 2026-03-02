# Global Codespace Test Plan (Phase 0 -> 1A -> 1B -> 1C -> 1D -> 2 -> 3 -> 4 -> 5)

Repository executable-artifact coverage closure is mandatory for phase completion.

## Scope Matrix

| Phase | Scope Under Test | Test Type(s) | Gate |
|---|---|---|---|
| 0 | Canonical schema bootstrap (`schema_bootstrap.sql`), foundational tables/constraints | Clean-room rebuild, schema equivalence | Bootstrap applies with `ON_ERROR_STOP=1`; schema dump checksum must match canonical bootstrap |
| 1A | Deterministic contract primitives carried in canonical schema | Integration validation SQL | Phase 1C validation checks all return zero |
| 1B | Replay-critical hashes, FK/hypertable safety, deterministic lineage constraints | Integration validation SQL | Phase 1C validation checks all return zero |
| 1C (Rev B/C) | Revision C repair artifacts, trigger/function/`_v2` cleanup readiness | Governance artifact verification + validation SQL | Required files exist and validation checks all return zero |
| 1D | Deterministic runtime execution modules (`execution/*`) and replay parity | Unit + DB integration + replay determinism tests | Runtime execution/replay tests pass; mismatch count zero; Python implementation coverage remains 100% line + branch |
| 2 | Replay harness architecture (boundary loader, canonical serialization, hash DAG, failure classification, window parity aggregation) | Unit + DB integration + validation SQL | Phase 2 validation checks all return zero; replay harness tests pass |
| 3 | Governed risk runtime implementation (profile-aware caps, volatility sizing, adaptive horizon routing) | Unit + DB integration + validation SQL | Phase 3 validation checks all return zero |
| 4 | Deterministic order lifecycle (signal → order → fill → lot → trade) | Unit + DB integration + validation SQL | Phase 4 validation checks all return zero |
| 5 | Deterministic portfolio/ledger engine (cash ledger + hourly state writers + replay parity extension) | Unit + DB integration + validation SQL | Phase 5 validation checks all return zero |
| 6A | Historical data foundation + continuous training bootstrap (full-history backfill, incremental sync, per-coin/global training orchestration) | Provider adapter contract tests + ingestion integration tests + training pipeline tests | Full available history coverage for Universe V1 verified; incremental sync/idempotency passes; retraining lineage and promotion-gate evidence is deterministic |
| Cross-Phase Coverage Policy | Repository executable-artifact coverage closure (Python + non-Python executables) | Coverage manifest + integration execution + contract tests | Every phase implementation is incomplete until coverage closure is achieved for executable artifacts introduced/modified by that phase |
| Future Productization (8A/8B/9A/9B/9C/10A) | Local-first runtime + macOS control plane + Kraken onboarding + model bundle updates | Contract tests + integration tests + security/privacy checks + deterministic replay checks | Local-first control, onboarding gates, per-currency limits, and model update safety gates all pass before phase closure |
| Production Ops & Reliability (10B/10C/10D/10E/10F/10G) | Compatibility governance + DR + incident response + audit export + retention + trust rotation | Contract tests + drill validations + release-gate checks | Production operations controls are validated and auditable before full production declaration |

## Test Categories

- Unit tests (deterministic/pure):
  - `tests/test_decision_engine.py`
  - `tests/test_activation_gate.py`
  - `tests/test_risk_runtime.py`
  - `tests/test_deterministic_context.py`
  - `tests/test_runtime_writer.py`
  - `tests/test_replay_engine_unit.py`
- Integration tests (ephemeral DB-backed):
  - `tests/integration/test_runtime_db_integration.py`
  - `tests/integration/test_replay_harness_integration.py`
  - `tests/integration/test_validation_sql.py`
- Determinism/replay parity:
  - `execution.replay_engine.replay_hour(...)` assertions in integration + unit tests
  - `execution.replay_harness.replay_manifest_parity(...)` + `replay_manifest_window_parity(...)` assertions
  - `execution.replay_harness.replay_manifest_tool_parity(...)` assertions
  - Adaptive-horizon path checks: verify no hardcoded global holding-window cap and deterministic re-evaluation of exit timing inputs
  - Replay CLI entrypoint present: `scripts/replay_cli.py` (`execute-hour`, `replay-hour`, `replay-manifest`, `replay-window`, `replay-tool`)
  - Governance parity gates in `docs/validations/PHASE_1D_RUNTIME_VALIDATION.sql`
- Governance SQL validations:
  - `docs/validations/PHASE_1C_VALIDATION.sql`
  - `docs/validations/PHASE_1D_RUNTIME_VALIDATION.sql`
  - `docs/validations/PHASE_2_REPLAY_HARNESS_VALIDATION.sql`
  - `docs/validations/PHASE_3_RUNTIME_VALIDATION.sql`
  - `docs/validations/PHASE_4_ORDER_LIFECYCLE_VALIDATION.sql`
  - `docs/validations/PHASE_5_PORTFOLIO_LEDGER_VALIDATION.sql`

- SQL artifact coverage policy:
  - Canonical SQL artifacts execute in integration coverage tests.
  - Duplicate SQL artifacts are enforced by strict equivalence to canonical repair files.
  - Historical SQL artifacts excluded from execution require explicit policy declaration.

- Non-SQL executable artifact contracts:
  - `scripts/test_all.sh` syntax and contract checks.
  - `.github/workflows/*.yml` clean-room gate contract checks.
  - `docker-compose.yml` parse/contract checks.
  - `Makefile` target contract checks.

- Productization planning scenarios (future authoritative gates):
  - First-run onboarding success path with valid Kraken key and required scopes.
  - Onboarding rejection for withdrawal-enabled keys.
  - Paper-first enforcement blocks live start until paper trial completion.
  - Risk warning + explicit confirmation flow before first live enablement.
  - Global budget cap enforcement under `PERCENT_OF_PV` and `ABSOLUTE_AMOUNT`.
  - Per-currency budget cap enforcement for `CAD`, `USD`, `USDC`.
  - Local runtime restart survival and deterministic state continuity.
  - Model update verifies signature/checksum and rejects tampered bundles.
  - Rollback to prior model bundle on failed update/compatibility check.
  - No secret leakage in logs/telemetry/crash outputs.
  - Full offline operation (except optional update check) remains functional.
  - Replay/audit parity remains intact after model-bundle update.

- Historical data + continuous training scenarios (Phase 6A/6B):
  - Historical provider adapter can backfill full available history for each Universe V1 symbol.
  - Incremental sync appends new bars/trades without duplicate key drift.
  - Gap detection emits explicit reconciliation tasks for missing intervals.
  - Dataset hash remains deterministic for identical source windows.
  - Per-coin specialist models and global models both train successfully and emit lineage metadata.
  - Promotion gate blocks activation when walk-forward/drift thresholds fail.

## Pass/Fail Gates

- Gate A: Clean-room DB bootstrap completes with no SQL errors.
- Gate B: `docs/validations/PHASE_1C_VALIDATION.sql` returns zero violations for all checks.
- Gate C: `docs/validations/PHASE_1D_RUNTIME_VALIDATION.sql` returns zero violations for all checks.
  - Includes explicit quantity overflow guard: `quantity_overflow_violation`.
- Gate D: `docs/validations/PHASE_2_REPLAY_HARNESS_VALIDATION.sql` returns zero violations for all checks.
- Gate E: `docs/validations/PHASE_3_RUNTIME_VALIDATION.sql` returns zero violations for all checks.
- Gate F: `docs/validations/PHASE_4_ORDER_LIFECYCLE_VALIDATION.sql` returns zero violations for all checks.
- Gate G: `docs/validations/PHASE_5_PORTFOLIO_LEDGER_VALIDATION.sql` returns zero violations for all checks.
- Gate H: Schema equivalence check succeeds (`live_schema.sql` equals `schema_bootstrap.sql`; identical SHA-256).
- Gate I: Pytest suite passes completely.
- Gate J: Coverage across `backend/*`, `execution/*`, and `scripts/*` is 100% line + branch.
- Gate K: SQL artifacts are fully covered by execution/equivalence policy with explicit excluded-artifact policy.
- Gate L: Repository executable-artifact coverage closure policy is enforced for phase completion evidence.
- Gate M: Command exits non-zero on any failure (abort discipline enforced by `set -euo pipefail`).
- Gate N: Local-first runtime control is validated without mandatory cloud dependency for core operation.
- Gate O: First live authorization is blocked until paper-trial completion and explicit risk confirmation.
- Gate P: Global and per-currency (`CAD`, `USD`, `USDC`) exposure caps are enforced with deterministic reason-code evidence.
- Gate Q: Model bundle updates enforce signature/checksum/compatibility checks with rollback-on-failure.
- Gate R: Universe V1 full-history backfill coverage is complete and auditable for all 30 symbols.
- Gate S: Continuous retraining/promotion gates run deterministically with reproducible lineage and no silent activation on failed validation.

## Commands

Primary single command:

```bash
make test
```

Equivalent direct command:

```bash
./scripts/test_all.sh
```

`./scripts/test_all.sh` performs:
1. Starts ephemeral TimescaleDB container.
2. Creates fresh `crypto_db_test`.
3. Applies `schema_bootstrap.sql` with `psql -v ON_ERROR_STOP=1`.
4. Runs Phase 1C + Phase 1D + Phase 2 + Phase 3 + Phase 4 + Phase 5 + Phase 6A + Phase 6B validation SQL (must be all zero).
5. Dumps schema and verifies canonical equivalence + SHA-256 match.
6. Enables test-only insert path on ephemeral DB via `docs/validations/TEST_RUNTIME_INSERT_ENABLE.sql`.
7. Runs Phase 2 replay-tool smoke check (`replay-tool`) on clean bootstrap state.
8. Runs `pytest` with coverage threshold enforcement.
