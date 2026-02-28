"""Model module imports for SQLAlchemy metadata registration."""

from __future__ import annotations

import logging

from backend.db.models.account import Account
from backend.db.models.asset import Asset
from backend.db.models.backtest import BacktestFoldResult, BacktestRun
from backend.db.models.cost_profile import CostProfile
from backend.db.models.execution import CashLedger, ExecutedTrade, OrderFill, OrderRequest, PositionLot
from backend.db.models.feature import FeatureDefinition, FeatureSnapshot
from backend.db.models.market_data import MarketOhlcvHourly, OrderBookSnapshot
from backend.db.models.model_outputs import MetaLearnerComponent, ModelPrediction, RegimeOutput
from backend.db.models.model_version import ModelTrainingWindow, ModelVersion
from backend.db.models.portfolio import PortfolioHourlyState, PositionHourlyState
from backend.db.models.risk import RiskEvent, RiskHourlyState
from backend.db.models.run_context import RunContext
from backend.db.models.signal import TradeSignal

logger = logging.getLogger(__name__)

__all__ = [
    "Account",
    "Asset",
    "BacktestFoldResult",
    "BacktestRun",
    "CashLedger",
    "CostProfile",
    "ExecutedTrade",
    "FeatureDefinition",
    "FeatureSnapshot",
    "MarketOhlcvHourly",
    "MetaLearnerComponent",
    "ModelPrediction",
    "ModelTrainingWindow",
    "ModelVersion",
    "OrderBookSnapshot",
    "OrderFill",
    "OrderRequest",
    "PortfolioHourlyState",
    "PositionHourlyState",
    "PositionLot",
    "RegimeOutput",
    "RiskEvent",
    "RiskHourlyState",
    "RunContext",
    "TradeSignal",
]
