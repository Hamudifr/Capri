"""Tests for the Gaussian processes training module."""

import unittest

from research.training.gp.core import (
    GaussianProcess,
    rbf_kernel, linear_kernel, matern_kernel, periodic_kernel,
    gram_matrix, cholesky_decompose, cholesky_solve,
    optimize_hyperparameters,
)


class TestKernels(unittest.TestCase):

    def test_rbf_same(self):
        self.assertAlmostEqual(rbf_kernel((1.0, 2.0), (1.0, 2.0)), 1.0)

    def test_rbf_different(self):
        val = rbf_kernel((0.0, 0.0), (1.0, 0.0))
        self.assertGreater(val, 0.0)
        self.assertLess(val, 1.0)

    def test_rbf_length_scale(self):
        # Smaller length scale = smaller kernel value
        small = rbf_kernel((0.0, 0.0), (1.0, 0.0), length_scale=0.5)
        large = rbf_kernel((0.0, 0.0), (1.0, 0.0), length_scale=2.0)
        self.assertLess(small, large)

    def test_linear_kernel(self):
        self.assertAlmostEqual(linear_kernel((1.0, 2.0), (3.0, 4.0)), 11.0)

    def test_matern_nu_05(self):
        val = matern_kernel((0.0, 0.0), (1.0, 0.0), nu=0.5)
        self.assertGreater(val, 0.0)
        self.assertLess(val, 1.0)

    def test_matern_nu_15(self):
        val = matern_kernel((0.0, 0.0), (1.0, 0.0), nu=1.5)
        self.assertGreater(val, 0.0)
        self.assertLess(val, 1.0)

    def test_matern_same_point(self):
        self.assertAlmostEqual(matern_kernel((1.0, 1.0), (1.0, 1.0), nu=1.5), 1.0)

    def test_periodic_kernel(self):
        val = periodic_kernel((0.0,), (1.0,), period=2.0)
        self.assertGreater(val, 0.0)


class TestGramMatrix(unittest.TestCase):

    def test_gram_matrix_size(self):
        points = [(0.0,), (1.0,), (2.0,)]
        K = gram_matrix(points, rbf_kernel)
        self.assertEqual(len(K), 3)
        self.assertEqual(len(K[0]), 3)

    def test_gram_matrix_diagonal(self):
        points = [(0.0,), (1.0,)]
        K = gram_matrix(points, rbf_kernel)
        self.assertAlmostEqual(K[0][0], 1.0)
        self.assertAlmostEqual(K[1][1], 1.0)


class TestCholesky(unittest.TestCase):

    def test_cholesky_2x2(self):
        A = [[4.0, 2.0], [2.0, 3.0]]
        L = cholesky_decompose(A)
        self.assertIsNotNone(L)
        # Check L L^T = A
        n = 2
        for i in range(n):
            for j in range(n):
                s = sum(L[i][k] * L[j][k] for k in range(j + 1))
                self.assertAlmostEqual(A[i][j], s, places=5)

    def test_cholesky_not_pd(self):
        A = [[1.0, 2.0], [2.0, 1.0]]
        L = cholesky_decompose(A)
        self.assertIsNone(L)

    def test_cholesky_solve(self):
        A = [[4.0, 2.0], [2.0, 3.0]]
        b = [6.0, 5.0]
        L = cholesky_decompose(A)
        x = cholesky_solve(L, b)
        # Verify A x = b
        for i in range(2):
            s = sum(A[i][j] * x[j] for j in range(2))
            self.assertAlmostEqual(s, b[i], places=5)


class TestGaussianProcess(unittest.TestCase):

    def test_fit_and_predict(self):
        X = [(0.0,), (1.0,), (2.0,), (3.0,)]
        y = [0.0, 1.0, 2.0, 3.0]
        gp = GaussianProcess(kernel=rbf_kernel, noise=1e-3)
        gp.fit(X, y)
        means, variances = gp.predict([(1.5,)])
        self.assertEqual(len(means), 1)
        self.assertEqual(len(variances), 1)
        # Should predict near the training value
        self.assertGreater(means[0], 0.0)
        self.assertLess(means[0], 3.0)

    def test_predict_multiple(self):
        X = [(0.0,), (1.0,), (2.0,)]
        y = [0.0, 1.0, 4.0]
        gp = GaussianProcess(kernel=rbf_kernel, noise=1e-3)
        gp.fit(X, y)
        means, variances = gp.predict([(0.5,), (1.5,), (2.5,)])
        self.assertEqual(len(means), 3)
        self.assertEqual(len(variances), 3)

    def test_log_marginal_likelihood(self):
        X = [(0.0,), (1.0,), (2.0,)]
        y = [0.0, 1.0, 2.0]
        gp = GaussianProcess(kernel=rbf_kernel, noise=1e-3)
        gp.fit(X, y)
        lml = gp.log_marginal_likelihood()
        self.assertIsInstance(lml, float)

    def test_predict_interpolation(self):
        # With very low noise, GP should interpolate training points
        X = [(0.0,), (1.0,), (2.0,)]
        y = [0.0, 1.0, 2.0]
        gp = GaussianProcess(kernel=rbf_kernel, noise=1e-6)
        gp.fit(X, y)
        means, _ = gp.predict([(1.0,)])
        self.assertAlmostEqual(means[0], 1.0, places=2)


class TestHyperparameterOptimization(unittest.TestCase):

    def test_optimize(self):
        X = [(0.0,), (1.0,), (2.0,), (3.0,)]
        y = [0.0, 1.0, 2.0, 3.0]
        best_ls, best_ml = optimize_hyperparameters(X, y, kernel_name="rbf", iterations=50)
        self.assertGreater(best_ls, 0.0)
        self.assertIsInstance(best_ml, float)


if __name__ == "__main__":
    unittest.main()
