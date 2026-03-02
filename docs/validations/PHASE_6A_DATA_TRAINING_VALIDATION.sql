-- Phase 6A deterministic data foundation and training bootstrap validation.

SELECT
    'phase6a_required_tables_missing' AS check_name,
    COUNT(*) AS violations
FROM (
    VALUES
        ('training_universe_version'),
        ('training_universe_symbol'),
        ('ingestion_cycle'),
        ('ingestion_watermark_history'),
        ('raw_trade_chunk_manifest'),
        ('data_gap_event'),
        ('dataset_snapshot'),
        ('dataset_snapshot_component'),
        ('training_cycle'),
        ('model_training_run'),
        ('hindcast_forecast_metric'),
        ('drift_event'),
        ('promotion_decision'),
        ('automation_event_log')
) AS required(table_name)
LEFT JOIN information_schema.tables t
  ON t.table_schema = 'public'
 AND t.table_name = required.table_name
WHERE t.table_name IS NULL;

SELECT
    'phase6a_invalid_source_policy_rows' AS check_name,
    COUNT(*) AS violations
FROM training_universe_version
WHERE source_policy <> 'COINAPI+KRAKEN_PUBLIC';

SELECT
    'phase6a_universe_v1_symbol_count_mismatch' AS check_name,
    COUNT(*) AS violations
FROM training_universe_version
WHERE symbol_count <> 30;

SELECT
    'phase6a_watermark_negative_records' AS check_name,
    COUNT(*) AS violations
FROM ingestion_watermark_history
WHERE records_ingested < 0;

SELECT
    'phase6a_raw_trade_chunk_negative_rows' AS check_name,
    COUNT(*) AS violations
FROM raw_trade_chunk_manifest
WHERE row_count < 0;

SELECT
    'phase6a_dataset_snapshot_nonpositive_rows' AS check_name,
    COUNT(*) AS violations
FROM dataset_snapshot
WHERE row_count <= 0 OR symbol_count <= 0;

SELECT
    'phase6a_data_gap_invalid_time_order' AS check_name,
    COUNT(*) AS violations
FROM data_gap_event
WHERE gap_end_ts_utc <= gap_start_ts_utc;

SELECT
    'phase6a_training_cycle_invalid_time_order' AS check_name,
    COUNT(*) AS violations
FROM training_cycle
WHERE completed_at_utc IS NOT NULL
  AND completed_at_utc < started_at_utc;

SELECT
    'phase6a_training_run_missing_snapshot_fk' AS check_name,
    COUNT(*) AS violations
FROM model_training_run r
LEFT JOIN dataset_snapshot s
  ON s.dataset_snapshot_id = r.dataset_snapshot_id
WHERE s.dataset_snapshot_id IS NULL;

SELECT
    'phase6a_hindcast_metric_range_violation' AS check_name,
    COUNT(*) AS violations
FROM hindcast_forecast_metric
WHERE directional_accuracy < 0
   OR directional_accuracy > 1
   OR brier_score < 0
   OR brier_score > 1
   OR ece < 0
   OR ece > 1;

SELECT
    'phase6a_promotion_missing_cycle_fk' AS check_name,
    COUNT(*) AS violations
FROM promotion_decision p
LEFT JOIN training_cycle c
  ON c.training_cycle_id = p.training_cycle_id
WHERE c.training_cycle_id IS NULL;
