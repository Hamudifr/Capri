"""Machine learning: SVMs, decision trees, k-means, naive Bayes.

Stdlib-only. Pure computation, no external dependencies.

Core concepts:
- Support vector machines: linear SVM with soft margin (sub-gradient)
- Decision trees: CART-style splitting with Gini impurity
- k-means clustering: Lloyd's algorithm with k-means++ init
- Naive Bayes: Gaussian and multinomial variants
"""

from __future__ import annotations

import math
import random

Point = list[float]


# ===========================================================================
# Support Vector Machine (linear, soft margin)
# ===========================================================================

def svm_train(
    X: list[Point],
    y: list[int],
    learning_rate: float = 0.001,
    lambda_param: float = 0.01,
    epochs: int = 1000,
    seed: int = 42,
) -> tuple[list[float], float]:
    """Train a linear SVM with sub-gradient descent (soft margin).

    Minimizes: (1/2)||w||^2 + C * sum(max(0, 1 - y_i(w·x_i + b)))
    Returns (w, b).
    """
    n_features = len(X[0]) if X else 0
    w = [0.0] * n_features
    b = 0.0
    C = 1.0 / lambda_param

    for _ in range(epochs):
        for i in range(len(X)):
            yi = 1.0 if y[i] == 1 else -1.0
            margin = yi * (sum(w[j] * X[i][j] for j in range(n_features)) + b)
            if margin < 1.0:
                # Hinge loss sub-gradient
                for j in range(n_features):
                    w[j] = w[j] - learning_rate * (2 * lambda_param * w[j] - C * yi * X[i][j])
                b = b - learning_rate * (-C * yi)
            else:
                for j in range(n_features):
                    w[j] = w[j] - learning_rate * 2 * lambda_param * w[j]

    return w, b


def svm_predict(w: list[float], b: float, x: Point) -> int:
    """Predict class label for a single point."""
    val = sum(w[j] * x[j] for j in range(len(w))) + b
    return 1 if val >= 0 else -1


def svm_decision_function(w: list[float], b: float, x: Point) -> float:
    """Return the raw decision value (signed distance to hyperplane)."""
    return sum(w[j] * x[j] for j in range(len(w))) + b


# ===========================================================================
# Decision Tree (CART)
# ===========================================================================

def gini_impurity(labels: list[int]) -> float:
    """Gini impurity of a set of labels."""
    if not labels:
        return 0.0
    counts: dict[int, int] = {}
    for lbl in labels:
        counts[lbl] = counts.get(lbl, 0) + 1
    n = len(labels)
    impurity = 1.0
    for count in counts.values():
        p = count / n
        impurity -= p * p
    return impurity


def entropy(labels: list[int]) -> float:
    """Shannon entropy of a set of labels (base 2)."""
    if not labels:
        return 0.0
    counts: dict[int, int] = {}
    for lbl in labels:
        counts[lbl] = counts.get(lbl, 0) + 1
    n = len(labels)
    ent = 0.0
    for count in counts.values():
        p = count / n
        if p > 0:
            ent -= p * math.log2(p)
    return ent


def information_gain(labels: list[int], left: list[int], right: list[int]) -> float:
    """Information gain of a split (using Gini impurity)."""
    n = len(labels)
    if n == 0:
        return 0.0
    parent_impurity = gini_impurity(labels)
    left_impurity = gini_impurity(left)
    right_impurity = gini_impurity(right)
    return parent_impurity - (len(left) / n * left_impurity + len(right) / n * right_impurity)


class DecisionTreeNode:
    """A node in a CART decision tree."""

    def __init__(self):
        self.feature: int | None = None
        self.threshold: float | None = None
        self.left: DecisionTreeNode | None = None
        self.right: DecisionTreeNode | None = None
        self.label: int | None = None  # Leaf prediction

    @property
    def is_leaf(self) -> bool:
        return self.label is not None


