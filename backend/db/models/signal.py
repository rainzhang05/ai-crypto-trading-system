"""Signal model definitions."""

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
    UniqueConstraint,
    Text,
    desc,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base
from backend.db.enums import horizon_enum, run_mode_enum, signal_action_enum

logger = logging.getLogger(__name__)


class TradeSignal(Base):
    """Append-only generated trade decisions from the decision engine."""

    __tablename__ = "trade_signal"
    __table_args__ = (
        PrimaryKeyConstraint("signal_id", name="pk_trade_signal"),
        UniqueConstraint(
            "run_id",
            "account_id",
            "asset_id",
            "horizon",
            name="uq_trade_signal_run_account_asset_horizon",
        ),
        UniqueConstraint(
            "signal_id",
            "run_id",
            "run_mode",
            "account_id",
            "asset_id",
            name="uq_trade_signal_identity",
        ),
        ForeignKeyConstraint(
            ["run_id", "run_mode", "hour_ts_utc"],
            ["run_context.run_id", "run_context.run_mode", "run_context.hour_ts_utc"],
            name="fk_trade_signal_run_context",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["run_mode", "account_id", "risk_state_hour_ts_utc"],
            ["risk_hourly_state.run_mode", "risk_hourly_state.account_id", "risk_hourly_state.hour_ts_utc"],
            name="fk_trade_signal_risk_hourly_state",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "date_trunc('hour', hour_ts_utc) = hour_ts_utc",
            name="ck_trade_signal_hour_aligned",
        ),
        CheckConstraint(
            "date_trunc('hour', risk_state_hour_ts_utc) = risk_state_hour_ts_utc",
            name="ck_trade_signal_risk_hour_aligned",
        ),
        CheckConstraint(
            "risk_state_hour_ts_utc = hour_ts_utc",
            name="ck_trade_signal_risk_hour_match",
        ),
        CheckConstraint(
            "direction IN ('LONG', 'FLAT')",
            name="ck_trade_signal_direction",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_trade_signal_confidence_range",
        ),
        CheckConstraint(
            "assumed_fee_rate >= 0 AND assumed_fee_rate <= 1",
            name="ck_trade_signal_fee_rate_range",
        ),
        CheckConstraint(
            "assumed_slippage_rate >= 0 AND assumed_slippage_rate <= 1",
            name="ck_trade_signal_slippage_rate_range",
        ),
        CheckConstraint(
            "position_size_fraction >= 0 AND position_size_fraction <= 1",
            name="ck_trade_signal_position_fraction_range",
        ),
        CheckConstraint(
            "target_position_notional >= 0",
            name="ck_trade_signal_target_notional_nonneg",
        ),
        CheckConstraint(
            "action <> 'ENTER' OR net_edge > 0",
            name="ck_trade_signal_enter_edge",
        ),
        CheckConstraint(
            "action <> 'ENTER' OR expected_return > (assumed_fee_rate + assumed_slippage_rate)",
            name="ck_trade_signal_enter_return_gt_cost",
        ),
        CheckConstraint(
            "action <> 'ENTER' OR direction = 'LONG'",
            name="ck_trade_signal_enter_direction",
        ),
        CheckConstraint(
            "action <> 'EXIT' OR direction = 'FLAT'",
            name="ck_trade_signal_exit_direction",
        ),
        Index(
            "idx_trade_signal_action_hour_desc",
            "action",
            desc("hour_ts_utc"),
        ),
        Index(
            "idx_trade_signal_account_hour_desc",
            "account_id",
            desc("hour_ts_utc"),
        ),
    )

    signal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    run_mode: Mapped[str] = mapped_column(run_mode_enum, nullable=False)
    account_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey(
            "account.account_id",
            name="fk_trade_signal_account",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    asset_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey(
            "asset.asset_id",
            name="fk_trade_signal_asset",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    hour_ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    horizon: Mapped[str] = mapped_column(horizon_enum, nullable=False)
    action: Mapped[str] = mapped_column(signal_action_enum, nullable=False)
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    expected_return: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    assumed_fee_rate: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    assumed_slippage_rate: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    net_edge: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    target_position_notional: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    position_size_fraction: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    risk_state_hour_ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decision_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
