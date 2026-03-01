# ARCHITECT REVISION - PHASE 1C REVISION B

## PHASE_1C_REVISION_B_SCHEMA_MIGRATION.md

## 1. Executive Summary

Phase 1C failed at M6 on `foreign keys to hypertables are not supported` while introducing strict risk-state binding on `trade_signal_v2`.

Revision B preserves deterministic contract v1.0 strictness and Timescale compatibility by replacing illegal hypertable FK targets with identity-table FK targets.

Core Revision B change:
- Introduce non-hypertable identity tables for hypertable FK targets.
- Synchronize identities from hypertables via schema triggers.
- Repoint all M6/M7 hypertable-target FKs to identity tables.
- Keep replay, hash, walk-forward, cluster-cap, risk-gate, cutover atomicity, and lock semantics intact.

Decision:
- Resume from failed M6 state, do not restart from M1.
- Keep existing lock active until M10 + full validation pass.

## 2. Root Cause Analysis

Direct failure:
- M6 attempted to create FK:
  - child: `trade_signal_v2`
  - target: `risk_hourly_state` hypertable
  - key: `(run_mode, account_id, risk_state_hour_ts_utc, risk_state_run_id)` -> `(run_mode, account_id, hour_ts_utc, source_run_id)`
- Timescale rejected FK creation because target is a hypertable.

Architectural defect class:
- Deterministic constraints were designed correctly for lineage strictness, but physical FK target class (hypertable) is incompatible with Timescale FK limitations.
- M7 had the same latent defect (`cluster_exposure_hourly_state` -> `risk_hourly_state`).

Corrective principle:
- Preserve constraint intent and strictness by separating:
  - logical identity enforcement (FK to normal identity table), and
  - state payload storage/performance (hypertable).

## 3. List of Illegal FK Patterns Identified

### 3.1 Identified in Phase 1C M6-M9 path

| Pattern ID | Child Table | FK Name (planned/existing) | Target Hypertable | Class | Revision B Action |
|---|---|---|---|---|---|
| ILLEGAL-FK-01 | `trade_signal_v2` | `fk_trade_signal_v2_risk_state_exact` | `risk_hourly_state` | Normal table -> hypertable | Replace with FK to `risk_hourly_state_identity` |
| ILLEGAL-FK-02 | `cluster_exposure_hourly_state` | `fk_cluster_exposure_hourly_state_risk` | `risk_hourly_state` | Normal table -> hypertable | Replace with FK to `risk_hourly_state_identity` |

### 3.2 Identified in baseline schema that remain physically illegal in Timescale model

| Pattern ID | Child Table | FK Name (bootstrap) | Target Hypertable | Class | Revision B Action |
|---|---|---|---|---|---|
| ILLEGAL-FK-03 | `risk_hourly_state` | `fk_risk_hourly_state_portfolio` | `portfolio_hourly_state` | Hypertable -> hypertable | Replace with FK to `portfolio_hourly_state_identity` |
| ILLEGAL-FK-04 | `trade_signal` | `fk_trade_signal_risk_hourly_state` | `risk_hourly_state` | Normal table -> hypertable | Replace with FK to `risk_hourly_state_identity` |
| ILLEGAL-FK-05 | `risk_event` | `fk_risk_event_risk_hourly_state` | `risk_hourly_state` | Normal table -> hypertable | Replace with FK to `risk_hourly_state_identity` |

### 3.3 Required analysis list confirmation

Hypertable targets requested for explicit review:
- `risk_hourly_state`: FK target used in M6 and M7; identity table required.
- `portfolio_hourly_state`: FK target in baseline (`risk_hourly_state`); identity table required.
- `position_hourly_state`: no FK consumers introduced in M6-M9; no identity table introduced in Revision B.
- `feature_snapshot`: no FK consumers introduced in M6-M9; no identity table introduced in Revision B.
- `model_prediction`: no FK consumers introduced in M6-M9; no identity table introduced in Revision B.
- `meta_learner_component`: no FK consumers introduced in M6-M9; no identity table introduced in Revision B.
- Any other hypertable targets in M6-M9: none.

Strictness note:
- No FK consumer of the above omitted targets exists in M6-M9 migration scope; therefore no corresponding identity table is needed for this revision.

## 4. Identity Table Strategy Definition

### 4.1 Strategy

For every hypertable that must be referenced by FK in migration scope:
1. Create a normal append-only identity table containing only FK identity key columns.
2. Add PK/UNIQUE on identity key in identity table.
3. Synchronize identity rows from hypertable inserts with trigger(s).
4. Prevent identity mutation (`UPDATE`/`DELETE`) via append-only trigger.
5. Reject orphan identity inserts via validation trigger (identity row must map to real hypertable row).
6. Repoint all child FKs to identity table.

### 4.2 Why this preserves deterministic strictness

- FK existence checks remain database-enforced (schema-level).
- Risk-state binding remains exact on `(run_mode, account_id, hour_ts_utc, source_run_id)`.
- Cluster-cap path still binds to same risk-state identity key.
- No application-layer fallback is introduced.

### 4.3 Identity coverage in Revision B

Introduced identity tables:
- `risk_hourly_state_identity`
- `portfolio_hourly_state_identity`

Not introduced (no FK consumers in scope):
- `position_hourly_state_identity`
- `feature_snapshot_identity`
- `model_prediction_identity`
- `meta_learner_component_identity`

## 5. DDL for Each Identity Table Introduced

### 5.1 `portfolio_hourly_state_identity`

```sql
CREATE TABLE IF NOT EXISTS portfolio_hourly_state_identity (
    run_mode run_mode_enum NOT NULL,
    account_id SMALLINT NOT NULL,
    hour_ts_utc TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_portfolio_hourly_state_identity
        PRIMARY KEY (run_mode, account_id, hour_ts_utc),
    CONSTRAINT ck_portfolio_hourly_state_identity_hour_aligned
        CHECK (date_trunc('hour', hour_ts_utc) = hour_ts_utc)
);

DROP TRIGGER IF EXISTS trg_portfolio_hourly_state_identity_append_only ON portfolio_hourly_state_identity;
CREATE TRIGGER trg_portfolio_hourly_state_identity_append_only
BEFORE UPDATE OR DELETE ON portfolio_hourly_state_identity
FOR EACH ROW EXECUTE FUNCTION fn_enforce_append_only();
```

### 5.2 `risk_hourly_state_identity`

```sql
CREATE TABLE IF NOT EXISTS risk_hourly_state_identity (
    run_mode run_mode_enum NOT NULL,
    account_id SMALLINT NOT NULL,
    hour_ts_utc TIMESTAMPTZ NOT NULL,
    source_run_id UUID NOT NULL,
    CONSTRAINT pk_risk_hourly_state_identity
        PRIMARY KEY (run_mode, account_id, hour_ts_utc, source_run_id),
    CONSTRAINT ck_risk_hourly_state_identity_hour_aligned
        CHECK (date_trunc('hour', hour_ts_utc) = hour_ts_utc),
    CONSTRAINT fk_risk_hourly_state_identity_run_context
        FOREIGN KEY (source_run_id, account_id, run_mode, hour_ts_utc)
        REFERENCES run_context (run_id, account_id, run_mode, hour_ts_utc)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT
);

DROP TRIGGER IF EXISTS trg_risk_hourly_state_identity_append_only ON risk_hourly_state_identity;
CREATE TRIGGER trg_risk_hourly_state_identity_append_only
BEFORE UPDATE OR DELETE ON risk_hourly_state_identity
FOR EACH ROW EXECUTE FUNCTION fn_enforce_append_only();
```

### 5.3 Identity bootstrap/backfill (safe/idempotent)

```sql
INSERT INTO portfolio_hourly_state_identity (run_mode, account_id, hour_ts_utc)
SELECT p.run_mode, p.account_id, p.hour_ts_utc
FROM portfolio_hourly_state p
ON CONFLICT DO NOTHING;

INSERT INTO risk_hourly_state_identity (run_mode, account_id, hour_ts_utc, source_run_id)
SELECT r.run_mode, r.account_id, r.hour_ts_utc, r.source_run_id
FROM risk_hourly_state r
ON CONFLICT DO NOTHING;
```

## 6. Insert Synchronization Trigger Definitions

### 6.1 Portfolio hypertable -> portfolio identity synchronization

```sql
CREATE OR REPLACE FUNCTION fn_sync_portfolio_hourly_state_identity_ins()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO portfolio_hourly_state_identity (run_mode, account_id, hour_ts_utc)
    VALUES (NEW.run_mode, NEW.account_id, NEW.hour_ts_utc)
    ON CONFLICT DO NOTHING;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_portfolio_hourly_state_identity_sync_ins ON portfolio_hourly_state;
CREATE TRIGGER trg_portfolio_hourly_state_identity_sync_ins
AFTER INSERT ON portfolio_hourly_state
FOR EACH ROW EXECUTE FUNCTION fn_sync_portfolio_hourly_state_identity_ins();
```

