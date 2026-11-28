"""Scenario-based forecasting, calibration, and prediction scoring.

A forecast is never a single directional guess. It is a probability-weighted set
of scenarios with an expected return, an uncertainty estimate, and explicit
invalidation conditions. This module also provides honest scoring (Brier score,
log loss, direction accuracy, calibration) so a forecast's quality can be
measured out of sample rather than asserted.

Only the Python standard library is used.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Sequence

from .core import _finite_number, expected_return, parse_utc_timestamp


@dataclass(frozen=True)
class Scenario:
    """One named scenario with a probability and an expected return."""

    name: str
    probability: float
    return_value: float

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("scenario name must be a non-empty string")
        object.__setattr__(
            self, "probability", _finite_number("probability", self.probability)
        )
        object.__setattr__(
            self, "return_value", _finite_number("return", self.return_value)
        )
        if not 0.0 <= self.probability <= 1.0:
            raise ValueError("scenario probability must be between zero and one")


def prediction_variance(scenarios: Sequence[Scenario]) -> float:
    """Probability-weighted variance of scenario returns."""
    pairs = [(scenario.probability, scenario.return_value) for scenario in scenarios]
    mean = expected_return(pairs)
    weighted = sum(
        probability * (return_value - mean) ** 2
        for probability, return_value in pairs
    )
    return weighted


@dataclass(frozen=True)
class ScenarioForecast:
    """A probability-weighted forecast for one instrument at one decision time."""

    instrument: str
    decision_at: datetime
    scenarios: tuple[Scenario, ...]
    invalidation: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, str) or not self.instrument.strip():
            raise ValueError("instrument must be a non-empty string")
        object.__setattr__(self, "decision_at", parse_utc_timestamp(self.decision_at))
        scenarios = tuple(self.scenarios)
        if not scenarios:
            raise ValueError("at least one scenario is required")
        object.__setattr__(self, "scenarios", scenarios)
        # Validate that probabilities sum to one via the shared engine.
        expected_return(
            [(scenario.probability, scenario.return_value) for scenario in scenarios]
        )

    @property
    def expected_return(self) -> float:
        return expected_return(
            [(scenario.probability, scenario.return_value) for scenario in self.scenarios]
        )

    @property
    def expected_variance(self) -> float:
        return prediction_variance(self.scenarios)

    @property
    def expected_volatility(self) -> float:
        return math.sqrt(self.expected_variance)


@dataclass
class PredictionScorecard:
    """Out-of-sample scoring of probability forecasts against realized outcomes."""

    records: list[tuple[float, float]] = field(default_factory=list)

    def add(self, predicted_probability: float, realized_outcome: float) -> None:
        """Record one forecast: a bullish probability and a realized return.

        ``realized_outcome`` is the actual return; ``+1``/``0``/``-1`` are not
        required — the scorecard derives direction from the sign of the return.
        """
        probability = _finite_number("predicted_probability", predicted_probability)
        outcome = _finite_number("realized_outcome", realized_outcome)
        if not 0.0 <= probability <= 1.0:
            raise ValueError("predicted_probability must be between zero and one")
        self.records.append((probability, outcome))

    def brier_score(self) -> float:
        """Mean squared error of bullish probability against an up/down outcome."""
        if not self.records:
            raise ValueError("no predictions recorded")
        total = 0.0
        for probability, outcome in self.records:
            realized = 1.0 if outcome > 0 else 0.0
            total += (probability - realized) ** 2
        return total / len(self.records)

    def log_loss(self) -> float:
        """Mean log loss of bullish probabilities against realized directions."""
        if not self.records:
            raise ValueError("no predictions recorded")
        # Clamp to avoid log(0); never let a perfect score hide a wrong forecast.
        epsilon = 1e-12
        total = 0.0
        for probability, outcome in self.records:
            realized = 1.0 if outcome > 0 else 0.0
            p = min(max(probability, epsilon), 1.0 - epsilon)
            total += -(realized * math.log(p) + (1.0 - realized) * math.log(1.0 - p))
        return total / len(self.records)

    def direction_accuracy(self) -> float:
        """Share of forecasts whose sign matched the realized return sign."""
        if not self.records:
            raise ValueError("no predictions recorded")
        correct = 0
        for probability, outcome in self.records:
            predicted_up = probability >= 0.5
            realized_up = outcome > 0
            if predicted_up == realized_up:
                correct += 1
        return correct / len(self.records)

    def calibration(self, bins: int = 5) -> list[tuple[float, float, int]]:
        """Reliability bins: (bin_center, predicted_prob, count) -> empirical rate.

        Returns tuples of ``(bin_center, predicted_probability, count, rate)``
        for each bin that has predictions, sorted by bin center.
        """
        if not self.records:
            raise ValueError("no predictions recorded")
        if bins < 1:
            raise ValueError("bins must be at least one")
        edges = [i / bins for i in range(bins + 1)]
        buckets: list[list[tuple[float, float]]] = [[] for _ in range(bins)]
        for probability, outcome in self.records:
            index = min(bins - 1, max(0, int(probability * bins)))
            buckets[index].append((probability, outcome))
        result: list[tuple[float, float, int, float]] = []
        for index, bucket in enumerate(buckets):
            if not bucket:
                continue
            center = (edges[index] + edges[index + 1]) / 2
            predicted = sum(probability for probability, _ in bucket) / len(bucket)
            rate = sum(1.0 for _, outcome in bucket if outcome > 0) / len(bucket)
            result.append((center, predicted, len(bucket), rate))
        return result

    def summary(self) -> dict[str, float]:
        return {
            "brier_score": self.brier_score(),
            "log_loss": self.log_loss(),
            "direction_accuracy": self.direction_accuracy(),
            "count": float(len(self.records)),
        }
