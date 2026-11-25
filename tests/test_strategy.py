import unittest

from capri_core.strategy import (
    StrategyEvaluationError,
    StrategyObservation,
    evaluate_strategies,
)


def cohort(
    *,
    count=20,
    candidate_overrides=None,
    baseline_overrides=None,
):
    candidate_overrides = candidate_overrides or {}
    baseline_overrides = baseline_overrides or {}
    records = []
    for index in range(count):
        task_id = f"task-{index:03d}"
        base = {
            "task_id": task_id,
            "scenario": "research",
            "evidence_ref": f"test://evidence/{task_id}",
            "tool_calls": 5,
            "context_tokens": 1_000,
            "estimated_cost_units": 100,
            "latency_ms": 2_000,
        }
        baseline = dict(base, strategy_id="baseline", outcome="verified_success")
        candidate = dict(base, strategy_id="candidate", outcome="verified_success")
        baseline.update(baseline_overrides.get(index, {}))
        candidate.update(candidate_overrides.get(index, {}))
        records.extend((StrategyObservation(**baseline), StrategyObservation(**candidate)))
    return records


class StrategyEvaluationTests(unittest.TestCase):
    def test_candidate_with_equal_quality_and_lower_cost_is_eligible_for_manual_review(self):
        records = cohort(candidate_overrides={
            index: {"estimated_cost_units": 80} for index in range(20)
        })
        result = evaluate_strategies("baseline", "candidate", records)
        self.assertTrue(result.eligible_for_manual_review)
        self.assertEqual(result.matched_pairs, 20)
        self.assertEqual(result.improved_dimensions, ("estimated_cost_units",))
        self.assertEqual(result.blocked_reasons, ())
        self.assertIn("not a causal proof", result.interpretation)

    def test_higher_verified_success_with_no_resource_regression_is_eligible(self):
        records = cohort(
            baseline_overrides={1: {"outcome": "verified_failure"}},
        )
        result = evaluate_strategies("baseline", "candidate", records)
        self.assertTrue(result.eligible_for_manual_review)
        self.assertIn("verified_success_rate", result.improved_dimensions)

    def test_no_strict_improvement_is_not_a_promotion_signal(self):
        result = evaluate_strategies("baseline", "candidate", cohort())
        self.assertFalse(result.eligible_for_manual_review)
        self.assertEqual(result.improved_dimensions, ())

    def test_safety_regression_blocks_candidate(self):
        records = cohort(candidate_overrides={0: {"safety_violation": True}})
        result = evaluate_strategies("baseline", "candidate", records)
        self.assertFalse(result.eligible_for_manual_review)
        self.assertIn("safety_regression", result.blocked_reasons)

    def test_verified_success_regression_blocks_candidate(self):
        records = cohort(candidate_overrides={0: {"outcome": "verified_failure"}})
        result = evaluate_strategies("baseline", "candidate", records)
        self.assertFalse(result.eligible_for_manual_review)
        self.assertIn("verified_success_regression", result.blocked_reasons)

    def test_each_resource_regression_blocks_candidate(self):
        fields = ("tool_calls", "context_tokens", "estimated_cost_units", "latency_ms")
        for field in fields:
            with self.subTest(field=field):
                records = cohort(candidate_overrides={
                    0: {field: 10_000},
                })
                result = evaluate_strategies("baseline", "candidate", records)
                self.assertFalse(result.eligible_for_manual_review)
                self.assertIn(f"{field}_regression", result.blocked_reasons)

    def test_pairwise_success_regression_cannot_be_hidden_by_another_win(self):
        records = cohort(
            baseline_overrides={0: {"outcome": "verified_failure"}},
            candidate_overrides={1: {"outcome": "verified_failure"}},
        )
        result = evaluate_strategies("baseline", "candidate", records)
        self.assertEqual(
            result.baseline.verified_success_rate,
            result.candidate.verified_success_rate,
        )
        self.assertFalse(result.eligible_for_manual_review)
        self.assertIn("verified_success_pair_regression", result.blocked_reasons)

    def test_pairwise_resource_regression_cannot_be_hidden_by_another_saving(self):
        records = cohort(candidate_overrides={
            0: {"estimated_cost_units": 200},
            1: {"estimated_cost_units": 0},
        })
        result = evaluate_strategies("baseline", "candidate", records)
        self.assertEqual(
            result.baseline.mean_estimated_cost_units,
            result.candidate.mean_estimated_cost_units,
        )
        self.assertFalse(result.eligible_for_manual_review)
        self.assertIn("estimated_cost_units_regression", result.blocked_reasons)

    def test_removing_a_safety_violation_is_a_strict_improvement(self):
        records = cohort(
            baseline_overrides={0: {"safety_violation": True}},
        )
        result = evaluate_strategies("baseline", "candidate", records)
        self.assertTrue(result.eligible_for_manual_review)
        self.assertIn("safety_violations", result.improved_dimensions)

    def test_sample_floor_is_required(self):
        result = evaluate_strategies("baseline", "candidate", cohort(count=19))
        self.assertFalse(result.eligible_for_manual_review)
        self.assertIn("insufficient_matched_pairs", result.blocked_reasons)

    def test_cohorts_must_match_exactly(self):
        records = cohort()
        records.pop(-2)  # remove the baseline record, leaving one candidate-only task
        result = evaluate_strategies("baseline", "candidate", records)
        self.assertFalse(result.eligible_for_manual_review)
        self.assertIn("unmatched_cohort", result.blocked_reasons)
        self.assertEqual(result.baseline_unmatched, 0)
        self.assertEqual(result.candidate_unmatched, 1)

    def test_matched_task_must_have_same_scenario(self):
        records = cohort()
        records[1] = StrategyObservation(
            task_id="task-000", scenario="different", strategy_id="candidate",
            outcome="verified_success", evidence_ref="test://evidence/task-000",
        )
        with self.assertRaisesRegex(StrategyEvaluationError, "same scenario"):
            evaluate_strategies("baseline", "candidate", records)

    def test_duplicate_strategy_task_pair_is_rejected(self):
        records = cohort()
        records.append(records[0])
        with self.assertRaisesRegex(StrategyEvaluationError, "duplicate task_id"):
            evaluate_strategies("baseline", "candidate", records)

    def test_unexpected_strategy_is_rejected(self):
        records = cohort()
        records.append(StrategyObservation(
            task_id="extra", scenario="research", strategy_id="third",
            outcome="verified_success", evidence_ref="test://extra",
        ))
        with self.assertRaisesRegex(StrategyEvaluationError, "unexpected strategy"):
            evaluate_strategies("baseline", "candidate", records)

    def test_evidence_reference_is_mandatory(self):
        records = cohort()
        records[0] = StrategyObservation(
            task_id="task-000", scenario="research", strategy_id="baseline",
            outcome="verified_success", evidence_ref="",
        )
        with self.assertRaisesRegex(StrategyEvaluationError, "evidence_ref"):
            evaluate_strategies("baseline", "candidate", records)

    def test_unverified_outcomes_do_not_count_as_success(self):
        records = cohort(candidate_overrides={
            index: {"outcome": "unverified"} for index in range(20)
        })
        result = evaluate_strategies("baseline", "candidate", records)
        self.assertEqual(result.candidate.verified_success_rate, 0.0)
        self.assertIn("verified_success_regression", result.blocked_reasons)

    def test_invalid_outcome_and_safety_flag_types_are_rejected(self):
        records = cohort()
        records[0] = StrategyObservation(
            task_id="task-000", scenario="research", strategy_id="baseline",
            outcome=[], evidence_ref="test://evidence/task-000",
        )
        with self.assertRaises(StrategyEvaluationError):
            evaluate_strategies("baseline", "candidate", records)
        records = cohort()
        records[0] = StrategyObservation(
            task_id="task-000", scenario="research", strategy_id="baseline",
            outcome="verified_success", evidence_ref="test://evidence/task-000",
            safety_violation=1,
        )
        with self.assertRaises(StrategyEvaluationError):
            evaluate_strategies("baseline", "candidate", records)

    def test_invalid_metric_types_and_ranges_are_rejected(self):
        invalid_values = (True, -1, 1.5, 10**13)
        for value in invalid_values:
            with self.subTest(value=value):
                records = cohort(candidate_overrides={0: {"tool_calls": value}})
                with self.assertRaises(StrategyEvaluationError):
                    evaluate_strategies("baseline", "candidate", records)

    def test_same_strategy_ids_and_invalid_sample_floor_are_rejected(self):
        with self.assertRaises(StrategyEvaluationError):
            evaluate_strategies("same", "same", cohort())
        with self.assertRaises(StrategyEvaluationError):
            evaluate_strategies("baseline", "candidate", cohort(), min_pairs=True)

    def test_cohort_fingerprint_is_order_independent_and_evidence_sensitive(self):
        records = cohort(candidate_overrides={
            index: {"estimated_cost_units": 90} for index in range(20)
        })
        first = evaluate_strategies("baseline", "candidate", records)
        reordered = evaluate_strategies("baseline", "candidate", reversed(records))
        self.assertEqual(first.cohort_sha256, reordered.cohort_sha256)
        self.assertEqual(len(first.cohort_sha256), 64)
        self.assertTrue(all(char in "0123456789abcdef" for char in first.cohort_sha256))

        changed = list(records)
        changed[0] = StrategyObservation(
            task_id="task-000", scenario="research", strategy_id="baseline",
            outcome="verified_success", evidence_ref="test://evidence/changed",
            tool_calls=5, context_tokens=1_000,
            estimated_cost_units=100, latency_ms=2_000,
        )
        changed_result = evaluate_strategies("baseline", "candidate", changed)
        self.assertEqual(first.to_dict()["baseline"], changed_result.to_dict()["baseline"])
        self.assertNotEqual(first.cohort_sha256, changed_result.cohort_sha256)

    def test_cohort_fingerprint_includes_unmatched_observations(self):
        records = cohort()
        records.pop(-2)
        first = evaluate_strategies("baseline", "candidate", records)
        changed = list(records)
        changed[-1] = StrategyObservation(
            task_id="task-019", scenario="research", strategy_id="candidate",
            outcome="verified_success", evidence_ref="test://evidence/changed",
            tool_calls=5, context_tokens=1_000,
            estimated_cost_units=100, latency_ms=2_000,
        )
        second = evaluate_strategies("baseline", "candidate", changed)
        self.assertFalse(first.eligible_for_manual_review)
        self.assertFalse(second.eligible_for_manual_review)
        self.assertNotEqual(first.cohort_sha256, second.cohort_sha256)

    def test_result_is_deterministic_and_does_not_activate_strategy(self):
        records = cohort(candidate_overrides={
            index: {"estimated_cost_units": 90} for index in range(20)
        })
        first = evaluate_strategies("baseline", "candidate", records).to_dict()
        second = evaluate_strategies("baseline", "candidate", reversed(records)).to_dict()
        self.assertEqual(first, second)
        self.assertNotIn("active_strategy", first)
        self.assertNotIn("permissions", first)

    def test_non_iterable_and_string_inputs_are_rejected(self):
        for records in (None, "not records"):
            with self.subTest(records=records):
                with self.assertRaises(StrategyEvaluationError):
                    evaluate_strategies("baseline", "candidate", records)


if __name__ == "__main__":
    unittest.main()