### 6.2 Risk hypertable -> risk identity synchronization

```sql
CREATE OR REPLACE FUNCTION fn_sync_risk_hourly_state_identity_ins()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO risk_hourly_state_identity (run_mode, account_id, hour_ts_utc, source_run_id)
    VALUES (NEW.run_mode, NEW.account_id, NEW.hour_ts_utc, NEW.source_run_id)
    ON CONFLICT DO NOTHING;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_risk_hourly_state_identity_sync_ins ON risk_hourly_state;
CREATE TRIGGER trg_risk_hourly_state_identity_sync_ins
AFTER INSERT ON risk_hourly_state
FOR EACH ROW EXECUTE FUNCTION fn_sync_risk_hourly_state_identity_ins();
```

### 6.3 Source-key immutability guard triggers (to prevent identity drift)

```sql
CREATE OR REPLACE FUNCTION fn_guard_portfolio_hourly_state_identity_key_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'portfolio_hourly_state is append-only for identity synchronization';
    END IF;

    IF NEW.run_mode IS DISTINCT FROM OLD.run_mode
       OR NEW.account_id IS DISTINCT FROM OLD.account_id
       OR NEW.hour_ts_utc IS DISTINCT FROM OLD.hour_ts_utc THEN
        RAISE EXCEPTION 'portfolio_hourly_state identity key mutation is not allowed';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_guard_portfolio_hourly_state_identity_key_mutation ON portfolio_hourly_state;
CREATE TRIGGER trg_guard_portfolio_hourly_state_identity_key_mutation
BEFORE UPDATE OR DELETE ON portfolio_hourly_state
FOR EACH ROW EXECUTE FUNCTION fn_guard_portfolio_hourly_state_identity_key_mutation();

CREATE OR REPLACE FUNCTION fn_guard_risk_hourly_state_identity_key_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'risk_hourly_state is append-only for identity synchronization';
    END IF;

    IF NEW.run_mode IS DISTINCT FROM OLD.run_mode
       OR NEW.account_id IS DISTINCT FROM OLD.account_id
       OR NEW.hour_ts_utc IS DISTINCT FROM OLD.hour_ts_utc
       OR NEW.source_run_id IS DISTINCT FROM OLD.source_run_id THEN
        RAISE EXCEPTION 'risk_hourly_state identity key mutation is not allowed';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_guard_risk_hourly_state_identity_key_mutation ON risk_hourly_state;
CREATE TRIGGER trg_guard_risk_hourly_state_identity_key_mutation
BEFORE UPDATE OR DELETE ON risk_hourly_state
FOR EACH ROW EXECUTE FUNCTION fn_guard_risk_hourly_state_identity_key_mutation();
```

### 6.4 Identity orphan prevention triggers

```sql
CREATE OR REPLACE FUNCTION fn_validate_portfolio_identity_source_exists()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM portfolio_hourly_state p
        WHERE p.run_mode = NEW.run_mode
          AND p.account_id = NEW.account_id
          AND p.hour_ts_utc = NEW.hour_ts_utc
    ) THEN
        RAISE EXCEPTION 'portfolio identity row has no source hypertable row';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS ctrg_portfolio_identity_source_exists ON portfolio_hourly_state_identity;
CREATE CONSTRAINT TRIGGER ctrg_portfolio_identity_source_exists
AFTER INSERT ON portfolio_hourly_state_identity
DEFERRABLE INITIALLY IMMEDIATE
FOR EACH ROW EXECUTE FUNCTION fn_validate_portfolio_identity_source_exists();

CREATE OR REPLACE FUNCTION fn_validate_risk_identity_source_exists()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM risk_hourly_state r
        WHERE r.run_mode = NEW.run_mode
          AND r.account_id = NEW.account_id
          AND r.hour_ts_utc = NEW.hour_ts_utc
          AND r.source_run_id = NEW.source_run_id
    ) THEN
        RAISE EXCEPTION 'risk identity row has no source hypertable row';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS ctrg_risk_identity_source_exists ON risk_hourly_state_identity;
CREATE CONSTRAINT TRIGGER ctrg_risk_identity_source_exists
AFTER INSERT ON risk_hourly_state_identity
DEFERRABLE INITIALLY IMMEDIATE
FOR EACH ROW EXECUTE FUNCTION fn_validate_risk_identity_source_exists();
```

## 7. Updated M6 (Risk-State Binding) Section

### 7.1 Intent (unchanged)

- Each decision/admission row must bind to exact risk state used at decision time.
- Binding must include source run lineage (`risk_state_run_id`).
- Runtime risk gate remains DB-enforced and deferred.

### 7.2 Revised M6 DDL (Timescale-compatible)

```sql
-- 7.2.1 Replace baseline illegal FK targets first (idempotent, safe)
ALTER TABLE risk_hourly_state
    DROP CONSTRAINT IF EXISTS fk_risk_hourly_state_portfolio;

ALTER TABLE risk_hourly_state
    ADD CONSTRAINT fk_risk_hourly_state_portfolio_identity
        FOREIGN KEY (run_mode, account_id, hour_ts_utc)
        REFERENCES portfolio_hourly_state_identity (run_mode, account_id, hour_ts_utc)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT;

ALTER TABLE trade_signal
    DROP CONSTRAINT IF EXISTS fk_trade_signal_risk_hourly_state;

ALTER TABLE trade_signal
    DROP CONSTRAINT IF EXISTS fk_trade_signal_risk_state_identity;

ALTER TABLE trade_signal
    ADD CONSTRAINT fk_trade_signal_risk_state_identity
        FOREIGN KEY (run_mode, account_id, risk_state_hour_ts_utc)
        REFERENCES risk_hourly_state_identity (run_mode, account_id, hour_ts_utc)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT;

ALTER TABLE risk_event
    DROP CONSTRAINT IF EXISTS fk_risk_event_risk_hourly_state;

ALTER TABLE risk_event
    DROP CONSTRAINT IF EXISTS fk_risk_event_risk_state_identity;

ALTER TABLE risk_event
    ADD CONSTRAINT fk_risk_event_risk_state_identity
        FOREIGN KEY (run_mode, account_id, related_state_hour_ts_utc)
        REFERENCES risk_hourly_state_identity (run_mode, account_id, hour_ts_utc)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT;

-- 7.2.2 Enforce exact source-run identity for revised phase-1C shadow path
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_risk_hourly_state_with_source'
          AND conrelid = 'risk_hourly_state'::regclass
    ) THEN
        ALTER TABLE risk_hourly_state
            ADD CONSTRAINT uq_risk_hourly_state_with_source
            UNIQUE (run_mode, account_id, hour_ts_utc, source_run_id);
    END IF;
END;
$$;

ALTER TABLE trade_signal_v2
    ADD COLUMN IF NOT EXISTS risk_state_run_id UUID;

ALTER TABLE trade_signal_v2
    ALTER COLUMN risk_state_run_id SET NOT NULL;

ALTER TABLE trade_signal_v2
    DROP CONSTRAINT IF EXISTS fk_trade_signal_v2_risk_state_exact;

ALTER TABLE trade_signal_v2
    ADD CONSTRAINT fk_trade_signal_v2_risk_state_exact_identity
        FOREIGN KEY (run_mode, account_id, risk_state_hour_ts_utc, risk_state_run_id)
        REFERENCES risk_hourly_state_identity (run_mode, account_id, hour_ts_utc, source_run_id)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT;

ALTER TABLE trade_signal_v2
    DROP CONSTRAINT IF EXISTS ck_trade_signal_v2_risk_not_future;

ALTER TABLE trade_signal_v2
    ADD CONSTRAINT ck_trade_signal_v2_risk_not_future
        CHECK (risk_state_hour_ts_utc <= hour_ts_utc);

ALTER TABLE trade_signal_v2
    DROP CONSTRAINT IF EXISTS uq_trade_signal_v2_signal_riskrun;

ALTER TABLE trade_signal_v2
    ADD CONSTRAINT uq_trade_signal_v2_signal_riskrun
        UNIQUE (signal_id, risk_state_run_id);

ALTER TABLE order_request_v2
    ADD COLUMN IF NOT EXISTS risk_state_run_id UUID;

ALTER TABLE order_request_v2
    ALTER COLUMN risk_state_run_id SET NOT NULL;

ALTER TABLE order_request_v2
    DROP CONSTRAINT IF EXISTS fk_order_request_v2_signal_riskrun;

ALTER TABLE order_request_v2
    ADD CONSTRAINT fk_order_request_v2_signal_riskrun
        FOREIGN KEY (signal_id, risk_state_run_id)
        REFERENCES trade_signal_v2 (signal_id, risk_state_run_id)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT;

-- 7.2.3 Optional parity reinforcement on shadow risk_event path before cutover
ALTER TABLE risk_event_v2
    DROP CONSTRAINT IF EXISTS fk_risk_event_v2_risk_state_identity;

ALTER TABLE risk_event_v2
    ADD CONSTRAINT fk_risk_event_v2_risk_state_identity
        FOREIGN KEY (run_mode, account_id, related_state_hour_ts_utc)
        REFERENCES risk_hourly_state_identity (run_mode, account_id, hour_ts_utc)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT;
```

