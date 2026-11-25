"""Regression tests for deterministic strategy evaluation replay."""
import unittest
from dataclasses import replace

from capri_core.strategy import (
    StrategyEvaluationError,
    StrategyObservation,
    evaluate_strategies,
    verify_strategy_evaluation,
)


def records():
    result = []
    for index in range(20):
        common = {
            "task_id": f"task-{index:03d}",
            "scenario": "research",
            "evidence_ref": f"test://evidence/{index}",
            "tool_calls": 5,
            "context_tokens": 1000,
            "estimated_cost_units": 100,
            "latency_ms": 2000,
        }
        result.append(StrategyObservation(
            **common, strategy_id="baseline", outcome="verified_success"
        ))
        result.append(StrategyObservation(
            **{**common, "estimated_cost_units": 80},
            strategy_id="candidate", outcome="verified_success"
        ))
    return result


class StrategyReplayVerificationTests(unittest.TestCase):
    def test_exact_result_replays_with_reordered_inputs(self):
        observations = records()
        expected = evaluate_strategies("baseline", "candidate", observations)
        self.assertTrue(verify_strategy_evaluation(
            expected, "baseline", "candidate", reversed(observations)
        ))

    def test_tampered_result_is_rejected(self):
        observations = records()
        expected = evaluate_strategies("baseline", "candidate", observations)
        tampered = replace(expected, eligible_for_manual_review=False)
        self.assertFalse(verify_strategy_evaluation(
            tampered, "baseline", "candidate", observations
        ))

    def test_changed_evidence_reference_is_rejected(self):
        observations = records()
        expected = evaluate_strategies("baseline", "candidate", observations)
        observations[0] = replace(
            observations[0], evidence_ref="test://evidence/changed"
        )
        self.assertFalse(verify_strategy_evaluation(
            expected, "baseline", "candidate", observations
        ))

    def test_untyped_expected_result_fails_closed(self):
        with self.assertRaises(StrategyEvaluationError):
            verify_strategy_evaluation(
                {}, "baseline", "candidate", records()
            )


if __name__ == "__main__":
    unittest.main()
