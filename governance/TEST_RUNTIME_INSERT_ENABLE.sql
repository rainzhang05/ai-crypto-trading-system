-- Test-only SQL for ephemeral DB harness.
-- Purpose: disable ts_insert_blocker triggers in bootstrap-restored tables
-- so integration fixtures can insert deterministic rows for runtime validation.
-- This file MUST NOT be applied to persistent production environments.

DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT n.nspname AS schema_name, c.relname AS table_name, t.tgname AS trigger_name
        FROM pg_trigger t
        JOIN pg_class c ON c.oid = t.tgrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND NOT t.tgisinternal
          AND t.tgname = 'ts_insert_blocker'
    LOOP
        EXECUTE format(
            'ALTER TABLE %I.%I DISABLE TRIGGER %I',
            r.schema_name,
            r.table_name,
            r.trigger_name
        );
    END LOOP;
END
$$;

SELECT
    'remaining_enabled_ts_insert_blocker' AS check_name,
    COUNT(*) AS violations
FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND NOT t.tgisinternal
  AND t.tgname = 'ts_insert_blocker'
  AND t.tgenabled <> 'D';