### 7.3 Revised runtime risk-gate trigger

```sql
CREATE OR REPLACE FUNCTION fn_enforce_runtime_risk_gate_v2()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    halt_flag BOOLEAN;
    kill_flag BOOLEAN;
BEGIN
    SELECT halt_new_entries, kill_switch_active
      INTO halt_flag, kill_flag
    FROM risk_hourly_state
    WHERE run_mode = NEW.run_mode
      AND account_id = NEW.account_id
      AND hour_ts_utc = NEW.hour_ts_utc
      AND source_run_id = NEW.risk_state_run_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'risk gate violation: missing exact risk_hourly_state row for run_mode %, account %, hour %, source_run_id %',
            NEW.run_mode, NEW.account_id, NEW.hour_ts_utc, NEW.risk_state_run_id;
    END IF;

    IF NEW.status <> 'REJECTED' AND (halt_flag OR kill_flag) THEN
        RAISE EXCEPTION 'risk gate violation: halted or kill switch active';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS ctrg_order_request_v2_risk_gate ON order_request_v2;
CREATE CONSTRAINT TRIGGER ctrg_order_request_v2_risk_gate
AFTER INSERT ON order_request_v2
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fn_enforce_runtime_risk_gate_v2();
```

### 7.4 Strictness confirmation for M6

Preserved semantics:
- Exact risk snapshot key binding: preserved.
- Source run lineage binding: preserved.
- Runtime halt/kill-switch enforcement: preserved.
- `risk_state_run_id` propagation into order admission path: preserved.

## 8. Updated M7 (Cluster) Section

### 8.1 Intent (unchanged)

- Cluster registry and membership remain normal tables.
- Hourly cluster exposure remains replay-authoritative state.
- Admission-time cluster cap remains DB-enforced via deferred trigger.

### 8.2 Revised M7 DDL (Timescale-compatible)

Only risk-state FK target changes.

```sql
CREATE TABLE cluster_exposure_hourly_state (
    run_mode run_mode_enum NOT NULL,
    account_id SMALLINT NOT NULL,
    cluster_id SMALLINT NOT NULL,
    hour_ts_utc TIMESTAMPTZ NOT NULL,
    source_run_id UUID NOT NULL,
    gross_exposure_notional NUMERIC(38,18) NOT NULL,
    exposure_pct NUMERIC(12,10) NOT NULL,
    max_cluster_exposure_pct NUMERIC(12,10) NOT NULL,
    state_hash CHAR(64) NOT NULL,
    CONSTRAINT pk_cluster_exposure_hourly_state
        PRIMARY KEY (run_mode, account_id, cluster_id, hour_ts_utc),
    CONSTRAINT ck_cluster_exposure_hourly_state_hour_aligned
        CHECK (date_trunc('hour', hour_ts_utc) = hour_ts_utc),
    CONSTRAINT ck_cluster_exposure_hourly_state_exposure_range
        CHECK (exposure_pct >= 0 AND exposure_pct <= 1),
    CONSTRAINT ck_cluster_exposure_hourly_state_cap_range
        CHECK (max_cluster_exposure_pct > 0 AND max_cluster_exposure_pct <= 0.08),
    CONSTRAINT fk_cluster_exposure_hourly_state_risk_identity
        FOREIGN KEY (run_mode, account_id, hour_ts_utc, source_run_id)
        REFERENCES risk_hourly_state_identity (run_mode, account_id, hour_ts_utc, source_run_id)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT,
    CONSTRAINT fk_cluster_exposure_hourly_state_cluster
        FOREIGN KEY (cluster_id)
        REFERENCES correlation_cluster (cluster_id)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT
);
```

All other M7 DDL remains unchanged.

### 8.3 Cluster-cap trigger behavior

`fn_enforce_cluster_cap_on_admission_v2` continues to resolve effective exposure from `cluster_exposure_hourly_state` and run-bound risk identity (`source_run_id = NEW.risk_state_run_id`) exactly as before.

Strictness status:
- Cluster cap semantics: preserved.
- Deterministic exposure lineage: preserved.
- Illegal FK class removed: yes.

## 9. Updated M8 (Walk-Forward) Section if needed

### 9.1 M8 compatibility result

No M8 FK in Phase 1C points to a hypertable target.

M8 FK targets are:
- `model_training_window`
- `backtest_fold_result`
- `model_activation_gate`

All are normal tables.

### 9.2 M8 DDL changes required

None.

### 9.3 M8 guardrail check (new pre-commit gate)

```sql
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_constraint c
        JOIN pg_class child_tbl ON child_tbl.oid = c.conrelid
        JOIN pg_namespace child_ns ON child_ns.oid = child_tbl.relnamespace
        JOIN pg_class parent_tbl ON parent_tbl.oid = c.confrelid
        JOIN pg_namespace parent_ns ON parent_ns.oid = parent_tbl.relnamespace
        JOIN timescaledb_information.hypertables h
          ON h.hypertable_schema = parent_ns.nspname
         AND h.hypertable_name = parent_tbl.relname
        WHERE c.contype = 'f'
          AND child_ns.nspname = 'public'
          AND child_tbl.relname IN (
              'model_prediction_v2',
              'regime_output_v2',
              'model_activation_gate'
          )
    ) THEN
        RAISE EXCEPTION 'M8 guard failed: walk-forward objects contain FK to hypertable target';
    END IF;
END;
$$;
```

## 10. Updated M9 (Hash Propagation) Section if needed

### 10.1 M9 compatibility risk addressed

M9 hash propagation must not rely on hypertable FK constraints.

Revision B guarantees this by:
- Routing identity referential checks through normal identity tables.
- Keeping parent-hash validation in explicit deferred triggers that read parent hypertables directly.

### 10.2 Identity-layer handling in hash model

Contract preservation choice:
- Replay-root composition remains unchanged from Revision A/Phase-1B scope.
- Identity tables are deterministic projections of parent hypertables and are **not added** to replay-root table list.

Required integrity check added:
- Identity bijection checks are mandatory and blocking in validation.

### 10.3 M9 trigger additions for non-FK parent hash enforcement

```sql
CREATE OR REPLACE FUNCTION fn_validate_risk_event_v2_parent_state_hash()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    expected_parent_hash CHAR(64);
BEGIN
    SELECT r.row_hash
      INTO expected_parent_hash
    FROM risk_hourly_state r
    WHERE r.run_mode = NEW.run_mode
      AND r.account_id = NEW.account_id
      AND r.hour_ts_utc = NEW.related_state_hour_ts_utc;

    IF expected_parent_hash IS NULL THEN
        RAISE EXCEPTION 'risk_event_v2 parent hash violation: missing parent risk row';
    END IF;

    IF NEW.parent_state_hash <> expected_parent_hash THEN
        RAISE EXCEPTION 'risk_event_v2 parent hash mismatch';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS ctrg_risk_event_v2_parent_state_hash ON risk_event_v2;
CREATE CONSTRAINT TRIGGER ctrg_risk_event_v2_parent_state_hash
AFTER INSERT ON risk_event_v2
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fn_validate_risk_event_v2_parent_state_hash();

CREATE OR REPLACE FUNCTION fn_validate_cluster_exposure_parent_risk_hash()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    expected_parent_hash CHAR(64);
BEGIN
    SELECT r.row_hash
      INTO expected_parent_hash
    FROM risk_hourly_state r
    WHERE r.run_mode = NEW.run_mode
      AND r.account_id = NEW.account_id
      AND r.hour_ts_utc = NEW.hour_ts_utc
      AND r.source_run_id = NEW.source_run_id;

    IF expected_parent_hash IS NULL THEN
        RAISE EXCEPTION 'cluster_exposure parent hash violation: missing exact parent risk row';
    END IF;

    IF NEW.parent_risk_hash <> expected_parent_hash THEN
        RAISE EXCEPTION 'cluster_exposure parent hash mismatch';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS ctrg_cluster_exposure_parent_risk_hash ON cluster_exposure_hourly_state;
CREATE CONSTRAINT TRIGGER ctrg_cluster_exposure_parent_risk_hash
AFTER INSERT ON cluster_exposure_hourly_state
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fn_validate_cluster_exposure_parent_risk_hash();
```

Strictness status:
- Hash propagation: preserved.
- Parent lineage verification: preserved.
- Dependence on hypertable FK enforcement: removed.

## 11. Dependency DAG (Revised)

