"""Deterministic, offline comparison of candidate strategies against a baseline.

This module evaluates recorded outcomes only. It never executes a strategy, grants
permissions, changes active configuration, or trains/modifies a model.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from statistics import fmean
from typing import Iterable, Literal


Outcome = Literal["verified_success", "verified_failure", "unverified"]
_ALLOWED_OUTCOMES = frozenset({"verified_success", "verified_failure", "unverified"})
_MAX_OBSERVATIONS = 20_000
_MAX_TEXT = 256


class StrategyEvaluationError(ValueError):
    """Raised when strategy comparison evidence is malformed or unsafe."""


@dataclass(frozen=True, slots=True)
class StrategyObservation:
    """One evidence-backed strategy execution on a task in a named cohort."""

    task_id: str
    scenario: str
    strategy_id: str
    outcome: Outcome
    evidence_ref: str
    strategy_version: str = "unversioned"
    safety_violation: bool = False
    tool_calls: int = 0
    context_tokens: int = 0
    estimated_cost_units: int = 0
    latency_ms: int = 0


@dataclass(frozen=True, slots=True)
class StrategyMetrics:
    sample_count: int
    verified_success_rate: float
    safety_violations: int
    mean_tool_calls: float
    mean_context_tokens: float
    mean_estimated_cost_units: float
    mean_latency_ms: float


@dataclass(frozen=True, slots=True)
class StrategyEvaluation:
    """A descriptive comparison; eligible means only eligible for manual review."""

    baseline_id: str
    candidate_id: str
    baseline_version: str
    candidate_version: str
    cohort_sha256: str
    matched_pairs: int
    baseline_unmatched: int
    candidate_unmatched: int
    baseline: StrategyMetrics
    candidate: StrategyMetrics
    improved_dimensions: tuple[str, ...]
    blocked_reasons: tuple[str, ...]
    eligible_for_manual_review: bool
    interpretation: str = (
        "Descriptive evidence from this matched cohort only; not a causal proof, "
        "statistical significance claim, live activation, or independent review."
    )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _require_text(value: object, label: str) -> str:
    if type(value) is not str or not value.strip() or len(value) > _MAX_TEXT:
        raise StrategyEvaluationError(f"{label} must be a non-empty string of at most {_MAX_TEXT} characters")
    if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise StrategyEvaluationError(f"{label} must contain Unicode scalar values")
    return value


def _validate_observation(item: object) -> StrategyObservation:
    if type(item) is not StrategyObservation:
        raise StrategyEvaluationError("observations must contain StrategyObservation records")
    _require_text(item.task_id, "task_id")
    _require_text(item.scenario, "scenario")
    _require_text(item.strategy_id, "strategy_id")
    _require_text(item.evidence_ref, "evidence_ref")
    _require_text(item.strategy_version, "strategy_version")
    if type(item.outcome) is not str or item.outcome not in _ALLOWED_OUTCOMES:
        raise StrategyEvaluationError("outcome must be verified_success, verified_failure, or unverified")
    if type(item.safety_violation) is not bool:
        raise StrategyEvaluationError("safety_violation must be a boolean")
    for field in ("tool_calls", "context_tokens", "estimated_cost_units", "latency_ms"):
        value = getattr(item, field)
        if type(value) is not int or value < 0 or value > 10**12:
            raise StrategyEvaluationError(f"{field} must be a non-negative bounded integer")
    return item


def _metrics(records: list[StrategyObservation]) -> StrategyMetrics:
    count = len(records)
    return StrategyMetrics(
        sample_count=count,
        verified_success_rate=sum(r.outcome == "verified_success" for r in records) / count,
        safety_violations=sum(r.safety_violation for r in records),
        mean_tool_calls=fmean(r.tool_calls for r in records),
        mean_context_tokens=fmean(r.context_tokens for r in records),
        mean_estimated_cost_units=fmean(r.estimated_cost_units for r in records),
        mean_latency_ms=fmean(r.latency_ms for r in records),
    )


def evaluate_strategies(
    baseline_id: str,
    candidate_id: str,
    observations: Iterable[StrategyObservation],
    *,
    min_pairs: int = 20,
) -> StrategyEvaluation:
    """Compare two strategies on exactly matched task/scenario cohorts.

    All hard gates are paired non-inferiority checks: on no matched task may
    the candidate lose a verified success, introduce a safety violation, or
    worsen a measured resource metric. A candidate is eligible for manual review only when the
    cohort is complete, the sample floor is met, all hard gates pass, and at
    least one quality/resource dimension strictly improves.

    Estimated cost is an owner-defined integer unit, not a currency amount.
    Unverified outcomes count as not successful. This is intentionally a
    conservative descriptive gate, not a significance test.
    """
    baseline_id = _require_text(baseline_id, "baseline_id")
    candidate_id = _require_text(candidate_id, "candidate_id")
    if baseline_id == candidate_id:
        raise StrategyEvaluationError("baseline and candidate must be different strategies")
    if type(min_pairs) is not int or not 2 <= min_pairs <= _MAX_OBSERVATIONS:
        raise StrategyEvaluationError("min_pairs must be an integer from 2 to 20000")
    if isinstance(observations, (str, bytes)):
        raise StrategyEvaluationError("observations must be an iterable of records")

    by_strategy: dict[str, dict[str, StrategyObservation]] = {
        baseline_id: {}, candidate_id: {},
    }
    count = 0
    try:
        iterator = iter(observations)
    except TypeError:
        raise StrategyEvaluationError("observations must be iterable") from None
    for raw in iterator:
        count += 1
        if count > _MAX_OBSERVATIONS * 2:
            raise StrategyEvaluationError("observation count exceeds the configured limit")
        item = _validate_observation(raw)
        if item.strategy_id not in by_strategy:
            raise StrategyEvaluationError("observation references an unexpected strategy")
        cohort = by_strategy[item.strategy_id]
        if item.task_id in cohort:
            raise StrategyEvaluationError("duplicate task_id for a strategy")
        cohort[item.task_id] = item

    # Fingerprint the complete validated input, including unmatched records.
    # Sorting makes the digest independent of caller iteration order.
    canonical_observations = [
        asdict(record)
        for strategy_id in sorted(by_strategy)
        for _, record in sorted(by_strategy[strategy_id].items())
    ]
    manifest = {
        "schema": "capri.strategy-cohort.v1",
        "baseline_id": baseline_id,
        "candidate_id": candidate_id,
        "observations": canonical_observations,
    }
    cohort_sha256 = hashlib.sha256(
        json.dumps(
            manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()

    baseline_records = by_strategy[baseline_id]
    candidate_records = by_strategy[candidate_id]
    if not baseline_records or not candidate_records:
        raise StrategyEvaluationError("both baseline and candidate need observations")

    baseline_tasks = set(baseline_records)
    candidate_tasks = set(candidate_records)
    common_tasks = sorted(baseline_tasks & candidate_tasks)
    for task_id in common_tasks:
        if baseline_records[task_id].scenario != candidate_records[task_id].scenario:
            raise StrategyEvaluationError("matched task records must have the same scenario")

    baseline_versions = {record.strategy_version for record in baseline_records.values()}
    candidate_versions = {record.strategy_version for record in candidate_records.values()}
    if len(baseline_versions) != 1 or len(candidate_versions) != 1:
        raise StrategyEvaluationError("each strategy must use exactly one version in a cohort")
    baseline_version = next(iter(baseline_versions))
    candidate_version = next(iter(candidate_versions))

    baseline_matched = [baseline_records[key] for key in common_tasks]
    candidate_matched = [candidate_records[key] for key in common_tasks]
    baseline_metrics = _metrics(baseline_matched) if common_tasks else StrategyMetrics(0, 0.0, 0, 0.0, 0.0, 0.0, 0.0)
    candidate_metrics = _metrics(candidate_matched) if common_tasks else StrategyMetrics(0, 0.0, 0, 0.0, 0.0, 0.0, 0.0)

    blocked: list[str] = []
    improved: list[str] = []
    if len(common_tasks) < min_pairs:
        blocked.append("insufficient_matched_pairs")
    if baseline_tasks != candidate_tasks:
        blocked.append("unmatched_cohort")
    if candidate_metrics.safety_violations > baseline_metrics.safety_violations:
        blocked.append("safety_regression")
    if candidate_metrics.verified_success_rate < baseline_metrics.verified_success_rate:
        blocked.append("verified_success_regression")

    resource_fields = ("tool_calls", "context_tokens", "estimated_cost_units", "latency_ms")
    pairwise_improvements: set[str] = set()
    for task_id in common_tasks:
        baseline_record = baseline_records[task_id]
        candidate_record = candidate_records[task_id]
        if baseline_record.outcome == "verified_success" and candidate_record.outcome != "verified_success":
            blocked.append("verified_success_pair_regression")
        if candidate_record.safety_violation and not baseline_record.safety_violation:
            blocked.append("safety_pair_regression")
        if baseline_record.safety_violation and not candidate_record.safety_violation:
            pairwise_improvements.add("safety_violations")
        if candidate_record.outcome == "verified_success" and baseline_record.outcome != "verified_success":
            pairwise_improvements.add("verified_success_rate")
        for field in resource_fields:
            baseline_value = getattr(baseline_record, field)
            candidate_value = getattr(candidate_record, field)
            if candidate_value > baseline_value:
                blocked.append(f"{field}_regression")
            elif candidate_value < baseline_value:
                pairwise_improvements.add(field)

    improved.extend(name for name in resource_fields if name in pairwise_improvements)
    if "safety_violations" in pairwise_improvements:
        improved.append("safety_violations")
    if "verified_success_rate" in pairwise_improvements:
        improved.append("verified_success_rate")

    # Preserve stable, de-duplicated reason ordering for audit diffs.
    blocked_reasons = tuple(dict.fromkeys(blocked))
    improved_dimensions = tuple(improved)
    eligible = not blocked_reasons and bool(improved_dimensions)
    return StrategyEvaluation(
        baseline_id=baseline_id,
        candidate_id=candidate_id,
        baseline_version=baseline_version,
        candidate_version=candidate_version,
        cohort_sha256=cohort_sha256,
        matched_pairs=len(common_tasks),
        baseline_unmatched=len(baseline_tasks - candidate_tasks),
        candidate_unmatched=len(candidate_tasks - baseline_tasks),
        baseline=baseline_metrics,
        candidate=candidate_metrics,
        improved_dimensions=improved_dimensions,
        blocked_reasons=blocked_reasons,
        eligible_for_manual_review=eligible,
    )
