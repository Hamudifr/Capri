"""Event windows, market-model abnormal returns, and cumulative abnormal returns.

An event study measures how an instrument reacted around a dated event, relative
to a benchmark and a fitted market model. This module keeps the estimation
window separate from the event window so the model is never fit on the data it
then evaluates (avoiding in-sample contamination).

Only the Python standard library is used. Return inputs come from
``prices.PriceSeries``; event inputs come from ``core.MarketEvent``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from .core import MarketEvent, parse_utc_timestamp
from .prices import PriceSeries


@dataclass(frozen=True)
class EventWindow:
    """A half-open event window ``[start, end)`` around an event."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "start", parse_utc_timestamp(self.start))
        object.__setattr__(self, "end", parse_utc_timestamp(self.end))
        if self.end <= self.start:
            raise ValueError("event window end must be after start")

    @classmethod
    def around(
        cls, event_at: str | datetime, *, before: timedelta, after: timedelta
    ) -> "EventWindow":
        moment = parse_utc_timestamp(event_at)
        return cls(
            start=moment - before,
            end=moment + after,
        )


@dataclass(frozen=True)
class MarketModel:
    """OLS market model: expected return = alpha + beta * benchmark return."""

    alpha: float
    beta: float
    r_squared: float
    n_observations: int


def ols_fit(benchmark_returns: Sequence[float], asset_returns: Sequence[float]) -> MarketModel:
    """Fit ``asset = alpha + beta * benchmark`` by ordinary least squares."""
    xs = list(benchmark_returns)
    ys = list(asset_returns)
    if len(xs) != len(ys):
        raise ValueError("benchmark and asset return series must be equal length")
    n = len(xs)
    if n < 2:
        raise ValueError("at least two observations are required to fit a model")
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx <= 0:
        raise ValueError("benchmark returns are constant; beta is undefined")
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    beta = sxy / sxx
    alpha = mean_y - beta * mean_x
    ss_res = sum((y - (alpha + beta * x)) ** 2 for x, y in zip(xs, ys))
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return MarketModel(
        alpha=alpha, beta=beta, r_squared=r_squared, n_observations=n
    )


def abnormal_return_market_model(
    model: MarketModel, asset_return: float, benchmark_return: float
) -> float:
    """Abnormal return under the market model: asset - (alpha + beta * bench)."""
    expected = model.alpha + model.beta * benchmark_return
    return asset_return - expected


@dataclass(frozen=True)
class EventStudyResult:
    """Outcome of an event-window study for one event."""

    event_id: str
    instrument: str
    window: EventWindow
    asset_returns: tuple[float, ...]
    benchmark_returns: tuple[float, ...]
    abnormal_returns: tuple[float, ...]
    car: float


def event_window_returns(
    series: PriceSeries, window: EventWindow
) -> list[float]:
    """Return adjusted simple returns between consecutive bars in the window."""
    bars = series.as_of(window.end)
    bars = [bar for bar in bars if bar.timestamp >= window.start]
    returns: list[float] = []
    for previous, current in zip(bars, bars[1:]):
        returns.append(
            current.close / previous.close - 1.0
        )
    return returns


def run_event_study(
    event: MarketEvent,
    series: PriceSeries,
    benchmark: PriceSeries,
    estimation_window: EventWindow,
    event_window: EventWindow,
) -> EventStudyResult:
    """Fit a market model on the estimation window and evaluate the event window.

    The estimation window must end before the event window starts; otherwise the
    model is contaminated by the event it is meant to evaluate.
    """
    if estimation_window.end > event_window.start:
        raise ValueError(
            "estimation window must end before the event window begins"
        )

    est_asset = event_window_returns(series, estimation_window)
    est_bench = event_window_returns(benchmark, estimation_window)
    if len(est_asset) < 2 or len(est_bench) < 2:
        raise ValueError("estimation window needs at least two return observations")
    model = ols_fit(est_bench, est_asset)

    win_asset = event_window_returns(series, event_window)
    win_bench = event_window_returns(benchmark, event_window)
    if len(win_asset) != len(win_bench):
        raise ValueError(
            "asset and benchmark must share the event-window bar grid"
        )
    abnormal = [
        abnormal_return_market_model(model, a, b)
        for a, b in zip(win_asset, win_bench)
    ]
    return EventStudyResult(
        event_id=event.event_id,
        instrument=event.instrument,
        window=event_window,
        asset_returns=tuple(win_asset),
        benchmark_returns=tuple(win_bench),
        abnormal_returns=tuple(abnormal),
        car=sum(abnormal),
    )


def cumulative_abnormal_return(abnormal_returns: Sequence[float]) -> float:
    """Sum abnormal returns into a cumulative abnormal return."""
    return math.fsum(abnormal_returns)
