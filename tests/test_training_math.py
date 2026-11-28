"""Tests for the math training module."""

import unittest
import math

from research.training.math.foundations import (
    dot, vector_add, vector_scale, vector_norm,
    mat_transpose, mat_multiply, mat_identity, mat_determinant,
    mat_inverse, power_iteration, svd_2x2,
    numerical_derivative, numerical_gradient, numerical_jacobian,
    mean, variance, stddev, covariance, correlation,
    linear_regression, r_squared,
    binomial_pmf, binomial_mean, binomial_variance,
    normal_pdf, normal_cdf,
    power_set, cartesian_product, factorial,
    permutations_count, combinations_count,
)


class TestLinearAlgebra(unittest.TestCase):

    def test_dot(self):
        self.assertAlmostEqual(dot([1, 2, 3], [4, 5, 6]), 32.0)

    def test_dot_length_mismatch(self):
        with self.assertRaises(ValueError):
            dot([1, 2], [1, 2, 3])

    def test_vector_ops(self):
        self.assertEqual(vector_add([1, 2], [3, 4]), [4, 6])
        self.assertEqual(vector_scale([1, 2], 3), [3, 6])
        self.assertAlmostEqual(vector_norm([3, 4]), 5.0)

    def test_mat_transpose(self):
        m = [[1, 2], [3, 4], [5, 6]]
        t = mat_transpose(m)
        self.assertEqual(t, [[1, 3, 5], [2, 4, 6]])

    def test_mat_multiply(self):
        a = [[1, 2], [3, 4]]
        b = [[5, 6], [7, 8]]
        result = mat_multiply(a, b)
        self.assertEqual(result, [[19, 22], [43, 50]])

    def test_mat_identity(self):
        i3 = mat_identity(3)
        self.assertEqual(i3, [[1, 0, 0], [0, 1, 0], [0, 0, 1]])

    def test_mat_determinant_2x2(self):
        m = [[1, 2], [3, 4]]
        self.assertAlmostEqual(mat_determinant(m), -2.0)

    def test_mat_determinant_3x3(self):
        m = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
        self.assertAlmostEqual(mat_determinant(m), 1.0)

    def test_mat_determinant_singular(self):
        m = [[1, 2], [2, 4]]  # det = 0
        self.assertAlmostEqual(mat_determinant(m), 0.0, places=10)

    def test_mat_inverse_2x2(self):
        m = [[1, 2], [3, 4]]
        inv = mat_inverse(m)
        # M * M_inv should be identity
        product = mat_multiply(m, inv)
        for i in range(2):
            for j in range(2):
                expected = 1.0 if i == j else 0.0
                self.assertAlmostEqual(product[i][j], expected, places=8)

    def test_mat_inverse_singular(self):
        with self.assertRaises(ValueError):
            mat_inverse([[1, 2], [2, 4]])

    def test_power_iteration(self):
        m = [[2, 1], [1, 2]]
        eigenval, eigenvec = power_iteration(m)
        # Dominant eigenvalue should be 3
        self.assertAlmostEqual(eigenval, 3.0, places=6)

    def test_svd_2x2(self):
        m = [[3, 0], [0, 2]]
        sv, u, vt = svd_2x2(m)
        # Singular values should be 3 and 2
        self.assertAlmostEqual(sv[0], 3.0, places=6)
        self.assertAlmostEqual(sv[1], 2.0, places=6)


class TestCalculus(unittest.TestCase):

    def test_numerical_derivative(self):
        f = lambda x: x ** 2
        self.assertAlmostEqual(numerical_derivative(f, 3.0), 6.0, places=4)

    def test_numerical_derivative_sin(self):
        f = math.sin
        self.assertAlmostEqual(numerical_derivative(f, 1.0), math.cos(1.0), places=4)

    def test_numerical_gradient(self):
        f = lambda p: p[0] ** 2 + p[1] ** 2
        grad = numerical_gradient(f, [3.0, 4.0])
        self.assertAlmostEqual(grad[0], 6.0, places=4)
        self.assertAlmostEqual(grad[1], 8.0, places=4)

    def test_numerical_jacobian(self):
        f = [lambda p: p[0] + p[1], lambda p: p[0] - p[1]]
        jac = numerical_jacobian(f, [2.0, 3.0])
        # jacobian should be [[1, 1], [1, -1]]
        self.assertAlmostEqual(jac[0][0], 1.0, places=4)
        self.assertAlmostEqual(jac[0][1], 1.0, places=4)
        self.assertAlmostEqual(jac[1][0], 1.0, places=4)
        self.assertAlmostEqual(jac[1][1], -1.0, places=4)


