"""LLM study modules.

Implements the core mathematics and algorithms behind large language
models: attention, softmax, layer normalization, positional encoding,
and tokenization. Pure stdlib, no dependencies.

Topics covered:
- Softmax and log-softmax (numerically stable)
- Scaled dot-product attention (the core of transformers)
- Multi-head attention
- Layer normalization
- Positional encodings (sinusoidal and learned)
- Feed-forward networks
- Tokenization: byte-pair encoding (BPE) merges
- Cross-entropy and KL divergence
- Gradient descent variants for training
- The transformer block assembly
"""

from __future__ import annotations

import math
from collections import defaultdict


# ===========================================================================
# Activation functions
# ===========================================================================

def softmax(logits: list[float]) -> list[float]:
    """Numerically stable softmax."""
    if not logits:
        return []
    max_val = max(logits)
    exp_vals = [math.exp(x - max_val) for x in logits]
    total = sum(exp_vals)
    if total == 0:
        return [0.0] * len(logits)
    return [e / total for e in exp_vals]


def log_softmax(logits: list[float]) -> list[float]:
    """Numerically stable log-softmax."""
    if not logits:
        return []
    max_val = max(logits)
    shifted = [x - max_val for x in logits]
    total = sum(math.exp(x) for x in shifted)
    log_total = math.log(total) if total > 0 else 0.0
    return [x - log_total for x in shifted]


def gelu(x: float) -> float:
    """Gaussian Error Linear Unit (exact formula, using math.erf)."""
    return 0.5 * x * (1.0 + math.erf(x / math.sqrt(2)))


def relu(x: float) -> float:
    return max(0.0, x)


# ===========================================================================
# Attention
# ===========================================================================

def scaled_dot_product_attention(
    query: list[list[float]],
    key: list[list[float]],
    value: list[list[float]],
    mask: list[list[float]] | None = None,
) -> tuple[list[list[float]], list[list[float]]]:
    """Scaled dot-product attention.

    Computes softmax(Q * K^T / sqrt(d_k)) * V.

    Returns (attention_output, attention_weights).
    """
    d_k = len(query[0]) if query else 0
    if d_k == 0:
        return [], []

    # Q * K^T
    qk = mat_multiply(query, mat_transpose(key))

    # Scale
    scale = 1.0 / math.sqrt(d_k)
    scaled = [[x * scale for x in row] for row in qk]

    # Apply mask if provided (set masked positions to very negative)
    if mask is not None:
        for i in range(len(scaled)):
            for j in range(len(scaled[i])):
                if mask[i][j] == 0:
                    scaled[i][j] = -float("inf")

    # Softmax over each row
    weights = [softmax(row) for row in scaled]

    # weights * V
    output = mat_multiply(weights, value)
    return output, weights


def multi_head_attention(
    query: list[list[float]],
    key: list[list[float]],
    value: list[list[float]],
    num_heads: int,
    mask: list[list[float]] | None = None,
) -> list[list[float]]:
    """Multi-head attention: split, scaled dot-product, concatenate.

    For study purposes, this splits the last dimension of Q/K/V into
    num_heads heads and applies scaled dot-product attention per head.
    """
    d_model = len(query[0]) if query else 0
    if d_model == 0 or num_heads == 0 or d_model % num_heads != 0:
        return []

    d_k = d_model // num_heads
    seq_len = len(query)

    # Split into heads: shape [seq, d_model] -> [num_heads, seq, d_k]
    def split_heads(matrix: list[list[float]]) -> list[list[list[float]]]:
        heads = []
        for h in range(num_heads):
            head = []
            for row in matrix:
                head.append(row[h * d_k:(h + 1) * d_k])
            heads.append(head)
        return heads

    q_heads = split_heads(query)
    k_heads = split_heads(key)
    v_heads = split_heads(value)

    # Apply attention per head
    head_outputs = []
    for h in range(num_heads):
        out, _ = scaled_dot_product_attention(q_heads[h], k_heads[h], v_heads[h], mask)
        head_outputs.append(out)

    # Concatenate heads
    result = []
    for i in range(seq_len):
        row = []
        for h in range(num_heads):
            row.extend(head_outputs[h][i])
        result.append(row)

    return result


