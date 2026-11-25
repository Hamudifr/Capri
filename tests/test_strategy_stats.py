import unittest

from capri_core.strategy_stats import paired_success_interval


class PairedSuccessIntervalTests(unittest.TestCase):
    def test_equal_outcomes_have_zero_delta_and_bounded_interval(self):
        result = paired_success_interval([True] * 20, [True] * 20)
        self.assertEqual(result.success_delta, 0.0)
        self.assertLessEqual(result.lower_95, 0.0)
        self.assertGreaterEqual(result.upper_95, 0.0)
        self.assertEqual(result.sample_size, 20)

    def test_candidate_wins_are_positive_but_small_sample_interval_is_wide(self):
        result = paired_success_interval([False] * 20, [True] * 20)
        self.assertEqual(result.success_delta, 1.0)
        self.assertGreater(result.lower_95, 0.0)
        self.assertEqual(result.upper_95, 1.0)

    def test_candidate_losses_are_negative(self):
        result = paired_success_interval([True] * 20, [False] * 20)
        self.assertEqual(result.success_delta, -1.0)
        self.assertEqual(result.lower_95, -1.0)
        self.assertLess(result.upper_95, 0.0)

    def test_rejects_mismatched_empty_and_non_boolean_pairs(self):
        for baseline, candidate in (([], []), ([True], []), ([1], [True])):
            with self.subTest(baseline=baseline, candidate=candidate):
                with self.assertRaises(ValueError):
                    paired_success_interval(baseline, candidate)

    def test_rejects_oversized_cohort(self):
        with self.assertRaisesRegex(ValueError, "20000"):
            paired_success_interval([True] * 20_001, [True] * 20_001)


if __name__ == "__main__":
    unittest.main()
