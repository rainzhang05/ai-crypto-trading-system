> Historical Artifact Notice
> This file records Phase 0-2 migration or implementation history and may contain then-active baseline defaults (for example hour-bucketed state, 10/20%/8% limits, and phase-locked constraints).
> Current implementation policy for new work is defined by:
> `docs/specs/TRADING_LOGIC_EXECUTION_SPEC.md`, `docs/specs/PROJECT_GOVERNANCE.md`, `docs/specs/RISK_RULES.md`, `docs/specs/MASTER_SPEC.md`, and `docs/specs/PROJECT_ROADMAP.md`.
>
# ARCHITECT REVISION — PHASE 1C-REV-A

## PHASE_1C_REVISION_A_SCHEMA_MIGRATION.md

## 1. Executive Summary of Defect

Phase 1C failed at M5 because `trade_signal_v2` was referenced before creation.

Defect class:
- Missing shadow-table definitions.
- Migration sequencing violation (consumer phase executed before producer DDL).
- Dependency-order defect (tables referenced by ALTER/trigger/FK not guaranteed to exist).

This revision corrects only structural omissions, dependency ordering, and sequencing while preserving deterministic contract v1.0 scope, invariants, hash propagation model, and enforcement strictness.

## 2. State Assessment (Post-M4 Partial State)

Observed state after prior run:
- M1 completed, migration lock `phase_1b_schema` active.
- M2 completed.
- M3 completed for execution-layer `_v2` tables only.
- M4 completed.
- M5 failed immediately on undefined table.
- No cutover executed.
- No append-only cutover triggers applied.
- No compression policy rebind executed.
- No replay regeneration executed.
- No rollback executed.

Safety determination:
- Current partial state safe: **YES**.
- Migration lock safe to keep active: **YES**.
- Deterministic replay can remain valid after correction: **YES** (because no cutover and no mixed-write unlock occurred).

## 3. Restart vs Resume Decision

Decision:
- Restart from M1: **NO**.
- Resume from M5: **YES**, with mandatory corrective bootstrap pre-step `M5.0` defined in this revision.
- Previously created execution `_v2` tables (`order_request_v2`, `order_fill_v2`, `position_lot_v2`, `executed_trade_v2`, `cash_ledger_v2`, `risk_event_v2`) must be dropped: **NO**.
- Action on existing execution `_v2` tables: **Preserve and extend**.

Mandatory gating:
- It is **not safe** to continue with original M5 directly.
- It is **safe** to continue from revised M5 only after successful execution of revised `M5.0` corrective shadow bootstrap.

## 4. Full Corrected Ordered Migration Plan (M1-M10)

### M1 — Pre-Migration Safety Lock (Unchanged)

- Keep existing `schema_migration_control` row for `phase_1b_schema` as authoritative lock.
- Keep write-block trigger function active.
- Preserve `T0` freeze boundary.

### M2 — Account Context Isolation Refactor (Unchanged)

- Preserve all M2 constraints already applied.
- No rollback or re-run required in current partial state.

### M3 — Shadow-Table Bootstrap (Corrected, Full)

Create all shadow tables before any later phase references them.

Producer order in M3:
1. Decision/model shadow tables (previously missing):
   - `trade_signal_v2`
   - `regime_output_v2`
   - `model_prediction_v2`
   - `meta_learner_component_v2`
2. Execution/risk shadow tables (already present in current run but included for completeness):
   - `order_request_v2`
   - `order_fill_v2`
   - `position_lot_v2`
   - `executed_trade_v2`
   - `cash_ledger_v2`
   - `risk_event_v2`

Rule:
- No later phase may reference any `_v2` table not created in M3.

### M4 — Temporal Refactor + Causality + Ledger Chain (Unchanged Scope)

- Keep completed M4 results.
- Ensure existing deferrable triggers remain attached to existing execution `_v2` tables.
- No drop/recreate required.

### M5.0 — Corrective Bootstrap for Current Partial State (New, Mandatory Resume Gate)

Execute only in current environment before revised M5:
- Create missing `_v2` tables from revised M3 using `IF NOT EXISTS`.
- Do not drop existing execution `_v2` tables.
- Verify existence of all ten `_v2` tables.
- Abort resume if any `_v2` table missing after `M5.0`.