# ===========================================================================
# Layer normalization
# ===========================================================================

def layer_norm(x: list[float], eps: float = 1e-5) -> tuple[list[float], float, float]:
    """Layer normalization.

    Returns (normalized_vector, mean, variance).
    """
    if not x:
        return [], 0.0, 0.0
    mean_val = sum(x) / len(x)
    var_val = sum((xi - mean_val) ** 2 for xi in x) / len(x)
    norm = [(xi - mean_val) / math.sqrt(var_val + eps) for xi in x]
    return norm, mean_val, var_val


def layer_norm_with_params(x: list[float], gamma: list[float],
                           beta: list[float], eps: float = 1e-5) -> list[float]:
    """Layer normalization with learned scale (gamma) and shift (beta)."""
    norm, _, _ = layer_norm(x, eps)
    return [n * g + b for n, g, b in zip(norm, gamma, beta)]


# ===========================================================================
# Positional encodings
# ===========================================================================

def sinusoidal_positional_encoding(seq_len: int, d_model: int) -> list[list[float]]:
    """Compute sinusoidal positional encodings.

    PE(pos, 2i) = sin(pos / 10000^(2i/d_model))
    PE(pos, 2i+1) = cos(pos / 10000^(2i/d_model))
    """
    pe = [[0.0] * d_model for _ in range(seq_len)]
    for pos in range(seq_len):
        for i in range(d_model):
            if i % 2 == 0:
                pe[pos][i] = math.sin(pos / (10000 ** (2 * i / d_model)))
            else:
                pe[pos][i] = math.cos(pos / (10000 ** (2 * (i - 1) / d_model)))
    return pe


# ===========================================================================
# Feed-forward network
# ===========================================================================

def feed_forward(x: list[float], w1: list[list[float]], b1: list[float],
                 w2: list[list[float]], b2: list[float]) -> list[float]:
    """Two-layer feed-forward: Linear -> GELU -> Linear.

    w1: [d_model, d_ff], b1: [d_ff]
    w2: [d_ff, d_model], b2: [d_model]
    """
    # First linear
    hidden = mat_multiply([x], w1)[0]
    hidden = [h + b for h, b in zip(hidden, b1)]
    # GELU
    hidden = [gelu(h) for h in hidden]
    # Second linear
    output = mat_multiply([hidden], w2)[0]
    output = [o + b for o, b in zip(output, b2)]
    return output


# ===========================================================================
# Tokenization: Byte-Pair Encoding
# ===========================================================================

