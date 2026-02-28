"""Asset reference model definitions."""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Identity,
    Index,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base

logger = logging.getLogger(__name__)


class Asset(Base):
    """Tradable asset metadata and exchange precision settings."""

    __tablename__ = "asset"
    __table_args__ = (
        PrimaryKeyConstraint("asset_id", name="pk_asset"),
        UniqueConstraint("venue", "symbol", name="uq_asset_venue_symbol"),
        CheckConstraint("length(btrim(venue)) > 0", name="ck_asset_venue_not_blank"),
        CheckConstraint("length(btrim(symbol)) > 0", name="ck_asset_symbol_not_blank"),
        CheckConstraint("symbol = upper(symbol)", name="ck_asset_symbol_upper"),
        CheckConstraint("base_asset = upper(base_asset)", name="ck_asset_base_upper"),
        CheckConstraint("quote_asset = upper(quote_asset)", name="ck_asset_quote_upper"),
        CheckConstraint("tick_size > 0", name="ck_asset_tick_size_pos"),
        CheckConstraint("lot_size > 0", name="ck_asset_lot_size_pos"),
        CheckConstraint(
            "delisted_at_utc IS NULL OR delisted_at_utc > listed_at_utc",
            name="ck_asset_delisted_after_listed",
        ),
        Index("idx_asset_is_active", "is_active"),
    )

    asset_id: Mapped[int] = mapped_column(
        SmallInteger,
        Identity(always=True),
        primary_key=True,
    )
    venue: Mapped[str] = mapped_column(Text, nullable=False)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    base_asset: Mapped[str] = mapped_column(Text, nullable=False)
    quote_asset: Mapped[str] = mapped_column(Text, nullable=False)
    tick_size: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    lot_size: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("TRUE"),
    )
    listed_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    delisted_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
