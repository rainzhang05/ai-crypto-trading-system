"""Cost profile model definitions."""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CHAR,
    CheckConstraint,
    DateTime,
    Identity,
    Index,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    UniqueConstraint,
    desc,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base

logger = logging.getLogger(__name__)


class CostProfile(Base):
    """Venue fee and slippage profile configuration."""

    __tablename__ = "cost_profile"
    __table_args__ = (
        PrimaryKeyConstraint("cost_profile_id", name="pk_cost_profile"),
        UniqueConstraint(
            "venue",
            "effective_from_utc",
            name="uq_cost_profile_venue_effective_from",
        ),
        CheckConstraint("venue = upper(venue)", name="ck_cost_profile_venue_upper"),
        CheckConstraint(
            "length(btrim(venue)) > 0",
            name="ck_cost_profile_venue_not_blank",
        ),
        CheckConstraint(
            "fee_rate >= 0 AND fee_rate <= 1",
            name="ck_cost_profile_fee_rate_range",
        ),
        CheckConstraint(
            "length(btrim(slippage_model_name)) > 0",
            name="ck_cost_profile_slippage_model_not_blank",
        ),
        CheckConstraint(
            "effective_to_utc IS NULL OR effective_to_utc > effective_from_utc",
            name="ck_cost_profile_effective_window",
        ),
        CheckConstraint(
            "venue <> 'KRAKEN' OR fee_rate = 0.004000",
            name="ck_cost_profile_kraken_fee_fixed",
        ),
        Index(
            "idx_cost_profile_venue_effective_from_desc",
            "venue",
            desc("effective_from_utc"),
        ),
        Index(
            "uqix_cost_profile_one_active_per_venue",
            "venue",
            unique=True,
            postgresql_where=text("is_active = TRUE"),
        ),
    )

    cost_profile_id: Mapped[int] = mapped_column(
        SmallInteger,
        Identity(always=True),
        primary_key=True,
    )
    venue: Mapped[str] = mapped_column(Text, nullable=False)
    fee_rate: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    slippage_model_name: Mapped[str] = mapped_column(Text, nullable=False)
    slippage_param_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    effective_from_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    effective_to_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("TRUE"),
    )
