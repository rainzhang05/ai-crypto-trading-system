"""Backtest run and fold-result model definitions."""

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
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    desc,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base

logger = logging.getLogger(__name__)


class BacktestRun(Base):
    """Backtest execution metadata and immutable configuration hashes."""

    __tablename__ = "backtest_run"
    __table_args__ = (
        PrimaryKeyConstraint("backtest_run_id", name="pk_backtest_run"),
        CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')",
            name="ck_backtest_run_status",
        ),
        CheckConstraint(
            "completed_at_utc IS NULL OR completed_at_utc >= started_at_utc",
            name="ck_backtest_run_completed_after_started",
        ),
        CheckConstraint(
            "initial_capital > 0",
            name="ck_backtest_run_initial_capital_pos",
        ),
        Index(
            "idx_backtest_run_status_started_desc",
            "status",
            desc("started_at_utc"),
        ),
        Index("idx_backtest_run_config_hash", "config_hash"),
    )

    backtest_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
    )
    account_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey(
            "account.account_id",
            name="fk_backtest_run_account",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    started_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_code_sha: Mapped[str] = mapped_column(CHAR(40), nullable=False)
    config_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    universe_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    initial_capital: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    cost_profile_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey(
            "cost_profile.cost_profile_id",
            name="fk_backtest_run_cost_profile",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    random_seed: Mapped[int] = mapped_column(Integer, nullable=False)


class BacktestFoldResult(Base):
    """Per-fold validation statistics for a backtest run."""

    __tablename__ = "backtest_fold_result"
    __table_args__ = (
        PrimaryKeyConstraint("backtest_run_id", "fold_index", name="pk_backtest_fold_result"),
        CheckConstraint("fold_index >= 0", name="ck_backtest_fold_result_fold_nonneg"),
        CheckConstraint(
            "train_start_utc < train_end_utc AND "
            "train_end_utc < valid_start_utc AND "
            "valid_start_utc < valid_end_utc",
            name="ck_backtest_fold_result_window_order",
        ),
        CheckConstraint(
            "trades_count >= 0",
            name="ck_backtest_fold_result_trades_nonneg",
        ),
        CheckConstraint(
            "max_drawdown_pct >= 0 AND max_drawdown_pct <= 1",
            name="ck_backtest_fold_result_drawdown_range",
        ),
        CheckConstraint(
            "win_rate >= 0 AND win_rate <= 1",
            name="ck_backtest_fold_result_win_rate_range",
        ),
        Index(
            "idx_backtest_fold_result_valid_range",
            "valid_start_utc",
            "valid_end_utc",
        ),
    )

    backtest_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "backtest_run.backtest_run_id",
            name="fk_backtest_fold_result_backtest_run",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    fold_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    train_start_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    train_end_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_start_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_end_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trades_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sharpe: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    max_drawdown_pct: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    net_return_pct: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    win_rate: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
