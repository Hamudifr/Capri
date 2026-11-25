import unittest

from soft_weights_floor_test import summarize


class SoftWeightFloorTests(unittest.TestCase):
    def test_raw_polynomial_floor_destroys_concentration(self):
        result = summarize(m=20, rounds=150, eta=0.2, n=10)
        self.assertGreater(result["raw_floor_average_loss"], 0.9)
        self.assertLess(result["standard_average_loss"], 1e-5)

    def test_regret_preserving_floor_is_exponentially_small_per_expert(self):
        result = summarize(m=20, rounds=150, eta=0.2, n=10)
        self.assertLess(result["normalized_floor_per_expert"], 1e-7)
        self.assertLess(result["floor_below_precision_ratio"], 1e-5)


if __name__ == "__main__":
    unittest.main()
