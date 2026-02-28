"""Run context model definitions."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    DateTime,
    ForeignKey,
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
        CheckConstraint(
            "date_trunc('hour', hour_ts_utc) = hour_ts_utc",
            name="ck_run_context_hour_aligned",
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

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
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
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'STARTED'"),
    )
