"""Portfolio and position state model definitions."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    desc,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base
from backend.db.enums import run_mode_enum

logger = logging.getLogger(__name__)


class PortfolioHourlyState(Base):
    """Hourly portfolio snapshot for account-level reconciliation."""

    __tablename__ = "portfolio_hourly_state"
    __table_args__ = (
        PrimaryKeyConstraint(
            "run_mode",
            "account_id",
            "hour_ts_utc",
            name="pk_portfolio_hourly_state",
        ),
        ForeignKeyConstraint(
            ["source_run_id", "run_mode", "hour_ts_utc"],
            ["run_context.run_id", "run_context.run_mode", "run_context.hour_ts_utc"],
            name="fk_portfolio_hourly_state_run_context",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "date_trunc('hour', hour_ts_utc) = hour_ts_utc",
            name="ck_portfolio_hourly_state_hour_aligned",
        ),
        CheckConstraint(
            "cash_balance >= 0",
            name="ck_portfolio_hourly_state_cash_nonneg",
        ),
        CheckConstraint(
            "market_value >= 0",
            name="ck_portfolio_hourly_state_market_nonneg",
        ),
        CheckConstraint(
            "portfolio_value >= 0",
            name="ck_portfolio_hourly_state_value_nonneg",
        ),
        CheckConstraint(
            "peak_portfolio_value >= 0",
            name="ck_portfolio_hourly_state_peak_nonneg",
        ),
        CheckConstraint(
            "drawdown_pct >= 0 AND drawdown_pct <= 1",
            name="ck_portfolio_hourly_state_drawdown_range",
        ),
        CheckConstraint(
            "total_exposure_pct >= 0 AND total_exposure_pct <= 1",
            name="ck_portfolio_hourly_state_exposure_range",
        ),
        CheckConstraint(
            "open_position_count >= 0 AND open_position_count <= 10",
            name="ck_portfolio_hourly_state_pos_count_range",
        ),
        CheckConstraint(
            "portfolio_value = cash_balance + market_value",
            name="ck_portfolio_hourly_state_value_reconcile",
        ),
        CheckConstraint(
            "peak_portfolio_value >= portfolio_value",
            name="ck_portfolio_hourly_state_peak_ge_value",
        ),
        Index(
            "idx_portfolio_hourly_account_hour_desc",
            "account_id",
            desc("hour_ts_utc"),
        ),
        Index(
            "idx_portfolio_hourly_halted_true_hour_desc",
            desc("hour_ts_utc"),
            postgresql_where=text("halted = TRUE"),
        ),
        Index("idx_portfolio_hourly_source_run_id", "source_run_id"),
    )

    run_mode: Mapped[str] = mapped_column(run_mode_enum, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey(
            "account.account_id",
            name="fk_portfolio_hourly_state_account",
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
    cash_balance: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    market_value: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    portfolio_value: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    peak_portfolio_value: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    drawdown_pct: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    total_exposure_pct: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    open_position_count: Mapped[int] = mapped_column(Integer, nullable=False)
    halted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("FALSE"),
    )
    source_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reconciliation_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)


class PositionHourlyState(Base):
    """Hourly per-asset position state snapshots."""

    __tablename__ = "position_hourly_state"
    __table_args__ = (
        PrimaryKeyConstraint(
            "run_mode",
            "account_id",
            "asset_id",
            "hour_ts_utc",
            name="pk_position_hourly_state",
        ),
        ForeignKeyConstraint(
            ["source_run_id", "run_mode", "hour_ts_utc"],
            ["run_context.run_id", "run_context.run_mode", "run_context.hour_ts_utc"],
            name="fk_position_hourly_state_run_context",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "date_trunc('hour', hour_ts_utc) = hour_ts_utc",
            name="ck_position_hourly_state_hour_aligned",
        ),
        CheckConstraint(
            "quantity >= 0",
            name="ck_position_hourly_state_qty_nonneg",
        ),
        CheckConstraint(
            "avg_cost >= 0",
            name="ck_position_hourly_state_avg_cost_nonneg",
        ),
        CheckConstraint(
            "mark_price > 0",
            name="ck_position_hourly_state_mark_price_pos",
        ),
        CheckConstraint(
            "market_value >= 0",
            name="ck_position_hourly_state_market_value_nonneg",
        ),
        CheckConstraint(
            "market_value = quantity * mark_price",
            name="ck_position_hourly_state_market_value_formula",
        ),
        CheckConstraint(
            "exposure_pct >= 0 AND exposure_pct <= 1",
            name="ck_position_hourly_state_exposure_range",
        ),
        Index(
            "idx_position_hourly_account_hour_desc",
            "account_id",
            desc("hour_ts_utc"),
        ),
        Index(
            "idx_position_hourly_asset_hour_desc",
            "asset_id",
            desc("hour_ts_utc"),
        ),
        Index("idx_position_hourly_source_run_id", "source_run_id"),
    )

    run_mode: Mapped[str] = mapped_column(run_mode_enum, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey(
            "account.account_id",
            name="fk_position_hourly_state_account",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
        primary_key=True,
    )
    asset_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey(
            "asset.asset_id",
            name="fk_position_hourly_state_asset",
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
    quantity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    avg_cost: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    mark_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    market_value: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    realized_pnl_cum: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    exposure_pct: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    source_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
