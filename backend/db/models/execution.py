"""Execution, fills, lots, trades, and cash ledger model definitions."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    UniqueConstraint,
    BigInteger,
    desc,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base
from backend.db.enums import (
    order_side_enum,
    order_status_enum,
    order_type_enum,
    run_mode_enum,
)

logger = logging.getLogger(__name__)


class OrderRequest(Base):
    """Order requests emitted from validated trade signals."""

    __tablename__ = "order_request"
    __table_args__ = (
        PrimaryKeyConstraint("order_id", name="pk_order_request"),
        UniqueConstraint(
            "client_order_id",
            name="uq_order_request_client_order_id",
        ),
        UniqueConstraint(
            "order_id",
            "run_id",
            "run_mode",
            "account_id",
            "asset_id",
            name="uq_order_request_identity",
        ),
        ForeignKeyConstraint(
            ["run_id", "account_id", "run_mode", "origin_hour_ts_utc"],
            ["run_context.run_id", "run_context.account_id", "run_context.run_mode", "run_context.origin_hour_ts_utc"],
            name="fk_order_request_run_context_origin",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["signal_id", "cluster_membership_id"],
            ["trade_signal.signal_id", "trade_signal.cluster_membership_id"],
            name="fk_order_request_signal_cluster",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["signal_id", "risk_state_run_id"],
            ["trade_signal.signal_id", "trade_signal.risk_state_run_id"],
            name="fk_order_request_signal_riskrun",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "length(btrim(client_order_id)) > 0",
            name="ck_order_request_client_order_id_not_blank",
        ),
        CheckConstraint(
            "date_trunc('hour', hour_ts_utc) = hour_ts_utc",
            name="ck_order_request_hour_aligned",
        ),
        CheckConstraint(
            "request_ts_utc >= hour_ts_utc AND request_ts_utc < hour_ts_utc + interval '1 hour'",
            name="ck_order_request_request_in_hour",
        ),
        CheckConstraint("tif IN ('GTC', 'IOC', 'FOK')", name="ck_order_request_tif"),
        CheckConstraint(
            "(order_type = 'LIMIT' AND limit_price IS NOT NULL AND limit_price > 0) OR "
            "(order_type = 'MARKET' AND limit_price IS NULL)",
            name="ck_order_request_limit_price_rule",
        ),
        CheckConstraint("requested_qty > 0", name="ck_order_request_qty_pos"),
        CheckConstraint("requested_notional > 0", name="ck_order_request_notional_pos"),
        CheckConstraint(
            "pre_order_cash_available >= 0",
            name="ck_order_request_cash_nonneg",
        ),
        CheckConstraint(
            "side <> 'BUY' OR requested_notional <= pre_order_cash_available",
            name="ck_order_request_no_leverage_buy",
        ),
        CheckConstraint(
            "risk_check_passed = TRUE OR status = 'REJECTED'",
            name="ck_order_request_risk_gate",
        ),
        CheckConstraint(
            "date_trunc('hour', origin_hour_ts_utc) = origin_hour_ts_utc",
            name="ck_order_request_origin_hour_aligned",
        ),
        CheckConstraint(
            "request_ts_utc >= origin_hour_ts_utc",
            name="ck_order_request_request_after_origin",
        ),
        Index(
            "idx_order_request_account_request_ts_desc",
            "account_id",
            desc("request_ts_utc"),
        ),
        Index(
            "idx_order_request_status_request_ts_desc",
            "status",
            desc("request_ts_utc"),
        ),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    signal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "trade_signal.signal_id",
            name="fk_order_request_signal_identity",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    run_mode: Mapped[str] = mapped_column(run_mode_enum, nullable=False)
    account_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey(
            "account.account_id",
            name="fk_order_request_account",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    asset_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey(
            "asset.asset_id",
            name="fk_order_request_asset",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    client_order_id: Mapped[str] = mapped_column(Text, nullable=False)
    request_ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    hour_ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    side: Mapped[str] = mapped_column(order_side_enum, nullable=False)
    order_type: Mapped[str] = mapped_column(order_type_enum, nullable=False)
    tif: Mapped[str] = mapped_column(Text, nullable=False)
    limit_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    requested_qty: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    requested_notional: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    pre_order_cash_available: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    risk_check_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(order_status_enum, nullable=False)
    cost_profile_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey(
            "cost_profile.cost_profile_id",
            name="fk_order_request_cost_profile",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    origin_hour_ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    risk_state_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    cluster_membership_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    parent_signal_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    row_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)


class OrderFill(Base):
    """Append-only order execution fill records."""

    __tablename__ = "order_fill"
    __table_args__ = (
        PrimaryKeyConstraint("fill_id", name="pk_order_fill"),
        UniqueConstraint(
            "order_id",
            "exchange_trade_id",
            name="uq_order_fill_order_exchange_trade",
        ),
        UniqueConstraint(
            "fill_id",
            "run_id",
            "run_mode",
            "account_id",
            "asset_id",
            name="uq_order_fill_identity",
        ),
        ForeignKeyConstraint(
            ["order_id", "run_id", "run_mode", "account_id", "asset_id"],
            [
                "order_request.order_id",
                "order_request.run_id",
                "order_request.run_mode",
                "order_request.account_id",
                "order_request.asset_id",
            ],
            name="fk_order_fill_order_request_identity",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["run_id", "account_id", "run_mode", "origin_hour_ts_utc"],
            ["run_context.run_id", "run_context.account_id", "run_context.run_mode", "run_context.origin_hour_ts_utc"],
            name="fk_order_fill_run_context_origin",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "length(btrim(exchange_trade_id)) > 0",
            name="ck_order_fill_exchange_trade_id_not_blank",
        ),
        CheckConstraint(
            "date_trunc('hour', hour_ts_utc) = hour_ts_utc",
            name="ck_order_fill_hour_aligned",
        ),
        CheckConstraint(
            "hour_ts_utc = date_trunc('hour', fill_ts_utc)",
            name="ck_order_fill_bucket_match",
        ),
        CheckConstraint("fill_price > 0", name="ck_order_fill_price_pos"),
        CheckConstraint("fill_qty > 0", name="ck_order_fill_qty_pos"),
        CheckConstraint("fill_notional > 0", name="ck_order_fill_notional_pos"),
        CheckConstraint(
            "fill_notional = fill_price * fill_qty",
            name="ck_order_fill_notional_formula",
        ),
        CheckConstraint("fee_paid >= 0", name="ck_order_fill_fee_nonneg"),
        CheckConstraint(
            "fee_rate >= 0 AND fee_rate <= 1",
            name="ck_order_fill_fee_rate_range",
        ),
        CheckConstraint(
            "realized_slippage_rate >= 0",
            name="ck_order_fill_slippage_nonneg",
        ),
        CheckConstraint(
            "liquidity_flag IN ('MAKER', 'TAKER', 'UNKNOWN')",
            name="ck_order_fill_liquidity_flag",
        ),
        CheckConstraint(
            "date_trunc('hour', origin_hour_ts_utc) = origin_hour_ts_utc",
            name="ck_order_fill_origin_hour_aligned",
        ),
        CheckConstraint(
            "fill_ts_utc >= origin_hour_ts_utc",
            name="ck_order_fill_fill_after_origin",
        ),
        CheckConstraint(
            "fee_paid = fee_expected",
            name="ck_order_fill_fee_formula",
        ),
        CheckConstraint(
            "slippage_cost = fill_notional * realized_slippage_rate",
            name="ck_order_fill_slippage_formula",
        ),
        Index(
            "idx_order_fill_account_fill_ts_desc",
            "account_id",
            desc("fill_ts_utc"),
        ),
        Index(
            "idx_order_fill_asset_hour_desc",
            "asset_id",
            desc("hour_ts_utc"),
        ),
        Index("idx_order_fill_order_id", "order_id"),
    )

    fill_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    run_mode: Mapped[str] = mapped_column(run_mode_enum, nullable=False)
    account_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey(
            "account.account_id",
            name="fk_order_fill_account",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    asset_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey(
            "asset.asset_id",
            name="fk_order_fill_asset",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    exchange_trade_id: Mapped[str] = mapped_column(Text, nullable=False)
    fill_ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    hour_ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fill_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    fill_qty: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    fill_notional: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    fee_paid: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    fee_rate: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    realized_slippage_rate: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    origin_hour_ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fee_expected: Mapped[Decimal] = mapped_column(
        Numeric(38, 18),
        Computed("fill_notional * fee_rate", persisted=True),
        nullable=False,
    )
    slippage_cost: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    parent_order_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    row_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    liquidity_flag: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'UNKNOWN'"),
    )


class PositionLot(Base):
    """Open lot inventory with remaining quantity tracking."""

    __tablename__ = "position_lot"
    __table_args__ = (
        PrimaryKeyConstraint("lot_id", name="pk_position_lot"),
        UniqueConstraint("open_fill_id", name="uq_position_lot_open_fill"),
        UniqueConstraint(
            "lot_id",
            "run_id",
            "run_mode",
            "account_id",
            "asset_id",
            name="uq_position_lot_identity",
        ),
        ForeignKeyConstraint(
            ["open_fill_id", "run_id", "run_mode", "account_id", "asset_id"],
            [
                "order_fill.fill_id",
                "order_fill.run_id",
                "order_fill.run_mode",
                "order_fill.account_id",
                "order_fill.asset_id",
            ],
            name="fk_position_lot_order_fill_identity",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["run_id", "account_id", "run_mode", "origin_hour_ts_utc"],
            ["run_context.run_id", "run_context.account_id", "run_context.run_mode", "run_context.origin_hour_ts_utc"],
            name="fk_position_lot_run_context_origin",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "date_trunc('hour', hour_ts_utc) = hour_ts_utc",
            name="ck_position_lot_hour_aligned",
        ),
        CheckConstraint(
            "hour_ts_utc = date_trunc('hour', open_ts_utc)",
            name="ck_position_lot_bucket_match",
        ),
        CheckConstraint("open_price > 0", name="ck_position_lot_open_price_pos"),
        CheckConstraint("open_qty > 0", name="ck_position_lot_open_qty_pos"),
        CheckConstraint("open_notional > 0", name="ck_position_lot_open_notional_pos"),
        CheckConstraint(
            "open_notional = open_price * open_qty",
            name="ck_position_lot_notional_formula",
        ),
        CheckConstraint("open_fee >= 0", name="ck_position_lot_open_fee_nonneg"),
        CheckConstraint(
            "remaining_qty >= 0 AND remaining_qty <= open_qty",
            name="ck_position_lot_remaining_range",
        ),
        CheckConstraint(
            "date_trunc('hour', origin_hour_ts_utc) = origin_hour_ts_utc",
            name="ck_position_lot_origin_hour_aligned",
        ),
        CheckConstraint(
            "open_ts_utc >= origin_hour_ts_utc",
            name="ck_position_lot_open_after_origin",
        ),
        Index(
            "idx_position_lot_account_asset_open_ts_desc",
            "account_id",
            "asset_id",
            desc("open_ts_utc"),
        ),
        Index("idx_position_lot_remaining_qty", "remaining_qty"),
    )

    lot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    open_fill_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    run_mode: Mapped[str] = mapped_column(run_mode_enum, nullable=False)
    account_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey(
            "account.account_id",
            name="fk_position_lot_account",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    asset_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey(
            "asset.asset_id",
            name="fk_position_lot_asset",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    hour_ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open_ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    open_qty: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    open_notional: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    open_fee: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    remaining_qty: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    origin_hour_ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    parent_fill_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    row_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)


class ExecutedTrade(Base):
    """Append-only closed trade records with PnL accounting."""

    __tablename__ = "executed_trade"
    __table_args__ = (
        PrimaryKeyConstraint("trade_id", name="pk_executed_trade"),
        UniqueConstraint(
            "lot_id",
            "exit_ts_utc",
            "quantity",
            name="uq_executed_trade_lot_exit_qty",
        ),
        ForeignKeyConstraint(
            ["lot_id", "run_id", "run_mode", "account_id", "asset_id"],
            [
                "position_lot.lot_id",
                "position_lot.run_id",
                "position_lot.run_mode",
                "position_lot.account_id",
                "position_lot.asset_id",
            ],
            name="fk_executed_trade_lot_identity",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["run_id", "account_id", "run_mode", "origin_hour_ts_utc"],
            ["run_context.run_id", "run_context.account_id", "run_context.run_mode", "run_context.origin_hour_ts_utc"],
            name="fk_executed_trade_run_context_origin",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "date_trunc('hour', hour_ts_utc) = hour_ts_utc",
            name="ck_executed_trade_hour_aligned",
        ),
        CheckConstraint(
            "hour_ts_utc = date_trunc('hour', exit_ts_utc)",
            name="ck_executed_trade_bucket_match",
        ),
        CheckConstraint(
            "exit_ts_utc >= entry_ts_utc",
            name="ck_executed_trade_time_order",
        ),
        CheckConstraint(
            "entry_price > 0",
            name="ck_executed_trade_entry_price_pos",
        ),
        CheckConstraint("exit_price > 0", name="ck_executed_trade_exit_price_pos"),
        CheckConstraint("quantity > 0", name="ck_executed_trade_qty_pos"),
        CheckConstraint("total_fee >= 0", name="ck_executed_trade_fee_nonneg"),
        CheckConstraint(
            "total_slippage_cost >= 0",
            name="ck_executed_trade_slippage_nonneg",
        ),
        CheckConstraint(
            "holding_hours >= 0",
            name="ck_executed_trade_holding_nonneg",
        ),
        CheckConstraint(
            "net_pnl = gross_pnl - total_fee - total_slippage_cost",
            name="ck_executed_trade_net_pnl_formula",
        ),
        CheckConstraint(
            "date_trunc('hour', origin_hour_ts_utc) = origin_hour_ts_utc",
            name="ck_executed_trade_origin_hour_aligned",
        ),
        CheckConstraint(
            "exit_ts_utc >= origin_hour_ts_utc",
            name="ck_executed_trade_exit_after_origin",
        ),
        Index(
            "idx_executed_trade_account_exit_ts_desc",
            "account_id",
            desc("exit_ts_utc"),
        ),
        Index(
            "idx_executed_trade_asset_exit_ts_desc",
            "asset_id",
            desc("exit_ts_utc"),
        ),
        Index("idx_executed_trade_lot_id", "lot_id"),
    )

    trade_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    lot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    run_mode: Mapped[str] = mapped_column(run_mode_enum, nullable=False)
    account_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey(
            "account.account_id",
            name="fk_executed_trade_account",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    asset_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey(
            "asset.asset_id",
            name="fk_executed_trade_asset",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    hour_ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    exit_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    gross_pnl: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    net_pnl: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    total_fee: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    total_slippage_cost: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    holding_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    origin_hour_ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    parent_lot_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    row_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)


class CashLedger(Base):
    """Append-only account cash ledger events."""

    __tablename__ = "cash_ledger"
    __table_args__ = (
        PrimaryKeyConstraint("ledger_id", name="pk_cash_ledger"),
        UniqueConstraint(
            "account_id",
            "run_mode",
            "event_ts_utc",
            "ref_type",
            "ref_id",
            "event_type",
            name="uq_cash_ledger_idempotency",
        ),
        UniqueConstraint(
            "account_id",
            "run_mode",
            "ledger_seq",
            name="uq_cash_ledger_account_mode_seq",
        ),
        ForeignKeyConstraint(
            ["run_id", "account_id", "run_mode", "origin_hour_ts_utc"],
            ["run_context.run_id", "run_context.account_id", "run_context.run_mode", "run_context.origin_hour_ts_utc"],
            name="fk_cash_ledger_run_context_origin",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "date_trunc('hour', hour_ts_utc) = hour_ts_utc",
            name="ck_cash_ledger_hour_aligned",
        ),
        CheckConstraint(
            "hour_ts_utc = date_trunc('hour', event_ts_utc)",
            name="ck_cash_ledger_bucket_match",
        ),
        CheckConstraint(
            "length(btrim(event_type)) > 0",
            name="ck_cash_ledger_event_type_not_blank",
        ),
        CheckConstraint(
            "length(btrim(ref_type)) > 0",
            name="ck_cash_ledger_ref_type_not_blank",
        ),
        CheckConstraint(
            "balance_after >= 0",
            name="ck_cash_ledger_balance_nonneg",
        ),
        CheckConstraint(
            "date_trunc('hour', origin_hour_ts_utc) = origin_hour_ts_utc",
            name="ck_cash_ledger_origin_hour_aligned",
        ),
        CheckConstraint(
            "event_ts_utc >= origin_hour_ts_utc",
            name="ck_cash_ledger_event_after_origin",
        ),
        CheckConstraint(
            "balance_after = balance_before + delta_cash",
            name="ck_cash_ledger_balance_chain",
        ),
        CheckConstraint(
            "(ledger_seq = 1 AND prev_ledger_hash IS NULL) OR (ledger_seq > 1 AND prev_ledger_hash IS NOT NULL)",
            name="ck_cash_ledger_prev_hash_presence",
        ),
        Index(
            "idx_cash_ledger_account_event_ts_desc",
            "account_id",
            desc("event_ts_utc"),
        ),
        Index("idx_cash_ledger_hour_desc", desc("hour_ts_utc")),
        Index("idx_cash_ledger_run_id", "run_id"),
    )

    ledger_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        nullable=False,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    run_mode: Mapped[str] = mapped_column(run_mode_enum, nullable=False)
    account_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey(
            "account.account_id",
            name="fk_cash_ledger_account",
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    event_ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    hour_ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    ref_type: Mapped[str] = mapped_column(Text, nullable=False)
    ref_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    delta_cash: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    balance_after: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    origin_hour_ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ledger_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_before: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    prev_ledger_hash: Mapped[str | None] = mapped_column(CHAR(64))
    economic_event_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    ledger_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    row_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
