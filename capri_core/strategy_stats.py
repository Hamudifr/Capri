"""Conservative uncertainty bounds for paired binary strategy outcomes.

This helper is descriptive only. It never makes a promotion decision.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import log, sqrt
from typing import Iterable


@dataclass(frozen=True, slots=True)
class PairedSuccessInterval:
    sample_size: int
    success_delta: float
    lower_95: float
    upper_95: float
    method: str = "95% Hoeffding bound; independent matched pairs assumed"


def paired_success_interval(
    baseline_success: Iterable[bool],
    candidate_success: Iterable[bool],
) -> PairedSuccessInterval:
    """Bound candidate-minus-baseline success-rate difference on matched tasks.

    Each pair contributes -1, 0, or +1. Hoeffding's inequality gives a
    distribution-free bound for independent pairs; dependence between tasks
    invalidates the nominal coverage. The interval is never a significance
    test and must not be used as a safety or promotion gate.
    """
    if isinstance(baseline_success, (str, bytes)) or isinstance(candidate_success, (str, bytes)):
        raise ValueError("paired outcomes must be iterables of booleans")
    try:
        baseline = list(baseline_success)
        candidate = list(candidate_success)
    except TypeError:
        raise ValueError("paired outcomes must be iterable") from None
    if not baseline or len(baseline) != len(candidate):
        raise ValueError("paired outcomes must be non-empty and have equal lengths")
    if len(baseline) > 20_000:
        raise ValueError("paired outcome count exceeds 20000")
    if any(type(value) is not bool for value in baseline + candidate):
        raise ValueError("paired outcomes must contain booleans only")

    n = len(baseline)
    delta = sum(int(c) - int(b) for b, c in zip(baseline, candidate)) / n
    radius = min(1.0, sqrt(2.0 * log(40.0) / n))
    return PairedSuccessInterval(
        sample_size=n,
        success_delta=delta,
        lower_95=max(-1.0, delta - radius),
        upper_95=min(1.0, delta + radius),
    )
