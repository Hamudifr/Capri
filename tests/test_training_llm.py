"""Tests for the LLM training module."""

import unittest
import math

from research.training.llm.core import (
    softmax, log_softmax, gelu, relu,
    scaled_dot_product_attention, multi_head_attention,
    layer_norm, layer_norm_with_params,
    sinusoidal_positional_encoding, feed_forward, BPETokenizer,
    cross_entropy, kl_divergence, entropy,
    gradient_descent, momentum_descent, adam,
    TransformerBlock,
)


class TestActivations(unittest.TestCase):

    def test_softmax_sums_to_one(self):
        result = softmax([1.0, 2.0, 3.0])
        self.assertAlmostEqual(sum(result), 1.0, places=10)

    def test_softmax_monotonic(self):
        result = softmax([0.0, 1.0, 2.0])
        self.assertGreater(result[2], result[1])
        self.assertGreater(result[1], result[0])

    def test_softmax_large_values(self):
        # Should not overflow
        result = softmax([100.0, 200.0, 300.0])
        self.assertAlmostEqual(sum(result), 1.0, places=10)

    def test_log_softmax(self):
        result = log_softmax([1.0, 2.0])
        # exp(log_softmax) should equal softmax
        softmax_result = softmax([1.0, 2.0])
        for i in range(2):
            self.assertAlmostEqual(math.exp(result[i]), softmax_result[i], places=8)

    def test_gelu_zero(self):
        self.assertAlmostEqual(gelu(0.0), 0.0, places=8)

    def test_gelu_positive(self):
        self.assertGreater(gelu(1.0), 0.5)

    def test_relu(self):
        self.assertEqual(relu(-1.0), 0.0)
        self.assertEqual(relu(2.0), 2.0)
        self.assertEqual(relu(0.0), 0.0)


class TestAttention(unittest.TestCase):

    def test_scaled_dot_product_attention_shapes(self):
        q = [[1.0, 0.0], [0.0, 1.0]]
        k = [[1.0, 0.0], [0.0, 1.0]]
        v = [[1.0, 0.0], [0.0, 1.0]]
        output, weights = scaled_dot_product_attention(q, k, v)
        self.assertEqual(len(output), 2)
        self.assertEqual(len(output[0]), 2)
        self.assertEqual(len(weights), 2)
        self.assertEqual(len(weights[0]), 2)

    def test_attention_weights_sum_to_one(self):
        q = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
        k = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
        v = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
        _, weights = scaled_dot_product_attention(q, k, v)
        for w in weights:
            self.assertAlmostEqual(sum(w), 1.0, places=8)

    def test_multi_head_attention_shape(self):
        d_model = 4
        num_heads = 2
        seq = 3
        q = [[1.0, 0.0, 0.0, 1.0] for _ in range(seq)]
        k = [[1.0, 0.0, 0.0, 1.0] for _ in range(seq)]
        v = [[1.0, 0.0, 0.0, 1.0] for _ in range(seq)]
        output = multi_head_attention(q, k, v, num_heads)
        self.assertEqual(len(output), seq)
        self.assertEqual(len(output[0]), d_model)

    def test_multi_head_invalid(self):
        q = [[1.0, 0.0, 0.0]]
        k = [[1.0, 0.0, 0.0]]
        v = [[1.0, 0.0, 0.0]]
        # 3 not divisible by 2
        result = multi_head_attention(q, k, v, 2)
        self.assertEqual(result, [])


class TestLayerNorm(unittest.TestCase):

    def test_layer_norm_zero_mean(self):
        norm, m, v = layer_norm([1.0, 2.0, 3.0])
        self.assertAlmostEqual(sum(norm), 0.0, places=8)

    def test_layer_norm_unit_variance(self):
        norm, m, v = layer_norm([1.0, 2.0, 3.0, 4.0])
        computed_var = sum(x * x for x in norm) / len(norm)
        self.assertAlmostEqual(computed_var, 1.0, places=4)

    def test_layer_norm_with_params(self):
        gamma = [1.0, 1.0, 1.0]
        beta = [0.0, 0.0, 0.0]
        result = layer_norm_with_params([1.0, 2.0, 3.0], gamma, beta)
        norm_no_params, _, _ = layer_norm([1.0, 2.0, 3.0])
        for i in range(3):
            self.assertAlmostEqual(result[i], norm_no_params[i], places=8)


class TestPositionalEncoding(unittest.TestCase):

    def test_shape(self):
        pe = sinusoidal_positional_encoding(10, 8)
        self.assertEqual(len(pe), 10)
        self.assertEqual(len(pe[0]), 8)

    def test_position_zero(self):
        pe = sinusoidal_positional_encoding(5, 4)
        # At position 0, sin(0) = 0 for even indices
        self.assertAlmostEqual(pe[0][0], 0.0, places=8)

    def test_no_overflow(self):
        pe = sinusoidal_positional_encoding(100, 64)
        for row in pe:
            for val in row:
                self.assertGreater(val, -2)
                self.assertLess(val, 2)


