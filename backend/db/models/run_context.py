"""Run context model definitions."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    BigInteger,
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


class RunContext(Base):
    """Execution cycle identity and deterministic replay context."""

    __tablename__ = "run_context"
    __table_args__ = (
        PrimaryKeyConstraint("run_id", name="pk_run_context"),
        UniqueConstraint(
        "account_id",
        "run_mode",
        "hour_ts_utc",
        name="uq_run_context_account_mode_hour",
        ),
        UniqueConstraint(
            "run_id",
            "run_mode",
            "hour_ts_utc",
            name="uq_run_context_run_mode_hour",
        ),
        UniqueConstraint(
            "run_id",
            "account_id",
            "run_mode",
            "hour_ts_utc",
            name="uq_run_context_run_account_mode_hour",
        ),
        UniqueConstraint(
            "run_id",
            "account_id",
            "run_mode",
            "origin_hour_ts_utc",
            name="uq_run_context_run_account_mode_origin_hour",
        ),
        CheckConstraint(
            "date_trunc('hour', hour_ts_utc) = hour_ts_utc",
            name="ck_run_context_hour_aligned",
        ),
        CheckConstraint(
            "date_trunc('hour', origin_hour_ts_utc) = origin_hour_ts_utc",
            name="ck_run_context_origin_hour_aligned",
        ),
        CheckConstraint("cycle_seq >= 0", name="ck_run_context_cycle_seq_pos"),
        CheckConstraint(
            "status IN ('STARTED', 'COMPLETED', 'FAILED', 'SKIPPED')",
            name="ck_run_context_status",
        ),
        CheckConstraint(
            "completed_at_utc IS NULL OR completed_at_utc >= started_at_utc",
            name="ck_run_context_completed_after_started",
        ),
        CheckConstraint(
            "(run_mode = 'BACKTEST' AND backtest_run_id IS NOT NULL) OR "
            "(run_mode IN ('PAPER', 'LIVE') AND backtest_run_id IS NULL)",
            name="ck_run_context_backtest_link",
        ),
        Index("idx_run_context_mode_hour_desc", "run_mode", desc("hour_ts_utc")),
        Index(
            "idx_run_context_account_mode_hour_desc",
            "account_id",
            "run_mode",
            desc("hour_ts_utc"),
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    account_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey(
            "account.account_id",
            name="fk_run_context_account",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    run_mode: Mapped[str] = mapped_column(run_mode_enum, nullable=False)
    hour_ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cycle_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    code_version_sha: Mapped[str] = mapped_column(CHAR(40), nullable=False)
    config_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    data_snapshot_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    random_seed: Mapped[int] = mapped_column(Integer, nullable=False)
    backtest_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "backtest_run.backtest_run_id",
            name="fk_run_context_backtest_run",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
    )
    started_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    completed_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    origin_hour_ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    run_seed_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    context_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    replay_root_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'STARTED'"),
    )


class ReplayManifest(Base):
    """Canonical replay manifest root hash for deterministic replay parity."""

    __tablename__ = "replay_manifest"
    __table_args__ = (
        PrimaryKeyConstraint("run_id", name="pk_replay_manifest"),
        ForeignKeyConstraint(
            ["run_id", "account_id", "run_mode", "origin_hour_ts_utc"],
            ["run_context.run_id", "run_context.account_id", "run_context.run_mode", "run_context.origin_hour_ts_utc"],
            name="fk_replay_manifest_run_context",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    account_id: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    run_mode: Mapped[str] = mapped_column(run_mode_enum, nullable=False)
    origin_hour_ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    run_seed_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    replay_root_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    authoritative_row_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    generated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class SchemaMigrationControl(Base):
    """Schema lock rows used to enforce migration gating rules."""

    __tablename__ = "schema_migration_control"
    __table_args__ = (
        PrimaryKeyConstraint(
            "migration_name",
            name="schema_migration_control_pkey",
        ),
    )

    migration_name: Mapped[str] = mapped_column(Text, nullable=False)
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False)
    lock_reason: Mapped[str] = mapped_column(Text, nullable=False)
    locked_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    unlocked_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