Revised dependency edges:
- `run_context` -> `portfolio_hourly_state`
- `portfolio_hourly_state` -> `portfolio_hourly_state_identity`
- `portfolio_hourly_state_identity` -> `risk_hourly_state`
- `run_context` -> `risk_hourly_state`
- `risk_hourly_state` -> `risk_hourly_state_identity`
- `risk_hourly_state_identity` -> `trade_signal` (baseline compatibility)
- `risk_hourly_state_identity` -> `risk_event` (baseline compatibility)
- `risk_hourly_state_identity` -> `trade_signal_v2` (M6 exact binding)
- `trade_signal_v2` -> `order_request_v2` (signal+risk-run coupling)
- `risk_hourly_state_identity` + `correlation_cluster` + `asset_cluster_membership` -> `cluster_exposure_hourly_state`
- `cluster_exposure_hourly_state` + `trade_signal_v2` -> `order_request_v2` cluster-cap deferred trigger
- `model_training_window` + `backtest_fold_result` + `model_activation_gate` -> `model_prediction_v2`
- `model_training_window` + `backtest_fold_result` + `model_activation_gate` -> `regime_output_v2`

Phase ordering impact:
- Identity-table DDL and sync triggers must execute before revised M6 FK creation.
- Revised M6 must complete before M7.
- M8 unchanged.
- M9 validation triggers run after `row_hash` columns exist.

## 12. Validation Strategy (Revised if required)

### 12.1 Structural legality checks

1. No FK targets on hypertables:

```sql
SELECT
    child_ns.nspname AS child_schema,
    child_tbl.relname AS child_table,
    c.conname AS fk_name,
    parent_ns.nspname AS parent_schema,
    parent_tbl.relname AS parent_table
FROM pg_constraint c
JOIN pg_class child_tbl ON child_tbl.oid = c.conrelid
JOIN pg_namespace child_ns ON child_ns.oid = child_tbl.relnamespace
JOIN pg_class parent_tbl ON parent_tbl.oid = c.confrelid
JOIN pg_namespace parent_ns ON parent_ns.oid = parent_tbl.relnamespace
JOIN timescaledb_information.hypertables h
  ON h.hypertable_schema = parent_ns.nspname
 AND h.hypertable_name = parent_tbl.relname
WHERE c.contype = 'f'
  AND child_ns.nspname = 'public';
```

Expected result: zero rows.

2. Identity trigger presence checks:
- `trg_portfolio_hourly_state_identity_sync_ins`
- `trg_risk_hourly_state_identity_sync_ins`
- `ctrg_portfolio_identity_source_exists`
- `ctrg_risk_identity_source_exists`
- `trg_portfolio_hourly_state_identity_append_only`
- `trg_risk_hourly_state_identity_append_only`

### 12.2 Identity synchronization checks

3. Portfolio identity bijection:

```sql
SELECT COUNT(*) AS missing_identity_rows
FROM portfolio_hourly_state p
LEFT JOIN portfolio_hourly_state_identity pi
  ON pi.run_mode = p.run_mode
 AND pi.account_id = p.account_id
 AND pi.hour_ts_utc = p.hour_ts_utc
WHERE pi.run_mode IS NULL;
```

Expected: `0`.

4. Risk identity bijection:

```sql
SELECT COUNT(*) AS missing_identity_rows
FROM risk_hourly_state r
LEFT JOIN risk_hourly_state_identity ri
  ON ri.run_mode = r.run_mode
 AND ri.account_id = r.account_id
 AND ri.hour_ts_utc = r.hour_ts_utc
 AND ri.source_run_id = r.source_run_id
WHERE ri.run_mode IS NULL;
```

Expected: `0`.

5. Identity orphan checks:

```sql
SELECT COUNT(*) AS orphan_identity_rows
FROM risk_hourly_state_identity ri
LEFT JOIN risk_hourly_state r
  ON r.run_mode = ri.run_mode
 AND r.account_id = ri.account_id
 AND r.hour_ts_utc = ri.hour_ts_utc
 AND r.source_run_id = ri.source_run_id
WHERE r.run_mode IS NULL;
```

Expected: `0`.

### 12.3 Contract enforcement checks

6. Risk gate test:
- Insert order with `status <> 'REJECTED'` against halted/kill-switch risk state; transaction must fail.

7. Cluster-cap test:
- Insert over-cap admission row; deferred trigger must fail transaction.

8. Walk-forward contamination tests (unchanged):
- BACKTEST prediction/regime row outside validation window must fail.

9. Hash checks:
- No null `row_hash`/parent hash fields where required.
- `risk_event_v2` and `cluster_exposure_hourly_state` parent hash triggers fire and pass.

10. Replay parity checks (unchanged scope):
- Regenerate replay-authoritative tables.
- Compute run-level root and compare deterministic parity.

Unlock condition:
- All validation categories above must pass before lock release.

## 13. Cutover Safety Confirmation

Atomic cutover semantics remain unchanged.

Confirmed unchanged properties:
- Single transaction rename/lock sequence for canonical swap.
- No partial rename state on failure.
- Archive tables preserved.
- Append-only trigger restoration still required on post-cutover canonical tables.
- Compression policy rebinding remains in M10.

Identity-table impact on cutover safety:
- Identity tables are additive and stable.
- No rename dependency on identity tables is required at cutover.
- Existing and new canonical names continue referencing the same identity tables.

## 14. Resume Strategy from Current State (after failed M6)

Current known state:
- Bootstrap schema clean.
- M1-M5 completed.
- M6 failed.
- M7-M10 not run.
- No cutover.
- Lock active.

Resume sequence from this exact state:

1. Verify lock still active and unique:

```sql
SELECT migration_name, locked, locked_at_utc, unlocked_at_utc
FROM schema_migration_control
WHERE migration_name = 'phase_1b_schema';
```

2. Normalize potential partial M6 artifacts (idempotent cleanup):

```sql
ALTER TABLE trade_signal_v2 DROP CONSTRAINT IF EXISTS fk_trade_signal_v2_risk_state_exact;
ALTER TABLE trade_signal_v2 DROP CONSTRAINT IF EXISTS fk_trade_signal_v2_risk_state_exact_identity;
ALTER TABLE trade_signal_v2 DROP CONSTRAINT IF EXISTS uq_trade_signal_v2_signal_riskrun;
ALTER TABLE trade_signal_v2 DROP CONSTRAINT IF EXISTS ck_trade_signal_v2_risk_not_future;

ALTER TABLE order_request_v2 DROP CONSTRAINT IF EXISTS fk_order_request_v2_signal_riskrun;
ALTER TABLE risk_event_v2 DROP CONSTRAINT IF EXISTS fk_risk_event_v2_risk_state_identity;

ALTER TABLE IF EXISTS cluster_exposure_hourly_state DROP CONSTRAINT IF EXISTS fk_cluster_exposure_hourly_state_risk;
ALTER TABLE IF EXISTS cluster_exposure_hourly_state DROP CONSTRAINT IF EXISTS fk_cluster_exposure_hourly_state_risk_identity;
```

3. Apply Section 5 and Section 6 identity DDL/triggers.
4. Apply Section 7 revised M6 DDL.
5. Apply Section 8 revised M7 DDL.
6. Apply Section 9 M8 guardrail (M8 logic unchanged otherwise).
7. Apply Section 10 M9 trigger additions after hash columns exist.
8. Continue with M10 atomic cutover and full validation.

Resume safety statement:
- This is a forward-only resume from M6 with deterministic guarantees preserved.
- No M1-M5 rollback or restart is required.

## 15. Explicit Statement: Restart vs Resume decision

Decision:
- Restart from M1: **NO**.
- Resume from failed M6 with Revision B pre-steps: **YES**.

Reason:
- M1-M5 are complete and compatible with Revision B.
- No cutover was executed.
- No post-failure writes were allowed (lock active).
- Revision B is additive/rebinding at schema level and deterministic-safe from current state.

## 16. Migration Lock Handling Instruction

Lock semantics are unchanged.

Rules:
- Keep `schema_migration_control('phase_1b_schema').locked = TRUE` throughout M6-M10 and all post-cutover validation.
- Do not unlock on DDL completion alone.
- Unlock only after full validation pass (Section 12).
- On any failure, stop immediately and keep lock active.

Unlock statement (unchanged):

```sql
UPDATE schema_migration_control
SET locked = FALSE,
    unlocked_at_utc = now()
WHERE migration_name = 'phase_1b_schema';
```

## 17. Final Architect Declaration

Revision B is approved as the deterministic and Timescale-compatible correction for Phase 1C failed-at-M6 state.

This revision:
- Replaces illegal hypertable-target FK patterns with identity-table FK patterns.
- Preserves strict deterministic contract v1.0 invariants.
- Preserves replay contract and hash propagation semantics.
- Preserves risk-state binding semantics with exact source-run identity.
- Preserves cluster-cap and walk-forward schema-level enforcement.
- Preserves atomic cutover and lock handling semantics.
- Requires resume from M6, not restart from M1.

ARCHITECT APPROVAL: PHASE 1C REVISION B ISSUED FOR PRODUCTION-SAFE RESUME.
# ARCHITECT REVISION - PHASE 1C REVISION B