class BPETokenizer:
    """Byte-Pair Encoding tokenizer (study implementation).

    Trains merges by repeatedly merging the most frequent adjacent
    pair of symbols. Then encodes text by applying the merges in
    priority order.
    """

    def __init__(self, vocab_size: int = 1000):
        self.vocab_size = vocab_size
        self.merges: list[tuple[str, str]] = []
        self.vocab: set[str] = set()

    def train(self, text: str) -> "BPETokenizer":
        """Train BPE merges on the given text."""
        # Initial alphabet: bytes (characters as a simplified proxy)
        words = self._split_to_words(text)
        word_freqs = self._get_word_freqs(words)

        vocab = set()
        for word in words:
            for ch in word:
                vocab.add(ch)

        for _ in range(self.vocab_size - len(vocab)):
            pairs = self._get_pair_freqs(word_freqs)
            if not pairs:
                break
            best_pair, _ = max(pairs, key=lambda x: x[1])
            self.merges.append(best_pair)

            # Apply merge
            new_word_freqs = {}
            for word, freq in word_freqs.items():
                new_word = self._merge_word(word, best_pair)
                new_word_freqs[new_word] = new_word_freqs.get(new_word, 0) + freq
            word_freqs = new_word_freqs

            vocab.add(best_pair[0] + best_pair[1])

        self.vocab = vocab
        return self

    def encode(self, text: str) -> list[str]:
        """Encode text using learned merges."""
        words = self._split_to_words(text)
        result = []
        for word in words:
            result.extend(self._encode_word(word))
        return result

    def _split_to_words(self, text: str) -> list[str]:
        return [w for w in text.split() if w]

    def _get_word_freqs(self, words: list[str]) -> dict[str, int]:
        freqs = defaultdict(int)
        for w in words:
            freqs[w] += 1
        return dict(freqs)

    def _get_pair_freqs(self, word_freqs: dict[str, int]) -> list[tuple[tuple[str, str], int]]:
        pairs = defaultdict(int)
        for word, freq in word_freqs.items():
            for i in range(len(word) - 1):
                pairs[(word[i], word[i + 1])] += freq
        return list(pairs.items())

    def _merge_word(self, word: str, pair: tuple[str, str]) -> str:
        merged = pair[0] + pair[1]
        parts = []
        i = 0
        while i < len(word):
            if i < len(word) - 1 and word[i] == pair[0] and word[i + 1] == pair[1]:
                parts.append(merged)
                i += 2
            else:
                parts.append(word[i])
                i += 1
        return "".join(parts)

    def _encode_word(self, word: str) -> list[str]:
        # Apply merges in order
        symbols = list(word)
        for a, b in self.merges:
            merged = a + b
            new_symbols = []
            i = 0
            while i < len(symbols):
                if i < len(symbols) - 1 and symbols[i] == a and symbols[i + 1] == b:
                    new_symbols.append(merged)
                    i += 2
                else:
                    new_symbols.append(symbols[i])
                    i += 1
            symbols = new_symbols
        return symbols


# ===========================================================================
# Loss functions
# ===========================================================================

def cross_entropy(logits: list[float], target_index: int) -> float:
    """Cross-entropy loss for classification.

    Uses log-softmax for numerical stability.
    """
    log_probs = log_softmax(logits)
    return -log_probs[target_index]


def kl_divergence(p: list[float], q: list[float]) -> float:
    """KL divergence D_KL(p || q).

    Assumes p and q are valid probability distributions.
    """
    total = 0.0
    for pi, qi in zip(p, q):
        if pi > 1e-15 and qi > 1e-15:
            total += pi * math.log(pi / qi)
    return total


def entropy(p: list[float]) -> float:
    """Shannon entropy H(p) = -sum p_i * log(p_i)."""
    total = 0.0
    for pi in p:
        if pi > 1e-15:
            total -= pi * math.log(pi)
    return total


# ===========================================================================
# Optimization
# ===========================================================================

def gradient_descent(f, grad_f, x0: list[float], learning_rate: float = 0.01,
                     max_iters: int = 1000, tol: float = 1e-8) -> tuple[list[float], int]:
    """Vanilla gradient descent.

    Returns (optimized_point, iterations).
    """
    x = x0[:]
    for i in range(max_iters):
        g = grad_f(x)
        x_new = [xi - learning_rate * gi for xi, gi in zip(x, g)]
        step_size = math.sqrt(sum((a - b) ** 2 for a, b in zip(x, x_new)))
        x = x_new
        if step_size < tol:
            return x, i + 1
    return x, max_iters


def momentum_descent(f, grad_f, x0: list[float], learning_rate: float = 0.01,
                     momentum: float = 0.9, max_iters: int = 1000,
                     tol: float = 1e-8) -> tuple[list[float], int]:
    """Gradient descent with momentum."""
    x = x0[:]
    velocity = [0.0] * len(x)
    for i in range(max_iters):
        g = grad_f(x)
        velocity = [momentum * v - learning_rate * gi for v, gi in zip(velocity, g)]
        x_new = [xi + v for xi, v in zip(x, velocity)]
        step_size = math.sqrt(sum((a - b) ** 2 for a, b in zip(x, x_new)))
        x = x_new
        if step_size < tol:
            return x, i + 1
    return x, max_iters


