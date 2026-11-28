"""Deep learning: backpropagation, MLPs, CNNs, RNNs.

Stdlib-only. Pure computation with numpy-style arrays implemented
from scratch using Python lists.

Core concepts:
- Activation functions and their derivatives
- Fully connected layers and matrix operations
- Backpropagation through a multilayer perceptron
- Convolutional layers (2D)
- Recurrent layers (vanilla RNN) and backpropagation through time
- Gradient descent training loop
"""

from __future__ import annotations

import math
import random

from research.training.math.foundations import (
    mat_multiply,
    mat_transpose,
)


# ===========================================================================
# Activation functions
# ===========================================================================

def sigmoid(x: float) -> float:
    """Sigmoid activation."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def sigmoid_derivative(x: float) -> float:
    """Derivative of sigmoid at x: sigmoid(x) * (1 - sigmoid(x))."""
    s = sigmoid(x)
    return s * (1.0 - s)


def tanh_activation(x: float) -> float:
    """Hyperbolic tangent activation."""
    return math.tanh(x)


def tanh_derivative(x: float) -> float:
    """Derivative of tanh at x: 1 - tanh(x)^2."""
    t = math.tanh(x)
    return 1.0 - t * t


def relu(x: float) -> float:
    """ReLU activation."""
    return max(0.0, x)


def relu_derivative(x: float) -> float:
    """Derivative of ReLU at x."""
    return 1.0 if x > 0 else 0.0


def softmax_row(row: list[float]) -> list[float]:
    """Numerically stable softmax of a 1D array."""
    max_val = max(row)
    exps = [math.exp(v - max_val) for v in row]
    total = sum(exps)
    return [e / total for e in exps]


def softmax_rows(X: list[list[float]]) -> list[list[float]]:
    """Softmax applied to each row of a 2D array."""
    return [softmax_row(row) for row in X]


# ===========================================================================
# Layer operations
# ===========================================================================

def add_bias(X: list[list[float]], bias: list[float]) -> list[list[float]]:
    """Add a bias vector to each row of X."""
    return [[X[i][j] + bias[j] for j in range(len(bias))] for i in range(len(X))]


def layer_forward(
    X: list[list[float]], weights: list[list[float]], bias: list[float], activation
) -> list[list[float]]:
    """Forward pass through a fully connected layer.

    X: (batch, input_dim)
    weights: (output_dim, input_dim)
    bias: (output_dim,)
    activation: function applied element-wise
    """
    Wt = mat_transpose(weights)
    raw = mat_multiply(X, Wt)  # (batch, output_dim)
    with_bias = add_bias(raw, bias)
    return [[activation(v) for v in row] for row in with_bias]


# ===========================================================================
# Multilayer Perceptron
# ===========================================================================

class MLP:
    """A multilayer perceptron with configurable hidden layers.

    Uses ReLU activation for hidden layers and softmax for output.
    Supports backpropagation and gradient descent training.
    """

    def __init__(
        self,
        layer_sizes: list[int],
        seed: int = 42,
        learning_rate: float = 0.01,
    ):
        self.layer_sizes = list(layer_sizes)
        self.learning_rate = learning_rate
        self.rng = random.Random(seed)

        # Initialize weights (He initialization for ReLU)
        self.weights: list[list[list[float]]] = []
        self.biases: list[list[float]] = []

        for i in range(len(layer_sizes) - 1):
            in_dim = layer_sizes[i]
            out_dim = layer_sizes[i + 1]
            # He initialization: std = sqrt(2 / in_dim)
            std = math.sqrt(2.0 / in_dim)
            w = [[self.rng.gauss(0.0, std) for _ in range(in_dim)] for _ in range(out_dim)]
            b = [0.0] * out_dim
            self.weights.append(w)
            self.biases.append(b)

        self.cache: dict = {}

    def forward(self, X: list[list[float]]) -> list[list[float]]:
        """Forward pass through the entire network."""
        self.cache = {"X": X, "activations": [list(X)], "z_values": []}
        current = list(X)
        n_layers = len(self.weights)

        for i in range(n_layers):
            is_last = i == n_layers - 1
            if is_last:
                # Output layer: linear then softmax
                Wt = mat_transpose(self.weights[i])
                raw = mat_multiply(current, Wt)
                with_bias = add_bias(raw, self.biases[i])
                current = softmax_rows(with_bias)
                self.cache["z_values"].append(with_bias)
            else:
                # Hidden layer: ReLU
                Wt = mat_transpose(self.weights[i])
                raw = mat_multiply(current, Wt)
                with_bias = add_bias(raw, self.biases[i])
                current = [[relu(v) for v in row] for row in with_bias]
                self.cache["z_values"].append(with_bias)

            self.cache["activations"].append(list(current))

        return current

    def predict(self, X: list[list[float]]) -> list[int]:
        """Return predicted class labels."""
        outputs = self.forward(X)
        return [max(range(len(row)), key=lambda i: row[i]) for row in outputs]

    def _softmax_cross_entropy_grad(
        self, output: list[list[float]], labels: list[int]
    ) -> list[list[float]]:
        """Gradient of softmax cross-entropy at the output layer.

        dL/dz = softmax(z) - one_hot(label)
        """
        batch = len(output)
        grad: list[list[float]] = []
        for i in range(batch):
            row = list(output[i])
            row[labels[i]] -= 1.0
            grad.append(row)
        return grad

    def backward(self, labels: list[int]) -> tuple[list, list]:
        """Backpropagation: compute gradients for all weights and biases."""
        batch = len(labels)
        activations = self.cache["activations"]
        z_values = self.cache["z_values"]
        n_layers = len(self.weights)

        grads_w: list[list[list[float]]] = []
        grads_b: list[list[float]] = []

        # Output layer gradient
        output = activations[-1]
        delta = self._softmax_cross_entropy_grad(output, labels)

        # Backpropagate through layers
        for i in reversed(range(n_layers)):
            a_prev = activations[i]
            # Gradient for weights: delta^T * a_prev / batch
            # delta: (batch, out_dim), a_prev: (batch, in_dim)
            # grad_w = delta^T * a_prev  -> (out_dim, in_dim)
            delta_t = mat_transpose(delta)
            grad_w = mat_multiply(delta_t, a_prev)
            # Scale by batch
            grad_w = [[g / batch for g in row] for row in grad_w]

            # Gradient for biases: average over batch -> list of floats
            grad_b = [
                sum(row[c] for row in delta) / batch
                for c in range(len(delta[0]) if delta else 0)
            ]

            grads_w.insert(0, grad_w)
            grads_b.insert(0, grad_b)

            # Propagate delta to previous layer (if not first)
            if i > 0:
                # delta_prev = (delta * W) * ReLU'(z_prev)
                W = self.weights[i]
                # delta * W: (batch, out_dim) * (out_dim, in_dim) = (batch, in_dim)
                delta_w = mat_multiply(delta, W)
                z_prev = z_values[i - 1]
                # ReLU derivative
                delta = [
                    [delta_w[r][c] * relu_derivative(z_prev[r][c]) for c in range(len(delta_w[r]))]
                    for r in range(len(delta_w))
                ]

        return grads_w, grads_b

    def train_step(
        self, X: list[list[float]], labels: list[int]
    ) -> float:
        """One gradient descent step. Returns the loss."""
        output = self.forward(X)
        # Cross-entropy loss
        loss = 0.0
        for i, label in enumerate(labels):
            loss -= math.log(max(output[i][label], 1e-12))
        loss /= len(labels)

        grads_w, grads_b = self.backward(labels)

        # Update weights and biases
        for i in range(len(self.weights)):
            self.weights[i] = [
                [self.weights[i][r][c] - self.learning_rate * grads_w[i][r][c]
                 for c in range(len(self.weights[i][r]))]
                for r in range(len(self.weights[i]))
            ]
            self.biases[i] = [
                self.biases[i][c] - self.learning_rate * grads_b[i][c]
                for c in range(len(self.biases[i]))
            ]

        return loss

    def train(
        self,
        X: list[list[float]],
        labels: list[int],
        epochs: int = 100,
    ) -> list[float]:
        """Train the MLP for multiple epochs. Returns loss history."""
        losses = []
        for _ in range(epochs):
            loss = self.train_step(X, labels)
            losses.append(loss)
        return losses

    def accuracy(self, X: list[list[float]], labels: list[int]) -> float:
        """Compute accuracy on a dataset."""
        preds = self.predict(X)
        correct = sum(1 for i in range(len(labels)) if preds[i] == labels[i])
        return correct / len(labels) if labels else 0.0


# ===========================================================================
# 2D Convolution
# ===========================================================================

def conv2d_forward(
    input_2d: list[list[float]],
    kernel: list[list[float]],
    stride: int = 1,
    padding: int = 0,
) -> list[list[float]]:
    """2D convolution (single input channel, single output channel).

    input_2d: (H, W)
    kernel: (Kh, Kw)
    Returns: (H_out, W_out)
    """
    H = len(input_2d)
    W = len(input_2d[0]) if H > 0 else 0
    Kh = len(kernel)
    Kw = len(kernel[0]) if Kh > 0 else 0

    H_pad = H + 2 * padding
    W_pad = W + 2 * padding
    padded = [[0.0] * W_pad for _ in range(H_pad)]
    for i in range(H):
        for j in range(W):
            padded[i + padding][j + padding] = input_2d[i][j]

    H_out = (H_pad - Kh) // stride + 1
    W_out = (W_pad - Kw) // stride + 1
    output = [[0.0] * W_out for _ in range(H_out)]

    for i in range(H_out):
        for j in range(W_out):
            val = 0.0
            for k in range(Kh):
                for l in range(Kw):
                    val += padded[i * stride + k][j * stride + l] * kernel[k][l]
            output[i][j] = val

    return output


def pool2d_forward(
    input_2d: list[list[float]],
    pool_size: int = 2,
    stride: int | None = None,
    mode: str = "max",
) -> list[list[float]]:
    """2D pooling (max or average)."""
    if stride is None:
        stride = pool_size
    H = len(input_2d)
    W = len(input_2d[0]) if H > 0 else 0
    H_out = (H - pool_size) // stride + 1
    W_out = (W - pool_size) // stride + 1
    output = [[0.0] * W_out for _ in range(H_out)]

    for i in range(H_out):
        for j in range(W_out):
            region = []
            for k in range(pool_size):
                for l in range(pool_size):
                    region.append(input_2d[i * stride + k][j * stride + l])
            if mode == "max":
                output[i][j] = max(region)
            elif mode == "avg":
                output[i][j] = sum(region) / len(region)
            else:
                raise ValueError(f"Unknown pooling mode: {mode}")

    return output


# ===========================================================================
# Vanilla RNN
# ===========================================================================

class VanillaRNN:
    """A simple vanilla RNN (Elman network) for sequence data.

    h_t = tanh(W_xh * x_t + W_hh * h_{t-1} + b)
    y_t = W_hy * h_t + b_y
    """

    def __init__(
        self,
        input_dim: int,
        hidden_dim: int,
        output_dim: int,
        seed: int = 42,
        learning_rate: float = 0.01,
    ):
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        self.output_dim = output_dim
        self.learning_rate = learning_rate
        self.rng = random.Random(seed)

        # He initialization
        std_x = math.sqrt(2.0 / input_dim)
        std_h = math.sqrt(2.0 / hidden_dim)
        self.W_xh = [[self.rng.gauss(0.0, std_x) for _ in range(input_dim)] for _ in range(hidden_dim)]
        self.W_hh = [[self.rng.gauss(0.0, std_h) for _ in range(hidden_dim)] for _ in range(hidden_dim)]
        self.W_hy = [[self.rng.gauss(0.0, std_h) for _ in range(hidden_dim)] for _ in range(output_dim)]
        self.b_h = [0.0] * hidden_dim
        self.b_y = [0.0] * output_dim

        self.cache: dict = {}

    def _forward_step(
        self, x: list[float], h_prev: list[float]
    ) -> tuple[list[float], list[float]]:
        """Single RNN step."""
        # h = tanh(W_xh * x + W_hh * h_prev + b_h)
        W_xh_x = mat_multiply([x], mat_transpose(self.W_xh))[0]
        W_hh_h = mat_multiply([h_prev], mat_transpose(self.W_hh))[0]
        z = [W_xh_x[i] + W_hh_h[i] + self.b_h[i] for i in range(len(W_xh_x))]
        h = [tanh_activation(v) for v in z]
        # y = W_hy * h + b_y
        W_hy_h = mat_multiply([h], mat_transpose(self.W_hy))[0]
        y = [W_hy_h[i] + self.b_y[i] for i in range(len(W_hy_h))]
        return h, y

    def forward(self, sequence: list[list[float]]) -> list[list[float]]:
        """Forward pass through a sequence."""
        h = [0.0] * self.hidden_dim
        hidden_seq: list[list[float]] = []
        output_seq: list[list[float]] = []

        for x in sequence:
            h, y = self._forward_step(x, h)
            hidden_seq.append(list(h))
            output_seq.append(list(y))

        self.cache = {"hidden_seq": hidden_seq, "output_seq": output_seq, "sequence": sequence}
        return output_seq

    def predict(self, sequence: list[list[float]]) -> list[int]:
        """Predict class labels for each timestep."""
        outputs = self.forward(sequence)
        return [max(range(len(row)), key=lambda i: row[i]) for row in outputs]

    def _bptt(
        self, labels: list[int]
    ) -> tuple[list, list, list]:
        """Backpropagation through time."""
        hidden_seq = self.cache["hidden_seq"]
        T = len(hidden_seq)

        # Initialize gradients
        grad_W_hy = [[0.0] * self.hidden_dim for _ in range(self.output_dim)]
        grad_b_y = [0.0] * self.output_dim
        grad_W_xh = [[0.0] * self.input_dim for _ in range(self.hidden_dim)]
        grad_W_hh = [[0.0] * self.hidden_dim for _ in range(self.hidden_dim)]
        grad_b_h = [0.0] * self.hidden_dim

        # Backward pass
        for t in reversed(range(T)):
            y = self.cache["output_seq"][t]
            h = hidden_seq[t]
            label = labels[t]

            # Output layer gradient (softmax cross-entropy)
            dy = list(y)
            dy[label] -= 1.0

            # grad W_hy
            for i in range(self.output_dim):
                for j in range(self.hidden_dim):
                    grad_W_hy[i][j] += dy[i] * h[j]
            # grad b_y
            for i in range(self.output_dim):
                grad_b_y[i] += dy[i]

            # dh = dy^T * W_hy
            dy_W = mat_multiply([dy], self.W_hy)[0]  # (hidden_dim,)

            # Hidden layer gradient
            dh = list(dy_W)

            if t > 0:
                h_prev = hidden_seq[t - 1]
            else:
                h_prev = [0.0] * self.hidden_dim

            # dz = dh * (1 - tanh(z)^2)
            dz = [dh[i] * tanh_derivative(h[i]) for i in range(self.hidden_dim)]

            # grad W_hh
            for i in range(self.hidden_dim):
                for j in range(self.hidden_dim):
                    grad_W_hh[i][j] += dz[i] * h_prev[j]

            # grad W_xh
            x = self.cache["sequence"][t]
            for i in range(self.hidden_dim):
                for j in range(self.input_dim):
                    grad_W_xh[i][j] += dz[i] * x[j]

            # grad b_h
            for i in range(self.hidden_dim):
                grad_b_h[i] += dz[i]

            # Propagate to previous timestep
            if t > 0:
                # dh_prev = dz^T * W_hh
                dh_prev = mat_multiply([dz], self.W_hh)[0]
                for i in range(self.hidden_dim):
                    dh[i] += dh_prev[i]

        # Scale by sequence length
        for mat in [grad_W_hy, grad_W_xh, grad_W_hh]:
            for row in mat:
                for j in range(len(row)):
                    row[j] /= T
        for vec in [grad_b_y, grad_b_h]:
            for i in range(len(vec)):
                vec[i] /= T

        return grad_W_xh, grad_W_hh, grad_W_hy, grad_b_h, grad_b_y

    def train_step(
        self, sequence: list[list[float]], labels: list[int]
    ) -> float:
        """One BPTT training step. Returns the loss."""
        outputs = self.forward(sequence)
        loss = 0.0
        for i, label in enumerate(labels):
            loss -= math.log(max(outputs[i][label], 1e-12))
        loss /= len(labels)

        grads = self._bptt(labels)
        grad_W_xh, grad_W_hh, grad_W_hy, grad_b_h, grad_b_y = grads

        self.W_xh = [
            [self.W_xh[i][j] - self.learning_rate * grad_W_xh[i][j] for j in range(len(self.W_xh[i]))]
            for i in range(len(self.W_xh))
        ]
        self.W_hh = [
            [self.W_hh[i][j] - self.learning_rate * grad_W_hh[i][j] for j in range(len(self.W_hh[i]))]
            for i in range(len(self.W_hh))
        ]
        self.W_hy = [
            [self.W_hy[i][j] - self.learning_rate * grad_W_hy[i][j] for j in range(len(self.W_hy[i]))]
            for i in range(len(self.W_hy))
        ]
        self.b_h = [self.b_h[i] - self.learning_rate * grad_b_h[i] for i in range(len(self.b_h))]
        self.b_y = [self.b_y[i] - self.learning_rate * grad_b_y[i] for i in range(len(self.b_y))]

        return loss