## PHASE_1C_REVISION_B_SCHEMA_MIGRATION.md

## 1. Executive Summary

Phase 1C failed at M6 on `foreign keys to hypertables are not supported` while introducing strict risk-state binding on `trade_signal_v2`.

Revision B preserves deterministic contract v1.0 strictness and Timescale compatibility by replacing illegal hypertable FK targets with identity-table FK targets.

Core Revision B change:
- Introduce non-hypertable identity tables for hypertable FK targets.
- Synchronize identities from hypertables via schema triggers.
- Repoint all M6/M7 hypertable-target FKs to identity tables.
- Keep replay, hash, walk-forward, cluster-cap, risk-gate, cutover atomicity, and lock semantics intact.

Decision:
- Resume from failed M6 state, do not restart from M1.
- Keep existing lock active until M10 + full validation pass.

## 2. Root Cause Analysis

Direct failure:
- M6 attempted to create FK:
  - child: `trade_signal_v2`
  - target: `risk_hourly_state` hypertable
  - key: `(run_mode, account_id, risk_state_hour_ts_utc, risk_state_run_id)` -> `(run_mode, account_id, hour_ts_utc, source_run_id)`
- Timescale rejected FK creation because target is a hypertable.

Architectural defect class:
- Deterministic constraints were designed correctly for lineage strictness, but physical FK target class (hypertable) is incompatible with Timescale FK limitations.
- M7 had the same latent defect (`cluster_exposure_hourly_state` -> `risk_hourly_state`).

Corrective principle:
- Preserve constraint intent and strictness by separating:
  - logical identity enforcement (FK to normal identity table), and
  - state payload storage/performance (hypertable).

## 3. List of Illegal FK Patterns Identified

### 3.1 Identified in Phase 1C M6-M9 path

| Pattern ID | Child Table | FK Name (planned/existing) | Target Hypertable | Class | Revision B Action |
|---|---|---|---|---|---|
| ILLEGAL-FK-01 | `trade_signal_v2` | `fk_trade_signal_v2_risk_state_exact` | `risk_hourly_state` | Normal table -> hypertable | Replace with FK to `risk_hourly_state_identity` |
| ILLEGAL-FK-02 | `cluster_exposure_hourly_state` | `fk_cluster_exposure_hourly_state_risk` | `risk_hourly_state` | Normal table -> hypertable | Replace with FK to `risk_hourly_state_identity` |

### 3.2 Identified in baseline schema that remain physically illegal in Timescale model

| Pattern ID | Child Table | FK Name (bootstrap) | Target Hypertable | Class | Revision B Action |
|---|---|---|---|---|---|
| ILLEGAL-FK-03 | `risk_hourly_state` | `fk_risk_hourly_state_portfolio` | `portfolio_hourly_state` | Hypertable -> hypertable | Replace with FK to `portfolio_hourly_state_identity` |
| ILLEGAL-FK-04 | `trade_signal` | `fk_trade_signal_risk_hourly_state` | `risk_hourly_state` | Normal table -> hypertable | Replace with FK to `risk_hourly_state_identity` |
| ILLEGAL-FK-05 | `risk_event` | `fk_risk_event_risk_hourly_state` | `risk_hourly_state` | Normal table -> hypertable | Replace with FK to `risk_hourly_state_identity` |

### 3.3 Required analysis list confirmation

Hypertable targets requested for explicit review:
- `risk_hourly_state`: FK target used in M6 and M7; identity table required.
- `portfolio_hourly_state`: FK target in baseline (`risk_hourly_state`); identity table required.
- `position_hourly_state`: no FK consumers introduced in M6-M9; no identity table introduced in Revision B.
- `feature_snapshot`: no FK consumers introduced in M6-M9; no identity table introduced in Revision B.
- `model_prediction`: no FK consumers introduced in M6-M9; no identity table introduced in Revision B.
- `meta_learner_component`: no FK consumers introduced in M6-M9; no identity table introduced in Revision B.
- Any other hypertable targets in M6-M9: none.

Strictness note:
- No FK consumer of the above omitted targets exists in M6-M9 migration scope; therefore no corresponding identity table is needed for this revision.

## 4. Identity Table Strategy Definition

### 4.1 Strategy

For every hypertable that must be referenced by FK in migration scope:
1. Create a normal append-only identity table containing only FK identity key columns.
2. Add PK/UNIQUE on identity key in identity table.
3. Synchronize identity rows from hypertable inserts with trigger(s).
4. Prevent identity mutation (`UPDATE`/`DELETE`) via append-only trigger.
5. Reject orphan identity inserts via validation trigger (identity row must map to real hypertable row).
6. Repoint all child FKs to identity table.

### 4.2 Why this preserves deterministic strictness

- FK existence checks remain database-enforced (schema-level).
- Risk-state binding remains exact on `(run_mode, account_id, hour_ts_utc, source_run_id)`.
- Cluster-cap path still binds to same risk-state identity key.
- No application-layer fallback is introduced.

### 4.3 Identity coverage in Revision B

Introduced identity tables:
- `risk_hourly_state_identity`
- `portfolio_hourly_state_identity`

Not introduced (no FK consumers in scope):
- `position_hourly_state_identity`
- `feature_snapshot_identity`
- `model_prediction_identity`
- `meta_learner_component_identity`

## 5. DDL for Each Identity Table Introduced

### 5.1 `portfolio_hourly_state_identity`

```sql
CREATE TABLE IF NOT EXISTS portfolio_hourly_state_identity (
    run_mode run_mode_enum NOT NULL,
    account_id SMALLINT NOT NULL,
    hour_ts_utc TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_portfolio_hourly_state_identity
        PRIMARY KEY (run_mode, account_id, hour_ts_utc),
    CONSTRAINT ck_portfolio_hourly_state_identity_hour_aligned
        CHECK (date_trunc('hour', hour_ts_utc) = hour_ts_utc)
);

DROP TRIGGER IF EXISTS trg_portfolio_hourly_state_identity_append_only ON portfolio_hourly_state_identity;
CREATE TRIGGER trg_portfolio_hourly_state_identity_append_only
BEFORE UPDATE OR DELETE ON portfolio_hourly_state_identity
FOR EACH ROW EXECUTE FUNCTION fn_enforce_append_only();
```

### 5.2 `risk_hourly_state_identity`

```sql
CREATE TABLE IF NOT EXISTS risk_hourly_state_identity (
    run_mode run_mode_enum NOT NULL,
    account_id SMALLINT NOT NULL,
    hour_ts_utc TIMESTAMPTZ NOT NULL,
    source_run_id UUID NOT NULL,
    CONSTRAINT pk_risk_hourly_state_identity
        PRIMARY KEY (run_mode, account_id, hour_ts_utc, source_run_id),
    CONSTRAINT ck_risk_hourly_state_identity_hour_aligned
        CHECK (date_trunc('hour', hour_ts_utc) = hour_ts_utc),
    CONSTRAINT fk_risk_hourly_state_identity_run_context
        FOREIGN KEY (source_run_id, account_id, run_mode, hour_ts_utc)
        REFERENCES run_context (run_id, account_id, run_mode, hour_ts_utc)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT
);

DROP TRIGGER IF EXISTS trg_risk_hourly_state_identity_append_only ON risk_hourly_state_identity;
CREATE TRIGGER trg_risk_hourly_state_identity_append_only
BEFORE UPDATE OR DELETE ON risk_hourly_state_identity
FOR EACH ROW EXECUTE FUNCTION fn_enforce_append_only();
```

### 5.3 Identity bootstrap/backfill (safe/idempotent)

```sql
INSERT INTO portfolio_hourly_state_identity (run_mode, account_id, hour_ts_utc)
SELECT p.run_mode, p.account_id, p.hour_ts_utc
FROM portfolio_hourly_state p
ON CONFLICT DO NOTHING;

INSERT INTO risk_hourly_state_identity (run_mode, account_id, hour_ts_utc, source_run_id)
SELECT r.run_mode, r.account_id, r.hour_ts_utc, r.source_run_id
FROM risk_hourly_state r
ON CONFLICT DO NOTHING;
```

## 6. Insert Synchronization Trigger Definitions

### 6.1 Portfolio hypertable -> portfolio identity synchronization

```sql
CREATE OR REPLACE FUNCTION fn_sync_portfolio_hourly_state_identity_ins()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO portfolio_hourly_state_identity (run_mode, account_id, hour_ts_utc)
    VALUES (NEW.run_mode, NEW.account_id, NEW.hour_ts_utc)
    ON CONFLICT DO NOTHING;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_portfolio_hourly_state_identity_sync_ins ON portfolio_hourly_state;
CREATE TRIGGER trg_portfolio_hourly_state_identity_sync_ins
AFTER INSERT ON portfolio_hourly_state
FOR EACH ROW EXECUTE FUNCTION fn_sync_portfolio_hourly_state_identity_ins();
```

