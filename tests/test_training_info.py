"""Tests for the information theory training module."""

import unittest
import math

from research.training.info.theory import (
    shannon_entropy, joint_entropy, marginal_probs,
    conditional_entropy, mutual_information,
    normalized_mutual_information, information_gain,
    kl_divergence_bits, cross_entropy_bits, entropy_from_counts,
    HuffmanCoder, mutual_information_feature,
)


class TestEntropy(unittest.TestCase):

    def test_shannon_entropy_uniform(self):
        # Uniform over 4 symbols → 2 bits
        self.assertAlmostEqual(shannon_entropy([0.25, 0.25, 0.25, 0.25]), 2.0, places=8)

    def test_shannon_entropy_deterministic(self):
        # Deterministic → 0 bits
        self.assertAlmostEqual(shannon_entropy([1.0, 0.0, 0.0]), 0.0, places=8)

    def test_shannon_entropy_binary(self):
        # Binary entropy at p=0.5 → 1 bit
        self.assertAlmostEqual(shannon_entropy([0.5, 0.5]), 1.0, places=8)

    def test_entropy_from_counts(self):
        # 4 symbols each appearing once → 2 bits
        self.assertAlmostEqual(entropy_from_counts([1, 1, 1, 1]), 2.0, places=8)


class TestJointEntropy(unittest.TestCase):

    def test_joint_entropy_independent(self):
        # Independent X (2 symbols) and Y (2 symbols)
        # Joint probs: each (x,y) pair has prob 0.25
        joint = [((0, 0), 0.25), ((0, 1), 0.25),
                 ((1, 0), 0.25), ((1, 1), 0.25)]
        self.assertAlmostEqual(joint_entropy(joint), 2.0, places=8)

    def test_marginal_probs(self):
        joint = [((0, 0), 0.2), ((0, 1), 0.3),
                 ((1, 0), 0.1), ((1, 1), 0.4)]
        px = marginal_probs(joint, 0)
        py = marginal_probs(joint, 1)
        self.assertAlmostEqual(px[0], 0.5, places=8)
        self.assertAlmostEqual(px[1], 0.5, places=8)
        self.assertAlmostEqual(py[0], 0.3, places=8)
        self.assertAlmostEqual(py[1], 0.7, places=8)

    def test_conditional_entropy_zero(self):
        # Y is a function of X → H(Y|X) = 0
        joint = [((0, 0), 0.5), ((1, 1), 0.5)]
        h_cond = conditional_entropy(joint)
        self.assertAlmostEqual(h_cond, 0.0, places=8)


class TestMutualInformation(unittest.TestCase):

    def test_mi_independent(self):
        # Independent variables → MI = 0
        joint = [((0, 0), 0.25), ((0, 1), 0.25),
                 ((1, 0), 0.25), ((1, 1), 0.25)]
        self.assertAlmostEqual(mutual_information(joint), 0.0, places=8)

    def test_mi_identical(self):
        # X = Y → MI = H(X)
        joint = [((0, 0), 0.5), ((1, 1), 0.5)]
        mi = mutual_information(joint)
        h_x = shannon_entropy([0.5, 0.5])
        self.assertAlmostEqual(mi, h_x, places=8)

    def test_normalized_mi_independent(self):
        joint = [((0, 0), 0.25), ((0, 1), 0.25),
                 ((1, 0), 0.25), ((1, 1), 0.25)]
        self.assertAlmostEqual(normalized_mutual_information(joint), 0.0, places=8)

    def test_normalized_mi_identical(self):
        joint = [((0, 0), 0.5), ((1, 1), 0.5)]
        self.assertAlmostEqual(normalized_mutual_information(joint), 1.0, places=8)

    def test_information_gain(self):
        # IG = H(X) - H(X|Y) = MI
        joint = [((0, 0), 0.5), ((1, 1), 0.5)]
        ig = information_gain(joint)
        mi = mutual_information(joint)
        self.assertAlmostEqual(ig, mi, places=8)


class TestDivergence(unittest.TestCase):

    def test_kl_divergence_zero(self):
        p = [0.2, 0.3, 0.5]
        self.assertAlmostEqual(kl_divergence_bits(p, p), 0.0, places=8)

    def test_kl_divergence_positive(self):
        p = [0.5, 0.5]
        q = [0.1, 0.9]
        self.assertGreater(kl_divergence_bits(p, q), 0.0)

    def test_cross_entropy(self):
        p = [0.5, 0.5]
        q = [0.5, 0.5]
        # H(p,q) = H(p) = 1 bit when p == q
        self.assertAlmostEqual(cross_entropy_bits(p, q), 1.0, places=8)

    def test_cross_entropy_deterministic(self):
        p = [1.0, 0.0]
        q = [0.9, 0.1]
        # H(p,q) = -1*log2(0.9) - 0 = -log2(0.9)
        self.assertAlmostEqual(cross_entropy_bits(p, q), -math.log2(0.9), places=8)


class TestHuffman(unittest.TestCase):

    def test_build_and_encode(self):
        freqs = {"a": 5, "b": 3, "c": 2, "d": 1}
        coder = HuffmanCoder().build(freqs)
        message = "abc"
        encoded = coder.encode(message)
        decoded = coder.decode(encoded)
        self.assertEqual(decoded, message)

    def test_huffman_roundtrip(self):
        freqs = {"a": 4, "b": 3, "c": 2, "d": 1, "e": 1}
        coder = HuffmanCoder().build(freqs)
        message = "aabbccde"
        encoded = coder.encode(message)
        decoded = coder.decode(encoded)
        self.assertEqual(decoded, message)

    def test_huffman_prefix_free(self):
        freqs = {"a": 1, "b": 1}
        coder = HuffmanCoder().build(freqs)
        # One symbol must be "0" and the other "1"
        codes = sorted(coder.codes.values())
        self.assertEqual(codes, ["0", "1"])

    def test_average_code_length(self):
        freqs = {"a": 5, "b": 3, "c": 2, "d": 1}
        coder = HuffmanCoder().build(freqs)
        avg_len = coder.average_code_length(freqs)
        # Should be less than naive fixed-length (2 bits for 4 symbols)
        self.assertLess(avg_len, 2.0)
        self.assertGreater(avg_len, 0.0)


class TestFeatureSelection(unittest.TestCase):

    def test_mutual_information_feature(self):
        # Feature 1 perfectly predicts target, feature 2 is noise
        features = [
            [0, 0, 1, 1],   # feature 1: correlates with target
            [1, 0, 1, 0],   # feature 2: random
        ]
        target = [0, 0, 1, 1]
        results = mutual_information_feature(features, target)
        self.assertGreater(results[0], 0.0)
        # Feature 1 should have higher MI than feature 2
        self.assertGreater(results[0], results[1])


if __name__ == "__main__":
    unittest.main()
