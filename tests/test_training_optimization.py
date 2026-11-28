"""Tests for the optimization training module."""

import unittest

from research.training.optimization.methods import (
    bisection_root, newtons_method, secant_method,
    golden_section_search, backtracking_line_search,
    conjugate_gradient, simulated_annealing, genetic_algorithm,
    step_decay, exponential_decay, cosine_annealing,
    linear_warmup, cosine_with_warmup, nelder_mead,
)


class TestRootFinding(unittest.TestCase):

    def test_bisection_root(self):
        f = lambda x: x ** 2 - 4
        root = bisection_root(f, 0.0, 3.0)
        self.assertAlmostEqual(root, 2.0, places=6)

    def test_bisection_no_sign_change(self):
        f = lambda x: x ** 2 + 1
        with self.assertRaises(ValueError):
            bisection_root(f, -1.0, 1.0)

    def test_newtons_method(self):
        f = lambda x: x ** 2 - 9
        df = lambda x: 2 * x
        root = newtons_method(f, df, 3.0)
        self.assertAlmostEqual(root, 3.0, places=6)

    def test_newtons_method_negative(self):
        f = lambda x: x ** 2 - 9
        df = lambda x: 2 * x
        root = newtons_method(f, df, -5.0)
        self.assertAlmostEqual(root, -3.0, places=6)

    def test_secant_method(self):
        f = lambda x: x ** 3 - 8
        root = secant_method(f, 1.0, 3.0)
        self.assertAlmostEqual(root, 2.0, places=6)


class TestLineSearch(unittest.TestCase):

    def test_golden_section_search(self):
        f = lambda x: (x - 3) ** 2
        result = golden_section_search(f, 0.0, 6.0)
        self.assertAlmostEqual(result, 3.0, places=4)

    def test_backtracking_line_search(self):
        # Minimize (x-2)^2; direction is -gradient
        grad = lambda x: [2 * (x[0] - 2)]
        f = lambda x: (x[0] - 2) ** 2
        alpha = backtracking_line_search(f, grad, [5.0], [-1.0])
        self.assertGreater(alpha, 0.0)


class TestConjugateGradient(unittest.TestCase):

    def test_conjugate_gradient(self):
        # Solve Ax = b for A = [[4, 1], [1, 3]], b = [1, 2]
        A = [[4.0, 1.0], [1.0, 3.0]]
        b = [1.0, 2.0]
        result = conjugate_gradient(A, b)
        # A^-1 b: inv = 1/11 * [[3, -1], [-1, 4]], so x = 1/11 * [1, 7]
        self.assertAlmostEqual(result[0], 1 / 11, places=4)
        self.assertAlmostEqual(result[1], 7 / 11, places=4)


class TestSimulatedAnnealing(unittest.TestCase):

    def test_simulated_annealing(self):
        f = lambda x: (x[0] - 5) ** 2
        best_x, best_val = simulated_annealing(f, [0.0])
        self.assertAlmostEqual(best_x[0], 5.0, places=2)
        self.assertLess(best_val, 1.0)


class TestGeneticAlgorithm(unittest.TestCase):

    def test_genetic_algorithm(self):
        f = lambda x: sum((x[i] - 7) ** 2 for i in range(2))
        best_x, best_val = genetic_algorithm(f, n_vars=2, population_size=30,
                                             generations=100)
        # GA is stochastic; allow reasonable tolerance
        self.assertLess(abs(best_x[0] - 7.0), 0.5)
        self.assertLess(abs(best_x[1] - 7.0), 0.5)
        self.assertLess(best_val, 1.0)


class TestLearningRateSchedules(unittest.TestCase):

    def test_step_decay(self):
        # LR = 0.1, milestones [10, 20], decay 0.1, at step 30
        lr = step_decay(0.1, [10, 20], 0.1, 30)
        self.assertAlmostEqual(lr, 0.1 * 0.1 * 0.1, places=8)

    def test_step_decay_no_step(self):
        lr = step_decay(0.1, [10, 20], 0.1, 5)
        self.assertAlmostEqual(lr, 0.1, places=8)

    def test_exponential_decay(self):
        lr = exponential_decay(0.1, 0.5, 10)
        self.assertAlmostEqual(lr, 0.1 * (0.5 ** 10), places=8)

    def test_cosine_annealing(self):
        lr_start = cosine_annealing(0.1, 0, 10)
        self.assertAlmostEqual(lr_start, 0.1, places=6)
        lr_end = cosine_annealing(0.1, 10, 10)
        self.assertAlmostEqual(lr_end, 0.0, places=6)

    def test_linear_warmup(self):
        lr = linear_warmup(0.1, 0, 5)
        self.assertAlmostEqual(lr, 0.0, places=8)
        lr_half = linear_warmup(0.1, 2, 5)
        self.assertAlmostEqual(lr_half, 0.04, places=8)
        lr_done = linear_warmup(0.1, 10, 5)
        self.assertAlmostEqual(lr_done, 0.1, places=8)

    def test_cosine_with_warmup(self):
        # Step 0 during warmup → LR is 0
        lr_zero = cosine_with_warmup(0.1, 0, 10, 3)
        self.assertEqual(lr_zero, 0.0)
        # Step 1 during warmup → LR is positive but less than max
        lr_warmup = cosine_with_warmup(0.1, 1, 10, 3)
        self.assertGreater(lr_warmup, 0.0)
        self.assertLess(lr_warmup, 0.1)
        # After warmup, LR starts cosine annealing
        lr_mid = cosine_with_warmup(0.1, 5, 10, 3)
        lr_end = cosine_with_warmup(0.1, 10, 10, 3)
        self.assertGreater(lr_mid, 0.0)
        self.assertLess(lr_end, lr_mid)


class TestNelderMead(unittest.TestCase):

    def test_nelder_mead_1d(self):
        f = lambda x: (x[0] - 2) ** 2
        result = nelder_mead(f, [0.0], max_iters=5000)
        self.assertAlmostEqual(result[0], 2.0, places=4)

    def test_nelder_mead_2d(self):
        f = lambda x: x[0] ** 2 + x[1] ** 2
        result = nelder_mead(f, [3.0, 4.0], max_iters=5000)
        self.assertAlmostEqual(result[0], 0.0, places=2)
        self.assertAlmostEqual(result[1], 0.0, places=2)


if __name__ == "__main__":
    unittest.main()
