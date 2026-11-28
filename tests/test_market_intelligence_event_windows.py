"""Contract tests for event windows, market models, and event studies."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1] / "research"
sys.path.insert(0, str(RESEARCH_ROOT))

from market_intelligence.core import MarketEvent  # noqa: E402
from market_intelligence.event_windows import (  # noqa: E402
    EventStudyResult,
    EventWindow,
    MarketModel,
    abnormal_return_market_model,
    cumulative_abnormal_return,
    event_window_returns,
    ols_fit,
    run_event_study,
)
from market_intelligence.prices import PriceObservation, PriceSeries  # noqa: E402


def stamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def bar(timestamp: str, close: float, instrument: str) -> PriceObservation:
    return PriceObservation(
        instrument=instrument,
        timestamp=stamp(timestamp),
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1_000.0,
    )


def make_event(event_id: str = "v1") -> MarketEvent:
    return MarketEvent(
        event_id=event_id,
        source_event_id="wire-123",
        instrument="NASDAQ:NVDA",
        category="earnings",
        headline="Quarterly results",
        source_name="Issuer IR",
        source_url="https://example.com/news",
        source_tier="primary",
        published_at=stamp("2026-11-28T10:00:00Z"),
        available_at=stamp("2026-11-28T10:00:00Z"),
        observed_at=stamp("2026-11-28T10:01:00Z"),
    )


class EventWindowTests(unittest.TestCase):
    def test_around_builds_bounded_window(self):
        window = EventWindow.around(
            "2026-11-28T10:00:00Z",
            before=timedelta(hours=1),
            after=timedelta(hours=2),
        )
        self.assertEqual(window.start, stamp("2026-11-28T09:00:00Z"))
        self.assertEqual(window.end, stamp("2026-11-28T12:00:00Z"))

    def test_rejects_end_before_start(self):
        with self.assertRaises(ValueError):
            EventWindow(stamp("2026-11-28T10:00:00Z"), stamp("2026-11-28T09:00:00Z"))


class OLSTests(unittest.TestCase):
    def test_perfect_fit_recovers_alpha_and_beta(self):
        bench = [0.01, 0.02, 0.03, 0.04]
        asset = [0.02, 0.04, 0.06, 0.08]  # 2x benchmark, alpha 0
        model = ols_fit(bench, asset)
        self.assertAlmostEqual(model.beta, 2.0, places=9)
        self.assertAlmostEqual(model.alpha, 0.0, places=9)
        self.assertAlmostEqual(model.r_squared, 1.0, places=9)

    def test_rejects_constant_benchmark(self):
        with self.assertRaises(ValueError):
            ols_fit([0.01, 0.01, 0.01], [0.01, 0.02, 0.03])

    def test_rejects_mismatched_lengths(self):
        with self.assertRaises(ValueError):
            ols_fit([0.01, 0.02], [0.01])

    def test_abnormal_return_uses_fitted_model(self):
        model = MarketModel(alpha=0.001, beta=1.5, r_squared=0.9, n_observations=10)
        value = abnormal_return_market_model(model, 0.03, 0.02)
        # 0.03 - (0.001 + 1.5*0.02) = 0.03 - 0.031 = -0.001
        self.assertAlmostEqual(value, -0.001, places=9)


class EventWindowReturnTests(unittest.TestCase):
    def setUp(self) -> None:
        self.series = PriceSeries(
            "NASDAQ:NVDA",
            [
                bar("2026-11-28T09:00:00Z", 100.0, "NASDAQ:NVDA"),
                bar("2026-11-28T10:00:00Z", 110.0, "NASDAQ:NVDA"),
                bar("2026-11-28T11:00:00Z", 121.0, "NASDAQ:NVDA"),
            ],
        )

    def test_event_window_returns_are_consecutive(self):
        window = EventWindow(
            stamp("2026-11-28T09:00:00Z"), stamp("2026-11-28T11:00:00Z")
        )
        returns = event_window_returns(self.series, window)
        self.assertAlmostEqual(returns[0], 0.10, places=9)
        self.assertAlmostEqual(returns[1], 0.10, places=9)

    def test_event_window_excludes_bars_before_start(self):
        window = EventWindow(
            stamp("2026-11-28T10:00:00Z"), stamp("2026-11-28T11:00:00Z")
        )
        returns = event_window_returns(self.series, window)
        self.assertEqual(len(returns), 1)


class EventStudyTests(unittest.TestCase):
    def setUp(self) -> None:
        # Asset moves with the benchmark during estimation, then jumps on the event.
        self.asset = PriceSeries(
            "NASDAQ:NVDA",
            [
                bar("2026-11-20T10:00:00Z", 100.0, "NASDAQ:NVDA"),
                bar("2026-11-21T10:00:00Z", 101.0, "NASDAQ:NVDA"),
                bar("2026-11-22T10:00:00Z", 102.0, "NASDAQ:NVDA"),
                bar("2026-11-23T10:00:00Z", 103.0, "NASDAQ:NVDA"),
                bar("2026-11-24T10:00:00Z", 104.0, "NASDAQ:NVDA"),
                bar("2026-11-28T10:00:00Z", 105.0, "NASDAQ:NVDA"),
                bar("2026-11-28T11:00:00Z", 115.0, "NASDAQ:NVDA"),
            ],
        )
        self.bench = PriceSeries(
            "SPX",
            [
                bar("2026-11-20T10:00:00Z", 100.0, "SPX"),
                bar("2026-11-21T10:00:00Z", 101.0, "SPX"),
                bar("2026-11-22T10:00:00Z", 102.0, "SPX"),
                bar("2026-11-23T10:00:00Z", 103.0, "SPX"),
                bar("2026-11-24T10:00:00Z", 104.0, "SPX"),
                bar("2026-11-28T10:00:00Z", 105.0, "SPX"),
                bar("2026-11-28T11:00:00Z", 106.0, "SPX"),
            ],
        )

    def test_run_event_study_produces_car(self):
        estimation = EventWindow(
            stamp("2026-11-20T10:00:00Z"), stamp("2026-11-24T10:00:00Z")
        )
        event_window = EventWindow(
            stamp("2026-11-28T10:00:00Z"), stamp("2026-11-28T11:00:00Z")
        )
        result = run_event_study(
            make_event(), self.asset, self.bench, estimation, event_window
        )
        self.assertIsInstance(result, EventStudyResult)
        self.assertEqual(result.instrument, "NASDAQ:NVDA")
        # Asset jumped 10% while benchmark rose ~1%; abnormal return is large.
        self.assertGreater(result.car, 0.05)

    def test_run_event_study_rejects_contaminated_window(self):
        estimation = EventWindow(
            stamp("2026-11-28T10:00:00Z"), stamp("2026-11-28T11:00:00Z")
        )
        event_window = EventWindow(
            stamp("2026-11-28T10:00:00Z"), stamp("2026-11-28T12:00:00Z")
        )
        with self.assertRaises(ValueError):
            run_event_study(
                make_event(), self.asset, self.bench, estimation, event_window
            )

    def test_cumulative_abnormal_return_sums(self):
        self.assertAlmostEqual(
            cumulative_abnormal_return([0.01, -0.02, 0.03]), 0.02, places=9
        )


if __name__ == "__main__":
    unittest.main()
