"""Tests for the deep learning training module."""

from __future__ import annotations

import unittest

from research.training.deeplearning import (
    MLP,
    VanillaRNN,
    conv2d_forward,
    pool2d_forward,
    relu,
    relu_derivative,
    sigmoid,
    sigmoid_derivative,
    softmax_row,
    softmax_rows,
    tanh_activation,
    tanh_derivative,
)


class TestActivations(unittest.TestCase):
    def test_sigmoid(self):
        self.assertAlmostEqual(sigmoid(0.0), 0.5)
        self.assertGreater(sigmoid(1.0), 0.5)
        self.assertLess(sigmoid(-1.0), 0.5)

    def test_sigmoid_derivative(self):
        # At x=0, derivative = 0.5 * 0.5 = 0.25
        self.assertAlmostEqual(sigmoid_derivative(0.0), 0.25)

    def test_tanh(self):
        self.assertAlmostEqual(tanh_activation(0.0), 0.0)
        self.assertGreater(tanh_activation(1.0), 0.0)

    def test_tanh_derivative(self):
        # At x=0, derivative = 1 - 0 = 1
        self.assertAlmostEqual(tanh_derivative(0.0), 1.0)

    def test_relu(self):
        self.assertEqual(relu(0.0), 0.0)
        self.assertEqual(relu(-1.0), 0.0)
        self.assertEqual(relu(2.0), 2.0)

    def test_relu_derivative(self):
        self.assertEqual(relu_derivative(1.0), 1.0)
        self.assertEqual(relu_derivative(-1.0), 0.0)

    def test_softmax(self):
        result = softmax_row([1.0, 2.0, 3.0])
        self.assertAlmostEqual(sum(result), 1.0)
        # Larger values get higher probability
        self.assertGreater(result[2], result[0])

    def test_softmax_rows(self):
        result = softmax_rows([[1.0, 2.0], [3.0, 1.0]])
        self.assertEqual(len(result), 2)
        for row in result:
            self.assertAlmostEqual(sum(row), 1.0)


class TestConv2D(unittest.TestCase):
    def test_conv2d_identity(self):
        # 3x3 input, 1x1 kernel = identity (no padding)
        input_2d = [[1.0, 2.0, 3.0],
                    [4.0, 5.0, 6.0],
                    [7.0, 8.0, 9.0]]
        kernel = [[1.0]]
        result = conv2d_forward(input_2d, kernel)
        self.assertEqual(len(result), 3)
        self.assertEqual(len(result[0]), 3)

    def test_conv2d_simple(self):
        # 2x2 input, 2x2 kernel
        input_2d = [[1.0, 2.0], [3.0, 4.0]]
        kernel = [[1.0, 0.0], [0.0, 1.0]]
        result = conv2d_forward(input_2d, kernel)
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]), 1)
        self.assertAlmostEqual(result[0][0], 5.0)  # 1*1 + 4*1

    def test_conv2d_with_padding(self):
        input_2d = [[1.0, 2.0], [3.0, 4.0]]
        kernel = [[1.0, 1.0], [1.0, 1.0]]
        result = conv2d_forward(input_2d, kernel, stride=1, padding=1)
        # 2x2 input + padding 1 + kernel 2, stride 1 -> 3x3 output
        self.assertEqual(len(result), 3)
        self.assertEqual(len(result[0]), 3)
        # Corner covers one real element (padded[1][1]=1) + 3 padded zeros
        self.assertAlmostEqual(result[0][0], 1.0)
        # Center covers the full 2x2 input: 1+2+3+4 = 10
        self.assertAlmostEqual(result[1][1], 10.0)

    def test_conv2d_stride(self):
        input_2d = [[1.0, 2.0, 3.0, 4.0],
                    [5.0, 6.0, 7.0, 8.0],
                    [9.0, 10.0, 11.0, 12.0],
                    [13.0, 14.0, 15.0, 16.0]]
        kernel = [[1.0, 1.0], [1.0, 1.0]]
        result = conv2d_forward(input_2d, kernel, stride=2)
        self.assertEqual(len(result), 2)
        self.assertEqual(len(result[0]), 2)