### M5 — Economic Formula Enforcement (Unchanged Intent)

Apply on guaranteed-existing targets:
- `trade_signal_v2`
- `order_fill_v2`
- `executed_trade_v2`

### M6 — Risk-State Binding Enforcement (Unchanged Intent)

Apply on guaranteed-existing targets:
- `risk_hourly_state`
- `trade_signal_v2`
- `order_request_v2`

### M7 — Cluster Exposure Enforcement (Unchanged Intent)

- Create `correlation_cluster`, `asset_cluster_membership`, `cluster_exposure_hourly_state`.
- Extend `trade_signal_v2` and `order_request_v2`.

### M8 — Walk-Forward Lineage Enforcement (Unchanged Intent)

Apply on guaranteed-existing targets:
- `model_training_window`
- `backtest_fold_result`
- `model_prediction_v2`
- `regime_output_v2`
- `model_activation_gate`

### M9 — Hash Propagation Introduction (Corrected Target Completeness)

- Preserve original hash propagation model and deterministic preimage rules.
- Apply row-hash and parent-hash columns to all replay-authoritative targets.
- Correct shadow-table inclusion for omitted model component shadow:
  - `meta_learner_component_v2` (not omitted).

### M10 — Constraint Hardening, Atomic Cutover, Final Validation

- Validate pending constraints.
- Execute single-transaction cutover rename for all shadow targets listed in M10 DDL.
- Apply append-only triggers on new canonical tables.
- Restore compression policies on new canonical table names.
- Keep migration lock active until post-cutover validation passes.
- Unlock only after full validation success.

## 5. Explicit DDL Blocks for Every `_v2` Table

### 5.1 `trade_signal_v2`

```sql
CREATE TABLE IF NOT EXISTS trade_signal_v2
(LIKE trade_signal INCLUDING ALL);
```

### 5.2 `regime_output_v2`

```sql
CREATE TABLE IF NOT EXISTS regime_output_v2
(LIKE regime_output INCLUDING ALL);
```

### 5.3 `model_prediction_v2`

```sql
CREATE TABLE IF NOT EXISTS model_prediction_v2
(LIKE model_prediction INCLUDING ALL);
```

### 5.4 `meta_learner_component_v2`

```sql
CREATE TABLE IF NOT EXISTS meta_learner_component_v2
(LIKE meta_learner_component INCLUDING ALL);
```

### 5.5 `order_request_v2`

```sql
CREATE TABLE IF NOT EXISTS order_request_v2
(LIKE order_request INCLUDING ALL);
```

### 5.6 `order_fill_v2`

```sql
CREATE TABLE IF NOT EXISTS order_fill_v2
(LIKE order_fill INCLUDING ALL);
```

### 5.7 `position_lot_v2`

```sql
CREATE TABLE IF NOT EXISTS position_lot_v2
(LIKE position_lot INCLUDING ALL);
```

### 5.8 `executed_trade_v2`

```sql
CREATE TABLE IF NOT EXISTS executed_trade_v2
(LIKE executed_trade INCLUDING ALL);
```

### 5.9 `cash_ledger_v2`

```sql
CREATE TABLE IF NOT EXISTS cash_ledger_v2
(LIKE cash_ledger INCLUDING ALL);
```

### 5.10 `risk_event_v2`

```sql
CREATE TABLE IF NOT EXISTS risk_event_v2
(LIKE risk_event INCLUDING ALL);
```

### 5.11 Corrective Resume Gate Check (`M5.0`)

