"""Account reference model definitions."""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Identity,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base

logger = logging.getLogger(__name__)


class Account(Base):
    """Trading account registry."""

    __tablename__ = "account"
    __table_args__ = (
        PrimaryKeyConstraint("account_id", name="pk_account"),
        UniqueConstraint("account_code", name="uq_account_code"),
        CheckConstraint(
            "length(btrim(account_code)) > 0",
            name="ck_account_code_not_blank",
        ),
        CheckConstraint(
            "base_currency = upper(base_currency)",
            name="ck_account_base_currency_upper",
        ),
    )

    account_id: Mapped[int] = mapped_column(
        SmallInteger,
        Identity(always=True),
        primary_key=True,
    )
    account_code: Mapped[str] = mapped_column(Text, nullable=False)
    base_currency: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("TRUE"),
    )
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
