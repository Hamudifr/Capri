import unittest

import numpy as np

from labels import make_direction_labels


class DirectionLabelTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(7)
        self.close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.001, 1000)))

    def test_shape_and_per_horizon_future_tail(self):
        horizons = (1, 4, 16, 96)
        labels, valid = make_direction_labels(self.close, horizons=horizons)
        self.assertEqual(labels.shape, (1000, 4))
        self.assertTrue(np.all(labels[valid] >= 0))
        self.assertTrue(np.all(labels[~valid] == -1))
        for column, horizon in enumerate(horizons):
            self.assertFalse(valid[-horizon:, column].any())
            self.assertTrue(valid[96:-horizon, column].all())

    def test_empty_horizons_rejected(self):
        with self.assertRaises(ValueError):
            make_direction_labels(self.close, horizons=())

    def test_non_positive_prices_rejected(self):
        bad = self.close.copy()
        bad[20] = 0.0
        with self.assertRaises(ValueError):
            make_direction_labels(bad)


if __name__ == "__main__":
    unittest.main()
