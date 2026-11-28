"""Tests for the ML training module (SVM, decision trees, k-means, naive Bayes)."""

from __future__ import annotations

import unittest

from research.training.ml import (
    DecisionTreeNode,
    GaussianNaiveBayes,
    MultinomialNaiveBayes,
    decision_tree_predict,
    decision_tree_train,
    entropy,
    gini_impurity,
    information_gain,
    kmeans,
    kmeans_plusplus_init,
    svm_decision_function,
    svm_predict,
    svm_train,
    silhouette_score,
)


class TestSVM(unittest.TestCase):
    def test_svm_linearly_separable(self):
        # Simple 2D linearly separable data
        X = [[0.0, 0.0], [0.5, 0.0], [0.0, 0.5], [1.0, 0.0],
         [5.0, 5.0], [5.5, 5.0], [5.0, 5.5], [6.0, 6.0]]
        y = [-1, -1, -1, -1, 1, 1, 1, 1]
        w, b = svm_train(X, y, learning_rate=0.01, lambda_param=0.01, epochs=2000)
        # Should predict correctly on most points
        correct = sum(1 for i in range(len(X)) if svm_predict(w, b, X[i]) == y[i])
        self.assertGreaterEqual(correct, 7)

    def test_svm_decision_function(self):
        X = [[0.0], [2.0], [4.0], [6.0]]
        y = [-1, -1, 1, 1]
        w, b = svm_train(X, y, epochs=2000)
        val = svm_decision_function(w, b, [5.0])
        self.assertGreater(val, 0)
        val2 = svm_decision_function(w, b, [0.0])
        self.assertLess(val2, 0)

    def test_svm_predict_sign(self):
        w = [1.0, -1.0]
        b = 0.0
        self.assertEqual(svm_predict(w, b, [1.0, 0.0]), 1)
        self.assertEqual(svm_predict(w, b, [0.0, 1.0]), -1)


class TestDecisionTree(unittest.TestCase):
    def test_gini_impurity_pure(self):
        self.assertEqual(gini_impurity([1, 1, 1]), 0.0)

    def test_gini_impurity_mixed(self):
        # 50/50 split -> impurity 0.5
        self.assertAlmostEqual(gini_impurity([0, 0, 1, 1]), 0.5)

    def test_entropy_pure(self):
        self.assertEqual(entropy([1, 1, 1]), 0.0)

    def test_entropy_mixed(self):
        # 50/50 split -> entropy 1.0
        self.assertAlmostEqual(entropy([0, 0, 1, 1]), 1.0)

    def test_information_gain(self):
        labels = [0, 0, 1, 1]
        left = [0, 0]
        right = [1, 1]
        gain = information_gain(labels, left, right)
        # Pure split should have gain equal to parent impurity
        self.assertAlmostEqual(gain, 0.5)

    def test_tree_train_predict(self):
        # Simple XOR-like data
        X = [[0.0, 0.0], [0.0, 1.0], [1.0, 0.0], [1.0, 1.0]]
        labels = [0, 1, 1, 0]
        tree = decision_tree_train(X, labels, max_depth=3)
        self.assertIsNotNone(tree)
        # Should be able to predict
        preds = [decision_tree_predict(tree, x) for x in X]
        self.assertEqual(len(preds), 4)

    def test_tree_leaf_is_leaf(self):
        node = DecisionTreeNode()
        node.label = 1
        self.assertTrue(node.is_leaf)

    def test_tree_classification(self):
        # Linearly separable
        X = [[0.0], [0.5], [1.0], [2.0], [3.0], [4.0]]
        labels = [0, 0, 0, 1, 1, 1]
        tree = decision_tree_train(X, labels, max_depth=4)
        preds = [decision_tree_predict(tree, x) for x in X]
        self.assertEqual(preds, labels)


class TestKMeans(unittest.TestCase):
    def test_kmeans_plusplus_init(self):
        X = [[float(i), float(i)] for i in range(10)]
        centroids = kmeans_plusplus_init(X, 3, __import__("random").Random(42))
        self.assertEqual(len(centroids), 3)

    def test_kmeans_converges(self):
        # Two well-separated clusters
        X = [[0.0, 0.0], [0.1, 0.0], [0.0, 0.1],
         [5.0, 5.0], [5.1, 5.0], [5.0, 5.1]]
        centroids, assignments = kmeans(X, k=2, max_iter=50)
        self.assertEqual(len(centroids), 2)
        self.assertEqual(len(assignments), 6)
        # Each cluster should have 3 members
        counts = [0, 0]
        for a in assignments:
            counts[a] += 1
        self.assertEqual(sorted(counts), [3, 3])

    def test_kmeans_cluster_centers(self):
        X = [[0.0], [0.0], [0.0], [10.0], [10.0], [10.0]]
        centroids, _ = kmeans(X, k=2, max_iter=50)
        # One centroid near 0, one near 10
        centers = sorted(c[0] for c in centroids)
        self.assertLess(centers[0], 1.0)
        self.assertGreater(centers[1], 9.0)

    def test_silhouette_score(self):
        X = [[0.0], [0.1], [5.0], [5.1]]
        _, assignments = kmeans(X, k=2)
        score = silhouette_score(X, assignments)
        # Should be positive for well-separated clusters
        self.assertGreater(score, 0.5)


class TestNaiveBayes(unittest.TestCase):
    def test_gaussian_nb_classification(self):
        X = [[0.0], [0.5], [1.0], [5.0], [5.5], [6.0]]
        y = [0, 0, 0, 1, 1, 1]
        model = GaussianNaiveBayes().fit(X, y)
        preds = model.predict(X)
        correct = sum(1 for i in range(len(X)) if preds[i] == y[i])
        self.assertGreaterEqual(correct, 5)

    def test_gaussian_nb_predict_one(self):
        X = [[0.0], [1.0], [2.0], [10.0], [11.0], [12.0]]
        y = [0, 0, 0, 1, 1, 1]
        model = GaussianNaiveBayes().fit(X, y)
        self.assertEqual(model.predict_one([0.5]), 0)
        self.assertEqual(model.predict_one([10.5]), 1)

    def test_multinomial_nb(self):
        # Document classification with word counts
        X = [[3, 0, 0], [2, 1, 0], [0, 0, 3], [0, 2, 1]]
        y = [0, 0, 1, 1]
        model = MultinomialNaiveBayes(alpha=1.0).fit(X, y)
        preds = model.predict(X)
        correct = sum(1 for i in range(len(X)) if preds[i] == y[i])
        self.assertGreaterEqual(correct, 3)

    def test_multinomial_nb_predict_one(self):
        X = [[5, 0], [4, 1], [0, 5], [1, 4]]
        y = [0, 0, 1, 1]
        model = MultinomialNaiveBayes().fit(X, y)
        self.assertEqual(model.predict_one([4, 0]), 0)
        self.assertEqual(model.predict_one([0, 4]), 1)


if __name__ == "__main__":
    unittest.main()
