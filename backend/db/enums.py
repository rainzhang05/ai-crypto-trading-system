"""PostgreSQL native enum contracts for the trading database schema."""

from __future__ import annotations

import enum
import logging

from sqlalchemy.dialects.postgresql import ENUM as PGEnum

logger = logging.getLogger(__name__)


class RunMode(str, enum.Enum):
    """Execution environment for a run."""

    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    LIVE = "LIVE"


class Horizon(str, enum.Enum):
    """Prediction and signal horizon."""

    H1 = "H1"
    H4 = "H4"
    H24 = "H24"


class ModelRole(str, enum.Enum):
    """Role of a model in the ensemble."""

    BASE_TREE = "BASE_TREE"
    BASE_DEEP = "BASE_DEEP"
    REGIME = "REGIME"
    META = "META"


class SignalAction(str, enum.Enum):
    """Trading signal action."""

    ENTER = "ENTER"
    EXIT = "EXIT"
    HOLD = "HOLD"


class OrderSide(str, enum.Enum):
    """Order side."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, enum.Enum):
    """Order type."""

    LIMIT = "LIMIT"
    MARKET = "MARKET"


class OrderStatus(str, enum.Enum):
    """Order lifecycle status."""

    NEW = "NEW"
    ACK = "ACK"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class DrawdownTier(str, enum.Enum):
    """Risk drawdown tier."""

    NORMAL = "NORMAL"
    DD10 = "DD10"
    DD15 = "DD15"
    HALT20 = "HALT20"


run_mode_enum = PGEnum(RunMode, name="run_mode_enum")
horizon_enum = PGEnum(Horizon, name="horizon_enum")
model_role_enum = PGEnum(ModelRole, name="model_role_enum")
signal_action_enum = PGEnum(SignalAction, name="signal_action_enum")
order_side_enum = PGEnum(OrderSide, name="order_side_enum")
order_type_enum = PGEnum(OrderType, name="order_type_enum")
order_status_enum = PGEnum(OrderStatus, name="order_status_enum")
drawdown_tier_enum = PGEnum(DrawdownTier, name="drawdown_tier_enum")
