"""Contract tests for market intelligence report assembly."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1] / "research"
sys.path.insert(0, str(RESEARCH_ROOT))

from market_intelligence.forecasting import Scenario, ScenarioForecast  # noqa: E402
from market_intelligence.reporting import (  # noqa: E402
    MarketIntelligenceReport,
    MarketSituation,
    build_report,
)


def stamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class MarketSituationTests(unittest.TestCase):
    def test_rejects_empty_instrument(self):
        with self.assertRaises(ValueError):
            MarketSituation(
                instrument="",
                decision_at=stamp("2026-11-28T10:00:00Z"),
            )


class ReportRenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.situation = MarketSituation(
            instrument="NASDAQ:NVDA",
            decision_at=stamp("2026-11-28T10:00:00Z"),
            price=100.0,
            trend="up",
            volatility=0.02,
            liquidity="high",
        )
        self.forecast = ScenarioForecast(
            instrument="NASDAQ:NVDA",
            decision_at=stamp("2026-11-28T10:00:00Z"),
            scenarios=(
                Scenario("strong", 0.5, 0.08),
                Scenario("mixed", 0.3, 0.01),
                Scenario("weak", 0.2, -0.10),
            ),
            invalidation=("Break below $95", "Guidance cut"),
        )
        self.report = build_report(
            "NASDAQ:NVDA",
            "2026-11-28T10:00:00Z",
            self.situation,
            developments=["Earnings released", "Guidance raised"],
            expectations=["Consensus EPS $1.00", "Actual EPS $1.10"],
            forecast=self.forecast,
            risk_invalidation=["Break below $95", "Guidance cut"],
            sources=["SEC 8-K", "Issuer IR"],
        )

    def test_render_contains_all_sections(self):
        text = self.report.render()
        for heading in (
            "1. Market situation",
            "2. Latest developments",
            "3. Expectations",
            "4. Fundamental impact",
            "5. Technical and positioning",
            "6. Cross-market impact",
            "7. Prediction",
            "8. Risk and invalidation",
            "9. Sources and verification",
        ):
            self.assertIn(heading, text)

    def test_render_includes_instrument_and_decision_time(self):
        text = self.report.render()
        self.assertIn("NASDAQ:NVDA", text)
        self.assertIn("2026-11-28T10:00:00+00:00", text)

    def test_render_includes_forecast_scenarios(self):
        text = self.report.render()
        self.assertIn("Expected return:", text)
        self.assertIn("strong", text)
        self.assertIn("50%", text)

    def test_prediction_block_handles_missing_forecast(self):
        report = build_report(
            "NASDAQ:NVDA",
            "2026-11-28T10:00:00Z",
            self.situation,
            forecast=None,
        )
        text = report.render()
        self.assertIn("not available", text)

    def test_empty_sections_render_as_not_available(self):
        report = build_report(
            "NASDAQ:NVDA",
            "2026-11-28T10:00:00Z",
            self.situation,
        )
        text = report.render()
        self.assertIn("Not available", text)

    def test_report_rejects_empty_instrument(self):
        with self.assertRaises(ValueError):
            MarketIntelligenceReport(
                instrument="",
                decision_at=stamp("2026-11-28T10:00:00Z"),
                situation=self.situation,
            )


if __name__ == "__main__":
    unittest.main()