def build_decision_tree(
    X: list[Point],
    labels: list[int],
    feature_indices: list[int],
    max_depth: int = 5,
    min_samples_split: int = 2,
) -> DecisionTreeNode:
    """Build a CART decision tree using Gini impurity."""
    node = DecisionTreeNode()

    # All same label -> leaf
    if len(set(labels)) == 1:
        node.label = labels[0]
        return node

    if max_depth <= 0 or len(labels) < min_samples_split or not feature_indices:
        # Majority vote
        counts: dict[int, int] = {}
        for lbl in labels:
            counts[lbl] = counts.get(lbl, 0) + 1
        node.label = max(counts, key=counts.get)
        return node

    # Find best split
    best_feature = feature_indices[0]
    best_threshold = 0.0
    best_gain = -1.0
    best_left_indices: list[int] = []
    best_right_indices: list[int] = []

    for feature in feature_indices:
        # Sort by feature value, try thresholds at midpoints
        sorted_indices = sorted(range(len(X)), key=lambda i: X[i][feature])
        values = [X[i][feature] for i in sorted_indices]

        for idx in range(1, len(sorted_indices)):
            if values[idx] == values[idx - 1]:
                continue
            threshold = (values[idx] + values[idx - 1]) / 2.0
            left_idx = [sorted_indices[j] for j in range(idx)]
            right_idx = [sorted_indices[j] for j in range(idx, len(sorted_indices))]
            left_labels = [labels[i] for i in left_idx]
            right_labels = [labels[i] for i in right_idx]
            gain = information_gain(labels, left_labels, right_labels)
            if gain > best_gain:
                best_gain = gain
                best_feature = feature
                best_threshold = threshold
                best_left_indices = left_idx
                best_right_indices = right_idx

    if best_gain <= 0:
        # No improvement -> leaf
        counts: dict[int, int] = {}
        for lbl in labels:
            counts[lbl] = counts.get(lbl, 0) + 1
        node.label = max(counts, key=counts.get)
        return node

    node.feature = best_feature
    node.threshold = best_threshold
    node.left = build_decision_tree(
        [X[i] for i in best_left_indices],
        [labels[i] for i in best_left_indices],
        feature_indices,
        max_depth - 1,
        min_samples_split,
    )
    node.right = build_decision_tree(
        [X[i] for i in best_right_indices],
        [labels[i] for i in best_right_indices],
        feature_indices,
        max_depth - 1,
        min_samples_split,
    )
    return node


def decision_tree_predict(node: DecisionTreeNode, x: Point) -> int:
    """Traverse the tree to predict a label."""
    if node.is_leaf:
        return node.label  # type: ignore[return-value]
    if node.feature is None or node.threshold is None:
        return node.label  # type: ignore[return-value]
    if x[node.feature] <= node.threshold:
        return decision_tree_predict(node.left, x)  # type: ignore[arg-type]
    return decision_tree_predict(node.right, x)  # type: ignore[arg-type]


def decision_tree_train(
    X: list[Point],
    labels: list[int],
    max_depth: int = 5,
    min_samples_split: int = 2,
) -> DecisionTreeNode:
    """Train a decision tree on labeled data."""
    n_features = len(X[0]) if X else 0
    return build_decision_tree(X, labels, list(range(n_features)), max_depth, min_samples_split)


# ===========================================================================
# k-means clustering
# ===========================================================================

def kmeans_plusplus_init(
    X: list[Point], k: int, rng: random.Random
) -> list[Point]:
    """k-means++ initialization."""
    n = len(X)
    if k >= n:
        return [list(x) for x in X]

    centroids: list[Point] = []
    # First centroid: random point
    idx = rng.randint(0, n - 1)
    centroids.append(list(X[idx]))

    for _ in range(1, k):
        # Compute squared distances to nearest centroid
        dists = [
            min(sum((x[j] - c[j]) ** 2 for j in range(len(x))) for c in centroids)
            for x in X
        ]
        total = sum(dists)
        if total == 0:
            # All points coincide with centroids
            idx = rng.randint(0, n - 1)
        else:
            r = rng.random() * total
            acc = 0.0
            for i, d in enumerate(dists):
                acc += d
                if acc >= r:
                    idx = i
                    break
            else:
                idx = n - 1
        centroids.append(list(X[idx]))

    return centroids


def kmeans(
    X: list[Point],
    k: int = 3,
    max_iter: int = 100,
    seed: int = 42,
) -> tuple[list[Point], list[int]]:
    """Lloyd's k-means algorithm. Returns (centroids, assignments)."""
    rng = random.Random(seed)
    if not X:
        return [], []

    n_features = len(X[0])
    centroids = kmeans_plusplus_init(X, k, rng)
    assignments = [0] * len(X)

    for _ in range(max_iter):
        # Assignment step
        for i, x in enumerate(X):
            best_dist = float("inf")
            best_k = 0
            for ci, c in enumerate(centroids):
                dist = sum((x[j] - c[j]) ** 2 for j in range(n_features))
                if dist < best_dist:
                    best_dist = dist
                    best_k = ci
            assignments[i] = best_k

        # Update step
        new_centroids: list[Point] = []
        for ci in range(k):
            members = [X[i] for i in range(len(X)) if assignments[i] == ci]
            if members:
                new_c = [sum(m[j] for m in members) / len(members) for j in range(n_features)]
            else:
                # Empty cluster: reinitialize at random point
                new_c = list(X[rng.randint(0, len(X) - 1)])
            new_centroids.append(new_c)

        # Check convergence
        converged = True
        for ci in range(k):
            if sum((new_centroids[ci][j] - centroids[ci][j]) ** 2 for j in range(n_features)) > 1e-6:
                converged = False
                break
        centroids = new_centroids
        if converged:
            break

    return centroids, assignments