class TestStatistics(unittest.TestCase):

    def test_mean(self):
        self.assertAlmostEqual(mean([1, 2, 3, 4, 5]), 3.0)

    def test_variance(self):
        # Sample variance of [2, 4, 4, 4, 5, 5, 7, 9] = 32/7
        self.assertAlmostEqual(variance([2, 4, 4, 4, 5, 5, 7, 9]), 32 / 7, places=6)

    def test_stddev(self):
        self.assertAlmostEqual(stddev([2, 4, 4, 4, 5, 5, 7, 9]), math.sqrt(32 / 7), places=6)

    def test_covariance_identical(self):
        data = [1, 2, 3, 4, 5]
        self.assertAlmostEqual(covariance(data, data), variance(data), places=6)

    def test_correlation_perfect_positive(self):
        x = [1, 2, 3, 4, 5]
        y = [2, 4, 6, 8, 10]
        self.assertAlmostEqual(correlation(x, y), 1.0, places=6)

    def test_correlation_perfect_negative(self):
        x = [1, 2, 3, 4, 5]
        y = [5, 4, 3, 2, 1]
        self.assertAlmostEqual(correlation(x, y), -1.0, places=6)

    def test_linear_regression(self):
        x = [1, 2, 3, 4, 5]
        y = [2, 4, 6, 8, 10]
        slope, intercept = linear_regression(x, y)
        self.assertAlmostEqual(slope, 2.0, places=6)
        self.assertAlmostEqual(intercept, 0.0, places=6)

    def test_r_squared_perfect(self):
        y_true = [1, 2, 3, 4, 5]
        y_pred = [1, 2, 3, 4, 5]
        self.assertAlmostEqual(r_squared(y_true, y_pred), 1.0, places=6)

    def test_r_squared_zero(self):
        y_true = [1, 2, 3, 4, 5]
        y_pred = [3, 3, 3, 3, 3]
        self.assertLess(r_squared(y_true, y_pred), 0.1)


class TestProbability(unittest.TestCase):

    def test_binomial_pmf(self):
        # P(X=2) for n=5, p=0.5
        self.assertAlmostEqual(binomial_pmf(5, 2, 0.5), 0.3125, places=6)

    def test_binomial_mean(self):
        self.assertAlmostEqual(binomial_mean(10, 0.3), 3.0)

    def test_binomial_variance(self):
        self.assertAlmostEqual(binomial_variance(10, 0.3), 2.1, places=6)

    def test_normal_pdf_peak(self):
        # PDF at mean should be 1/(sigma*sqrt(2pi))
        pdf_at_mu = normal_pdf(0.0, 0.0, 1.0)
        self.assertAlmostEqual(pdf_at_mu, 1.0 / math.sqrt(2 * math.pi), places=6)

    def test_normal_cdf(self):
        # CDF at 0 should be 0.5
        self.assertAlmostEqual(normal_cdf(0.0, 0.0, 1.0), 0.5, places=6)


class TestCombinatorics(unittest.TestCase):

    def test_power_set(self):
        ps = power_set([1, 2])
        self.assertEqual(len(ps), 4)
        self.assertIn(set(), ps)
        self.assertIn({1, 2}, ps)

    def test_cartesian_product(self):
        cp = cartesian_product([1, 2], ["a", "b"])
        self.assertEqual(len(cp), 4)
        self.assertIn((1, "a"), cp)
        self.assertIn((2, "b"), cp)

    def test_factorial(self):
        self.assertEqual(factorial(5), 120)

    def test_permutations_count(self):
        self.assertEqual(permutations_count(5), 120)
        self.assertEqual(permutations_count(5, 2), 20)

    def test_combinations_count(self):
        self.assertEqual(combinations_count(5, 2), 10)
        self.assertEqual(combinations_count(5, 5), 1)


if __name__ == "__main__":
    unittest.main()
