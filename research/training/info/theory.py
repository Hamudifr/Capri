"""Information theory study modules.

Implements the core concepts of information theory: entropy,
mutual information, cross-entropy, and related measures.
Pure stdlib, no dependencies.

Topics covered:
- Shannon entropy and joint/conditional entropy
- Mutual information and information gain
- Kullback-Leibler divergence and cross-entropy
- Normalized mutual information
- Mutual information in decision trees
- Data compression: Huffman coding
- Mutual information for feature selection
"""

from __future__ import annotations

import math
from collections import defaultdict


# ===========================================================================
# Entropy
# ===========================================================================

def shannon_entropy(probs: list[float]) -> float:
    """Shannon entropy H(X) = -sum p_i * log2(p_i).

    Uses log base 2 so the result is in bits.
    """
    ent = 0.0
    for p in probs:
        if p > 1e-15:
            ent -= p * math.log2(p)
    return ent


def joint_entropy(joint_probs: list[tuple, float]) -> float:
    """Joint entropy H(X,Y) = -sum p(x,y) * log2(p(x,y)).

    joint_probs: list of ((x, y), p(x,y)) pairs.
    """
    ent = 0.0
    for _, p in joint_probs:
        if p > 1e-15:
            ent -= p * math.log2(p)
    return ent


def marginal_probs(joint_probs: list[tuple, float], key_index: int = 0) -> dict:
    """Compute marginal probabilities from a joint distribution.

    key_index: 0 for X, 1 for Y.
    """
    marginal: dict = defaultdict(float)
    for key, p in joint_probs:
        marginal[key[key_index]] += p
    return dict(marginal)


def conditional_entropy(joint_probs: list[tuple, float]) -> float:
    """Conditional entropy H(X|Y) = H(X,Y) - H(Y)."""
    h_joint = joint_entropy(joint_probs)
    p_y = marginal_probs(joint_probs, key_index=1)
    probs_y = list(p_y.values())
    h_y = shannon_entropy(probs_y)
    return h_joint - h_y


# ===========================================================================
# Mutual information
# ===========================================================================

def mutual_information(joint_probs: list[tuple, float]) -> float:
    """Mutual information I(X;Y) = H(X) + H(Y) - H(X,Y).

    joint_probs: list of ((x, y), p(x,y)) pairs.
    """
    p_x = marginal_probs(joint_probs, key_index=0)
    p_y = marginal_probs(joint_probs, key_index=1)
    h_x = shannon_entropy(list(p_x.values()))
    h_y = shannon_entropy(list(p_y.values()))
    h_xy = joint_entropy(joint_probs)
    return h_x + h_y - h_xy


def normalized_mutual_information(joint_probs: list[tuple, float]) -> float:
    """Normalized mutual information: I(X;Y) / sqrt(H(X) * H(Y)).

    Ranges from 0 (no shared information) to 1 (identical).
    """
    p_x = marginal_probs(joint_probs, key_index=0)
    p_y = marginal_probs(joint_probs, key_index=1)
    h_x = shannon_entropy(list(p_x.values()))
    h_y = shannon_entropy(list(p_y.values()))

    if h_x == 0 or h_y == 0:
        return 0.0

    mi = mutual_information(joint_probs)
    return mi / math.sqrt(h_x * h_y)


def information_gain(joint_probs: list[tuple, float]) -> float:
    """Information gain = H(X) - H(X|Y) = I(X;Y).

    Used in decision tree splitting: how much uncertainty about X
    is reduced by knowing Y.
    """
    p_x = marginal_probs(joint_probs, key_index=0)
    h_x = shannon_entropy(list(p_x.values()))
    return h_x - conditional_entropy(joint_probs)


# ===========================================================================
# Divergence and cross-entropy
# ===========================================================================

def kl_divergence_bits(p: list[float], q: list[float]) -> float:
    """Kullback-Leibler divergence D_KL(p||q) in bits."""
    total = 0.0
    for pi, qi in zip(p, q):
        if pi > 1e-15 and qi > 1e-15:
            total += pi * math.log2(pi / qi)
    return total


