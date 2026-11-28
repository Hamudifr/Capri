"""Contract tests for the point-in-time market intelligence core."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1] / "research"
sys.path.insert(0, str(RESEARCH_ROOT))

from market_intelligence.core import (  # noqa: E402
    MarketEvent,
    abnormal_return,
    compute_surprise,
    events_as_of,
    expected_return,
    parse_utc_timestamp,
    simple_return,
)


def stamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def event(
    event_id: str,
    *,
    available_at: str = "2026-11-28T10:00:00Z",
    observed_at: str = "2026-11-28T10:01:00Z",
    headline: str = "Quarterly results released",
    source_updated_at: str | None = None,
    event_at: str | None = None,
) -> MarketEvent:
    return MarketEvent(
        event_id=event_id,
        source_event_id="wire-123",
        instrument="NASDAQ:NVDA",
        category="earnings",
        headline=headline,
        source_name="Issuer IR",
        source_url="https://investor.example.com/news/123",
        source_tier="primary",
        published_at=stamp("2026-11-28T10:00:00Z"),
        available_at=stamp(available_at),
        observed_at=stamp(observed_at),
        event_at=stamp(event_at) if event_at is not None else None,
        source_updated_at=(
            stamp(source_updated_at) if source_updated_at is not None else None
        ),
    )


class TimestampTests(unittest.TestCase):
    def test_normalizes_offset_timestamp_to_utc(self):
        value = parse_utc_timestamp("2026-11-28T12:30:00+02:00")
        self.assertEqual(value, stamp("2026-11-28T10:30:00Z"))
        self.assertEqual(value.tzinfo, timezone.utc)

    def test_rejects_naive_timestamp(self):
        with self.assertRaises(ValueError):
            parse_utc_timestamp("2026-11-28T10:00:00")

    def test_event_occurrence_time_is_normalized_separately(self):
        item = event("v1", event_at="2026-11-28T12:00:00+02:00")
        self.assertEqual(item.event_at, stamp("2026-11-28T10:00:00Z"))


class MarketEventTests(unittest.TestCase):
    def test_rejects_observation_before_market_availability(self):
        with self.assertRaises(ValueError):
            event(
                "v1",
                available_at="2026-11-28T10:00:00Z",
                observed_at="2026-11-28T09:59:00Z",
            )

    def test_rejects_revision_timestamp_after_availability(self):
        with self.assertRaises(ValueError):
            event(
                "v2",
                source_updated_at="2026-11-28T10:05:00Z",
                available_at="2026-11-28T10:00:00Z",
                observed_at="2026-11-28T10:06:00Z",
            )

    def test_as_of_uses_latest_version_available_at_decision_time(self):
        original = event("v1")
        revision = event(
            "v2",
            available_at="2026-11-28T10:05:00Z",
            observed_at="2026-11-28T10:06:00Z",
            headline="Quarterly results corrected",
            source_updated_at="2026-11-28T10:05:00Z",
        )
        later = events_as_of(
            [original, revision], stamp("2026-11-28T10:03:00Z")
        )
        self.assertEqual([item.event_id for item in later], ["v1"])
        after_revision = events_as_of(
            [original, revision], stamp("2026-11-28T10:07:00Z")
        )
        self.assertEqual([item.event_id for item in after_revision], ["v2"])

    def test_as_of_keeps_distinct_events(self):
        first = event("v1")
        second = MarketEvent(
            **{
                **first.__dict__,
                "event_id": "v2",
                "source_event_id": "wire-456",
            }
        )
        result = events_as_of([first, second], stamp("2026-11-28T10:02:00Z"))
        self.assertEqual(
            {item.source_event_id for item in result}, {"wire-123", "wire-456"}
        )


class QuantitativeTests(unittest.TestCase):
    def test_surprise_respects_indicator_direction(self):
        # A higher-than-expected CPI reading is adverse when direction is -1.
        result = compute_surprise(
            actual=3.4,
            consensus=3.2,
            historical_std=0.1,
            favorable_direction=-1,
        )
        self.assertAlmostEqual(result.raw, 0.2)
        self.assertAlmostEqual(result.z_score, 2.0)
        self.assertAlmostEqual(result.favorable, -0.2)
        self.assertAlmostEqual(result.favorable_z_score, -2.0)

    def test_surprise_rejects_zero_historical_dispersion(self):
        with self.assertRaises(ValueError):
            compute_surprise(3.4, 3.2, 0.0)

    def test_surprise_rejects_boolean_direction(self):
        with self.assertRaises(TypeError):
            compute_surprise(3.4, 3.2, 0.1, favorable_direction=True)

    def test_expected_return_is_probability_weighted(self):
        self.assertAlmostEqual(
            expected_return([(0.5, 0.08), (0.3, 0.01), (0.2, -0.10)]),
            0.023,
        )

    def test_expected_return_rejects_unclosed_probability_mass(self):
        with self.assertRaises(ValueError):
            expected_return([(0.5, 0.08), (0.3, -0.02)])

    def test_abnormal_and_simple_returns(self):
        self.assertAlmostEqual(abnormal_return(0.05, 0.02), 0.03)
        self.assertAlmostEqual(simple_return(100.0, 105.0), 0.05)

    def test_simple_return_rejects_non_positive_prices(self):
        with self.assertRaises(ValueError):
            simple_return(0.0, 105.0)


if __name__ == "__main__":
    unittest.main()
