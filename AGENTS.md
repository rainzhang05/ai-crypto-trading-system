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
- Uses adaptive holding duration (no fixed maximum hold window such as 24h)
- Uses active campaign management (tactical partial exits/re-entries before final campaign exit)
- Is fully backtestable and replayable
- Uses append-only accounting
- Prevents leverage
- Uses profile-configurable drawdown and exposure controls with governed defaults
- Guarantees deterministic execution paths

This is a **production-grade financial system**.  
Architectural integrity and financial safety override performance or experimentation.

Authoritative governance rules are defined in:

- `docs/specs/PROJECT_GOVERNANCE.md`
- `docs/specs/RISK_RULES.md`
- `docs/specs/SCHEMA_DDL_MASTER.md`
- `docs/specs/TRADING_LOGIC_EXECUTION_SPEC.md`

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
- The authoritative schema contract is `schema_bootstrap.sql` and `docs/specs/SCHEMA_DDL_MASTER.md`.
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
- `docs/specs/SCHEMA_DDL_MASTER.md`

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

- Risk rules (`docs/specs/RISK_RULES.md`)
- Governance constraints (`docs/specs/PROJECT_GOVERNANCE.md`)
- Schema contract (`docs/specs/SCHEMA_DDL_MASTER.md`)

No logic may bypass database constraints.

---

# 6. GOVERNANCE LAYER

Location:
docs/

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
- `TRADING_LOGIC_EXECUTION_SPEC.md`

These define:
- Financial invariants
- Schema invariants
- Change management
- Risk constraints
- Strategy and decision-layer execution logic

Agents must treat these as binding contracts.

---

## 6.2 phases/

Contains phase-by-phase implementation logs:

- Phase 0 – Data layer foundation
- Phase 1A–1D – Deterministic contract hardening
- Phase 2 – Replay harness architecture
- Phase 3 – Governed risk runtime implementation
- Phase 4 – Deterministic order lifecycle closure
- Phase 5 – Deterministic portfolio/ledger runtime closure

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
docs/specs/SCHEMA_DDL_MASTER.md

The schema enforces:

- No leverage
- Drawdown-tier and entry-gating safety constraints (default profile values may evolve)
- Append-only financial tables
- Deterministic join keys
- Replay-safe hashes
- Risk-tier mapping constraints

Phase-alignment note:
- The Phase 0-2 canonical schema includes baseline fixed numeric safety defaults used by completed deterministic scaffolding.
- New implementation work for live strategy phases must follow `docs/specs/TRADING_LOGIC_EXECUTION_SPEC.md` and `docs/specs/PROJECT_ROADMAP.md` for profile-configurable controls and continuous live decisioning, implemented through governed schema/runtime evolution.

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

Phase 0-2 replay surfaces are hour-bucketed and must be reproducible from stored state.
Future live runtime phases remain required to preserve deterministic replay guarantees.

---

# 10. WHAT THIS CODESPACE IS NOT

This repository is **not**:

- A discretionary trading bot
- An experimentation playground
- A leverage-enabled system
- A latency-optimized HFT engine
- A fixed-window-only strategy locked to short holding periods
- A strategy research notebook

It is a capital-preserving deterministic trading infrastructure.

---

# 11. CURRENT PROJECT STATE

Completed:

- Phase 0 – Data foundation
- Phase 1A–1D – Deterministic contract enforcement
- Phase 2 – Replay harness architecture (deterministic replay tool implemented and validated)
- Phase 3 – Governed risk runtime implementation (profile persistence, volatility sizing, adaptive horizon, severe-loss recovery intent)
- Phase 4 – Deterministic order lifecycle engine (Signal→Order→Fill→Lot→Trade, deterministic retry/partial-fill handling, FIFO sell realization, replay parity extension)
- Phase 5 – Deterministic portfolio/ledger engine (runtime-owned hourly economic state materialization, deterministic cash-ledger writes, and replay parity for economic artifacts)
- Walk-forward gating
- Runtime risk enforcement
- Replay validation
- Test coverage

The system currently operates as a deterministic trading core with runtime-owned economic state materialization.
Phase 5 is closed; Phase 6 is the next active roadmap slice per `docs/specs/PROJECT_ROADMAP.md`.
Phase 5 closure details are documented in:

- `docs/phases/phase_5_portfolio_ledger/IMPLEMENTATION_LOG_PHASE_5.md`
- `docs/specs/ARCHITECT_DECISIONS.md`
- `docs/specs/PROJECT_ROADMAP.md`

Phase 4 handoff details remain documented in:
- `docs/phases/phase_4_order_lifecycle/IMPLEMENTATION_LOG_PHASE_4.md`
- `docs/specs/PROJECT_ROADMAP.md`

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
