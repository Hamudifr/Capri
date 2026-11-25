"""Small, dependency-free Capri execution ledger primitives."""

from .ledger import HashChainLedger, LedgerIntegrityError
from .health import HealthState, build_health_report
from .models import EvaluationRecord, EvidenceStage, EvaluatorType, Status
from .strategy import (
    StrategyEvaluation,
    StrategyEvaluationError,
    StrategyMetrics,
    StrategyObservation,
    evaluate_strategies,
    verify_strategy_evaluation,
)
from .strategy_promotion import (
    CohortPromotionResult,
    PromotionCohort,
    StrategyPromotionAssessment,
    StrategyPromotionError,
    assess_strategy_canary,
)
from .validation import RecordValidationError, contains_surrogate, validate_record

__all__ = [
    "EvaluationRecord", "EvidenceStage", "EvaluatorType", "Status",
    "RecordValidationError", "contains_surrogate", "validate_record", "HashChainLedger",
    "LedgerIntegrityError", "HealthState", "build_health_report",
    "StrategyEvaluation", "StrategyEvaluationError", "StrategyMetrics",
    "StrategyObservation", "evaluate_strategies", "verify_strategy_evaluation",
    "PromotionCohort", "CohortPromotionResult", "StrategyPromotionAssessment",
    "StrategyPromotionError", "assess_strategy_canary",
]
