"""Market data model definitions."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    BigInteger,
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


class MarketOhlcvHourly(Base):
    """Append-only hourly OHLCV market candles."""

    __tablename__ = "market_ohlcv_hourly"
    __table_args__ = (
        PrimaryKeyConstraint(
            "asset_id",
            "hour_ts_utc",
            "source_venue",
            name="pk_market_ohlcv_hourly",
        ),
        CheckConstraint(
            "date_trunc('hour', hour_ts_utc) = hour_ts_utc",
            name="ck_market_ohlcv_hourly_hour_aligned",
        ),
        CheckConstraint("open_price > 0", name="ck_market_ohlcv_hourly_open_pos"),
        CheckConstraint("high_price > 0", name="ck_market_ohlcv_hourly_high_pos"),
        CheckConstraint("low_price > 0", name="ck_market_ohlcv_hourly_low_pos"),
        CheckConstraint("close_price > 0", name="ck_market_ohlcv_hourly_close_pos"),
        CheckConstraint("high_price >= low_price", name="ck_market_ohlcv_hourly_high_low"),
        CheckConstraint(
            "high_price >= greatest(open_price, close_price, low_price)",
            name="ck_market_ohlcv_hourly_high_bounds",
        ),
        CheckConstraint(
            "low_price <= least(open_price, close_price, high_price)",
            name="ck_market_ohlcv_hourly_low_bounds",
        ),
        CheckConstraint(
            "volume_base >= 0",
            name="ck_market_ohlcv_hourly_volume_base_nonneg",
        ),
        CheckConstraint(
            "volume_quote >= 0",
            name="ck_market_ohlcv_hourly_volume_quote_nonneg",
        ),
        CheckConstraint(
            "trade_count >= 0",
            name="ck_market_ohlcv_hourly_trade_count_nonneg",
        ),
        Index("idx_market_ohlcv_hour_desc", desc("hour_ts_utc")),
    )

    asset_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey(
            "asset.asset_id",
            name="fk_market_ohlcv_hourly_asset",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    hour_ts_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        primary_key=True,
    )
    open_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    high_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    low_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    close_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    volume_base: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    volume_quote: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    trade_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_venue: Mapped[str] = mapped_column(Text, nullable=False, primary_key=True)
    ingest_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "run_context.run_id",
            name="fk_market_ohlcv_hourly_run_context",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )


class OrderBookSnapshot(Base):
    """Append-only order book top-of-book snapshots."""

    __tablename__ = "order_book_snapshot"
    __table_args__ = (
        PrimaryKeyConstraint(
            "asset_id",
            "snapshot_ts_utc",
            "source_venue",
            name="pk_order_book_snapshot",
        ),
        CheckConstraint(
            "date_trunc('hour', hour_ts_utc) = hour_ts_utc",
            name="ck_order_book_snapshot_hour_aligned",
        ),
        CheckConstraint(
            "hour_ts_utc = date_trunc('hour', snapshot_ts_utc)",
            name="ck_order_book_snapshot_bucket_match",
        ),
        CheckConstraint("best_bid_price > 0", name="ck_order_book_snapshot_bid_pos"),
        CheckConstraint("best_ask_price > 0", name="ck_order_book_snapshot_ask_pos"),
        CheckConstraint(
            "best_ask_price >= best_bid_price",
            name="ck_order_book_snapshot_ask_ge_bid",
        ),
        CheckConstraint(
            "best_bid_size >= 0",
            name="ck_order_book_snapshot_bid_size_nonneg",
        ),
        CheckConstraint(
            "best_ask_size >= 0",
            name="ck_order_book_snapshot_ask_size_nonneg",
        ),
        Index(
            "idx_order_book_asset_hour_desc",
            "asset_id",
            desc("hour_ts_utc"),
        ),
        Index("idx_order_book_hour_desc", desc("hour_ts_utc")),
    )

    asset_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey(
            "asset.asset_id",
            name="fk_order_book_snapshot_asset",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    snapshot_ts_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        primary_key=True,
    )
    hour_ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    best_bid_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    best_ask_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    best_bid_size: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    best_ask_size: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    spread_abs: Mapped[Decimal] = mapped_column(
        Numeric(38, 18),
        Computed("best_ask_price - best_bid_price", persisted=True),
        nullable=False,
    )
    spread_bps: Mapped[Decimal] = mapped_column(
        Numeric(12, 8),
        Computed(
            "((best_ask_price - best_bid_price) / NULLIF(best_bid_price, 0)) * 10000::numeric",
            persisted=True,
        ),
        nullable=False,
    )
    source_venue: Mapped[str] = mapped_column(Text, nullable=False, primary_key=True)
    ingest_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "run_context.run_id",
            name="fk_order_book_snapshot_run_context",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
