"""Deterministic promotion gate logic and persistence for Phase 6."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from execution.decision_engine import stable_hash
from execution.phase6.common import Phase6Database, deterministic_uuid


@dataclass(frozen=True)
class PromotionThresholds:
    """Absolute promotion thresholds."""

    min_acc_h1: Decimal
    min_acc_h4: Decimal
    min_acc_h24: Decimal
    max_brier: Decimal
    max_ece: Decimal
    min_sharpe: Decimal
    max_drawdown: Decimal
    min_net_return: Decimal


@dataclass(frozen=True)
class PromotionMetrics:
    """Candidate metrics used for promotion decision."""

    acc_h1: Decimal
    acc_h4: Decimal
    acc_h24: Decimal
    brier: Decimal
    ece: Decimal
    sharpe: Decimal
    max_drawdown: Decimal
    net_return: Decimal


@dataclass(frozen=True)
class PromotionDecision:
    """Promotion decision payload."""

    approved: bool
    reason_code: str


DEFAULT_THRESHOLDS = PromotionThresholds(
    min_acc_h1=Decimal("0.53"),
    min_acc_h4=Decimal("0.54"),
    min_acc_h24=Decimal("0.56"),
    max_brier=Decimal("0.23"),
    max_ece=Decimal("0.04"),
    min_sharpe=Decimal("0.60"),
    max_drawdown=Decimal("0.18"),
    min_net_return=Decimal("0.0000000001"),
)



def evaluate_promotion(metrics: PromotionMetrics, thresholds: PromotionThresholds = DEFAULT_THRESHOLDS) -> PromotionDecision:
    """Evaluate deterministic promotion gates."""
    if metrics.acc_h1 < thresholds.min_acc_h1:
        return PromotionDecision(False, "ACC_H1_BELOW_THRESHOLD")
    if metrics.acc_h4 < thresholds.min_acc_h4:
        return PromotionDecision(False, "ACC_H4_BELOW_THRESHOLD")
    if metrics.acc_h24 < thresholds.min_acc_h24:
        return PromotionDecision(False, "ACC_H24_BELOW_THRESHOLD")
    if metrics.brier > thresholds.max_brier:
        return PromotionDecision(False, "BRIER_ABOVE_THRESHOLD")
    if metrics.ece > thresholds.max_ece:
        return PromotionDecision(False, "ECE_ABOVE_THRESHOLD")
    if metrics.sharpe < thresholds.min_sharpe:
        return PromotionDecision(False, "SHARPE_BELOW_THRESHOLD")
    if metrics.max_drawdown > thresholds.max_drawdown:
        return PromotionDecision(False, "DRAWDOWN_ABOVE_THRESHOLD")
    if metrics.net_return <= thresholds.min_net_return:
        return PromotionDecision(False, "NET_RETURN_NOT_POSITIVE")
    return PromotionDecision(True, "APPROVED")


def persist_promotion_decision(
    db: Phase6Database,
    *,
    training_cycle_id: str,
    candidate_model_set_hash: str,
    decision: PromotionDecision,
    metrics: PromotionMetrics,
) -> str:
    """Persist promotion decision and return decision id."""
    decision_id = str(deterministic_uuid("phase6_promotion_decision", training_cycle_id, candidate_model_set_hash, decision.reason_code))
    db.execute(
        """
        INSERT INTO promotion_decision (
            promotion_decision_id, training_cycle_id, candidate_model_set_hash,
            approved, reason_code, metrics_hash,
            decided_at_utc, row_hash
        ) VALUES (
            :promotion_decision_id, :training_cycle_id, :candidate_model_set_hash,
            :approved, :reason_code, :metrics_hash,
            :decided_at_utc, :row_hash
        )
        """,
        {
            "promotion_decision_id": decision_id,
            "training_cycle_id": training_cycle_id,
            "candidate_model_set_hash": candidate_model_set_hash,
            "approved": decision.approved,
            "reason_code": decision.reason_code,
            "metrics_hash": stable_hash(
                (
                    "promotion_metrics",
                    str(metrics.acc_h1),
                    str(metrics.acc_h4),
                    str(metrics.acc_h24),
                    str(metrics.brier),
                    str(metrics.ece),
                    str(metrics.sharpe),
                    str(metrics.max_drawdown),
                    str(metrics.net_return),
                )
            ),
            "decided_at_utc": datetime.now(tz=timezone.utc),
            "row_hash": stable_hash(("promotion_decision", decision_id, int(decision.approved), decision.reason_code)),
        },
    )
    return decision_id
