"""Risk state and risk event model definitions."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

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
    Text,
    desc,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base
from backend.db.enums import drawdown_tier_enum, run_mode_enum

logger = logging.getLogger(__name__)


class RiskHourlyState(Base):
    """Hourly account-level risk controls and drawdown enforcement state."""

    __tablename__ = "risk_hourly_state"
    __table_args__ = (
        PrimaryKeyConstraint(
            "run_mode",
            "account_id",
            "hour_ts_utc",
            name="pk_risk_hourly_state",
        ),
        ForeignKeyConstraint(
            ["run_mode", "account_id", "hour_ts_utc"],
            [
                "portfolio_hourly_state.run_mode",
                "portfolio_hourly_state.account_id",
                "portfolio_hourly_state.hour_ts_utc",
            ],
            name="fk_risk_hourly_state_portfolio",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_run_id", "run_mode", "hour_ts_utc"],
            ["run_context.run_id", "run_context.run_mode", "run_context.hour_ts_utc"],
            name="fk_risk_hourly_state_run_context",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "date_trunc('hour', hour_ts_utc) = hour_ts_utc",
            name="ck_risk_hourly_state_hour_aligned",
        ),
        CheckConstraint(
            "drawdown_pct >= 0 AND drawdown_pct <= 1",
            name="ck_risk_hourly_state_drawdown_range",
        ),
        CheckConstraint(
            "base_risk_fraction >= 0 AND base_risk_fraction <= 0.02",
            name="ck_risk_hourly_state_base_risk_range",
        ),
        CheckConstraint(
            "max_concurrent_positions >= 0 AND max_concurrent_positions <= 10",
            name="ck_risk_hourly_state_max_pos_range",
        ),
        CheckConstraint(
            "max_total_exposure_pct > 0 AND max_total_exposure_pct <= 0.20",
            name="ck_risk_hourly_state_total_exposure_cap",
        ),
        CheckConstraint(
            "max_cluster_exposure_pct > 0 AND max_cluster_exposure_pct <= 0.08",
            name="ck_risk_hourly_state_cluster_exposure_cap",
        ),
        CheckConstraint(
            "peak_portfolio_value >= portfolio_value",
            name="ck_risk_hourly_state_peak_ge_value",
        ),
        CheckConstraint(
            "(drawdown_pct < 0.10 AND drawdown_tier = 'NORMAL') OR "
            "(drawdown_pct >= 0.10 AND drawdown_pct < 0.15 AND drawdown_tier = 'DD10') OR "
            "(drawdown_pct >= 0.15 AND drawdown_pct < 0.20 AND drawdown_tier = 'DD15') OR "
            "(drawdown_pct >= 0.20 AND drawdown_tier = 'HALT20')",
            name="ck_risk_hourly_state_tier_mapping",
        ),
        CheckConstraint(
            "drawdown_pct < 0.10 OR base_risk_fraction <= 0.015",
            name="ck_risk_hourly_state_dd10_controls",
        ),
        CheckConstraint(
            "drawdown_pct < 0.15 OR (base_risk_fraction <= 0.01 AND max_concurrent_positions <= 5)",
            name="ck_risk_hourly_state_dd15_controls",
        ),
        CheckConstraint(
            "drawdown_pct < 0.20 OR ("
            "halt_new_entries = TRUE AND "
            "requires_manual_review = TRUE AND "
            "base_risk_fraction = 0 AND "
            "drawdown_tier = 'HALT20'"
            ")",
            name="ck_risk_hourly_state_dd20_halt",
        ),
        CheckConstraint(
            "kill_switch_active = FALSE OR length(btrim(coalesce(kill_switch_reason, ''))) > 0",
            name="ck_risk_hourly_state_kill_switch_reason",
        ),
        Index(
            "idx_risk_hourly_tier_hour_desc",
            "drawdown_tier",
            desc("hour_ts_utc"),
        ),
        Index(
            "idx_risk_hourly_halt_true_hour_desc",
            desc("hour_ts_utc"),
            postgresql_where=text("halt_new_entries = TRUE"),
        ),
        Index("idx_risk_hourly_source_run_id", "source_run_id"),
    )

    run_mode: Mapped[str] = mapped_column(run_mode_enum, primary_key=True)
    account_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    hour_ts_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        primary_key=True,
    )
    portfolio_value: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    peak_portfolio_value: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    drawdown_pct: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    drawdown_tier: Mapped[str] = mapped_column(drawdown_tier_enum, nullable=False)
    base_risk_fraction: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    max_concurrent_positions: Mapped[int] = mapped_column(Integer, nullable=False)
    max_total_exposure_pct: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    max_cluster_exposure_pct: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    halt_new_entries: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("FALSE"),
    )
    kill_switch_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("FALSE"),
    )
    kill_switch_reason: Mapped[str | None] = mapped_column(Text)
    requires_manual_review: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("FALSE"),
    )
    evaluated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    source_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    state_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)


class RiskEvent(Base):
    """Append-only emitted risk events for controls and incidents."""

    __tablename__ = "risk_event"
    __table_args__ = (
        PrimaryKeyConstraint("risk_event_id", name="pk_risk_event"),
        ForeignKeyConstraint(
            ["run_id", "run_mode", "hour_ts_utc"],
            ["run_context.run_id", "run_context.run_mode", "run_context.hour_ts_utc"],
            name="fk_risk_event_run_context",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["run_mode", "account_id", "related_state_hour_ts_utc"],
            ["risk_hourly_state.run_mode", "risk_hourly_state.account_id", "risk_hourly_state.hour_ts_utc"],
            name="fk_risk_event_risk_hourly_state",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "date_trunc('hour', hour_ts_utc) = hour_ts_utc",
            name="ck_risk_event_hour_aligned",
        ),
        CheckConstraint(
            "hour_ts_utc = date_trunc('hour', event_ts_utc)",
            name="ck_risk_event_bucket_match",
        ),
        CheckConstraint(
            "length(btrim(event_type)) > 0",
            name="ck_risk_event_event_type_not_blank",
        ),
        CheckConstraint(
            "length(btrim(reason_code)) > 0",
            name="ck_risk_event_reason_not_blank",
        ),
        CheckConstraint(
            "severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')",
            name="ck_risk_event_severity",
        ),
        CheckConstraint(
            "related_state_hour_ts_utc <= hour_ts_utc",
            name="ck_risk_event_related_state_not_future",
        ),
        Index(
            "idx_risk_event_type_event_ts_desc",
            "event_type",
            desc("event_ts_utc"),
        ),
        Index(
            "idx_risk_event_severity_event_ts_desc",
            "severity",
            desc("event_ts_utc"),
        ),
        Index(
            "idx_risk_event_account_event_ts_desc",
            "account_id",
            desc("event_ts_utc"),
        ),
    )

    risk_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    run_mode: Mapped[str] = mapped_column(run_mode_enum, nullable=False)
    account_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey(
            "account.account_id",
            name="fk_risk_event_account",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    event_ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    hour_ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    reason_code: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    related_state_hour_ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
