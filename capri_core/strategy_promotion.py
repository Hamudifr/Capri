"""Offline, fail-closed eligibility assessment for bounded strategy canaries.

This module evaluates already-recorded matched evidence. It does not collect
evidence, authenticate its origin, issue grants, activate strategies, or route
live tasks. A trusted host must enforce the returned assessment and all owner
policy gates before any transition.
"""
from __future__ import annotations

import hashlib
import random
from collections import Counter
from dataclasses import dataclass
from statistics import fmean
from typing import Iterable, Literal

from .strategy import StrategyEvaluationError, StrategyObservation, evaluate_strategies


_POLICY_VERSION = "capri.strategy-promotion.v1"
_ALLOWED_TASK_FAMILIES = frozenset({
    "coding",
    "formatting",
    "general_qa",
    "research",
    "retrieval",
    "summarization",
    "writing",
})
_ALLOWED_STRATEGY_CLASSES = frozenset({
    "formatting",
    "planning",
    "reasoning",
    "retrieval",
    "tool_routing",
})
_PRIMARY_METRICS = frozenset({
    "tool_calls",
    "context_tokens",
    "estimated_cost_units",
    "latency_ms",
    "verified_success_rate",
    "safety_violations",
})
_MIN_COHORTS = 2
_MAX_COHORTS = 4
_MAX_OBSERVATIONS_PER_COHORT = 20_000
_MIN_PAIRS = 100
_MIN_SCENARIOS = 5
_MIN_PAIRS_PER_SCENARIO = 20
_BOOTSTRAP_RESAMPLES = 5_000
_CONFIDENCE_LEVEL = 0.95


class StrategyPromotionError(ValueError):
    """Raised when a promotion assessment request is malformed."""


@dataclass(frozen=True, slots=True)
class PromotionCohort:
    """One independently collected, already-verified cohort of paired records."""

    cohort_id: str
    observations: tuple[StrategyObservation, ...]


@dataclass(frozen=True, slots=True)
class CohortPromotionResult:
    cohort_id: str
    matched_pairs: int
    scenario_count: int
    primary_metric: str
    mean_improvement: float | None
    lower_95_ci: float | None
    upper_95_ci: float | None
    blocked_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StrategyPromotionAssessment:
    policy_version: str
    strategy_class: str
    task_family: str
    baseline_id: str
    candidate_id: str
    baseline_version: str | None
    candidate_version: str | None
    primary_metric: str
    cohorts: tuple[CohortPromotionResult, ...]
    eligible_for_canary: bool
    blocked_reasons: tuple[str, ...]
    interpretation: str = (
        "Offline eligibility assessment only. This is not an activation grant, "
        "evidence-authentication result, causal proof, or live canary."
    )


def _require_identifier(value: object, label: str) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > 128:
        raise StrategyPromotionError(f"{label} must be a normalized non-empty string of at most 128 characters")
    if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise StrategyPromotionError(f"{label} must contain Unicode scalar values")
    return value


def _improvement_deltas(
    baseline: dict[str, StrategyObservation],
    candidate: dict[str, StrategyObservation],
    metric: str,
) -> list[tuple[str, float]]:
    values: list[tuple[str, float]] = []
    for task_id in sorted(baseline):
        left = baseline[task_id]
        right = candidate[task_id]
        if metric in {"tool_calls", "context_tokens", "estimated_cost_units", "latency_ms"}:
            delta = float(getattr(left, metric) - getattr(right, metric))
        elif metric == "verified_success_rate":
            delta = float(right.outcome == "verified_success") - float(
                left.outcome == "verified_success"
            )
        else:
            delta = float(left.safety_violation) - float(right.safety_violation)
        values.append((left.scenario, delta))
    return values