### 6.2 Risk hypertable -> risk identity synchronization

```sql
CREATE OR REPLACE FUNCTION fn_sync_risk_hourly_state_identity_ins()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO risk_hourly_state_identity (run_mode, account_id, hour_ts_utc, source_run_id)
    VALUES (NEW.run_mode, NEW.account_id, NEW.hour_ts_utc, NEW.source_run_id)
    ON CONFLICT DO NOTHING;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_risk_hourly_state_identity_sync_ins ON risk_hourly_state;
CREATE TRIGGER trg_risk_hourly_state_identity_sync_ins
AFTER INSERT ON risk_hourly_state
FOR EACH ROW EXECUTE FUNCTION fn_sync_risk_hourly_state_identity_ins();
```

### 6.3 Source-key immutability guard triggers (to prevent identity drift)

```sql
CREATE OR REPLACE FUNCTION fn_guard_portfolio_hourly_state_identity_key_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'portfolio_hourly_state is append-only for identity synchronization';
    END IF;

    IF NEW.run_mode IS DISTINCT FROM OLD.run_mode
       OR NEW.account_id IS DISTINCT FROM OLD.account_id
       OR NEW.hour_ts_utc IS DISTINCT FROM OLD.hour_ts_utc THEN
        RAISE EXCEPTION 'portfolio_hourly_state identity key mutation is not allowed';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_guard_portfolio_hourly_state_identity_key_mutation ON portfolio_hourly_state;
CREATE TRIGGER trg_guard_portfolio_hourly_state_identity_key_mutation
BEFORE UPDATE OR DELETE ON portfolio_hourly_state
FOR EACH ROW EXECUTE FUNCTION fn_guard_portfolio_hourly_state_identity_key_mutation();

CREATE OR REPLACE FUNCTION fn_guard_risk_hourly_state_identity_key_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'risk_hourly_state is append-only for identity synchronization';
    END IF;

    IF NEW.run_mode IS DISTINCT FROM OLD.run_mode
       OR NEW.account_id IS DISTINCT FROM OLD.account_id
       OR NEW.hour_ts_utc IS DISTINCT FROM OLD.hour_ts_utc
       OR NEW.source_run_id IS DISTINCT FROM OLD.source_run_id THEN
        RAISE EXCEPTION 'risk_hourly_state identity key mutation is not allowed';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_guard_risk_hourly_state_identity_key_mutation ON risk_hourly_state;
CREATE TRIGGER trg_guard_risk_hourly_state_identity_key_mutation
BEFORE UPDATE OR DELETE ON risk_hourly_state
FOR EACH ROW EXECUTE FUNCTION fn_guard_risk_hourly_state_identity_key_mutation();
```

### 6.4 Identity orphan prevention triggers

```sql
CREATE OR REPLACE FUNCTION fn_validate_portfolio_identity_source_exists()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM portfolio_hourly_state p
        WHERE p.run_mode = NEW.run_mode
          AND p.account_id = NEW.account_id
          AND p.hour_ts_utc = NEW.hour_ts_utc
    ) THEN
        RAISE EXCEPTION 'portfolio identity row has no source hypertable row';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS ctrg_portfolio_identity_source_exists ON portfolio_hourly_state_identity;
CREATE CONSTRAINT TRIGGER ctrg_portfolio_identity_source_exists
AFTER INSERT ON portfolio_hourly_state_identity
DEFERRABLE INITIALLY IMMEDIATE
FOR EACH ROW EXECUTE FUNCTION fn_validate_portfolio_identity_source_exists();

CREATE OR REPLACE FUNCTION fn_validate_risk_identity_source_exists()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM risk_hourly_state r
        WHERE r.run_mode = NEW.run_mode
          AND r.account_id = NEW.account_id
          AND r.hour_ts_utc = NEW.hour_ts_utc
          AND r.source_run_id = NEW.source_run_id
    ) THEN
        RAISE EXCEPTION 'risk identity row has no source hypertable row';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS ctrg_risk_identity_source_exists ON risk_hourly_state_identity;
CREATE CONSTRAINT TRIGGER ctrg_risk_identity_source_exists
AFTER INSERT ON risk_hourly_state_identity
DEFERRABLE INITIALLY IMMEDIATE
FOR EACH ROW EXECUTE FUNCTION fn_validate_risk_identity_source_exists();
```

## 7. Updated M6 (Risk-State Binding) Section

### 7.1 Intent (unchanged)

- Each decision/admission row must bind to exact risk state used at decision time.
- Binding must include source run lineage (`risk_state_run_id`).
- Runtime risk gate remains DB-enforced and deferred.

### 7.2 Revised M6 DDL (Timescale-compatible)

```sql
-- 7.2.1 Replace baseline illegal FK targets first (idempotent, safe)
ALTER TABLE risk_hourly_state
    DROP CONSTRAINT IF EXISTS fk_risk_hourly_state_portfolio;

ALTER TABLE risk_hourly_state
    ADD CONSTRAINT fk_risk_hourly_state_portfolio_identity
        FOREIGN KEY (run_mode, account_id, hour_ts_utc)
        REFERENCES portfolio_hourly_state_identity (run_mode, account_id, hour_ts_utc)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT;

ALTER TABLE trade_signal
    DROP CONSTRAINT IF EXISTS fk_trade_signal_risk_hourly_state;

ALTER TABLE trade_signal
    DROP CONSTRAINT IF EXISTS fk_trade_signal_risk_state_identity;

ALTER TABLE trade_signal
    ADD CONSTRAINT fk_trade_signal_risk_state_identity
        FOREIGN KEY (run_mode, account_id, risk_state_hour_ts_utc)
        REFERENCES risk_hourly_state_identity (run_mode, account_id, hour_ts_utc)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT;

ALTER TABLE risk_event
    DROP CONSTRAINT IF EXISTS fk_risk_event_risk_hourly_state;

ALTER TABLE risk_event
    DROP CONSTRAINT IF EXISTS fk_risk_event_risk_state_identity;

ALTER TABLE risk_event
    ADD CONSTRAINT fk_risk_event_risk_state_identity
        FOREIGN KEY (run_mode, account_id, related_state_hour_ts_utc)
        REFERENCES risk_hourly_state_identity (run_mode, account_id, hour_ts_utc)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT;

-- 7.2.2 Enforce exact source-run identity for revised phase-1C shadow path
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_risk_hourly_state_with_source'
          AND conrelid = 'risk_hourly_state'::regclass
    ) THEN
        ALTER TABLE risk_hourly_state
            ADD CONSTRAINT uq_risk_hourly_state_with_source
            UNIQUE (run_mode, account_id, hour_ts_utc, source_run_id);
    END IF;
END;
$$;

ALTER TABLE trade_signal_v2
    ADD COLUMN IF NOT EXISTS risk_state_run_id UUID;

ALTER TABLE trade_signal_v2
    ALTER COLUMN risk_state_run_id SET NOT NULL;

ALTER TABLE trade_signal_v2
    DROP CONSTRAINT IF EXISTS fk_trade_signal_v2_risk_state_exact;

ALTER TABLE trade_signal_v2
    ADD CONSTRAINT fk_trade_signal_v2_risk_state_exact_identity
        FOREIGN KEY (run_mode, account_id, risk_state_hour_ts_utc, risk_state_run_id)
        REFERENCES risk_hourly_state_identity (run_mode, account_id, hour_ts_utc, source_run_id)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT;

ALTER TABLE trade_signal_v2
    DROP CONSTRAINT IF EXISTS ck_trade_signal_v2_risk_not_future;

ALTER TABLE trade_signal_v2
    ADD CONSTRAINT ck_trade_signal_v2_risk_not_future
        CHECK (risk_state_hour_ts_utc <= hour_ts_utc);

ALTER TABLE trade_signal_v2
    DROP CONSTRAINT IF EXISTS uq_trade_signal_v2_signal_riskrun;

ALTER TABLE trade_signal_v2
    ADD CONSTRAINT uq_trade_signal_v2_signal_riskrun
        UNIQUE (signal_id, risk_state_run_id);

ALTER TABLE order_request_v2
    ADD COLUMN IF NOT EXISTS risk_state_run_id UUID;

ALTER TABLE order_request_v2
    ALTER COLUMN risk_state_run_id SET NOT NULL;

ALTER TABLE order_request_v2
    DROP CONSTRAINT IF EXISTS fk_order_request_v2_signal_riskrun;

ALTER TABLE order_request_v2
    ADD CONSTRAINT fk_order_request_v2_signal_riskrun
        FOREIGN KEY (signal_id, risk_state_run_id)
        REFERENCES trade_signal_v2 (signal_id, risk_state_run_id)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT;

-- 7.2.3 Optional parity reinforcement on shadow risk_event path before cutover
ALTER TABLE risk_event_v2
    DROP CONSTRAINT IF EXISTS fk_risk_event_v2_risk_state_identity;

ALTER TABLE risk_event_v2
    ADD CONSTRAINT fk_risk_event_v2_risk_state_identity
        FOREIGN KEY (run_mode, account_id, related_state_hour_ts_utc)
        REFERENCES risk_hourly_state_identity (run_mode, account_id, hour_ts_utc)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT;
```