class TestTokenization(unittest.TestCase):

    def test_bpe_trains(self):
        text = "the cat sat on the mat the cat sat on the log"
        tokenizer = BPETokenizer(vocab_size=50)
        tokenizer.train(text)
        self.assertGreater(len(tokenizer.merges), 0)

    def test_bpe_encode_known(self):
        text = "the cat the cat the cat"
        tokenizer = BPETokenizer(vocab_size=30)
        tokenizer.train(text)
        tokens = tokenizer.encode(text)
        self.assertGreater(len(tokens), 0)

    def test_bpe_reproducible(self):
        text = "hello world hello world hello world"
        t1 = BPETokenizer(vocab_size=20)
        t1.train(text)
        t2 = BPETokenizer(vocab_size=20)
        t2.train(text)
        self.assertEqual(t1.merges, t2.merges)


class TestLoss(unittest.TestCase):

    def test_cross_entropy_correct(self):
        # If target matches the max logit, loss should be small
        logits = [2.0, 1.0, 0.5]
        loss = cross_entropy(logits, 0)
        self.assertLess(loss, 1.0)

    def test_cross_entropy_wrong(self):
        # If target is the smallest logit, loss should be large
        logits = [2.0, 1.0, 0.5]
        loss = cross_entropy(logits, 2)
        self.assertGreater(loss, 1.0)

    def test_kl_divergence_zero(self):
        # KL(p||p) = 0
        p = [0.2, 0.3, 0.5]
        self.assertAlmostEqual(kl_divergence(p, p), 0.0, places=8)

    def test_kl_divergence_positive(self):
        p = [0.5, 0.5]
        q = [0.1, 0.9]
        self.assertGreater(kl_divergence(p, q), 0.0)

    def test_entropy_uniform(self):
        # Uniform distribution has maximum entropy
        p = [0.25, 0.25, 0.25, 0.25]
        self.assertAlmostEqual(entropy(p), math.log(4), places=6)

    def test_entropy_zero(self):
        # Deterministic distribution has zero entropy
        p = [1.0, 0.0, 0.0]
        self.assertAlmostEqual(entropy(p), 0.0, places=8)


class TestOptimization(unittest.TestCase):

    def test_gradient_descent_quadratic(self):
        f = lambda x: sum(v ** 2 for v in x)
        grad_f = lambda x: [2 * v for v in x]
        x0 = [10.0, -5.0]
        result, _ = gradient_descent(f, grad_f, x0, learning_rate=0.1, max_iters=500)
        self.assertLess(abs(result[0]), 0.01)
        self.assertLess(abs(result[1]), 0.01)

    def test_momentum_descent_quadratic(self):
        f = lambda x: sum(v ** 2 for v in x)
        grad_f = lambda x: [2 * v for v in x]
        x0 = [5.0, 3.0]
        result, _ = momentum_descent(f, grad_f, x0, learning_rate=0.1, max_iters=500)
        self.assertLess(abs(result[0]), 0.01)
        self.assertLess(abs(result[1]), 0.01)

    def test_adam_quadratic(self):
        f = lambda x: sum(v ** 2 for v in x)
        grad_f = lambda x: [2 * v for v in x]
        x0 = [8.0, -3.0]
        result, _ = adam(f, grad_f, x0, learning_rate=0.1, max_iters=500)
        self.assertLess(abs(result[0]), 0.01)
        self.assertLess(abs(result[1]), 0.01)


class TestFeedForward(unittest.TestCase):

    def test_feed_forward_shape(self):
        d_model = 4
        d_ff = 8
        w1 = [[0.1] * d_ff for _ in range(d_model)]
        b1 = [0.0] * d_ff
        w2 = [[0.1] * d_model for _ in range(d_ff)]
        b2 = [0.0] * d_model
        result = feed_forward([1.0, 0.0, 0.0, 0.0], w1, b1, w2, b2)
        self.assertEqual(len(result), d_model)

    def test_feed_forward_zero_input(self):
        d_model = 3
        d_ff = 6
        # Zero weights and biases → GELU(0) = 0 → output 0
        w1 = [[0.0] * d_ff for _ in range(d_model)]
        b1 = [0.0] * d_ff
        w2 = [[0.0] * d_model for _ in range(d_ff)]
        b2 = [0.0] * d_model
        result = feed_forward([0.0, 0.0, 0.0], w1, b1, w2, b2)
        for v in result:
            self.assertAlmostEqual(v, 0.0, places=8)


class TestTransformerBlock(unittest.TestCase):

    def test_forward_shape(self):
        block = TransformerBlock(d_model=4, d_ff=8, num_heads=2)
        x = [[1.0, 2.0, 3.0, 4.0]]
        result = block.forward(x)
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]), 4)

    def test_forward_adds_positional(self):
        block = TransformerBlock(d_model=4, d_ff=8, num_heads=2)
        x = [[0.0, 0.0, 0.0, 0.0]]
        result = block.forward(x)
        # With zero input, output should be the positional encoding
        pe = block.pe[0]
        for i in range(4):
            self.assertAlmostEqual(result[0][i], pe[i], places=8)

    def test_forward_multi_length(self):
        block = TransformerBlock(d_model=4, d_ff=8, num_heads=2)
        x = [[1.0] * 4, [2.0] * 4, [3.0] * 4]
        result = block.forward(x)
        self.assertEqual(len(result), 3)
        for row in result:
            self.assertEqual(len(row), 4)


if __name__ == "__main__":
    unittest.main()
