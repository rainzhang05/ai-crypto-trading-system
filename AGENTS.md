# AGENTS.md
## AI Crypto Trading System – Codespace Orientation Document

This document exists solely to explain the structure, purpose, and architectural intent of this repository to AI agents operating inside this codespace.
It defines what this system is, what it enforces, and how the components fit together.

---

# 1. SYSTEM PURPOSE

This repository implements a **deterministic, capital-preserving, AI-driven crypto trading system**.

The system:

- Trades crypto assets (Kraken assumed venue)
- Enforces strict capital control
- Is fully backtestable and replayable
- Uses append-only accounting
- Prevents leverage
- Enforces hard 20% drawdown halt
- Guarantees deterministic execution paths

This is a **production-grade financial system**.  
Architectural integrity and financial safety override performance or experimentation.

Authoritative governance rules are defined in:

- `governance/specs/PROJECT_GOVERNANCE.md`
- `governance/specs/RISK_RULES.md`
- `governance/specs/SCHEMA_DDL_MASTER.md`

These documents define non-negotiable constraints.

---

# 2. HIGH-LEVEL ARCHITECTURE

The system consists of:

1. Deterministic database layer (PostgreSQL + TimescaleDB)
2. Execution layer (Python runtime logic)
3. Governance layer (specifications, constraints, migration history)
4. Test & validation layer (unit + integration + SQL validation)
5. Replay-safe accounting layer

All runtime state must be reconstructable from database records.

---

# 3. DIRECTORY STRUCTURE

## Root

- `LICENSE` – legal license
- `Makefile` – developer automation commands
- `README.md` – human-readable project intro
- `docker-compose.yml` – database container orchestration
- `schema_bootstrap.sql` – canonical executable schema snapshot
- `pytest.ini` – test configuration
- `requirements-dev.txt` – development dependencies
- `scripts/test_all.sh` – unified test runner

---

# 4. BACKEND DATABASE LAYER

Location:
backend/db/

This contains SQLAlchemy model definitions for the core database domain.

Important:
- The authoritative schema contract is `schema_bootstrap.sql` and `governance/specs/SCHEMA_DDL_MASTER.md`.
- Phase 1D/2 runtime + replay logic is SQL-first (deterministic query surfaces in `execution/`).
- ORM classes are helpful references for application code, but schema governance must always follow the canonical SQL contract.

## 4.1 Core Files

- `base.py` – SQLAlchemy base
- `enums.py` – enum definitions aligned with schema contract

## 4.2 Models

Each file in:
backend/db/models/

Represents a schema table from `SCHEMA_DDL_MASTER.md`.

Examples:

- `account.py`
- `asset.py`
- `portfolio.py`
- `risk.py`
- `signal.py`
- `execution.py`
- `model_outputs.py`
- `run_context.py`

These must remain structurally aligned with:

- `schema_bootstrap.sql`
- `governance/specs/SCHEMA_DDL_MASTER.md`

Schema drift in canonical SQL is not allowed.

---

# 5. EXECUTION LAYER

Location:
execution/

This is the deterministic runtime decision engine.

## Files:

- `activation_gate.py`  
  Controls model activation eligibility.

- `decision_engine.py`  
  Generates trade signals based on model outputs and risk state.

- `deterministic_context.py`  
  Ensures replay-consistent state handling.

- `replay_engine.py`  
  Reconstructs execution flow from database history.

- `replay_harness.py`  
  Phase 2 replay harness (boundary loading, canonical serialization, hash DAG recomputation, parity comparison).

- `scripts/replay_cli.py`  
  CLI entrypoint for deterministic replay operations (`execute-hour`, `replay-hour`, `replay-manifest`, `replay-window`, `replay-tool`).

- `risk_runtime.py`  
  Enforces runtime drawdown and capital controls.

- `runtime_writer.py`  
  Writes signals, orders, and state transitions to DB.

This layer must strictly respect:

