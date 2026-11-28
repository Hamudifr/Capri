"""Earnings and macroeconomic surprise datasets.

Markets respond to surprises relative to expectations, not to whether a headline
number "looks good." These records preserve the expectation as it stood before a
release (point-in-time), the actual result, the prior/revised values, and the
forecast dispersion so that a standardized, direction-aware surprise can be
computed without leaking post-release revisions into the expectation.

Only the Python standard library is used.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import Sequence

from .core import MarketEvent, _finite_number, compute_surprise, parse_utc_timestamp


@dataclass(frozen=True)
class ForecastSnapshot:
    """A point-in-time consensus snapshot taken before a release."""

    instrument: str
    indicator: str
    as_of: datetime
    consensus: float
    estimate_dispersion: float = 0.0
    analyst_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, str) or not self.instrument.strip():
            raise ValueError("instrument must be a non-empty string")
        if not isinstance(self.indicator, str) or not self.indicator.strip():
            raise ValueError("indicator must be a non-empty string")
        object.__setattr__(self, "as_of", parse_utc_timestamp(self.as_of))
        object.__setattr__(
            self, "consensus", _finite_number("consensus", self.consensus)
        )
        dispersion = _finite_number("estimate_dispersion", self.estimate_dispersion)
        if dispersion < 0:
            raise ValueError("estimate_dispersion must not be negative")
        object.__setattr__(self, "estimate_dispersion", dispersion)
        if self.analyst_count < 0:
            raise ValueError("analyst_count must not be negative")


@dataclass(frozen=True)
class EarningsRecord:
    """A reported earnings result compared against its pre-release expectation."""

    instrument: str
    period: str
    expected_eps: float
    actual_eps: float
    reported_at: datetime
    prior_eps: float | None = None
    guidance: str | None = None
    event: MarketEvent | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, str) or not self.instrument.strip():
            raise ValueError("instrument must be a non-empty string")
        if not isinstance(self.period, str) or not self.period.strip():
            raise ValueError("period must be a non-empty string")
        object.__setattr__(self, "expected_eps", _finite_number("expected_eps", self.expected_eps))
        object.__setattr__(self, "actual_eps", _finite_number("actual_eps", self.actual_eps))
        object.__setattr__(self, "reported_at", parse_utc_timestamp(self.reported_at))
        if self.prior_eps is not None:
            object.__setattr__(
                self, "prior_eps", _finite_number("prior_eps", self.prior_eps)
            )

    def surprise(self, historical_std: float) -> object:
        """Compute a direction-aware surprise (higher EPS is favorable)."""
        return compute_surprise(
            actual=self.actual_eps,
            consensus=self.expected_eps,
            historical_std=historical_std,
            favorable_direction=1,
        )


@dataclass(frozen=True)
class MacroReleaseRecord:
    """A macroeconomic indicator release compared against consensus."""

    indicator: str
    period: str
    consensus: float
    actual: float
    released_at: datetime
    prior: float | None = None
    revised_prior: float | None = None
    favorable_direction: int = 1
    event: MarketEvent | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.indicator, str) or not self.indicator.strip():
            raise ValueError("indicator must be a non-empty string")
        if not isinstance(self.period, str) or not self.period.strip():
            raise ValueError("period must be a non-empty string")
        object.__setattr__(self, "consensus", _finite_number("consensus", self.consensus))
        object.__setattr__(self, "actual", _finite_number("actual", self.actual))
        object.__setattr__(self, "released_at", parse_utc_timestamp(self.released_at))
        if self.prior is not None:
            object.__setattr__(self, "prior", _finite_number("prior", self.prior))
        if self.revised_prior is not None:
            object.__setattr__(
                self, "revised_prior", _finite_number("revised_prior", self.revised_prior)
            )
        if isinstance(self.favorable_direction, bool) or self.favorable_direction not in (-1, 1):
            raise ValueError("favorable_direction must be -1 or 1")

    def surprise(self, historical_std: float) -> object:
        """Compute a direction-aware surprise for this indicator."""
        return compute_surprise(
            actual=self.actual,
            consensus=self.consensus,
            historical_std=historical_std,
            favorable_direction=self.favorable_direction,
        )


@dataclass
class SurpriseDataset:
    """A point-in-time collection of earnings and macro surprise records."""

    earnings: list[EarningsRecord] = field(default_factory=list)
    macro: list[MacroReleaseRecord] = field(default_factory=list)
    snapshots: list[ForecastSnapshot] = field(default_factory=list)

    def add_earnings(self, record: EarningsRecord) -> None:
        self.earnings.append(record)

    def add_macro(self, record: MacroReleaseRecord) -> None:
        self.macro.append(record)

    def add_snapshot(self, snapshot: ForecastSnapshot) -> None:
        self.snapshots.append(snapshot)

    def snapshot_at(
        self, instrument: str, indicator: str, decision_at: str | datetime
    ) -> ForecastSnapshot | None:
        """Return the latest snapshot for an indicator visible at ``decision_at``."""
        cutoff = parse_utc_timestamp(decision_at)
        candidates = [
            snap
            for snap in self.snapshots
            if snap.instrument == instrument
            and snap.indicator == indicator
            and snap.as_of <= cutoff
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda snap: snap.as_of)

    def dispersion(self, instrument: str, indicator: str) -> float:
        """Latest estimate dispersion for an indicator, or zero if absent."""
        candidates = [
            snap
            for snap in self.snapshots
            if snap.instrument == instrument and snap.indicator == indicator
        ]
        if not candidates:
            return 0.0
        return max(candidates, key=lambda snap: snap.as_of).estimate_dispersion

    def earnings_surprises(self, historical_std: float) -> list[object]:
        return [record.surprise(historical_std) for record in self.earnings]

    def macro_surprises(self, historical_std: float) -> list[object]:
        return [record.surprise(historical_std) for record in self.macro]


def forecast_dispersion(estimates: Sequence[float]) -> float:
    """Sample standard deviation of analyst estimates (zero for fewer than two)."""
    values = [_finite_number("estimate", estimate) for estimate in estimates]
    if len(values) < 2:
        return 0.0
    return statistics.stdev(values)