def _percentile(sorted_values: list[float], probability: float) -> float:
    if not sorted_values:
        raise StrategyPromotionError("bootstrap sample cannot be empty")
    position = (len(sorted_values) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = position - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * fraction


def _paired_bootstrap_interval(
    deltas: list[tuple[str, float]],
    *,
    cohort_index: int,
    metric: str,
) -> tuple[float, float, float]:
    grouped: dict[str, list[float]] = {}
    for scenario, delta in deltas:
        grouped.setdefault(scenario, []).append(delta)
    scenario_names = sorted(grouped)
    observed = [value for _, value in deltas]
    mean_improvement = fmean(observed)

    seed_material = f"{_POLICY_VERSION}:{cohort_index}:{metric}:paired-stratified".encode("utf-8")
    seed = int.from_bytes(hashlib.sha256(seed_material).digest()[:8], "big")
    rng = random.Random(seed)
    estimates: list[float] = []
    for _ in range(_BOOTSTRAP_RESAMPLES):
        sample: list[float] = []
        for scenario in scenario_names:
            values = grouped[scenario]
            sample.extend(values[rng.randrange(len(values))] for _ in range(len(values)))
        estimates.append(fmean(sample))
    estimates.sort()
    alpha = 1.0 - _CONFIDENCE_LEVEL
    return (
        mean_improvement,
        _percentile(estimates, alpha / 2),
        _percentile(estimates, 1.0 - alpha / 2),
    )


def assess_strategy_canary(
    *,
    strategy_class: str,
    task_family: str,
    baseline_id: str,
    candidate_id: str,
    primary_metric: str,
    cohorts: Iterable[PromotionCohort],
) -> StrategyPromotionAssessment:
    """Assess two or more independent cohorts against the fixed canary policy.

    Each cohort must contain >=100 exactly matched pairs, >=5 scenarios, and
    >=20 pairs in every represented scenario. All per-task success, safety,
    and resource non-regression gates are inherited from evaluate_strategies.
    The declared primary metric must have a positive lower bound on a
    stratified paired-bootstrap 95% percentile interval in every cohort.

    The function returns eligibility only. It never grants authority or
    activates a strategy. Cohort provenance must be authenticated by the host.
    """
    strategy_class = _require_identifier(strategy_class, "strategy_class")
    task_family = _require_identifier(task_family, "task_family")
    primary_metric = _require_identifier(primary_metric, "primary_metric")
    baseline_id = _require_identifier(baseline_id, "baseline_id")
    candidate_id = _require_identifier(candidate_id, "candidate_id")
    if baseline_id == candidate_id:
        raise StrategyPromotionError("baseline and candidate must differ")
    if strategy_class not in _ALLOWED_STRATEGY_CLASSES:
        raise StrategyPromotionError("strategy_class is not allow-listed for autonomous canaries")
    if task_family not in _ALLOWED_TASK_FAMILIES:
        raise StrategyPromotionError("task_family is not allow-listed for autonomous canaries")
    if primary_metric not in _PRIMARY_METRICS:
        raise StrategyPromotionError("primary_metric is not supported")
    if isinstance(cohorts, (str, bytes)):
        raise StrategyPromotionError("cohorts must be an iterable of PromotionCohort records")
    try:
        cohort_iterator = iter(cohorts)
    except TypeError:
        raise StrategyPromotionError("cohorts must be iterable") from None
    collected_cohorts: list[PromotionCohort] = []
    for cohort in cohort_iterator:
        if len(collected_cohorts) >= _MAX_COHORTS:
            raise StrategyPromotionError("cohort count exceeds the bounded maximum of 4")
        collected_cohorts.append(cohort)
    cohort_list = tuple(collected_cohorts)
    if any(type(item) is not PromotionCohort for item in cohort_list):
        raise StrategyPromotionError("cohorts must contain PromotionCohort records")
    for item in cohort_list:
        _require_identifier(item.cohort_id, "cohort_id")
    cohort_list = tuple(sorted(cohort_list, key=lambda item: item.cohort_id))

    blocked: list[str] = []
    if len(cohort_list) < _MIN_COHORTS:
        blocked.append("insufficient_independent_cohorts")

    cohort_ids: set[str] = set()
    seen_tasks: set[str] = set()
    seen_evidence: set[str] = set()
    results: list[CohortPromotionResult] = []
    versions: set[tuple[str, str]] = set()

    for index, cohort in enumerate(cohort_list):
        cohort_id = _require_identifier(cohort.cohort_id, "cohort_id")
        if cohort_id in cohort_ids:
            blocked.append("duplicate_cohort_id")
        cohort_ids.add(cohort_id)
        if type(cohort.observations) is not tuple:
            raise StrategyPromotionError("cohort observations must be an immutable tuple")
        if len(cohort.observations) > _MAX_OBSERVATIONS_PER_COHORT:
            raise StrategyPromotionError("cohort observations exceed the bounded maximum of 20000")

        # Validate every record before hashing caller-controlled task/evidence
        # fields. StrategyObservation is a public dataclass and can be directly
        # constructed with malformed, unhashable values despite its annotations.
        try:
            evaluation = evaluate_strategies(
                baseline_id, candidate_id, cohort.observations, min_pairs=_MIN_PAIRS,
            )
        except StrategyEvaluationError:
            results.append(CohortPromotionResult(
                cohort_id, 0, 0, primary_metric, None, None, None,
                ("invalid_or_inconsistent_cohort",),
            ))
            blocked.append("invalid_or_inconsistent_cohort")
            continue

        local_tasks = {item.task_id for item in cohort.observations}
        local_evidence = {item.evidence_ref for item in cohort.observations}
        if seen_tasks & local_tasks:
            blocked.append("overlapping_task_ids_between_cohorts")
        if len(local_evidence) != len(cohort.observations):
            blocked.append("duplicate_evidence_refs_within_cohort")
        if seen_evidence & local_evidence:
            blocked.append("overlapping_evidence_refs_between_cohorts")
        seen_tasks.update(local_tasks)
        seen_evidence.update(local_evidence)

        by_strategy = {
            baseline_id: {
                item.task_id: item for item in cohort.observations
                if item.strategy_id == baseline_id
            },
            candidate_id: {
                item.task_id: item for item in cohort.observations
                if item.strategy_id == candidate_id
            },
        }
        common = set(by_strategy[baseline_id]) & set(by_strategy[candidate_id])
        scenario_counts = Counter(
            by_strategy[baseline_id][task_id].scenario for task_id in common
        )
        cohort_reasons = list(evaluation.blocked_reasons)
        if evaluation.matched_pairs < _MIN_PAIRS:
            cohort_reasons.append("insufficient_matched_pairs")
        if len(scenario_counts) < _MIN_SCENARIOS:
            cohort_reasons.append("insufficient_scenario_coverage")
        if any(count < _MIN_PAIRS_PER_SCENARIO for count in scenario_counts.values()):
            cohort_reasons.append("insufficient_pairs_per_scenario")
        if evaluation.baseline_version == "unversioned" or evaluation.candidate_version == "unversioned":
            cohort_reasons.append("unversioned_strategy")
        versions.add((evaluation.baseline_version, evaluation.candidate_version))

        interval: tuple[float, float, float] | None = None
        if not cohort_reasons:
            deltas = _improvement_deltas(
                by_strategy[baseline_id], by_strategy[candidate_id], primary_metric,
            )
            interval = _paired_bootstrap_interval(
                deltas, cohort_index=index, metric=primary_metric,
            )
            if interval[1] <= 0.0:
                cohort_reasons.append("primary_metric_not_confidently_improved")

        cohort_reasons = list(dict.fromkeys(cohort_reasons))
        results.append(CohortPromotionResult(
            cohort_id=cohort_id,
            matched_pairs=evaluation.matched_pairs,
            scenario_count=len(scenario_counts),
            primary_metric=primary_metric,
            mean_improvement=interval[0] if interval else None,
            lower_95_ci=interval[1] if interval else None,
            upper_95_ci=interval[2] if interval else None,
            blocked_reasons=tuple(cohort_reasons),
        ))
        blocked.extend(cohort_reasons)

    if len(versions) > 1:
        blocked.append("strategy_versions_differ_between_cohorts")
    if len(versions) == 1:
        baseline_version, candidate_version = next(iter(versions))
    else:
        baseline_version = candidate_version = None

    blocked_reasons = tuple(dict.fromkeys(blocked))
    return StrategyPromotionAssessment(
        policy_version=_POLICY_VERSION,
        strategy_class=strategy_class,
        task_family=task_family,
        baseline_id=baseline_id,
        candidate_id=candidate_id,
        baseline_version=baseline_version,
        candidate_version=candidate_version,
        primary_metric=primary_metric,
        cohorts=tuple(results),
        eligible_for_canary=not blocked_reasons and len(results) >= _MIN_COHORTS,
        blocked_reasons=blocked_reasons,
    )
