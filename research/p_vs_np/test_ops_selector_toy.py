import unittest

from ops_selector_toy import (
    find_two_point_antichecker,
    fixed_sample_counterexample,
    subcube_function_class,
    truth_table_bit,
    verify_antichecker,
)


class OpsSelectorToyTests(unittest.TestCase):
    def test_adaptive_pair_refutes_all_subcube_functions(self):
        n, k = 6, 3
        target = 0
        for x in range(1 << n):
            if x.bit_count() & 1:
                target |= 1 << x
        candidates = subcube_function_class(n, k)
        sample = find_two_point_antichecker(target, n, k)
        self.assertEqual(sample[0] & ((1 << k) - 1), sample[1] & ((1 << k) - 1))
        self.assertNotEqual(truth_table_bit(target, sample[0]), truth_table_bit(target, sample[1]))
        self.assertTrue(verify_antichecker(target, candidates, sample))

    def test_fixed_incomplete_sample_can_be_defeated(self):
        n, k = 6, 3
        fixed = (0, 1, 2, 3, 4)
        target = fixed_sample_counterexample(fixed, n, k)
        candidates = subcube_function_class(n, k)
        self.assertTrue(all(truth_table_bit(target, x) == 0 for x in fixed))
        self.assertIn(0, candidates)
        self.assertNotIn(target, candidates)
        self.assertFalse(verify_antichecker(target, candidates, fixed))

    def test_full_domain_sample_cannot_be_defeated(self):
        n, k = 4, 2
        with self.assertRaises(ValueError):
            fixed_sample_counterexample(tuple(range(1 << n)), n, k)


if __name__ == "__main__":
    unittest.main()
