import unittest

import torch

from model import GoldTemporalNet, class_probabilities


class GoldTemporalNetTests(unittest.TestCase):
    def test_multi_horizon_output_and_probabilities(self):
        model = GoldTemporalNet(feature_count=7, horizon_count=4, dropout=0.0)
        logits = model(torch.randn(3, 32, 7))
        self.assertEqual(tuple(logits.shape), (3, 4, 3))
        probabilities = class_probabilities(logits)
        self.assertTrue(torch.allclose(
            probabilities.sum(dim=-1), torch.ones(3, 4), atol=1e-6
        ))

    def test_rejects_wrong_feature_count(self):
        model = GoldTemporalNet(feature_count=7)
        with self.assertRaises(ValueError):
            model(torch.randn(2, 10, 6))

    def test_rejects_sequence_over_limit(self):
        model = GoldTemporalNet(feature_count=7, max_sequence_length=8)
        with self.assertRaises(ValueError):
            model(torch.randn(2, 9, 7))


if __name__ == "__main__":
    unittest.main()
