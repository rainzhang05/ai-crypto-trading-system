# Global Codespace Test Plan (Phase 0 -> 1A -> 1B -> 1C -> 1D)

## Scope Matrix

| Phase | Scope Under Test | Test Type(s) | Gate |
|---|---|---|---|
| 0 | Canonical schema bootstrap (`schema_bootstrap.sql`), foundational tables/constraints | Clean-room rebuild, schema equivalence | Bootstrap applies with `ON_ERROR_STOP=1`; schema dump checksum must match canonical bootstrap |
| 1A | Deterministic contract primitives carried in canonical schema | Integration validation SQL | Phase 1C validation checks all return zero |
| 1B | Replay-critical hashes, FK/hypertable safety, deterministic lineage constraints | Integration validation SQL | Phase 1C validation checks all return zero |
| 1C (Rev B/C) | Revision C repair artifacts, trigger/function/`_v2` cleanup readiness | Governance artifact verification + validation SQL | Required files exist and validation checks all return zero |
| 1D | Deterministic runtime execution modules (`execution/*`) and replay parity | Unit + DB integration + replay determinism tests | Runtime execution/replay tests pass; mismatch count zero; execution module coverage target = 100% |

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
  - `tests/integration/test_validation_sql.py`
- Determinism/replay parity:
  - `execution.replay_engine.replay_hour(...)` assertions in integration + unit tests
  - Governance parity gates in `governance/validations/PHASE_1D_RUNTIME_VALIDATION.sql`
- Governance SQL validations:
  - `governance/validations/PHASE_1C_VALIDATION.sql`
  - `governance/validations/PHASE_1D_RUNTIME_VALIDATION.sql`

## Pass/Fail Gates

- Gate A: Clean-room DB bootstrap completes with no SQL errors.
- Gate B: `governance/validations/PHASE_1C_VALIDATION.sql` returns zero violations for all checks.
- Gate C: `governance/validations/PHASE_1D_RUNTIME_VALIDATION.sql` returns zero violations for all checks.
- Gate D: Schema equivalence check succeeds (`live_schema.sql` equals `schema_bootstrap.sql`; identical SHA-256).
- Gate E: Pytest suite passes completely.
- Gate F: Coverage across `execution/*` is 100% line coverage.
- Gate G: Command exits non-zero on any failure (abort discipline enforced by `set -euo pipefail`).

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
4. Runs Phase 1C + Phase 1D validation SQL (must be all zero).
5. Dumps schema and verifies canonical equivalence + SHA-256 match.
6. Enables test-only insert path on ephemeral DB via `governance/validations/TEST_RUNTIME_INSERT_ENABLE.sql`.
7. Runs `pytest` with coverage threshold enforcement.