def silhouette_score(X: list[Point], labels: list[int]) -> float:
    """Silhouette coefficient for clustering evaluation (simplified)."""
    unique_labels = set(labels)
    if len(unique_labels) < 2:
        return 0.0

    n = len(X)
    scores = []
    for i in range(n):
        same_cluster = [j for j in range(n) if j != i and labels[j] == labels[i]]
        other_clusters = [j for j in range(n) if j != i and labels[j] != labels[i]]

        if not same_cluster:
            scores.append(0.0)
            continue

        a = sum(
            math.sqrt(sum((X[i][d] - X[j][d]) ** 2 for d in range(len(X[0]))))
            for j in same_cluster
        ) / len(same_cluster)

        if not other_clusters:
            scores.append(0.0)
            continue

        # Minimum average distance to other clusters
        min_b = float("inf")
        for other_label in unique_labels:
            if other_label == labels[i]:
                continue
            members = [j for j in other_clusters if labels[j] == other_label]
            if not members:
                continue
            b = sum(
                math.sqrt(sum((X[i][d] - X[j][d]) ** 2 for d in range(len(X[0]))))
                for j in members
            ) / len(members)
            min_b = min(min_b, b)

        if min_b == float("inf"):
            scores.append(0.0)
        else:
            scores.append((min_b - a) / max(a, min_b) if max(a, min_b) > 0 else 0.0)

    return sum(scores) / len(scores)


# ===========================================================================
# Naive Bayes
# ===========================================================================

class GaussianNaiveBayes:
    """Gaussian Naive Bayes classifier for continuous features."""

    def fit(self, X: list[Point], y: list[int]) -> "GaussianNaiveBayes":
        self.classes: list[int] = sorted(set(y))
        self.means: dict[int, list[float]] = {}
        self.variances: dict[int, list[float]] = {}
        self.priors: dict[int, float] = {}

        for cls in self.classes:
            members = [X[i] for i in range(len(X)) if y[i] == cls]
            n_features = len(X[0]) if X else 0
            mean = [sum(m[j] for m in members) / len(members) for j in range(n_features)]
            var = [
                sum((m[j] - mean[j]) ** 2 for m in members) / len(members)
                for j in range(n_features)
            ]
            # Avoid zero variance
            var = [max(v, 1e-9) for v in var]
            self.means[cls] = mean
            self.variances[cls] = var
            self.priors[cls] = len(members) / len(X)

        return self

    def _log_likelihood(self, x: Point, cls: int) -> float:
        mean = self.means[cls]
        var = self.variances[cls]
        log_prior = math.log(self.priors[cls] + 1e-12)
        log_like = 0.0
        for j in range(len(x)):
            diff = x[j] - mean[j]
            log_like += -0.5 * math.log(2.0 * math.pi * var[j]) - (diff * diff) / (2.0 * var[j])
        return log_prior + log_like

    def predict(self, X: list[Point]) -> list[int]:
        return [
            max(self.classes, key=lambda c: self._log_likelihood(x, c))
            for x in X
        ]

    def predict_one(self, x: Point) -> int:
        return max(self.classes, key=lambda c: self._log_likelihood(x, c))


class MultinomialNaiveBayes:
    """Multinomial Naive Bayes for discrete count features."""

    def __init__(self, alpha: float = 1.0):
        self.alpha = alpha
        self.classes: list[int] = []
        self.feature_log_probs: dict[int, list[float]] = {}
        self.class_log_priors: dict[int, float] = {}

    def fit(self, X: list[Point], y: list[int]) -> "MultinomialNaiveBayes":
        self.classes = sorted(set(y))
        n_features = len(X[0]) if X else 0

        for cls in self.classes:
            members = [X[i] for i in range(len(X)) if y[i] == cls]
            total_count = sum(sum(m) for m in members)
            class_count = len(members)
            self.class_log_priors[cls] = math.log(class_count / len(X))

            feature_counts = [0.0] * n_features
            for m in members:
                for j in range(n_features):
                    feature_counts[j] += m[j]

            # Laplace smoothing
            self.feature_log_probs[cls] = [
                math.log((feature_counts[j] + self.alpha) / (total_count + self.alpha * n_features))
                for j in range(n_features)
            ]
        return self

    def _log_likelihood(self, x: Point, cls: int) -> float:
        log_prior = self.class_log_priors[cls]
        log_like = 0.0
        for j in range(len(x)):
            if x[j] > 0:
                log_like += x[j] * self.feature_log_probs[cls][j]
        return log_prior + log_like

    def predict(self, X: list[Point]) -> list[int]:
        return [
            max(self.classes, key=lambda c: self._log_likelihood(x, c))
            for x in X
        ]

    def predict_one(self, x: Point) -> int:
        return max(self.classes, key=lambda c: self._log_likelihood(x, c))
