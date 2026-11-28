"""Contract tests for point-in-time price series and corporate actions."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1] / "research"
sys.path.insert(0, str(RESEARCH_ROOT))

from market_intelligence.prices import (  # noqa: E402
    CorporateAction,
    PriceObservation,
    PriceSeries,
    aligned_returns,
)


def stamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def bar(
    timestamp: str,
    close: float,
    *,
    instrument: str = "NASDAQ:NVDA",
    open_price: float | None = None,
    high: float | None = None,
    low: float | None = None,
    volume: float = 1_000_000.0,
) -> PriceObservation:
    open_value = open_price if open_price is not None else close
    high_value = high if high is not None else max(open_value, close)
    low_value = low if low is not None else min(open_value, close)
    return PriceObservation(
        instrument=instrument,
        timestamp=stamp(timestamp),
        open=open_value,
        high=high_value,
        low=low_value,
        close=close,
        volume=volume,
    )


class PriceObservationTests(unittest.TestCase):
    def test_rejects_negative_price(self):
        with self.assertRaises(ValueError):
            bar("2026-11-28T10:00:00Z", -5.0)

    def test_rejects_high_below_low(self):
        with self.assertRaises(ValueError):
            bar(
                "2026-11-28T10:00:00Z",
                10.0,
                high=8.0,
                low=12.0,
            )

    def test_rejects_close_outside_range(self):
        with self.assertRaises(ValueError):
            bar("2026-11-28T10:00:00Z", 10.0, high=9.0, low=8.0)


class PointInTimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.series = PriceSeries(
            "NASDAQ:NVDA",
            [
                bar("2026-11-28T10:00:00Z", 100.0),
                bar("2026-11-28T11:00:00Z", 110.0),
                bar("2026-11-28T12:00:00Z", 120.0),
            ],
        )

    def test_as_of_excludes_future_prices(self):
        visible = self.series.as_of("2026-11-28T11:00:00Z")
        self.assertEqual([obs.close for obs in visible], [100.0, 110.0])

    def test_as_of_at_exact_timestamp_includes_that_bar(self):
        visible = self.series.as_of("2026-11-28T12:00:00Z")
        self.assertEqual([obs.close for obs in visible], [100.0, 110.0, 120.0])

    def test_return_between_uses_visible_prices(self):
        self.assertAlmostEqual(
            self.series.return_between(
                "2026-11-28T10:00:00Z", "2026-11-28T11:00:00Z"
            ),
            0.10,
        )


class CorporateActionTests(unittest.TestCase):
    def test_split_adjustment_halves_pre_split_prices(self):
        series = PriceSeries(
            "NASDAQ:NVDA",
            [
                bar("2026-11-28T10:00:00Z", 200.0),
                bar("2026-11-29T10:00:00Z", 100.0),
            ],
            actions=[
                CorporateAction(
                    instrument="NASDAQ:NVDA",
                    action_type="split",
                    ex_date=stamp("2026-11-29T10:00:00Z"),
                    factor=0.5,
                )
            ],
        )
        # Pre-split 200 adjusts to 100; the post-split 100 stays 100.
        self.assertAlmostEqual(series.adjusted_close("2026-11-28T10:00:00Z"), 100.0)
        self.assertAlmostEqual(series.adjusted_close("2026-11-29T10:00:00Z"), 100.0)
        # The return across the split is ~0 on an adjusted basis.
        self.assertAlmostEqual(
            series.return_between("2026-11-28T10:00:00Z", "2026-11-29T10:00:00Z"),
            0.0,
            delta=1e-9,
        )

    def test_dividend_adjustment_reduces_pre_ex_date_prices(self):
        series = PriceSeries(
            "NASDAQ:NVDA",
            [
                bar("2026-11-28T10:00:00Z", 100.0),
                bar("2026-11-29T10:00:00Z", 99.0),
            ],
            actions=[
                CorporateAction(
                    instrument="NASDAQ:NVDA",
                    action_type="dividend",
                    ex_date=stamp("2026-11-29T10:00:00Z"),
                    factor=1.0,
                    cash_amount=1.0,
                )
            ],
        )
        # Pre-ex-date 100 adjusts by (99 - 1)/99.
        expected = 100.0 * (99.0 - 1.0) / 99.0
        self.assertAlmostEqual(
            series.adjusted_close("2026-11-28T10:00:00Z"), expected
        )

    def test_return_across_dividend_captures_total_return(self):
        series = PriceSeries(
            "NASDAQ:NVDA",
            [
                bar("2026-11-28T10:00:00Z", 100.0),
                bar("2026-11-29T10:00:00Z", 100.0),
            ],
            actions=[
                CorporateAction(
                    instrument="NASDAQ:NVDA",
                    action_type="dividend",
                    ex_date=stamp("2026-11-29T10:00:00Z"),
                    factor=1.0,
                    cash_amount=1.0,
                )
            ],
        )
        # Price unchanged; the adjusted return is the total return, which
        # includes the dividend: 1/99 ~= 1.01%, not zero.
        self.assertAlmostEqual(
            series.return_between("2026-11-28T10:00:00Z", "2026-11-29T10:00:00Z"),
            1.0 / 99.0,
            delta=1e-9,
        )


class BenchmarkTests(unittest.TestCase):
    def test_benchmark_return_is_asset_minus_benchmark(self):
        asset = PriceSeries(
            "NASDAQ:NVDA",
            [
                bar("2026-11-28T10:00:00Z", 100.0),
                bar("2026-11-28T11:00:00Z", 110.0),
            ],
        )
        bench = PriceSeries(
            "SPX",
            [
                bar("2026-11-28T10:00:00Z", 100.0, instrument="SPX"),
                bar("2026-11-28T11:00:00Z", 105.0, instrument="SPX"),
            ],
        )
        self.assertAlmostEqual(
            asset.benchmark_return(bench, "2026-11-28T10:00:00Z", "2026-11-28T11:00:00Z"),
            0.05,
        )

    def test_aligned_returns_maps_instrument_to_return(self):
        first = PriceSeries(
            "AAA",
            [
                bar("2026-11-28T10:00:00Z", 100.0, instrument="AAA"),
                bar("2026-11-28T11:00:00Z", 110.0, instrument="AAA"),
            ],
        )
        second = PriceSeries(
            "BBB",
            [
                bar("2026-11-28T10:00:00Z", 100.0, instrument="BBB"),
                bar("2026-11-28T11:00:00Z", 90.0, instrument="BBB"),
            ],
        )
        result = aligned_returns(
            [first, second], "2026-11-28T10:00:00Z", "2026-11-28T11:00:00Z"
        )
        self.assertAlmostEqual(result["AAA"], 0.10)
        self.assertAlmostEqual(result["BBB"], -0.10)


if __name__ == "__main__":
    unittest.main()
