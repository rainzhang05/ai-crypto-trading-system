-- PHASE 2 replay harness validation gate
-- All SELECT statements must return violations = 0.

-- 1) run_context replay-critical hashes must remain hex-encoded.
SELECT
    'run_context_hash_format_violation' AS check_name,
    COUNT(*) AS violations
FROM run_context
WHERE lower(btrim(run_seed_hash::text)) !~ '^[0-9a-f]{64}$'
   OR lower(btrim(context_hash::text)) !~ '^[0-9a-f]{64}$'
   OR lower(btrim(replay_root_hash::text)) !~ '^[0-9a-f]{64}$';

-- 2) replay_manifest replay-critical hashes must remain hex-encoded.
SELECT
    'replay_manifest_hash_format_violation' AS check_name,
    COUNT(*) AS violations
FROM replay_manifest
WHERE lower(btrim(run_seed_hash::text)) !~ '^[0-9a-f]{64}$'
   OR lower(btrim(replay_root_hash::text)) !~ '^[0-9a-f]{64}$';

-- 3) replay_manifest rows must map to an existing run_context replay key.
SELECT
    'replay_manifest_orphan_rows' AS check_name,
    COUNT(*) AS violations
FROM replay_manifest rm
LEFT JOIN run_context rc
  ON rc.run_id = rm.run_id
 AND rc.account_id = rm.account_id
 AND rc.run_mode = rm.run_mode
 AND rc.origin_hour_ts_utc = rm.origin_hour_ts_utc
WHERE rc.run_id IS NULL;

-- 4) Every run_context replay key must have a replay_manifest row.
SELECT
    'run_context_missing_replay_manifest_rows' AS check_name,
    COUNT(*) AS violations
FROM run_context rc
LEFT JOIN replay_manifest rm
  ON rm.run_id = rc.run_id
 AND rm.account_id = rc.account_id
 AND rm.run_mode = rc.run_mode
 AND rm.origin_hour_ts_utc = rc.origin_hour_ts_utc
WHERE rm.run_id IS NULL;

-- 5) replay_manifest.run_seed_hash must match run_context.run_seed_hash.
SELECT
    'replay_manifest_run_seed_mismatch' AS check_name,
    COUNT(*) AS violations
FROM replay_manifest rm
JOIN run_context rc
  ON rc.run_id = rm.run_id
 AND rc.account_id = rm.account_id
 AND rc.run_mode = rm.run_mode
 AND rc.origin_hour_ts_utc = rm.origin_hour_ts_utc
WHERE rm.run_seed_hash <> rc.run_seed_hash;

-- 6) replay_manifest.replay_root_hash must match run_context.replay_root_hash.
SELECT
    'replay_manifest_root_mismatch' AS check_name,
    COUNT(*) AS violations
FROM replay_manifest rm
JOIN run_context rc
  ON rc.run_id = rm.run_id
 AND rc.account_id = rm.account_id
 AND rc.run_mode = rm.run_mode
 AND rc.origin_hour_ts_utc = rm.origin_hour_ts_utc
WHERE rm.replay_root_hash <> rc.replay_root_hash;

-- 7) authoritative row count must be non-negative.
SELECT
    'replay_manifest_negative_authoritative_row_count' AS check_name,
    COUNT(*) AS violations
FROM replay_manifest
WHERE authoritative_row_count < 0;

-- 8) Deterministic parity for identical replay seeds at identical replay keys.
WITH parity_pairs AS (
    SELECT
        a.run_id AS run_id_a,
        b.run_id AS run_id_b,
        (a.replay_root_hash = b.replay_root_hash) AS root_hash_match,
        (a.authoritative_row_count = b.authoritative_row_count) AS row_count_match
    FROM replay_manifest a
    JOIN replay_manifest b
      ON a.account_id = b.account_id
     AND a.run_mode = b.run_mode
     AND a.origin_hour_ts_utc = b.origin_hour_ts_utc
    WHERE a.run_id <> b.run_id
      AND a.run_seed_hash = b.run_seed_hash
)
SELECT
    'replay_seed_collision_parity_mismatch_pairs' AS check_name,
    COUNT(*) AS violations
FROM parity_pairs
WHERE NOT (root_hash_match AND row_count_match);
