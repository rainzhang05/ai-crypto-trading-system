"""Feature definition and snapshot model definitions."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    UniqueConstraint,
    desc,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base
from backend.db.enums import run_mode_enum

logger = logging.getLogger(__name__)


class FeatureDefinition(Base):
    """Feature metadata catalog."""

    __tablename__ = "feature_definition"
    __table_args__ = (
        PrimaryKeyConstraint("feature_id", name="pk_feature_definition"),
        UniqueConstraint(
            "feature_name",
            "feature_version",
            name="uq_feature_definition_name_version",
        ),
        CheckConstraint(
            "length(btrim(feature_name)) > 0",
            name="ck_feature_definition_name_not_blank",
        ),
        CheckConstraint(
            "length(btrim(feature_group)) > 0",
            name="ck_feature_definition_group_not_blank",
        ),
        CheckConstraint(
            "lookback_hours >= 0",
            name="ck_feature_definition_lookback_nonneg",
        ),
        CheckConstraint(
            "value_dtype IN ('NUMERIC')",
            name="ck_feature_definition_dtype",
        ),
    )

    feature_id: Mapped[int] = mapped_column(
        Integer,
        Identity(always=True),
        primary_key=True,
    )
    feature_name: Mapped[str] = mapped_column(Text, nullable=False)
    feature_group: Mapped[str] = mapped_column(Text, nullable=False)
    lookback_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    value_dtype: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'NUMERIC'"),
    )
    feature_version: Mapped[str] = mapped_column(Text, nullable=False)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class FeatureSnapshot(Base):
    """Hourly feature values keyed to deterministic run context."""

    __tablename__ = "feature_snapshot"
    __table_args__ = (
        PrimaryKeyConstraint(
            "run_id",
            "asset_id",
            "feature_id",
            "hour_ts_utc",
            name="pk_feature_snapshot",
        ),
        ForeignKeyConstraint(
            ["run_id", "run_mode", "hour_ts_utc"],
            ["run_context.run_id", "run_context.run_mode", "run_context.hour_ts_utc"],
            name="fk_feature_snapshot_run_context",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "date_trunc('hour', hour_ts_utc) = hour_ts_utc",
            name="ck_feature_snapshot_hour_aligned",
        ),
        CheckConstraint(
            "source_window_start_utc <= source_window_end_utc AND "
            "source_window_end_utc <= hour_ts_utc",
            name="ck_feature_snapshot_source_window",
        ),
        Index(
            "idx_feature_snapshot_asset_hour_desc",
            "asset_id",
            desc("hour_ts_utc"),
        ),
        Index(
            "idx_feature_snapshot_feature_hour_desc",
            "feature_id",
            desc("hour_ts_utc"),
        ),
        Index(
            "idx_feature_snapshot_mode_hour_desc",
            "run_mode",
            desc("hour_ts_utc"),
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    run_mode: Mapped[str] = mapped_column(run_mode_enum, nullable=False)
    asset_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey(
            "asset.asset_id",
            name="fk_feature_snapshot_asset",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
        primary_key=True,
    )
    hour_ts_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        primary_key=True,
    )
    feature_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "feature_definition.feature_id",
            name="fk_feature_snapshot_feature_definition",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
        primary_key=True,
    )
    feature_value: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    source_window_start_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_window_end_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_data_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
