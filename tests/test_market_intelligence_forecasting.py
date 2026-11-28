"""Contract tests for scenario forecasting and prediction scoring."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1] / "research"
sys.path.insert(0, str(RESEARCH_ROOT))

from market_intelligence.forecasting import (  # noqa: E402
    Scenario,
    ScenarioForecast,
    PredictionScorecard,
    prediction_variance,
)


def stamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class ScenarioTests(unittest.TestCase):
    def test_rejects_probability_out_of_range(self):
        with self.assertRaises(ValueError):
            Scenario(name="bull", probability=1.5, return_value=0.1)

    def test_rejects_empty_name(self):
        with self.assertRaises(ValueError):
            Scenario(name="", probability=0.5, return_value=0.1)


class ScenarioForecastTests(unittest.TestCase):
    def test_expected_return_is_probability_weighted(self):
        forecast = ScenarioForecast(
            instrument="NASDAQ:NVDA",
            decision_at=stamp("2026-11-28T10:00:00Z"),
            scenarios=(
                Scenario("strong", 0.5, 0.08),
                Scenario("mixed", 0.3, 0.01),
                Scenario("weak", 0.2, -0.10),
            ),
        )
        self.assertAlmostEqual(forecast.expected_return, 0.023, places=9)

    def test_expected_variance_and_volatility(self):
        forecast = ScenarioForecast(
            instrument="NASDAQ:NVDA",
            decision_at=stamp("2026-11-28T10:00:00Z"),
            scenarios=(
                Scenario("up", 0.5, 0.10),
                Scenario("down", 0.5, -0.10),
            ),
        )
        # Mean 0; variance = 0.5*(0.1)^2 + 0.5*(-0.1)^2 = 0.01
        self.assertAlmostEqual(forecast.expected_variance, 0.01, places=9)
        self.assertAlmostEqual(forecast.expected_volatility, 0.10, places=9)

    def test_rejects_unclosed_probability_mass(self):
        with self.assertRaises(ValueError):
            ScenarioForecast(
                instrument="NASDAQ:NVDA",
                decision_at=stamp("2026-11-28T10:00:00Z"),
                scenarios=(Scenario("up", 0.5, 0.1), Scenario("down", 0.3, -0.1)),
            )

    def test_rejects_empty_scenarios(self):
        with self.assertRaises(ValueError):
            ScenarioForecast(
                instrument="NASDAQ:NVDA",
                decision_at=stamp("2026-11-28T10:00:00Z"),
                scenarios=(),
            )

    def test_prediction_variance_helper(self):
        self.assertAlmostEqual(
            prediction_variance(
                [Scenario("up", 0.5, 0.10), Scenario("down", 0.5, -0.10)]
            ),
            0.01,
            places=9,
        )


class PredictionScorecardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scorecard = PredictionScorecard()
        # Three bullish calls (prob >= 0.5), two realized up, one down.
        self.scorecard.add(0.8, 0.05)
        self.scorecard.add(0.7, 0.02)
        self.scorecard.add(0.6, -0.03)
        # Two bearish calls (prob < 0.5), both realized down.
        self.scorecard.add(0.3, -0.04)
        self.scorecard.add(0.2, -0.06)

    def test_brier_score(self):
        # Outcomes: up, up, down, down, down -> 1,1,0,0,0
        expected = ((0.8 - 1) ** 2 + (0.7 - 1) ** 2 + (0.6 - 0) ** 2
                    + (0.3 - 0) ** 2 + (0.2 - 0) ** 2) / 5
        self.assertAlmostEqual(self.scorecard.brier_score(), expected, places=9)

    def test_direction_accuracy(self):
        # Predicted up: first three (two up, one down) -> 2 correct.
        # Predicted down: last two (both down) -> 2 correct. Total 4/5.
        self.assertAlmostEqual(self.scorecard.direction_accuracy(), 0.8, places=9)

    def test_log_loss_is_finite_and_positive(self):
        value = self.scorecard.log_loss()
        self.assertGreater(value, 0.0)
        self.assertTrue(math_isfinite(value))

    def test_calibration_bins_are_sorted(self):
        calibration = self.scorecard.calibration(bins=5)
        centers = [row[0] for row in calibration]
        self.assertEqual(centers, sorted(centers))
        self.assertTrue(all(row[2] > 0 for row in calibration))

    def test_summary_keys(self):
        summary = self.scorecard.summary()
        self.assertEqual(
            set(summary),
            {"brier_score", "log_loss", "direction_accuracy", "count"},
        )
        self.assertEqual(summary["count"], 5.0)

    def test_rejects_out_of_range_probability(self):
        with self.assertRaises(ValueError):
            self.scorecard.add(1.5, 0.01)

    def test_empty_scorecard_raises(self):
        empty = PredictionScorecard()
        with self.assertRaises(ValueError):
            empty.brier_score()


def math_isfinite(value: float) -> bool:
    import math

    return math.isfinite(value)


if __name__ == "__main__":
    unittest.main()