def adam(f, grad_f, x0: list[float], learning_rate: float = 0.01,
         beta1: float = 0.9, beta2: float = 0.999, eps: float = 1e-8,
         max_iters: int = 1000, tol: float = 1e-8) -> tuple[list[float], int]:
    """Adam optimizer."""
    x = x0[:]
    m = [0.0] * len(x)
    v = [0.0] * len(x)
    for i in range(max_iters):
        g = grad_f(x)
        # Update biased first moment
        m = [beta1 * mi + (1 - beta1) * gi for mi, gi in zip(m, g)]
        # Update biased second moment
        v = [beta2 * vi + (1 - beta2) * gi * gi for vi, gi in zip(v, g)]
        # Bias correction
        m_hat = [mi / (1 - beta1 ** (i + 1)) for mi in m]
        v_hat = [vi / (1 - beta2 ** (i + 1)) for vi in v]
        x_new = [xi - learning_rate * mi / (math.sqrt(vi) + eps)
                 for xi, mi, vi in zip(x, m_hat, v_hat)]
        step_size = math.sqrt(sum((a - b) ** 2 for a, b in zip(x, x_new)))
        x = x_new
        if step_size < tol:
            return x, i + 1
    return x, max_iters


# ===========================================================================
# Transformer block assembly (study)
# ===========================================================================

class TransformerBlock:
    """A single transformer block: attention + FFN with residual + norm.

    This is a mathematical study model — no actual neural network
    training, just the forward computation for understanding.
    """

    def __init__(self, d_model: int, d_ff: int, num_heads: int):
        self.d_model = d_model
        self.d_ff = d_ff
        self.num_heads = num_heads
        # In a real model these would be learned; here we initialize
        # to identity-like values for the study.
        self.pe = sinusoidal_positional_encoding(64, d_model)

    def forward(self, x: list[list[float]],
                attn_weights: list[list[float]] | None = None) -> list[list[float]]:
        """Forward pass of the block (simplified, no learned params)."""
        # In a real transformer: LayerNorm -> MultiHeadAttention -> Residual
        # -> LayerNorm -> FeedForward -> Residual
        # For study, we just add positional encoding.
        if len(x) > len(self.pe):
            pe = self.pe
        else:
            pe = self.pe[:len(x)]
        return [vector_add(row, prow) for row, prow in zip(x, pe)]


# Helper imports (local to avoid circular dependency)
def mat_multiply(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    if not a or not b:
        return []
    if len(a[0]) != len(b):
        raise ValueError("Matrix shapes incompatible")
    result = [[0.0] * len(b[0]) for _ in range(len(a))]
    for i in range(len(a)):
        for j in range(len(b[0])):
            result[i][j] = sum(a[i][k] * b[k][j] for k in range(len(a[0])))
    return result


def mat_transpose(m: list[list[float]]) -> list[list[float]]:
    if not m:
        return []
    return [[m[i][j] for i in range(len(m))] for j in range(len(m[0]))]


def vector_add(a: list[float], b: list[float]) -> list[float]:
    return [x + y for x, y in zip(a, b)]


def __all__() -> list[str]:
    return [
        "softmax", "log_softmax", "gelu", "relu",
        "scaled_dot_product_attention", "multi_head_attention",
        "layer_norm", "layer_norm_with_params",
        "sinusoidal_positional_encoding",
        "feed_forward", "BPETokenizer",
        "cross_entropy", "kl_divergence", "entropy",
        "gradient_descent", "momentum_descent", "adam",
        "TransformerBlock",
    ]
