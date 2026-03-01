\set ON_ERROR_STOP on

BEGIN;

DO $$
BEGIN
    IF to_regprocedure('public.fn_enforce_cluster_cap_on_admission()') IS NULL THEN
        RAISE EXCEPTION 'Missing canonical function: public.fn_enforce_cluster_cap_on_admission()';
    END IF;

    IF to_regprocedure('public.fn_enforce_runtime_risk_gate()') IS NULL THEN
        RAISE EXCEPTION 'Missing canonical function: public.fn_enforce_runtime_risk_gate()';
    END IF;

    IF to_regprocedure('public.fn_validate_risk_event_parent_state_hash()') IS NULL THEN
        RAISE EXCEPTION 'Missing canonical function: public.fn_validate_risk_event_parent_state_hash()';
    END IF;
END;
$$;

DROP TRIGGER IF EXISTS ctrg_order_request_v2_cluster_cap ON order_request;
DROP TRIGGER IF EXISTS ctrg_order_request_cluster_cap ON order_request;
CREATE CONSTRAINT TRIGGER ctrg_order_request_cluster_cap
AFTER INSERT ON order_request
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fn_enforce_cluster_cap_on_admission();

DROP TRIGGER IF EXISTS ctrg_order_request_v2_risk_gate ON order_request;
DROP TRIGGER IF EXISTS ctrg_order_request_risk_gate ON order_request;
CREATE CONSTRAINT TRIGGER ctrg_order_request_risk_gate
AFTER INSERT ON order_request
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fn_enforce_runtime_risk_gate();

DROP TRIGGER IF EXISTS ctrg_risk_event_v2_parent_state_hash ON risk_event;
DROP TRIGGER IF EXISTS ctrg_risk_event_parent_state_hash ON risk_event;
CREATE CONSTRAINT TRIGGER ctrg_risk_event_parent_state_hash
AFTER INSERT ON risk_event
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fn_validate_risk_event_parent_state_hash();

COMMIT;

SELECT
    COUNT(*) AS triggers_with_v2_refs
FROM information_schema.triggers
WHERE action_statement ILIKE '%\_v2%' ESCAPE '\';