### 7.3 Revised runtime risk-gate trigger

```sql
CREATE OR REPLACE FUNCTION fn_enforce_runtime_risk_gate_v2()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    halt_flag BOOLEAN;
    kill_flag BOOLEAN;
BEGIN
    SELECT halt_new_entries, kill_switch_active
      INTO halt_flag, kill_flag
    FROM risk_hourly_state
    WHERE run_mode = NEW.run_mode
      AND account_id = NEW.account_id
      AND hour_ts_utc = NEW.hour_ts_utc
      AND source_run_id = NEW.risk_state_run_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'risk gate violation: missing exact risk_hourly_state row for run_mode %, account %, hour %, source_run_id %',
            NEW.run_mode, NEW.account_id, NEW.hour_ts_utc, NEW.risk_state_run_id;
    END IF;

    IF NEW.status <> 'REJECTED' AND (halt_flag OR kill_flag) THEN
        RAISE EXCEPTION 'risk gate violation: halted or kill switch active';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS ctrg_order_request_v2_risk_gate ON order_request_v2;
CREATE CONSTRAINT TRIGGER ctrg_order_request_v2_risk_gate
AFTER INSERT ON order_request_v2
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fn_enforce_runtime_risk_gate_v2();
```

### 7.4 Strictness confirmation for M6

Preserved semantics:
- Exact risk snapshot key binding: preserved.
- Source run lineage binding: preserved.
- Runtime halt/kill-switch enforcement: preserved.
- `risk_state_run_id` propagation into order admission path: preserved.

## 8. Updated M7 (Cluster) Section

### 8.1 Intent (unchanged)

- Cluster registry and membership remain normal tables.
- Hourly cluster exposure remains replay-authoritative state.
- Admission-time cluster cap remains DB-enforced via deferred trigger.

### 8.2 Revised M7 DDL (Timescale-compatible)

Only risk-state FK target changes.

```sql
CREATE TABLE cluster_exposure_hourly_state (
    run_mode run_mode_enum NOT NULL,
    account_id SMALLINT NOT NULL,
    cluster_id SMALLINT NOT NULL,
    hour_ts_utc TIMESTAMPTZ NOT NULL,
    source_run_id UUID NOT NULL,
    gross_exposure_notional NUMERIC(38,18) NOT NULL,
    exposure_pct NUMERIC(12,10) NOT NULL,
    max_cluster_exposure_pct NUMERIC(12,10) NOT NULL,
    state_hash CHAR(64) NOT NULL,
    CONSTRAINT pk_cluster_exposure_hourly_state
        PRIMARY KEY (run_mode, account_id, cluster_id, hour_ts_utc),
    CONSTRAINT ck_cluster_exposure_hourly_state_hour_aligned
        CHECK (date_trunc('hour', hour_ts_utc) = hour_ts_utc),
    CONSTRAINT ck_cluster_exposure_hourly_state_exposure_range
        CHECK (exposure_pct >= 0 AND exposure_pct <= 1),
    CONSTRAINT ck_cluster_exposure_hourly_state_cap_range
        CHECK (max_cluster_exposure_pct > 0 AND max_cluster_exposure_pct <= 0.08),
    CONSTRAINT fk_cluster_exposure_hourly_state_risk_identity
        FOREIGN KEY (run_mode, account_id, hour_ts_utc, source_run_id)
        REFERENCES risk_hourly_state_identity (run_mode, account_id, hour_ts_utc, source_run_id)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT,
    CONSTRAINT fk_cluster_exposure_hourly_state_cluster
        FOREIGN KEY (cluster_id)
        REFERENCES correlation_cluster (cluster_id)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT
);
```

All other M7 DDL remains unchanged.

### 8.3 Cluster-cap trigger behavior

`fn_enforce_cluster_cap_on_admission_v2` continues to resolve effective exposure from `cluster_exposure_hourly_state` and run-bound risk identity (`source_run_id = NEW.risk_state_run_id`) exactly as before.

Strictness status:
- Cluster cap semantics: preserved.
- Deterministic exposure lineage: preserved.
- Illegal FK class removed: yes.

## 9. Updated M8 (Walk-Forward) Section if needed

### 9.1 M8 compatibility result

No M8 FK in Phase 1C points to a hypertable target.

M8 FK targets are:
- `model_training_window`
- `backtest_fold_result`
- `model_activation_gate`

All are normal tables.

### 9.2 M8 DDL changes required

None.

### 9.3 M8 guardrail check (new pre-commit gate)

```sql
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_constraint c
        JOIN pg_class child_tbl ON child_tbl.oid = c.conrelid
        JOIN pg_namespace child_ns ON child_ns.oid = child_tbl.relnamespace
        JOIN pg_class parent_tbl ON parent_tbl.oid = c.confrelid
        JOIN pg_namespace parent_ns ON parent_ns.oid = parent_tbl.relnamespace
        JOIN timescaledb_information.hypertables h
          ON h.hypertable_schema = parent_ns.nspname
         AND h.hypertable_name = parent_tbl.relname
        WHERE c.contype = 'f'
          AND child_ns.nspname = 'public'
          AND child_tbl.relname IN (
              'model_prediction_v2',
              'regime_output_v2',
              'model_activation_gate'
          )
    ) THEN
        RAISE EXCEPTION 'M8 guard failed: walk-forward objects contain FK to hypertable target';
    END IF;
END;
$$;
```

## 10. Updated M9 (Hash Propagation) Section if needed

### 10.1 M9 compatibility risk addressed

M9 hash propagation must not rely on hypertable FK constraints.

Revision B guarantees this by:
- Routing identity referential checks through normal identity tables.
- Keeping parent-hash validation in explicit deferred triggers that read parent hypertables directly.

### 10.2 Identity-layer handling in hash model

Contract preservation choice:
- Replay-root composition remains unchanged from Revision A/Phase-1B scope.
- Identity tables are deterministic projections of parent hypertables and are **not added** to replay-root table list.

Required integrity check added:
- Identity bijection checks are mandatory and blocking in validation.

### 10.3 M9 trigger additions for non-FK parent hash enforcement

```sql
CREATE OR REPLACE FUNCTION fn_validate_risk_event_v2_parent_state_hash()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    expected_parent_hash CHAR(64);
BEGIN
    SELECT r.row_hash
      INTO expected_parent_hash
    FROM risk_hourly_state r
    WHERE r.run_mode = NEW.run_mode
      AND r.account_id = NEW.account_id
      AND r.hour_ts_utc = NEW.related_state_hour_ts_utc;

    IF expected_parent_hash IS NULL THEN
        RAISE EXCEPTION 'risk_event_v2 parent hash violation: missing parent risk row';
    END IF;

    IF NEW.parent_state_hash <> expected_parent_hash THEN
        RAISE EXCEPTION 'risk_event_v2 parent hash mismatch';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS ctrg_risk_event_v2_parent_state_hash ON risk_event_v2;
CREATE CONSTRAINT TRIGGER ctrg_risk_event_v2_parent_state_hash
AFTER INSERT ON risk_event_v2
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fn_validate_risk_event_v2_parent_state_hash();

CREATE OR REPLACE FUNCTION fn_validate_cluster_exposure_parent_risk_hash()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    expected_parent_hash CHAR(64);
BEGIN
    SELECT r.row_hash
      INTO expected_parent_hash
    FROM risk_hourly_state r
    WHERE r.run_mode = NEW.run_mode
      AND r.account_id = NEW.account_id
      AND r.hour_ts_utc = NEW.hour_ts_utc
      AND r.source_run_id = NEW.source_run_id;

    IF expected_parent_hash IS NULL THEN
        RAISE EXCEPTION 'cluster_exposure parent hash violation: missing exact parent risk row';
    END IF;

    IF NEW.parent_risk_hash <> expected_parent_hash THEN
        RAISE EXCEPTION 'cluster_exposure parent hash mismatch';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS ctrg_cluster_exposure_parent_risk_hash ON cluster_exposure_hourly_state;
CREATE CONSTRAINT TRIGGER ctrg_cluster_exposure_parent_risk_hash
AFTER INSERT ON cluster_exposure_hourly_state
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fn_validate_cluster_exposure_parent_risk_hash();
```

Strictness status:
- Hash propagation: preserved.
- Parent lineage verification: preserved.
- Dependence on hypertable FK enforcement: removed.

## 11. Dependency DAG (Revised)

