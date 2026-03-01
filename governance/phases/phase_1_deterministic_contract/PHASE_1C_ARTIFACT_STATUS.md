# PHASE 1C ARTIFACT STATUS

## Purpose of Revision C SQL files

### `PHASE_1C_REVISION_C_SCHEMA_REPAIR_BLUEPRINT.sql`
- Role: Architect-approved repair blueprint for Phase 1C Revision C.
- Use: Historical/audit migration artifact for the repair sequence.
- Status: **Retain (do not delete)**.

### `PHASE_1C_REVISION_C_TRIGGER_REPAIR.sql`
- Role: Minimal correction-loop script for `_v2` trigger/function drift elimination.
- Use: Historical/audit artifact documenting the drift-repair path.
- Status: **Retain (do not delete)**.

## Are these part of the "actual SQL files"?

Yes, as migration-history artifacts under phase governance.

No, as bootstrap baseline for new environments.

For new environment provisioning and current-state bootstrap, use:
- `/schema_bootstrap.sql`

`schema_bootstrap.sql` was regenerated from live `crypto_db` schema after Phase 1C Revision C closure (2026-03-01 UTC), and is the canonical executable snapshot of current state.

## Policy

- Keep both Revision C SQL files immutable and versioned under this phase folder.
- Do not remove them.
- Do not use them as a substitute for bootstrap in fresh deployments.
