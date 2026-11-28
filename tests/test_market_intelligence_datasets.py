"""Contract tests for earnings and macro surprise datasets."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1] / "research"
sys.path.insert(0, str(RESEARCH_ROOT))

from market_intelligence.core import MarketEvent  # noqa: E402
from market_intelligence.datasets import (  # noqa: E402
    EarningsRecord,
    ForecastSnapshot,
    MacroReleaseRecord,
    SurpriseDataset,
    forecast_dispersion,
)


def stamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


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


class EarningsRecordTests(unittest.TestCase):
    def test_surprise_is_actual_minus_expected(self):
        record = EarningsRecord(
            instrument="NASDAQ:NVDA",
            period="Q4 2026",
            expected_eps=1.00,
            actual_eps=1.10,
            reported_at=stamp("2026-11-28T10:00:00Z"),
        )
        result = record.surprise(historical_std=0.05)
        self.assertAlmostEqual(result.raw, 0.10, places=9)
        self.assertAlmostEqual(result.z_score, 2.0, places=9)

    def test_rejects_empty_instrument(self):
        with self.assertRaises(ValueError):
            EarningsRecord(
                instrument="",
                period="Q4",
                expected_eps=1.0,
                actual_eps=1.0,
                reported_at=stamp("2026-11-28T10:00:00Z"),
            )


class MacroReleaseRecordTests(unittest.TestCase):
    def test_surprise_respects_direction_for_lower_is_better(self):
        # CPI higher than expected is adverse (favorable_direction=-1).
        record = MacroReleaseRecord(
            indicator="CPI",
            period="Oct 2026",
            consensus=3.2,
            actual=3.4,
            released_at=stamp("2026-11-28T10:00:00Z"),
            favorable_direction=-1,
        )
        result = record.surprise(historical_std=0.1)
        self.assertAlmostEqual(result.favorable, -0.2, places=9)

    def test_rejects_invalid_favorable_direction(self):
        with self.assertRaises(ValueError):
            MacroReleaseRecord(
                indicator="CPI",
                period="Oct",
                consensus=3.2,
                actual=3.4,
                released_at=stamp("2026-11-28T10:00:00Z"),
                favorable_direction=0,
            )


class ForecastSnapshotTests(unittest.TestCase):
    def test_rejects_negative_dispersion(self):
        with self.assertRaises(ValueError):
            ForecastSnapshot(
                instrument="NASDAQ:NVDA",
                indicator="EPS",
                as_of=stamp("2026-11-28T09:00:00Z"),
                consensus=1.0,
                estimate_dispersion=-0.1,
            )


class SurpriseDatasetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dataset = SurpriseDataset()
        self.dataset.add_snapshot(
            ForecastSnapshot(
                instrument="NASDAQ:NVDA",
                indicator="EPS",
                as_of=stamp("2026-11-27T10:00:00Z"),
                consensus=1.00,
                estimate_dispersion=0.05,
                analyst_count=10,
            )
        )
        self.dataset.add_snapshot(
            ForecastSnapshot(
                instrument="NASDAQ:NVDA",
                indicator="EPS",
                as_of=stamp("2026-11-28T09:00:00Z"),
                consensus=1.05,
                estimate_dispersion=0.06,
                analyst_count=12,
            )
        )

    def test_snapshot_at_returns_latest_before_cutoff(self):
        snap = self.dataset.snapshot_at(
            "NASDAQ:NVDA", "EPS", "2026-11-28T09:30:00Z"
        )
        self.assertIsNotNone(snap)
        self.assertAlmostEqual(snap.consensus, 1.05, places=9)

    def test_snapshot_at_returns_none_when_no_snapshot_visible(self):
        snap = self.dataset.snapshot_at(
            "NASDAQ:NVDA", "EPS", "2026-11-26T10:00:00Z"
        )
        self.assertIsNone(snap)

    def test_dispersion_returns_latest_value(self):
        self.assertAlmostEqual(
            self.dataset.dispersion("NASDAQ:NVDA", "EPS"), 0.06, places=9
        )

    def test_dispersion_returns_zero_when_absent(self):
        self.assertAlmostEqual(
            self.dataset.dispersion("NASDAQ:NVDA", "REVENUE"), 0.0, places=9
        )

    def test_earnings_and_macro_surprise_collections(self):
        self.dataset.add_earnings(
            EarningsRecord(
                instrument="NASDAQ:NVDA",
                period="Q4",
                expected_eps=1.0,
                actual_eps=1.2,
                reported_at=stamp("2026-11-28T10:00:00Z"),
            )
        )
        self.dataset.add_macro(
            MacroReleaseRecord(
                indicator="CPI",
                period="Oct",
                consensus=3.2,
                actual=3.2,
                released_at=stamp("2026-11-28T10:00:00Z"),
            )
        )
        self.assertEqual(len(self.dataset.earnings_surprises(0.1)), 1)
        self.assertEqual(len(self.dataset.macro_surprises(0.1)), 1)


class ForecastDispersionTests(unittest.TestCase):
    def test_dispersion_of_estimates(self):
        self.assertAlmostEqual(
            forecast_dispersion([1.0, 1.2, 1.4, 1.1]),
            0.1707825,
            places=5,
        )

    def test_dispersion_zero_for_single_estimate(self):
        self.assertAlmostEqual(forecast_dispersion([1.0]), 0.0, places=9)


if __name__ == "__main__":
    unittest.main()