def cross_entropy_bits(p: list[float], q: list[float]) -> float:
    """Cross-entropy H(p,q) = -sum p_i * log2(q_i)."""
    total = 0.0
    for pi, qi in zip(p, q):
        if pi > 1e-15 and qi > 1e-15:
            total -= pi * math.log2(qi)
    return total


def entropy_from_counts(counts: list[int]) -> float:
    """Compute entropy from a list of counts."""
    total = sum(counts)
    if total == 0:
        return 0.0
    probs = [c / total for c in counts]
    return shannon_entropy(probs)


# ===========================================================================
# Huffman coding
# ===========================================================================

class HuffmanNode:
    """Node in a Huffman tree."""

    def __init__(self, symbol: str | None = None, freq: int = 0):
        self.symbol = symbol
        self.freq = freq
        self.left: HuffmanNode | None = None
        self.right: HuffmanNode | None = None

    def is_leaf(self) -> bool:
        return self.left is None and self.right is None


class HuffmanCoder:
    """Huffman coding: lossless data compression.

    Builds a prefix-free code tree from symbol frequencies, then
    encodes/decodes messages.
    """

    def __init__(self):
        self.codes: dict[str, str] = {}
        self.reverse: dict[str, str] = {}

    def build(self, freqs: dict[str, int]) -> "HuffmanCoder":
        """Build the Huffman code from symbol frequencies."""
        if not freqs:
            return self

        heap = [HuffmanNode(sym, f) for sym, f in freqs.items()]

        # Merge lowest-frequency nodes
        while len(heap) > 1:
            heap.sort(key=lambda n: n.freq)
            left = heap.pop(0)
            right = heap.pop(0)
            merged = HuffmanNode(freq=left.freq + right.freq)
            merged.left = left
            merged.right = right
            heap.append(merged)

        root = heap[0]
        self._build_codes(root, "")
        return self

    def _build_codes(self, node: HuffmanNode, prefix: str) -> None:
        if node.is_leaf():
            self.codes[node.symbol] = prefix
            self.reverse[prefix] = node.symbol
            return
        self._build_codes(node.left, prefix + "0")
        self._build_codes(node.right, prefix + "1")

    def encode(self, message: str) -> str:
        """Encode a message using the Huffman code."""
        return "".join(self.codes[ch] for ch in message)

    def decode(self, encoded: str) -> str:
        """Decode a Huffman-encoded bitstring."""
        result = []
        current = ""
        for bit in encoded:
            current += bit
            if current in self.reverse:
                result.append(self.reverse[current])
                current = ""
        return "".join(result)

    def average_code_length(self, freqs: dict[str, int]) -> float:
        """Average bits per symbol."""
        total_freq = sum(freqs.values())
        if total_freq == 0:
            return 0.0
        return sum(
            len(self.codes[sym]) * f for sym, f in freqs.items()
        ) / total_freq


# ===========================================================================
# Mutual information for feature selection
# ===========================================================================

def mutual_information_feature(
    features: list[list], target: list
) -> list[float]:
    """Compute mutual information between each feature and the target.

    features: list of feature vectors (each a list of values).
    target: the target variable.
    Returns a list of MI values, one per feature.
    """
    results = []
    for feature in features:
        # Build joint distribution
        pairs: dict[tuple, float] = defaultdict(float)
        for f_val, t_val in zip(feature, target):
            pairs[(f_val, t_val)] += 1
        n = len(target)
        joint_probs = [(k, v / n) for k, v in pairs.items()]
        results.append(mutual_information(joint_probs))
    return results


def __all__() -> list[str]:
    return [
        "shannon_entropy", "joint_entropy", "marginal_probs",
        "conditional_entropy", "mutual_information",
        "normalized_mutual_information", "information_gain",
        "kl_divergence_bits", "cross_entropy_bits",
        "entropy_from_counts", "HuffmanNode", "HuffmanCoder",
        "mutual_information_feature",
    ]
