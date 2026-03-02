"""Deterministic Phase 6B backtest orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Sequence
from uuid import UUID

from execution.decision_engine import stable_hash
from execution.phase6.common import Phase6Database, deterministic_uuid
from execution.phase6.walk_forward import FoldWindow


@dataclass(frozen=True)
class BacktestFoldMetric:
    """Minimal deterministic fold metric set."""

    fold_index: int
    trades_count: int
    sharpe: Decimal
    max_drawdown_pct: Decimal
    net_return_pct: Decimal
    win_rate: Decimal


@dataclass(frozen=True)
class BacktestRunResult:
    """Backtest run summary."""

    backtest_run_id: UUID
    fold_metrics: tuple[BacktestFoldMetric, ...]



def _simulate_fold_metric(fold: FoldWindow, labeled_frame: object) -> BacktestFoldMetric:
    valid = labeled_frame[(labeled_frame["trade_ts_utc"] >= fold.valid_start_utc) & (labeled_frame["trade_ts_utc"] < fold.valid_end_utc)]
    if valid.empty:
        return BacktestFoldMetric(
            fold_index=fold.fold_index,
            trades_count=0,
            sharpe=Decimal("0"),
            max_drawdown_pct=Decimal("0"),
            net_return_pct=Decimal("0"),
            win_rate=Decimal("0"),
        )

    returns = valid["label_ret_H1"].astype(float)
    mean = float(returns.mean())
    std = float(returns.std())
    sharpe = Decimal(str(0.0 if std == 0 else mean / std))
    win_rate = Decimal(str(float((returns > 0).mean())))
    net_return = Decimal(str(float(returns.sum())))
    max_drawdown = Decimal(str(float(min(0.0, returns.min())) * -1.0))

    return BacktestFoldMetric(
        fold_index=fold.fold_index,
        trades_count=int(len(valid)),
        sharpe=sharpe,
        max_drawdown_pct=max_drawdown,
        net_return_pct=net_return,
        win_rate=win_rate,
    )


def run_phase6b_backtest(
    *,
    db: Phase6Database,
    account_id: int,
    cost_profile_id: int,
    initial_capital: Decimal,
    strategy_code_sha: str,
    config_hash: str,
    universe_hash: str,
    folds: Sequence[FoldWindow],
    labeled_frame: object,
    random_seed: int,
) -> BacktestRunResult:
    """Persist deterministic backtest run + fold results."""
    backtest_run_id = deterministic_uuid("phase6_backtest_run", account_id, config_hash, universe_hash, len(folds), random_seed)
    started_at = datetime.now(tz=timezone.utc)

    db.execute(
        """
        INSERT INTO backtest_run (
            backtest_run_id, account_id, started_at_utc, completed_at_utc,
            status, strategy_code_sha, config_hash, universe_hash,
            initial_capital, cost_profile_id, random_seed, row_hash
        ) VALUES (
            :backtest_run_id, :account_id, :started_at_utc, :completed_at_utc,
            'COMPLETED', :strategy_code_sha, :config_hash, :universe_hash,
            :initial_capital, :cost_profile_id, :random_seed, :row_hash
        )
        """,
        {
            "backtest_run_id": str(backtest_run_id),
            "account_id": account_id,
            "started_at_utc": started_at,
            "completed_at_utc": datetime.now(tz=timezone.utc),
            "strategy_code_sha": strategy_code_sha,
            "config_hash": config_hash,
            "universe_hash": universe_hash,
            "initial_capital": initial_capital,
            "cost_profile_id": cost_profile_id,
            "random_seed": random_seed,
            "row_hash": stable_hash(("backtest_run", str(backtest_run_id), account_id, config_hash, universe_hash)),
        },
    )

    metrics: list[BacktestFoldMetric] = []
    for fold in folds:
        metric = _simulate_fold_metric(fold, labeled_frame)
        metrics.append(metric)
        db.execute(
            """
            INSERT INTO backtest_fold_result (
                backtest_run_id, fold_index,
                train_start_utc, train_end_utc,
                valid_start_utc, valid_end_utc,
                trades_count, sharpe, max_drawdown_pct,
                net_return_pct, win_rate, row_hash
            ) VALUES (
                :backtest_run_id, :fold_index,
                :train_start_utc, :train_end_utc,
                :valid_start_utc, :valid_end_utc,
                :trades_count, :sharpe, :max_drawdown_pct,
                :net_return_pct, :win_rate, :row_hash
            )
            """,
            {
                "backtest_run_id": str(backtest_run_id),
                "fold_index": fold.fold_index,
                "train_start_utc": fold.train_start_utc,
                "train_end_utc": fold.train_end_utc,
                "valid_start_utc": fold.valid_start_utc,
                "valid_end_utc": fold.valid_end_utc,
                "trades_count": metric.trades_count,
                "sharpe": metric.sharpe,
                "max_drawdown_pct": metric.max_drawdown_pct,
                "net_return_pct": metric.net_return_pct,
                "win_rate": metric.win_rate,
                "row_hash": stable_hash(("backtest_fold", str(backtest_run_id), fold.fold_index, fold.fold_hash, metric.trades_count)),
            },
        )

    return BacktestRunResult(backtest_run_id=backtest_run_id, fold_metrics=tuple(metrics))