- Risk rules (`governance/specs/RISK_RULES.md`)
- Governance constraints (`governance/specs/PROJECT_GOVERNANCE.md`)
- Schema contract (`governance/specs/SCHEMA_DDL_MASTER.md`)

No logic may bypass database constraints.

---

# 6. GOVERNANCE LAYER

Location:
governance/

This is the architectural control center.

## 6.1 specs/

Contains authoritative rule definitions:

- `MASTER_SPEC.md`
- `PROJECT_ROADMAP.md`
- `PROJECT_GOVERNANCE.md`
- `RISK_RULES.md`
- `SCHEMA_DDL_MASTER.md`
- `ARCHITECT_DECISIONS.md`
- `MODEL_ASSUMPTIONS.md`

These define:
- Financial invariants
- Schema invariants
- Change management
- Risk constraints

Agents must treat these as binding contracts.

---

## 6.2 phases/

Contains phase-by-phase implementation logs:

- Phase 0 – Data layer foundation
- Phase 1A–1D – Deterministic contract hardening
- Phase 2 – Replay harness architecture

These logs document architectural evolution and repair cycles.

---

## 6.3 validations/

SQL validation scripts used to verify schema correctness.

---

## 6.4 repairs/

Schema repair blueprints for drift correction.

---

## 6.5 reports/

Test plans and reports documenting system validation.

---

## 6.6 test_logs/

Captured execution logs from container runs, schema validation, and test cycles.

These are historical artifacts and must not be treated as runtime logic.

---

# 7. TEST LAYER

Location:
tests/

Contains:

- Unit tests for execution layer
- Integration tests for runtime → DB path
- SQL validation checks
- Deterministic replay validation

Structure:

tests/
├── integration/
├── utils/
├── test_*.py

The system is not considered stable unless:

- All tests pass
- SQL validations pass
- No schema drift is detected
- Runtime replay matches historical state

---

# 8. SCHEMA & DATABASE CONTRACT

Authoritative schema:
schema_bootstrap.sql

Source-of-truth spec:
governance/specs/SCHEMA_DDL_MASTER.md

The schema enforces:

- No leverage
- Hard 20% drawdown halt
- Append-only financial tables
- Deterministic join keys
- Replay-safe hashes
- Risk-tier mapping constraints

Database constraints are considered first-class safety controls.

Runtime must not weaken them.

---

# 9. DETERMINISM REQUIREMENT

Determinism is enforced via:

- `run_id`
- `account_id`
- `hour_ts_utc`
- Composite FK keys
- Immutable hash fields
- Append-only triggers
- Unique signal identity
- Replay engine

Every trading hour must be reproducible from stored state.

---

# 10. WHAT THIS CODESPACE IS NOT

This repository is **not**:

- A discretionary trading bot
- An experimentation playground
- A leverage-enabled system
- A latency-optimized HFT engine
- A strategy research notebook

It is a capital-preserving deterministic trading infrastructure.

---

# 11. CURRENT PROJECT STATE

Completed:

- Phase 0 – Data foundation
- Phase 1A–1D – Deterministic contract enforcement
- Phase 2 – Replay harness architecture (deterministic replay tool implemented and validated)
- Walk-forward gating
- Runtime risk enforcement
- Replay validation
- Test coverage

The system currently operates as a deterministic trading core.
Phase 2 is closed; Phase 3 is ready to begin per `governance/specs/PROJECT_ROADMAP.md`.

Future phases (per roadmap) will extend:

- Live exchange connectivity
- Paper trading deployment
- Monitoring / dashboards
- Production orchestration

---

# 12. AGENT EXPECTATIONS

Agents operating in this codespace must:

- Preserve schema integrity
- Preserve risk constraints
- Avoid architectural drift
- Maintain deterministic behavior
- Never bypass financial safety logic
- Respect governance documents as binding contracts

If conflict arises:

1. Capital preservation
2. Determinism
3. Risk enforcement
4. Backtest integrity
5. Performance

Priority order must be preserved.

---

END OF AGENTS.md