class TestPool2D(unittest.TestCase):
    def test_max_pool(self):
        input_2d = [[1.0, 2.0, 3.0, 4.0],
                    [5.0, 6.0, 7.0, 8.0],
                    [9.0, 10.0, 11.0, 12.0],
                    [13.0, 14.0, 15.0, 16.0]]
        result = pool2d_forward(input_2d, pool_size=2, mode="max")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][0], 6.0)
        self.assertEqual(result[1][1], 16.0)

    def test_avg_pool(self):
        input_2d = [[1.0, 2.0], [3.0, 4.0]]
        result = pool2d_forward(input_2d, pool_size=2, mode="avg")
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0][0], 2.5)


class TestMLP(unittest.TestCase):
    def test_mlp_forward_shape(self):
        mlp = MLP([2, 4, 2], seed=42)
        X = [[0.0, 0.0], [1.0, 1.0]]
        output = mlp.forward(X)
        self.assertEqual(len(output), 2)
        self.assertEqual(len(output[0]), 2)

    def test_mlp_softmax_sums_to_one(self):
        mlp = MLP([2, 4, 3], seed=42)
        X = [[0.5, 0.3], [1.0, -1.0]]
        output = mlp.forward(X)
        for row in output:
            self.assertAlmostEqual(sum(row), 1.0, places=5)

    def test_mlp_train_xor(self):
        # XOR problem
        X = [[0.0, 0.0], [0.0, 1.0], [1.0, 0.0], [1.0, 1.0]]
        labels = [0, 1, 1, 0]
        mlp = MLP([2, 8, 8, 2], seed=42, learning_rate=0.1)
        losses = mlp.train(X, labels, epochs=500)
        # Loss should decrease
        self.assertLess(losses[-1], losses[0])

    def test_mlp_accuracy(self):
        # Simple linearly separable
        X = [[0.0, 0.0], [0.5, 0.0], [1.0, 0.0],
         [5.0, 5.0], [5.5, 5.0], [6.0, 6.0]]
        labels = [0, 0, 0, 1, 1, 1]
        mlp = MLP([2, 4, 2], seed=42, learning_rate=0.1)
        mlp.train(X, labels, epochs=200)
        acc = mlp.accuracy(X, labels)
        self.assertGreater(acc, 0.8)

    def test_mlp_predict(self):
        mlp = MLP([2, 4, 2], seed=42)
        X = [[0.0, 0.0], [1.0, 1.0]]
        preds = mlp.predict(X)
        self.assertEqual(len(preds), 2)


class TestVanillaRNN(unittest.TestCase):
    def test_rnn_forward_shape(self):
        rnn = VanillaRNN(input_dim=2, hidden_dim=4, output_dim=2, seed=42)
        sequence = [[0.0, 0.0], [1.0, 1.0], [0.5, 0.5]]
        outputs = rnn.forward(sequence)
        self.assertEqual(len(outputs), 3)
        self.assertEqual(len(outputs[0]), 2)

    def test_rnn_predict(self):
        rnn = VanillaRNN(input_dim=2, hidden_dim=4, output_dim=2, seed=42)
        sequence = [[0.0, 0.0], [1.0, 1.0]]
        preds = rnn.predict(sequence)
        self.assertEqual(len(preds), 2)

    def test_rnn_train_step(self):
        rnn = VanillaRNN(input_dim=2, hidden_dim=4, output_dim=2, seed=42, learning_rate=0.01)
        sequence = [[0.0, 0.0], [1.0, 1.0]]
        labels = [0, 1]
        loss = rnn.train_step(sequence, labels)
        self.assertIsInstance(loss, float)


if __name__ == "__main__":
    unittest.main()
