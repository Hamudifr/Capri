"""Point-in-time price and benchmark series with corporate-action adjustment.

Prices are point-in-time: a caller can only observe a price at or before a
decision timestamp, so a future price cannot leak into a historical feature.
Corporate actions (splits, dividends) are applied retroactively to produce a
continuous adjusted series for return calculations.

Only the Python standard library is used. There is no network access; price data
is supplied by a caller (CSV/JSONL import, user export, or a future adapter).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Sequence

from .core import _finite_number, parse_utc_timestamp


@dataclass(frozen=True)
class PriceObservation:
    """One OHLCV bar for an instrument at an exact timestamp (UTC)."""

    instrument: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, str) or not self.instrument.strip():
            raise ValueError("instrument must be a non-empty string")
        object.__setattr__(self, "timestamp", parse_utc_timestamp(self.timestamp))
        for name in ("open", "high", "low", "close", "volume"):
            value = _finite_number(name, getattr(self, name))
            if name != "volume" and value <= 0:
                raise ValueError(f"{name} must be greater than zero")
            object.__setattr__(self, name, value)
        if self.high < self.low:
            raise ValueError("high must be greater than or equal to low")
        if not (self.low <= self.open <= self.high):
            raise ValueError("open must lie within the high/low range")
        if not (self.low <= self.close <= self.high):
            raise ValueError("close must lie within the high/low range")


@dataclass(frozen=True)
class CorporateAction:
    """A split or dividend that adjusts the historical price series."""

    instrument: str
    action_type: str  # "split" or "dividend"
    ex_date: datetime
    factor: float  # split ratio multiplier (e.g. 0.5 for a 2:1 split)
    cash_amount: float = 0.0  # dividend per share (for dividends)

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, str) or not self.instrument.strip():
            raise ValueError("instrument must be a non-empty string")
        if self.action_type not in ("split", "dividend"):
            raise ValueError("action_type must be 'split' or 'dividend'")
        object.__setattr__(self, "ex_date", parse_utc_timestamp(self.ex_date))
        factor = _finite_number("factor", self.factor)
        if factor <= 0:
            raise ValueError("factor must be greater than zero")
        object.__setattr__(self, "factor", factor)
        cash = _finite_number("cash_amount", self.cash_amount)
        if cash < 0:
            raise ValueError("cash_amount must not be negative")
        object.__setattr__(self, "cash_amount", cash)


class PriceSeries:
    """An instrument's price observations and corporate actions.

    Prices are stored raw. ``adjusted_close`` and ``return_between`` apply
    retroactive corporate-action adjustment so returns are comparable across
    splits and dividends. ``as_of`` enforces point-in-time visibility.
    """

    def __init__(
        self,
        instrument: str,
        observations: Iterable[PriceObservation] = (),
        actions: Iterable[CorporateAction] = (),
    ) -> None:
        self.instrument = instrument
        self.observations = tuple(
            obs for obs in observations if obs.instrument == instrument
        )
        self.actions = tuple(act for act in actions if act.instrument == instrument)
        self._observations_sorted = tuple(
            sorted(self.observations, key=lambda obs: obs.timestamp)
        )
        self._actions_sorted = tuple(
            sorted(self.actions, key=lambda act: act.ex_date)
        )

    def as_of(self, decision_at: str | datetime) -> list[PriceObservation]:
        """Return observations visible at or before ``decision_at`` (point-in-time)."""
        cutoff = parse_utc_timestamp(decision_at)
        return [obs for obs in self._observations_sorted if obs.timestamp <= cutoff]

    def _adjustment_factor(self, as_of: datetime) -> float:
        """Retroactive multiplier: product of factors for actions after ``as_of``.

        Each action with ``ex_date > as_of`` adjusts prices observed at ``as_of``.
        Splits scale prices by ``factor``; dividends scale by ``(close - cash)/close``
        using the closing price on the ex-date.
        """
        factor = 1.0
        for action in self._actions_sorted:
            if action.ex_date <= as_of:
                continue
            if action.action_type == "split":
                factor *= action.factor
            else:  # dividend
                close = self._close_at_or_before(action.ex_date)
                if close is None or close <= 0:
                    # Cannot compute a dividend adjustment without the ex-date
                    # close; skip rather than invent a factor.
                    continue
                factor *= (close - action.cash_amount) / close
        return factor

    def _close_at_or_before(self, timestamp: datetime) -> float | None:
        visible = self.as_of(timestamp)
        if not visible:
            return None
        return visible[-1].close

    def adjusted_close(self, timestamp: str | datetime) -> float:
        """Adjusted closing price at a timestamp, or raise if not visible."""
        moment = parse_utc_timestamp(timestamp)
        match = self._close_at_or_before(moment)
        if match is None:
            raise ValueError(f"no price observation at or before {moment.isoformat()}")
        return match * self._adjustment_factor(moment)

    def return_between(
        self, start: str | datetime, end: str | datetime
    ) -> float:
        """Adjusted simple return between two timestamps (end/start - 1)."""
        start_value = self.adjusted_close(start)
        end_value = self.adjusted_close(end)
        return end_value / start_value - 1.0

    def benchmark_return(
        self,
        benchmark: "PriceSeries",
        start: str | datetime,
        end: str | datetime,
    ) -> float:
        """Return this instrument's adjusted return minus the benchmark's."""
        return self.return_between(start, end) - benchmark.return_between(start, end)


def aligned_returns(
    series: Sequence[PriceSeries],
    start: str | datetime,
    end: str | datetime,
) -> dict[str, float]:
    """Return adjusted returns for each instrument over the same window."""
    return {
        item.instrument: item.return_between(start, end) for item in series
    }


def _safe_sqrt(value: float) -> float:
    return math.sqrt(value) if value > 0 else 0.0
