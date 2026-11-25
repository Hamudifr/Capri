import unittest

from capri_core.strategy import StrategyObservation
from capri_core.strategy_promotion import (
    PromotionCohort,
    StrategyPromotionError,
    assess_strategy_canary,
)


def make_cohorts(
    *,
    cohort_count=2,
    scenario_count=5,
    pairs_per_scenario=20,
    improved_pairs=100,
    regression_at=None,
    version_override=None,
    shared_task_ids=False,
):
    cohorts = []
    for cohort_index in range(cohort_count):
        cohort_id = f"cohort-{cohort_index}"
        observations = []
        pair_index = 0
        for scenario_index in range(scenario_count):
            for _ in range(pairs_per_scenario):
                task_suffix = f"task-{pair_index:03d}"
                task_id = task_suffix if shared_task_ids else f"{cohort_id}-{task_suffix}"
                scenario = f"scenario-{scenario_index}"
                candidate_cost = 90 if pair_index < improved_pairs else 100
                if regression_at == pair_index:
                    candidate_cost = 110
                baseline = StrategyObservation(
                    task_id=task_id,
                    scenario=scenario,
                    strategy_id="baseline",
                    outcome="verified_success",
                    evidence_ref=f"fixture:{cohort_id}:baseline:{task_id}",
                    tool_calls=5,
                    context_tokens=1000,
                    estimated_cost_units=100,
                    latency_ms=2000,
                    strategy_version="1.0",
                )
                candidate_version = (
                    version_override if version_override is not None and cohort_index == 1
                    else "2.0"
                )
                candidate = StrategyObservation(
                    task_id=task_id,
                    scenario=scenario,
                    strategy_id="candidate",
                    outcome="verified_success",
                    evidence_ref=f"fixture:{cohort_id}:candidate:{task_id}",
                    tool_calls=5,
                    context_tokens=1000,
                    estimated_cost_units=candidate_cost,
                    latency_ms=2000,
                    strategy_version=candidate_version,
                )
                observations.extend((baseline, candidate))
                pair_index += 1
        cohorts.append(PromotionCohort(cohort_id, tuple(observations)))
    return tuple(cohorts)


class StrategyPromotionTests(unittest.TestCase):
    def assess(self, cohorts, **overrides):
        args = {
            "strategy_class": "reasoning",
            "baseline_id": "baseline",
            "candidate_id": "candidate",
            "primary_metric": "estimated_cost_units",
            "cohorts": cohorts,
        }
        args.update(overrides)
        return assess_strategy_canary(**args)

    def test_two_independent_strong_cohorts_qualify_deterministically(self):
        cohorts = make_cohorts()
        first = self.assess(cohorts)
        second = self.assess(cohorts)
        self.assertTrue(first.eligible_for_canary)
        self.assertEqual(first, second)
        self.assertEqual(first.policy_version, "capri.strategy-promotion.v1")
        self.assertEqual(first.baseline_version, "1.0")
        self.assertEqual(first.candidate_version, "2.0")
        self.assertEqual(len(first.cohorts), 2)
        for result in first.cohorts:
            self.assertEqual(result.matched_pairs, 100)
            self.assertEqual(result.scenario_count, 5)
            self.assertGreater(result.lower_95_ci, 0)
            self.assertEqual(result.blocked_reasons, ())
        self.assertFalse(hasattr(first, "activation_grant"))

    def test_single_cohort_cannot_qualify(self):
        result = self.assess(make_cohorts(cohort_count=1))
        self.assertFalse(result.eligible_for_canary)
        self.assertIn("insufficient_independent_cohorts", result.blocked_reasons)

    def test_scenario_coverage_and_per_scenario_floor_are_required(self):
        too_few_scenarios = self.assess(make_cohorts(scenario_count=4, pairs_per_scenario=25))
        self.assertFalse(too_few_scenarios.eligible_for_canary)
        self.assertIn(
            "insufficient_scenario_coverage", too_few_scenarios.blocked_reasons,
        )

        too_few_per_scenario = self.assess(
            make_cohorts(scenario_count=6, pairs_per_scenario=17)
        )
        self.assertFalse(too_few_per_scenario.eligible_for_canary)
        self.assertIn(
            "insufficient_pairs_per_scenario", too_few_per_scenario.blocked_reasons,
        )

    def test_primary_metric_requires_positive_lower_confidence_bound(self):
        result = self.assess(make_cohorts(improved_pairs=1))
        self.assertFalse(result.eligible_for_canary)
        self.assertIn(
            "primary_metric_not_confidently_improved", result.blocked_reasons,
        )

    def test_any_per_task_resource_regression_blocks_canary(self):
        result = self.assess(make_cohorts(regression_at=0))
        self.assertFalse(result.eligible_for_canary)
        self.assertIn("estimated_cost_units_regression", result.blocked_reasons)

    def test_high_risk_or_unknown_strategy_classes_are_rejected(self):
        with self.assertRaises(StrategyPromotionError):
            self.assess(make_cohorts(), strategy_class="payments")

    def test_cohorts_must_not_reuse_task_ids_or_evidence(self):
        result = self.assess(make_cohorts(shared_task_ids=True))
        self.assertFalse(result.eligible_for_canary)
        self.assertIn("overlapping_task_ids_between_cohorts", result.blocked_reasons)

    def test_strategy_versions_must_match_across_cohorts(self):
        result = self.assess(make_cohorts(version_override="2.1"))
        self.assertFalse(result.eligible_for_canary)
        self.assertIn(
            "strategy_versions_differ_between_cohorts", result.blocked_reasons,
        )

    def test_primary_metric_is_allowlisted(self):
        with self.assertRaises(StrategyPromotionError):
            self.assess(make_cohorts(), primary_metric="prompt_tokens")


if __name__ == "__main__":
    unittest.main()