```sql
DO $$
BEGIN
    IF to_regclass('public.trade_signal_v2') IS NULL THEN
        RAISE EXCEPTION 'M5.0 gate failed: trade_signal_v2 missing';
    END IF;
    IF to_regclass('public.regime_output_v2') IS NULL THEN
        RAISE EXCEPTION 'M5.0 gate failed: regime_output_v2 missing';
    END IF;
    IF to_regclass('public.model_prediction_v2') IS NULL THEN
        RAISE EXCEPTION 'M5.0 gate failed: model_prediction_v2 missing';
    END IF;
    IF to_regclass('public.meta_learner_component_v2') IS NULL THEN
        RAISE EXCEPTION 'M5.0 gate failed: meta_learner_component_v2 missing';
    END IF;
    IF to_regclass('public.order_request_v2') IS NULL THEN
        RAISE EXCEPTION 'M5.0 gate failed: order_request_v2 missing';
    END IF;
    IF to_regclass('public.order_fill_v2') IS NULL THEN
        RAISE EXCEPTION 'M5.0 gate failed: order_fill_v2 missing';
    END IF;
    IF to_regclass('public.position_lot_v2') IS NULL THEN
        RAISE EXCEPTION 'M5.0 gate failed: position_lot_v2 missing';
    END IF;
    IF to_regclass('public.executed_trade_v2') IS NULL THEN
        RAISE EXCEPTION 'M5.0 gate failed: executed_trade_v2 missing';
    END IF;
    IF to_regclass('public.cash_ledger_v2') IS NULL THEN
        RAISE EXCEPTION 'M5.0 gate failed: cash_ledger_v2 missing';
    END IF;
    IF to_regclass('public.risk_event_v2') IS NULL THEN
        RAISE EXCEPTION 'M5.0 gate failed: risk_event_v2 missing';
    END IF;
END;
$$;
```

## 6. Dependency DAG Ordering Justification

Ordered dependency graph:
- `run_context` -> `trade_signal_v2` -> `order_request_v2` -> `order_fill_v2` -> `position_lot_v2` -> `executed_trade_v2`.
- `run_context` -> `cash_ledger_v2`.
- `risk_hourly_state` -> `trade_signal_v2` and `risk_event_v2`.
- `model_training_window` + `backtest_fold_result` + `model_activation_gate` -> `model_prediction_v2` and `regime_output_v2`.
- `model_version` + `run_context` -> `meta_learner_component_v2`.
- `risk_hourly_state` + `correlation_cluster` + `asset_cluster_membership` -> `cluster_exposure_hourly_state` -> `order_request_v2` cluster-cap trigger path.

Ordering guarantees enforced in this revision:
- Parent tables exist before child FK creation.
- `_v2` tables are created before any ALTER/trigger references.
- DEFERRABLE triggers are created only after target tables and referenced lookup tables exist.
- No `ALTER TABLE` appears before corresponding `CREATE TABLE` for the same object.

## 7. Cutover Atomicity Guarantee

Atomic cutover transaction (single unit, no partial rename state):

```sql
BEGIN;

LOCK TABLE
    trade_signal,
    regime_output,
    model_prediction,
    meta_learner_component,
    order_request,
    order_fill,
    position_lot,
    executed_trade,
    cash_ledger,
    risk_event
IN ACCESS EXCLUSIVE MODE;

DO $$
BEGIN
    IF to_regclass('public.trade_signal_v2') IS NULL THEN RAISE EXCEPTION 'cutover abort: trade_signal_v2 missing'; END IF;
    IF to_regclass('public.regime_output_v2') IS NULL THEN RAISE EXCEPTION 'cutover abort: regime_output_v2 missing'; END IF;
    IF to_regclass('public.model_prediction_v2') IS NULL THEN RAISE EXCEPTION 'cutover abort: model_prediction_v2 missing'; END IF;
    IF to_regclass('public.meta_learner_component_v2') IS NULL THEN RAISE EXCEPTION 'cutover abort: meta_learner_component_v2 missing'; END IF;
    IF to_regclass('public.order_request_v2') IS NULL THEN RAISE EXCEPTION 'cutover abort: order_request_v2 missing'; END IF;
    IF to_regclass('public.order_fill_v2') IS NULL THEN RAISE EXCEPTION 'cutover abort: order_fill_v2 missing'; END IF;
    IF to_regclass('public.position_lot_v2') IS NULL THEN RAISE EXCEPTION 'cutover abort: position_lot_v2 missing'; END IF;
    IF to_regclass('public.executed_trade_v2') IS NULL THEN RAISE EXCEPTION 'cutover abort: executed_trade_v2 missing'; END IF;
    IF to_regclass('public.cash_ledger_v2') IS NULL THEN RAISE EXCEPTION 'cutover abort: cash_ledger_v2 missing'; END IF;
    IF to_regclass('public.risk_event_v2') IS NULL THEN RAISE EXCEPTION 'cutover abort: risk_event_v2 missing'; END IF;
END;
$$;

ALTER TABLE trade_signal RENAME TO trade_signal_phase1a_archive;
ALTER TABLE regime_output RENAME TO regime_output_phase1a_archive;
ALTER TABLE model_prediction RENAME TO model_prediction_phase1a_archive;
ALTER TABLE meta_learner_component RENAME TO meta_learner_component_phase1a_archive;
ALTER TABLE order_request RENAME TO order_request_phase1a_archive;
ALTER TABLE order_fill RENAME TO order_fill_phase1a_archive;
ALTER TABLE position_lot RENAME TO position_lot_phase1a_archive;
ALTER TABLE executed_trade RENAME TO executed_trade_phase1a_archive;
ALTER TABLE cash_ledger RENAME TO cash_ledger_phase1a_archive;
ALTER TABLE risk_event RENAME TO risk_event_phase1a_archive;

ALTER TABLE trade_signal_v2 RENAME TO trade_signal;
ALTER TABLE regime_output_v2 RENAME TO regime_output;
ALTER TABLE model_prediction_v2 RENAME TO model_prediction;
ALTER TABLE meta_learner_component_v2 RENAME TO meta_learner_component;
ALTER TABLE order_request_v2 RENAME TO order_request;
ALTER TABLE order_fill_v2 RENAME TO order_fill;
ALTER TABLE position_lot_v2 RENAME TO position_lot;
ALTER TABLE executed_trade_v2 RENAME TO executed_trade;
ALTER TABLE cash_ledger_v2 RENAME TO cash_ledger;
ALTER TABLE risk_event_v2 RENAME TO risk_event;

COMMIT;
```