Revised dependency edges:
- `run_context` -> `portfolio_hourly_state`
- `portfolio_hourly_state` -> `portfolio_hourly_state_identity`
- `portfolio_hourly_state_identity` -> `risk_hourly_state`
- `run_context` -> `risk_hourly_state`
- `risk_hourly_state` -> `risk_hourly_state_identity`
- `risk_hourly_state_identity` -> `trade_signal` (baseline compatibility)
- `risk_hourly_state_identity` -> `risk_event` (baseline compatibility)
- `risk_hourly_state_identity` -> `trade_signal_v2` (M6 exact binding)
- `trade_signal_v2` -> `order_request_v2` (signal+risk-run coupling)
- `risk_hourly_state_identity` + `correlation_cluster` + `asset_cluster_membership` -> `cluster_exposure_hourly_state`
- `cluster_exposure_hourly_state` + `trade_signal_v2` -> `order_request_v2` cluster-cap deferred trigger
- `model_training_window` + `backtest_fold_result` + `model_activation_gate` -> `model_prediction_v2`
- `model_training_window` + `backtest_fold_result` + `model_activation_gate` -> `regime_output_v2`

Phase ordering impact:
- Identity-table DDL and sync triggers must execute before revised M6 FK creation.
- Revised M6 must complete before M7.
- M8 unchanged.
- M9 validation triggers run after `row_hash` columns exist.

## 12. Validation Strategy (Revised if required)

### 12.1 Structural legality checks

1. No FK targets on hypertables:

```sql
SELECT
    child_ns.nspname AS child_schema,
    child_tbl.relname AS child_table,
    c.conname AS fk_name,
    parent_ns.nspname AS parent_schema,
    parent_tbl.relname AS parent_table
FROM pg_constraint c
JOIN pg_class child_tbl ON child_tbl.oid = c.conrelid
JOIN pg_namespace child_ns ON child_ns.oid = child_tbl.relnamespace
JOIN pg_class parent_tbl ON parent_tbl.oid = c.confrelid
JOIN pg_namespace parent_ns ON parent_ns.oid = parent_tbl.relnamespace
JOIN timescaledb_information.hypertables h
  ON h.hypertable_schema = parent_ns.nspname
 AND h.hypertable_name = parent_tbl.relname
WHERE c.contype = 'f'
  AND child_ns.nspname = 'public';
```

Expected result: zero rows.

2. Identity trigger presence checks:
- `trg_portfolio_hourly_state_identity_sync_ins`
- `trg_risk_hourly_state_identity_sync_ins`
- `ctrg_portfolio_identity_source_exists`
- `ctrg_risk_identity_source_exists`
- `trg_portfolio_hourly_state_identity_append_only`
- `trg_risk_hourly_state_identity_append_only`

### 12.2 Identity synchronization checks

3. Portfolio identity bijection:

```sql
SELECT COUNT(*) AS missing_identity_rows
FROM portfolio_hourly_state p
LEFT JOIN portfolio_hourly_state_identity pi
  ON pi.run_mode = p.run_mode
 AND pi.account_id = p.account_id
 AND pi.hour_ts_utc = p.hour_ts_utc
WHERE pi.run_mode IS NULL;
```

Expected: `0`.

4. Risk identity bijection:

```sql
SELECT COUNT(*) AS missing_identity_rows
FROM risk_hourly_state r
LEFT JOIN risk_hourly_state_identity ri
  ON ri.run_mode = r.run_mode
 AND ri.account_id = r.account_id
 AND ri.hour_ts_utc = r.hour_ts_utc
 AND ri.source_run_id = r.source_run_id
WHERE ri.run_mode IS NULL;
```

Expected: `0`.

5. Identity orphan checks:

```sql
SELECT COUNT(*) AS orphan_identity_rows
FROM risk_hourly_state_identity ri
LEFT JOIN risk_hourly_state r
  ON r.run_mode = ri.run_mode
 AND r.account_id = ri.account_id
 AND r.hour_ts_utc = ri.hour_ts_utc
 AND r.source_run_id = ri.source_run_id
WHERE r.run_mode IS NULL;
```

Expected: `0`.

### 12.3 Contract enforcement checks

6. Risk gate test:
- Insert order with `status <> 'REJECTED'` against halted/kill-switch risk state; transaction must fail.

7. Cluster-cap test:
- Insert over-cap admission row; deferred trigger must fail transaction.

8. Walk-forward contamination tests (unchanged):
- BACKTEST prediction/regime row outside validation window must fail.

9. Hash checks:
- No null `row_hash`/parent hash fields where required.
- `risk_event_v2` and `cluster_exposure_hourly_state` parent hash triggers fire and pass.

10. Replay parity checks (unchanged scope):
- Regenerate replay-authoritative tables.
- Compute run-level root and compare deterministic parity.

Unlock condition:
- All validation categories above must pass before lock release.

## 13. Cutover Safety Confirmation

Atomic cutover semantics remain unchanged.

Confirmed unchanged properties:
- Single transaction rename/lock sequence for canonical swap.
- No partial rename state on failure.
- Archive tables preserved.
- Append-only trigger restoration still required on post-cutover canonical tables.
- Compression policy rebinding remains in M10.

Identity-table impact on cutover safety:
- Identity tables are additive and stable.
- No rename dependency on identity tables is required at cutover.
- Existing and new canonical names continue referencing the same identity tables.

## 14. Resume Strategy from Current State (after failed M6)

Current known state:
- Bootstrap schema clean.
- M1-M5 completed.
- M6 failed.
- M7-M10 not run.
- No cutover.
- Lock active.

Resume sequence from this exact state:

1. Verify lock still active and unique:

```sql
SELECT migration_name, locked, locked_at_utc, unlocked_at_utc
FROM schema_migration_control
WHERE migration_name = 'phase_1b_schema';
```

2. Normalize potential partial M6 artifacts (idempotent cleanup):

```sql
ALTER TABLE trade_signal_v2 DROP CONSTRAINT IF EXISTS fk_trade_signal_v2_risk_state_exact;
ALTER TABLE trade_signal_v2 DROP CONSTRAINT IF EXISTS fk_trade_signal_v2_risk_state_exact_identity;
ALTER TABLE trade_signal_v2 DROP CONSTRAINT IF EXISTS uq_trade_signal_v2_signal_riskrun;
ALTER TABLE trade_signal_v2 DROP CONSTRAINT IF EXISTS ck_trade_signal_v2_risk_not_future;

ALTER TABLE order_request_v2 DROP CONSTRAINT IF EXISTS fk_order_request_v2_signal_riskrun;
ALTER TABLE risk_event_v2 DROP CONSTRAINT IF EXISTS fk_risk_event_v2_risk_state_identity;

ALTER TABLE IF EXISTS cluster_exposure_hourly_state DROP CONSTRAINT IF EXISTS fk_cluster_exposure_hourly_state_risk;
ALTER TABLE IF EXISTS cluster_exposure_hourly_state DROP CONSTRAINT IF EXISTS fk_cluster_exposure_hourly_state_risk_identity;
```

3. Apply Section 5 and Section 6 identity DDL/triggers.
4. Apply Section 7 revised M6 DDL.
5. Apply Section 8 revised M7 DDL.
6. Apply Section 9 M8 guardrail (M8 logic unchanged otherwise).
7. Apply Section 10 M9 trigger additions after hash columns exist.
8. Continue with M10 atomic cutover and full validation.

Resume safety statement:
- This is a forward-only resume from M6 with deterministic guarantees preserved.
- No M1-M5 rollback or restart is required.

## 15. Explicit Statement: Restart vs Resume decision

Decision:
- Restart from M1: **NO**.
- Resume from failed M6 with Revision B pre-steps: **YES**.

Reason:
- M1-M5 are complete and compatible with Revision B.
- No cutover was executed.
- No post-failure writes were allowed (lock active).
- Revision B is additive/rebinding at schema level and deterministic-safe from current state.

## 16. Migration Lock Handling Instruction

Lock semantics are unchanged.

Rules:
- Keep `schema_migration_control('phase_1b_schema').locked = TRUE` throughout M6-M10 and all post-cutover validation.
- Do not unlock on DDL completion alone.
- Unlock only after full validation pass (Section 12).
- On any failure, stop immediately and keep lock active.

Unlock statement (unchanged):

```sql
UPDATE schema_migration_control
SET locked = FALSE,
    unlocked_at_utc = now()
WHERE migration_name = 'phase_1b_schema';
```

## 17. Final Architect Declaration

Revision B is approved as the deterministic and Timescale-compatible correction for Phase 1C failed-at-M6 state.

This revision:
- Replaces illegal hypertable-target FK patterns with identity-table FK patterns.
- Preserves strict deterministic contract v1.0 invariants.
- Preserves replay contract and hash propagation semantics.
- Preserves risk-state binding semantics with exact source-run identity.
- Preserves cluster-cap and walk-forward schema-level enforcement.
- Preserves atomic cutover and lock handling semantics.
- Requires resume from M6, not restart from M1.

ARCHITECT APPROVAL: PHASE 1C REVISION B ISSUED FOR PRODUCTION-SAFE RESUME.
