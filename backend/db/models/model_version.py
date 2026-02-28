"""Model registry and training-window model definitions."""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CHAR,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    BigInteger,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    desc,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base
from backend.db.enums import horizon_enum, model_role_enum

logger = logging.getLogger(__name__)


class ModelVersion(Base):
    """Model artifact registry with immutable hashes for reproducibility."""

    __tablename__ = "model_version"
    __table_args__ = (
        PrimaryKeyConstraint("model_version_id", name="pk_model_version"),
        UniqueConstraint("model_name", "version_label", name="uq_model_version_name_label"),
        CheckConstraint(
            "length(btrim(model_name)) > 0",
            name="ck_model_version_model_name_not_blank",
        ),
        CheckConstraint(
            "length(btrim(version_label)) > 0",
            name="ck_model_version_version_label_not_blank",
        ),
        CheckConstraint(
            "length(btrim(mlflow_model_uri)) > 0",
            name="ck_model_version_mlflow_uri_not_blank",
        ),
        CheckConstraint(
            "length(btrim(mlflow_run_id)) > 0",
            name="ck_model_version_mlflow_run_id_not_blank",
        ),
        Index("idx_model_version_role_active", "model_role", "is_active"),
        Index(
            "uqix_model_version_one_active_per_name_role",
            "model_name",
            "model_role",
            unique=True,
            postgresql_where=text("is_active = TRUE"),
        ),
    )

    model_version_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        primary_key=True,
    )
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    model_role: Mapped[str] = mapped_column(model_role_enum, nullable=False)
    version_label: Mapped[str] = mapped_column(Text, nullable=False)
    mlflow_model_uri: Mapped[str] = mapped_column(Text, nullable=False)
    mlflow_run_id: Mapped[str] = mapped_column(Text, nullable=False)
    feature_set_version: Mapped[str] = mapped_column(Text, nullable=False)
    hyperparams_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    training_data_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("TRUE"),
    )


class ModelTrainingWindow(Base):
    """Train-validation windows used for model version backtesting folds."""

    __tablename__ = "model_training_window"
    __table_args__ = (
        PrimaryKeyConstraint("training_window_id", name="pk_model_training_window"),
        UniqueConstraint(
            "model_version_id",
            "fold_index",
            "horizon",
            name="uq_model_training_window_model_fold_horizon",
        ),
        CheckConstraint(
            "fold_index >= 0",
            name="ck_model_training_window_fold_nonneg",
        ),
        CheckConstraint(
            "train_start_utc < train_end_utc AND "
            "train_end_utc < valid_start_utc AND "
            "valid_start_utc < valid_end_utc",
            name="ck_model_training_window_ordering",
        ),
        Index(
            "idx_model_training_window_valid_range",
            "valid_start_utc",
            "valid_end_utc",
        ),
    )

    training_window_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        primary_key=True,
    )
    model_version_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "model_version.model_version_id",
            name="fk_model_training_window_model_version",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    fold_index: Mapped[int] = mapped_column(Integer, nullable=False)
    horizon: Mapped[str] = mapped_column(horizon_enum, nullable=False)
    train_start_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    train_end_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_start_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_end_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
