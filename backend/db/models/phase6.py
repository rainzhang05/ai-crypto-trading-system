"""Phase 6A/6B ingestion/training lineage model definitions."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base
from backend.db.enums import horizon_enum


class TrainingUniverseVersion(Base):
    """Versioned training universe registry."""

    __tablename__ = "training_universe_version"
    __table_args__ = (
        PrimaryKeyConstraint("universe_version_code", name="pk_training_universe_version"),
        CheckConstraint(
            "source_policy = 'COINAPI+KRAKEN_PUBLIC'",
            name="ck_training_universe_source_policy",
        ),
        CheckConstraint("symbol_count > 0", name="ck_training_universe_symbol_count"),
    )

    universe_version_code: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    universe_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    source_policy: Mapped[str] = mapped_column(Text, nullable=False)
    symbol_count: Mapped[int] = mapped_column(Integer, nullable=False)
    row_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)


class TrainingUniverseSymbol(Base):
    """Versioned universe symbol membership with venue metadata."""

    __tablename__ = "training_universe_symbol"
    __table_args__ = (
        PrimaryKeyConstraint("universe_version_code", "symbol", name="pk_training_universe_symbol"),
        CheckConstraint("symbol = upper(symbol)", name="ck_training_universe_symbol_upper"),
        CheckConstraint("market_cap_rank >= 1", name="ck_training_universe_market_cap_rank"),
        CheckConstraint("market_cap_usd >= 0", name="ck_training_universe_market_cap_nonneg"),
    )

    universe_version_code: Mapped[str] = mapped_column(
        Text,
        ForeignKey(
            "training_universe_version.universe_version_code",
            name="fk_training_universe_symbol_version",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    market_cap_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    market_cap_usd: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    is_kraken_tradable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    kraken_pair: Mapped[str | None] = mapped_column(Text)
    row_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)


class IngestionCycle(Base):
    """Ingestion cycle metadata and deterministic state transitions."""

    __tablename__ = "ingestion_cycle"
    __table_args__ = (
        PrimaryKeyConstraint("ingestion_cycle_id", name="pk_ingestion_cycle"),
        CheckConstraint(
            "cycle_kind IN ('BOOTSTRAP', 'INCREMENTAL', 'GAP_REPAIR')",
            name="ck_ingestion_cycle_kind",
        ),
        CheckConstraint(
            "status IN ('RUNNING', 'COMPLETED', 'FAILED')",
            name="ck_ingestion_cycle_status",
        ),
        CheckConstraint(
            "completed_at_utc IS NULL OR completed_at_utc >= started_at_utc",
            name="ck_ingestion_cycle_time_order",
        ),
    )

    ingestion_cycle_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    cycle_kind: Mapped[str] = mapped_column(Text, nullable=False)
    started_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    details_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    row_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)


class IngestionWatermarkHistory(Base):
    """Append-only ingestion watermark lineage."""

    __tablename__ = "ingestion_watermark_history"
    __table_args__ = (
        PrimaryKeyConstraint("watermark_id", name="pk_ingestion_watermark_history"),
        CheckConstraint(
            "source_name IN ('COINAPI', 'KRAKEN_PUBLIC')",
            name="ck_ingestion_watermark_source",
        ),
        CheckConstraint("symbol = upper(symbol)", name="ck_ingestion_watermark_symbol_upper"),
        CheckConstraint(
            "watermark_kind IN ('BOOTSTRAP_END', 'INCREMENTAL_END')",
            name="ck_ingestion_watermark_kind",
        ),
        CheckConstraint("records_ingested >= 0", name="ck_ingestion_watermark_records_nonneg"),
    )

    watermark_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), nullable=False)
    ingestion_cycle_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey(
            "ingestion_cycle.ingestion_cycle_id",
            name="fk_ingestion_watermark_cycle",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    source_name: Mapped[str] = mapped_column(Text, nullable=False)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    watermark_kind: Mapped[str] = mapped_column(Text, nullable=False)
    watermark_ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    watermark_cursor: Mapped[str | None] = mapped_column(Text)
    records_ingested: Mapped[int] = mapped_column(BigInteger, nullable=False)
    row_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)


class RawTradeChunkManifest(Base):
    """Local raw-trade chunk metadata persisted for lineage and replay."""

    __tablename__ = "raw_trade_chunk_manifest"
    __table_args__ = (
        PrimaryKeyConstraint("chunk_manifest_id", name="pk_raw_trade_chunk_manifest"),
        UniqueConstraint(
            "source_name",
            "symbol",
            "day_utc",
            "file_sha256",
            name="uq_raw_trade_chunk_manifest_identity",
        ),
        CheckConstraint("source_name = 'COINAPI'", name="ck_raw_trade_chunk_source"),
        CheckConstraint("symbol = upper(symbol)", name="ck_raw_trade_chunk_symbol_upper"),
        CheckConstraint("row_count >= 0", name="ck_raw_trade_chunk_rows_nonneg"),
        CheckConstraint("max_trade_ts_utc >= min_trade_ts_utc", name="ck_raw_trade_chunk_ts_order"),
    )

    chunk_manifest_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), nullable=False)
    ingestion_cycle_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey(
            "ingestion_cycle.ingestion_cycle_id",
            name="fk_raw_trade_chunk_cycle",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    source_name: Mapped[str] = mapped_column(Text, nullable=False)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    day_utc: Mapped[date] = mapped_column(Date, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    row_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    min_trade_ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    max_trade_ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    chunk_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    row_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)


class DataGapEvent(Base):
    """Detected data gaps and deterministic reconciliation outcomes."""

    __tablename__ = "data_gap_event"
    __table_args__ = (
        PrimaryKeyConstraint("gap_event_id", name="pk_data_gap_event"),
        CheckConstraint("source_name = 'COINAPI'", name="ck_data_gap_source"),
        CheckConstraint("symbol = upper(symbol)", name="ck_data_gap_symbol_upper"),
        CheckConstraint("gap_end_ts_utc > gap_start_ts_utc", name="ck_data_gap_ordering"),
        CheckConstraint("status IN ('PENDING', 'REPAIRED', 'FAILED')", name="ck_data_gap_status"),
        CheckConstraint(
            "resolved_at_utc IS NULL OR resolved_at_utc >= detected_at_utc",
            name="ck_data_gap_resolve_time",
        ),
    )

    gap_event_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    source_name: Mapped[str] = mapped_column(Text, nullable=False)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    gap_start_ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    gap_end_ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    detected_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    details_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    row_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)


class DatasetSnapshot(Base):
    """Materialized deterministic dataset metadata."""

    __tablename__ = "dataset_snapshot"
    __table_args__ = (
        PrimaryKeyConstraint("dataset_snapshot_id", name="pk_dataset_snapshot"),
        UniqueConstraint("dataset_hash", name="uq_dataset_snapshot_hash"),
        CheckConstraint("row_count > 0", name="ck_dataset_snapshot_row_count"),
        CheckConstraint("symbol_count > 0", name="ck_dataset_snapshot_symbol_count"),
    )

    dataset_snapshot_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    generated_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dataset_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    row_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    symbol_count: Mapped[int] = mapped_column(Integer, nullable=False)
    materialized_path: Mapped[str] = mapped_column(Text, nullable=False)
    component_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    row_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)


class DatasetSnapshotComponent(Base):
    """Dataset component lineage table."""

    __tablename__ = "dataset_snapshot_component"
    __table_args__ = (
        PrimaryKeyConstraint(
            "dataset_snapshot_id",
            "symbol",
            "component_path",
            name="pk_dataset_snapshot_component",
        ),
        CheckConstraint("symbol = upper(symbol)", name="ck_dataset_component_symbol_upper"),
        CheckConstraint("component_row_count >= 0", name="ck_dataset_component_row_count"),
    )

    dataset_snapshot_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey(
            "dataset_snapshot.dataset_snapshot_id",
            name="fk_dataset_component_snapshot",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    component_path: Mapped[str] = mapped_column(Text, nullable=False)
    component_row_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    component_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    row_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)


class TrainingCycle(Base):
    """Training/retraining cycle registry."""

    __tablename__ = "training_cycle"
    __table_args__ = (
        PrimaryKeyConstraint("training_cycle_id", name="pk_training_cycle"),
        CheckConstraint(
            "cycle_kind IN ('SCHEDULED', 'DRIFT_TRIGGERED', 'MANUAL')",
            name="ck_training_cycle_kind",
        ),
        CheckConstraint(
            "status IN ('RUNNING', 'COMPLETED', 'REJECTED', 'FAILED')",
            name="ck_training_cycle_status",
        ),
        CheckConstraint(
            "completed_at_utc IS NULL OR completed_at_utc >= started_at_utc",
            name="ck_training_cycle_time_order",
        ),
    )

    training_cycle_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    cycle_kind: Mapped[str] = mapped_column(Text, nullable=False)
    started_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    details_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    row_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)


class ModelTrainingRun(Base):
    """Summary record for one candidate model-set training run."""

    __tablename__ = "model_training_run"
    __table_args__ = (
        PrimaryKeyConstraint("training_cycle_id", name="pk_model_training_run"),
        CheckConstraint(
            "tree_model_count >= 0 AND deep_model_count >= 0",
            name="ck_model_training_run_counts_nonneg",
        ),
    )

    training_cycle_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey(
            "training_cycle.training_cycle_id",
            name="fk_model_training_run_cycle",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    dataset_snapshot_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey(
            "dataset_snapshot.dataset_snapshot_id",
            name="fk_model_training_run_snapshot",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    candidate_model_set_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    tree_model_count: Mapped[int] = mapped_column(Integer, nullable=False)
    deep_model_count: Mapped[int] = mapped_column(Integer, nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason_code: Mapped[str] = mapped_column(Text, nullable=False)
    run_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    row_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)


class HindcastForecastMetric(Base):
    """Hindcast and forecast quality metric history."""

    __tablename__ = "hindcast_forecast_metric"
    __table_args__ = (
        PrimaryKeyConstraint("metric_id", name="pk_hindcast_forecast_metric"),
        CheckConstraint("symbol = upper(symbol)", name="ck_hindcast_symbol_upper"),
        CheckConstraint(
            "metric_kind IN ('HINDCAST', 'FORECAST', 'ROLLING')",
            name="ck_hindcast_metric_kind",
        ),
        CheckConstraint(
            "directional_accuracy >= 0 AND directional_accuracy <= 1",
            name="ck_hindcast_accuracy_range",
        ),
        CheckConstraint(
            "brier_score >= 0 AND brier_score <= 1",
            name="ck_hindcast_brier_range",
        ),
        CheckConstraint("ece >= 0 AND ece <= 1", name="ck_hindcast_ece_range"),
    )

    metric_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), nullable=False)
    training_cycle_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey(
            "training_cycle.training_cycle_id",
            name="fk_hindcast_cycle",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    horizon: Mapped[str] = mapped_column(horizon_enum, nullable=False)
    metric_kind: Mapped[str] = mapped_column(Text, nullable=False)
    directional_accuracy: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    brier_score: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    ece: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    measured_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    row_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)


class DriftEvent(Base):
    """Persisted drift trigger evidence."""

    __tablename__ = "drift_event"
    __table_args__ = (
        PrimaryKeyConstraint("drift_event_id", name="pk_drift_event"),
        CheckConstraint("symbol = upper(symbol)", name="ck_drift_symbol_upper"),
        CheckConstraint("accuracy_drop_pp >= 0", name="ck_drift_accuracy_nonneg"),
        CheckConstraint("ece_delta >= 0", name="ck_drift_ece_nonneg"),
        CheckConstraint("psi_value >= 0", name="ck_drift_psi_nonneg"),
    )

    drift_event_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    training_cycle_ref: Mapped[str] = mapped_column(Text, nullable=False)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    horizon: Mapped[str] = mapped_column(horizon_enum, nullable=False)
    accuracy_drop_pp: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    ece_delta: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    psi_value: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    triggered_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    threshold_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    row_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)


class PromotionDecision(Base):
    """Promotion gate decisions for model-set activation."""

    __tablename__ = "promotion_decision"
    __table_args__ = (
        PrimaryKeyConstraint("promotion_decision_id", name="pk_promotion_decision"),
    )

    promotion_decision_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    training_cycle_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey(
            "training_cycle.training_cycle_id",
            name="fk_promotion_decision_cycle",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    candidate_model_set_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason_code: Mapped[str] = mapped_column(Text, nullable=False)
    metrics_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    decided_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    row_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)


class AutomationEventLog(Base):
    """Operational automation event log."""

    __tablename__ = "automation_event_log"
    __table_args__ = (
        PrimaryKeyConstraint("event_id", name="pk_automation_event_log"),
        CheckConstraint(
            "length(btrim(event_type)) > 0",
            name="ck_automation_event_type_not_blank",
        ),
        CheckConstraint(
            "length(btrim(status)) > 0",
            name="ck_automation_event_status_not_blank",
        ),
    )

    event_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), nullable=False)
    event_ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False)
    row_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
