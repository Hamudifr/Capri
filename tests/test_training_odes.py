"""Tests for the ODEs training module (Euler, Heun, RK4, RK45, systems)."""

from __future__ import annotations

import math
import unittest

from research.training.odes import (
    euler,
    euler_system,
    harmonic_oscillator_solution,
    heun,
    logistic_growth_solution,
    rk4,
    rk4_system,
    rk45,
    second_order_to_first,
)


class TestEuler(unittest.TestCase):
    def test_euler_exponential_decay(self):
        # y' = -y, y(0) = 1, solution y(t) = exp(-t)
        result = euler(lambda t, y: -y, 0.0, 1.0, 1.0, 0.01)
        final_t, final_y = result[-1]
        self.assertAlmostEqual(final_t, 1.0, places=4)
        # Euler overestimates decay for y'=-y, so y should be < exp(-1)
        self.assertLess(final_y, math.exp(-1.0))
        self.assertGreater(final_y, math.exp(-1.0) - 0.05)
        self.assertLess(final_y, 1.0)

    def test_euler_constant_derivative(self):
        # y' = 2, y(0) = 0, solution y(t) = 2t
        result = euler(lambda t, y: 2.0, 0.0, 0.0, 1.0, 0.01)
        final_y = result[-1][1]
        self.assertAlmostEqual(final_y, 2.0, places=2)

    def test_euler_returns_correct_length(self):
        result = euler(lambda t, y: y, 0.0, 1.0, 1.0, 0.1)
        # Should have ~11 points (0, 0.1, ..., 1.0)
        self.assertGreaterEqual(len(result), 10)
        self.assertEqual(result[0], (0.0, 1.0))


class TestHeun(unittest.TestCase):
    def test_heun_exponential_decay(self):
        result = heun(lambda t, y: -y, 0.0, 1.0, 1.0, 0.01)
        final_y = result[-1][1]
        # Heun is more accurate than Euler
        self.assertLess(abs(final_y - math.exp(-1.0)), 0.05)

    def test_heun_constant(self):
        result = heun(lambda t, y: 3.0, 0.0, 0.0, 1.0, 0.01)
        self.assertAlmostEqual(result[-1][1], 3.0, places=2)


class TestRK4(unittest.TestCase):
    def test_rk4_exponential_decay(self):
        result = rk4(lambda t, y: -y, 0.0, 1.0, 1.0, 0.01)
        final_y = result[-1][1]
        # RK4 is very accurate for this
        self.assertLess(abs(final_y - math.exp(-1.0)), 1e-4)

    def test_rk4_constant(self):
        result = rk4(lambda t, y: 5.0, 0.0, 0.0, 2.0, 0.1)
        self.assertAlmostEqual(result[-1][1], 10.0, places=4)

    def test_rk4_accuracy_vs_euler(self):
        # RK4 should be more accurate than Euler for the same step size
        euler_result = euler(lambda t, y: -y, 0.0, 1.0, 2.0, 0.05)
        rk4_result = rk4(lambda t, y: -y, 0.0, 1.0, 2.0, 0.05)
        exp_val = math.exp(-2.0)
        euler_err = abs(euler_result[-1][1] - exp_val)
        rk4_err = abs(rk4_result[-1][1] - exp_val)
        self.assertLess(rk4_err, euler_err)


class TestRK45(unittest.TestCase):
    def test_rk45_exponential_decay(self):
        result = rk45(lambda t, y: -y, 0.0, 1.0, 2.0, h0=0.1, tol=1e-6)
        final_y = result[-1][1]
        self.assertLess(abs(final_y - math.exp(-2.0)), 1e-3)

    def test_rk45_variable_steps(self):
        result = rk45(lambda t, y: y, 0.0, 1.0, 1.0, h0=0.5, tol=1e-4)
        self.assertGreater(len(result), 2)


class TestSystems(unittest.TestCase):
    def test_euler_system(self):
        # System: y1' = y2, y2' = -y1 (harmonic oscillator)
        def f(t, y):
            return [y[1], -y[0]]

        result = euler_system(f, 0.0, [1.0, 0.0], 1.0, 0.01)
        self.assertGreater(len(result), 5)
        # Should have 2-element state vectors
        for _, state in result:
            self.assertEqual(len(state), 2)

    def test_rk4_system_harmonic(self):
        # Harmonic oscillator: y'' + y = 0, y(0)=1, y'(0)=0
        def f(t, y):
            return [y[1], -y[0]]

        result = rk4_system(f, 0.0, [1.0, 0.0], math.pi / 2, 0.01)
        final_state = result[-1][1]
        final_y = final_state[0]
        # At t=pi/2, y should be ~0 (cos(pi/2) = 0)
        self.assertLess(abs(final_y), 0.01)

    def test_second_order_to_first(self):
        # y'' = -y -> system [y, y'] -> [y', -y]
        sys_f = second_order_to_first(lambda t, y, yp: -y)
        state = [1.0, 0.0]
        result = sys_f(0.0, state)
        self.assertEqual(len(result), 2)
        self.assertAlmostEqual(result[0], 0.0)  # y'
        self.assertAlmostEqual(result[1], -1.0)  # y'' = -y

    def test_harmonic_oscillator_solution(self):
        val = harmonic_oscillator_solution(0.0, 1.0)
        self.assertAlmostEqual(val, 1.0)
        val = harmonic_oscillator_solution(math.pi / 2, 1.0)
        self.assertAlmostEqual(val, 0.0, places=5)

    def test_logistic_growth_solution(self):
        val = logistic_growth_solution(0.0, 1.0, 1.0)
        self.assertAlmostEqual(val, 0.5)
        val = logistic_growth_solution(10.0, 1.0, 1.0)
        # Should approach K
        self.assertGreater(val, 0.99)


if __name__ == "__main__":
    unittest.main()
