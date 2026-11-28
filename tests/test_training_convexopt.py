"""Tests for the convex optimization training module."""

from __future__ import annotations

import unittest

from research.training.convexopt import (
    gradient_descent,
    gradient_descent_momentum,
    gradient_projection,
    interior_point_log_barrier,
    is_convex_quadratic,
    is_convex_quadratic_multivariate,
    kkt_check,
    lagrangian,
    lasso_coordinate_descent,
    nesterov_accelerated,
    subgradient_descent,
)


def quadratic_loss(x: list[float]) -> tuple[float, list[float]]:
    """f(x) = (x-2)^2 + (x-3)^2, gradient = 2*(x-2), 2*(x-3)."""
    loss = sum((x[i] - (2.0 if i == 0 else 3.0)) ** 2 for i in range(len(x)))
    grad = [2.0 * (x[i] - (2.0 if i == 0 else 3.0)) for i in range(len(x))]
    return loss, grad


def simple_quadratic(x: list[float]) -> tuple[float, list[float]]:
    """f(x) = x^2, gradient = 2x."""
    return x[0] ** 2, [2.0 * x[0]]


class TestConvexity(unittest.TestCase):
    def test_convex_quadratic(self):
        self.assertTrue(is_convex_quadratic(1.0, 0.0, 0.0))
        self.assertTrue(is_convex_quadratic(0.0, 0.0, 0.0))  # linear
        self.assertFalse(is_convex_quadratic(-1.0, 0.0, 0.0))

    def test_convex_quadratic_multivariate_2x2(self):
        # Positive definite: [[2, 0], [0, 2]]
        self.assertTrue(is_convex_quadratic_multivariate([[2.0, 0.0], [0.0, 2.0]]))

        # Not positive definite: [[-1, 0], [0, 2]]
        self.assertFalse(is_convex_quadratic_multivariate([[-1.0, 0.0], [0.0, 2.0]]))


class TestGradientDescent(unittest.TestCase):
    def test_gradient_descent_quadratic(self):
        x = gradient_descent(simple_quadratic, [5.0], learning_rate=0.1, max_iter=1000)
        # Should converge to x = 0
        self.assertLess(abs(x[0]), 0.1)

    def test_gradient_descent_2d(self):
        x = gradient_descent(quadratic_loss, [0.0, 0.0], learning_rate=0.1, max_iter=1000)
        self.assertLess(abs(x[0] - 2.0), 0.1)
        self.assertLess(abs(x[1] - 3.0), 0.1)

    def test_gradient_descent_momentum(self):
        x = gradient_descent_momentum(simple_quadratic, [5.0], learning_rate=0.1, max_iter=500)
        self.assertLess(abs(x[0]), 0.5)

    def test_nesterov_accelerated(self):
        x = nesterov_accelerated(simple_quadratic, [5.0], learning_rate=0.1, max_iter=500)
        self.assertLess(abs(x[0]), 0.5)

    def test_gradient_projection(self):
        # Minimize (x-5)^2 subject to 0 <= x <= 2
        # Solution is x = 2 (projected from 5)
        def f(x):
            return (x[0] - 5.0) ** 2, [2.0 * (x[0] - 5.0)]

        x = gradient_projection(f, [5.0], bounds=[(0.0, 2.0)], learning_rate=0.1, max_iter=1000)
        self.assertAlmostEqual(x[0], 2.0, places=2)


class TestSubgradient(unittest.TestCase):
    def test_subgradient_descent(self):
        # f(x) = |x| (non-smooth, minimum at 0)
        def abs_loss(x):
            val = abs(x[0])
            subgrad = [1.0 if x[0] > 0 else -1.0 if x[0] < 0 else 0.0]
            return val, subgrad

        x = subgradient_descent(abs_loss, [5.0], learning_rate=0.1, max_iter=1000)
        self.assertLess(abs(x[0]), 1.0)

    def test_lasso_coordinate_descent(self):
        # Simple linear regression with L1
        X = [[1.0, 0.0], [1.0, 1.0], [1.0, 2.0], [1.0, 3.0]]
        y = [1.0, 2.0, 3.0, 4.0]
        w = lasso_coordinate_descent(X, y, lam=0.01, max_iter=200)
        # w should be close to [1.0, 1.0] (the true model y = 1 + x)
        self.assertGreater(w[0], 0.5)
        self.assertLess(w[0], 1.5)


class TestInteriorPoint(unittest.TestCase):
    def test_interior_point_simple(self):
        # Minimize x^2 + y^2 subject to x, y > 0
        # Solution is (0, 0) but constrained to positive, so approaches 0
        def cost(x):
            return sum(v * v for v in x)

        def grad(x):
            return [2.0 * v for v in x]

        def hessian(x):
            n = len(x)
            return [[2.0 if i == j else 0.0 for j in range(n)] for i in range(n)]

        x = interior_point_log_barrier(
            cost, grad, hessian, [1.0, 1.0], mu=0.1, max_iter=50
        )
        # Should decrease toward 0 (barrier keeps it positive)
        self.assertLess(x[0], 1.0)
        self.assertLess(x[1], 1.0)
        self.assertGreater(x[0], 0.0)
        self.assertGreater(x[1], 0.0)


class TestKKT(unittest.TestCase):
    def test_kkt_trivial(self):
        # No constraints, x = 0, gradient = 0
        def cost(x):
            return sum(v * v for v in x)

        def grad(x):
            return [2.0 * v for v in x]

        # At x = 0, grad = 0, no constraints
        self.assertTrue(kkt_check(cost, grad, [0.0], [], [], []))

    def test_lagrangian(self):
        # L(x, lambda) = x^2 + lambda * (x - 1)
        def cost(x):
            return x[0] ** 2

        # At x = 0.5, constraint g(x) = x - 1 = -0.5
        constraints = [-0.5]
        lambdas = [1.0]
        result = lagrangian(cost, constraints, [0.5], lambdas)
        # L = 0.25 + 1.0 * (-0.5) = -0.25
        self.assertAlmostEqual(result, -0.25, places=5)


if __name__ == "__main__":
    unittest.main()