Guarantee statement:
- If any statement fails before `COMMIT`, the transaction rolls back and **no rename persists**.
- Therefore partial rename state is structurally prevented.

## 8. Validation Strategy Post-Revision

Validation sequence after revised M10:

1. Schema completeness checks:
- Confirm all canonical targets exist after cutover.
- Confirm all archive tables exist.
- Confirm no required table is missing.

2. Constraint health checks:
- `ALTER TABLE ... VALIDATE CONSTRAINT` for all `NOT VALID` constraints introduced in migration.
- Verify no invalid constraints remain in `pg_constraint` for migrated targets.

3. Trigger health checks:
- Confirm deferred enforcement triggers exist on canonical tables:
  - causality,
  - ledger chain,
  - risk gate,
  - cluster cap,
  - walk-forward contamination.
- Confirm append-only triggers exist on canonical append-only tables.

4. Deterministic replay validation:
- Regenerate replay-authoritative tables under lock.
- Recompute row hashes and replay roots.
- Validate replay parity and lineage continuity.
- Validate ledger arithmetic continuity and hash-chain continuity.

5. Safety unlock gate:
- Unlock migration only if all checks pass.
- If any check fails, keep lock active and do not resume writes.

## 9. Migration Lock Handling Instruction

Lock policy for this revision:
- Keep `phase_1b_schema` lock active through M5-M10 and post-cutover validation.
- Do not unlock immediately after cutover rename.
- Unlock only after validation strategy Section 8 succeeds.

Unlock DDL:

```sql
UPDATE schema_migration_control
SET locked = FALSE,
    unlocked_at_utc = now()
WHERE migration_name = 'phase_1b_schema';
```

Failure handling:
- On any migration failure before unlock, keep lock active.
- No rollback to M1 required.
- Resume from failed phase after defect correction and precondition revalidation.

## 10. Final Architect Declaration

This revision:
- Fixes missing `_v2` table creation defects.
- Fixes sequencing and dependency-order defects causing M5 failure.
- Preserves deterministic contract v1.0 scope and strict invariants.
- Preserves hash propagation model and enforcement logic.
- Preserves already successful M1-M4 work in current environment.
- Requires resume from revised M5 (with mandatory `M5.0` corrective bootstrap), not restart from M1.
- Requires preserving and extending existing execution `_v2` tables, not dropping them.
- Guarantees atomic cutover and guarantees no partial rename state.

ARCHITECT APPROVAL: PHASE 1C REVISION A ISSUED FOR PRODUCTION-SAFE RESUME.
