"""Model output table definitions."""

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
    Index,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    BigInteger,
    Text,
    desc,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base
from backend.db.enums import horizon_enum, model_role_enum, run_mode_enum

logger = logging.getLogger(__name__)


class RegimeOutput(Base):
    """Regime model classification outputs."""

    __tablename__ = "regime_output"
    __table_args__ = (
        PrimaryKeyConstraint(
            "run_id",
            "asset_id",
            "hour_ts_utc",
            name="pk_regime_output",
        ),
        ForeignKeyConstraint(
            ["run_id", "run_mode", "hour_ts_utc"],
            ["run_context.run_id", "run_context.run_mode", "run_context.hour_ts_utc"],
            name="fk_regime_output_run_context",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "date_trunc('hour', hour_ts_utc) = hour_ts_utc",
            name="ck_regime_output_hour_aligned",
        ),
        CheckConstraint(
            "length(btrim(regime_label)) > 0",
            name="ck_regime_output_label_not_blank",
        ),
        CheckConstraint(
            "regime_probability >= 0 AND regime_probability <= 1",
            name="ck_regime_output_probability_range",
        ),
        Index(
            "idx_regime_output_label_hour_desc",
            "regime_label",
            desc("hour_ts_utc"),
        ),
        Index(
            "idx_regime_output_asset_hour_desc",
            "asset_id",
            desc("hour_ts_utc"),
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    run_mode: Mapped[str] = mapped_column(run_mode_enum, nullable=False)
    asset_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey(
            "asset.asset_id",
            name="fk_regime_output_asset",
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
    model_version_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "model_version.model_version_id",
            name="fk_regime_output_model_version",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    regime_label: Mapped[str] = mapped_column(Text, nullable=False)
    regime_probability: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    input_feature_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)


class ModelPrediction(Base):
    """Per-model prediction probabilities and expected returns."""

    __tablename__ = "model_prediction"
    __table_args__ = (
        PrimaryKeyConstraint(
            "run_id",
            "asset_id",
            "horizon",
            "model_version_id",
            "hour_ts_utc",
            name="pk_model_prediction",
        ),
        ForeignKeyConstraint(
            ["run_id", "run_mode", "hour_ts_utc"],
            ["run_context.run_id", "run_context.run_mode", "run_context.hour_ts_utc"],
            name="fk_model_prediction_run_context",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "date_trunc('hour', hour_ts_utc) = hour_ts_utc",
            name="ck_model_prediction_hour_aligned",
        ),
        CheckConstraint(
            "prob_up >= 0 AND prob_up <= 1",
            name="ck_model_prediction_prob_range",
        ),
        Index(
            "idx_model_prediction_asset_hour_horizon",
            "asset_id",
            desc("hour_ts_utc"),
            "horizon",
        ),
        Index(
            "idx_model_prediction_role_hour_desc",
            "model_role",
            desc("hour_ts_utc"),
        ),
        Index(
            "uqix_model_prediction_meta_per_run_asset_horizon_hour",
            "run_id",
            "asset_id",
            "horizon",
            "hour_ts_utc",
            unique=True,
            postgresql_where=text("model_role = 'META'"),
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    run_mode: Mapped[str] = mapped_column(run_mode_enum, nullable=False)
    asset_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey(
            "asset.asset_id",
            name="fk_model_prediction_asset",
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
    horizon: Mapped[str] = mapped_column(horizon_enum, nullable=False, primary_key=True)
    model_version_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "model_version.model_version_id",
            name="fk_model_prediction_model_version",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
        primary_key=True,
    )
    model_role: Mapped[str] = mapped_column(model_role_enum, nullable=False)
    prob_up: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    expected_return: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    input_feature_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)


class MetaLearnerComponent(Base):
    """Meta-model component decomposition for auditability."""

    __tablename__ = "meta_learner_component"
    __table_args__ = (
        PrimaryKeyConstraint(
            "run_id",
            "asset_id",
            "horizon",
            "meta_model_version_id",
            "base_model_version_id",
            "hour_ts_utc",
            name="pk_meta_learner_component",
        ),
        ForeignKeyConstraint(
            ["run_id", "run_mode", "hour_ts_utc"],
            ["run_context.run_id", "run_context.run_mode", "run_context.hour_ts_utc"],
            name="fk_meta_component_run_context",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "date_trunc('hour', hour_ts_utc) = hour_ts_utc",
            name="ck_meta_learner_component_hour_aligned",
        ),
        CheckConstraint(
            "base_prob_up >= 0 AND base_prob_up <= 1",
            name="ck_meta_learner_component_prob_range",
        ),
        CheckConstraint(
            "meta_model_version_id <> base_model_version_id",
            name="ck_meta_learner_component_distinct_models",
        ),
        Index(
            "idx_meta_component_meta_model_hour_desc",
            "meta_model_version_id",
            desc("hour_ts_utc"),
        ),
        Index(
            "idx_meta_component_asset_hour_desc",
            "asset_id",
            desc("hour_ts_utc"),
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    run_mode: Mapped[str] = mapped_column(run_mode_enum, nullable=False)
    asset_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey(
            "asset.asset_id",
            name="fk_meta_component_asset",
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
    horizon: Mapped[str] = mapped_column(horizon_enum, nullable=False, primary_key=True)
    meta_model_version_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "model_version.model_version_id",
            name="fk_meta_component_meta_model",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
        primary_key=True,
    )
    base_model_version_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "model_version.model_version_id",
            name="fk_meta_component_base_model",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
        primary_key=True,
    )
    base_prob_up: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    base_expected_return: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    component_weight: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
