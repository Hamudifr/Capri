"""Tests for the stochastic processes training module."""

from __future__ import annotations

import math
import random
import unittest

from research.training.stochastic import (
    CTMC,
    KalmanFilter,
    ParticleFilter,
    brownian_motion,
    brownian_motion_quadratic_variation,
    geometric_brownian_motion,
    metropolis_hastings,
    poisson_count,
    poisson_interarrival,
    poisson_process_simulate,
)


class TestPoisson(unittest.TestCase):
    def test_poisson_interarrival_positive(self):
        rng = random.Random(42)
        times = [poisson_interarrival(2.0, rng) for _ in range(100)]
        self.assertTrue(all(t > 0 for t in times))

    def test_poisson_count(self):
        rng = random.Random(42)
        counts = [poisson_count(3.0, 1.0, rng) for _ in range(1000)]
        # Mean should be approximately lambda * t = 3
        avg = sum(counts) / len(counts)
        self.assertGreater(avg, 2.0)
        self.assertLess(avg, 4.0)

    def test_poisson_process(self):
        rng = random.Random(42)
        events = poisson_process_simulate(2.0, 5.0, rng)
        self.assertTrue(all(0 <= e <= 5.0 for e in events))
        self.assertGreater(len(events), 0)


class TestBrownianMotion(unittest.TestCase):
    def test_brownian_motion_length(self):
        rng = random.Random(42)
        path = brownian_motion(100, 0.01, rng)
        self.assertEqual(len(path), 101)
        self.assertEqual(path[0], 0.0)

    def test_brownian_motion_variance(self):
        rng = random.Random(42)
        path = brownian_motion(1000, 0.01, rng)
        # Var(W_t) = t, so Var(W_1) ≈ 1
        final = path[-1]
        self.assertGreater(final, -5.0)
        self.assertLess(final, 5.0)

    def test_quadratic_variation(self):
        rng = random.Random(42)
        # T = 1000 * 0.01 = 10, so quadratic variation should be ~10
        qv = brownian_motion_quadratic_variation(1000, 0.01, rng)
        self.assertGreater(qv, 8.0)
        self.assertLess(qv, 12.0)

    def test_geometric_brownian_motion(self):
        rng = random.Random(42)
        path = geometric_brownian_motion(100.0, 0.05, 0.2, 100, 0.01, rng)
        self.assertEqual(len(path), 101)
        self.assertEqual(path[0], 100.0)
        # All values should be positive
        self.assertTrue(all(p > 0 for p in path))


class TestCTMC(unittest.TestCase):
    def test_ctmc_simulate(self):
        # Two-state CTMC
        Q = [[-2.0, 2.0], [1.0, -1.0]]
        ctmc = CTMC(Q)
        rng = random.Random(42)
        states, times = ctmc.simulate(20, rng, start=0)
        self.assertEqual(len(states), 21)  # initial + 20 transitions
        self.assertTrue(all(0 <= s <= 1 for s in states))

    def test_ctmc_stationary_distribution(self):
        Q = [[-2.0, 2.0], [1.0, -1.0]]
        ctmc = CTMC(Q)
        pi = ctmc.stationary_distribution()
        # Should sum to 1
        self.assertAlmostEqual(sum(pi), 1.0, places=2)


class TestKalmanFilter(unittest.TestCase):
    def test_kalman_filter_constant(self):
        # Constant position with noisy observations
        F = [[1.0, 0.0], [0.0, 1.0]]  # state: [position, velocity]
        H = [[1.0, 0.0]]  # observe position
        Q = [[0.01, 0.0], [0.0, 0.01]]
        R = [[1.0]]
        x0 = [0.0, 0.0]
        P0 = [[1.0, 0.0], [0.0, 1.0]]

        kf = KalmanFilter(F, H, Q, R, x0, P0)

        # Simulate noisy observations around constant value 5
        rng = random.Random(42)
        observations = [[5.0 + rng.gauss(0, 1)] for _ in range(20)]

        states = kf.filter(observations)
        self.assertEqual(len(states), 20)
        # Final estimate should be close to 5
        self.assertGreater(states[-1][0], 3.0)
        self.assertLess(states[-1][0], 7.0)


class TestParticleFilter(unittest.TestCase):
    def test_particle_filter(self):
        # 1D constant position
        def transition(x, noise):
            return x + noise

        def observation(x, noise):
            return x + noise

        def process_noise(rng):
            return rng.gauss(0, 0.1)

        def obs_noise(rng):
            return rng.gauss(0, 0.5)

        pf = ParticleFilter(
            200, transition, observation, process_noise, obs_noise, rng=random.Random(42)
        )
        pf.initialize([2.0] * 200)

        # Feed observations around value 3.0
        estimates = []
        rng = random.Random(42)
        for _ in range(50):
            z = 3.0 + rng.gauss(0, 0.5)
            estimate = pf.step(z)
            estimates.append(estimate)

        # Final estimate should be near 3.0 (with some tolerance)
        self.assertGreater(estimates[-1], 1.0)
        self.assertLess(estimates[-1], 5.0)


class TestMetropolisHastings(unittest.TestCase):
    def test_metropolis_hastings_normal(self):
        # Target: standard normal log-density
        def log_density(x):
            return -0.5 * x * x

        samples = metropolis_hastings(
            log_density, n_samples=2000, initial=0.0, proposal_std=1.0, burn_in=500
        )
        # Mean should be near 0
        mean = sum(samples) / len(samples)
        self.assertGreater(mean, -0.5)
        self.assertLess(mean, 0.5)

        # Standard deviation should be near 1
        var = sum((s - mean) ** 2 for s in samples) / len(samples)
        self.assertGreater(math.sqrt(var), 0.5)
        self.assertLess(math.sqrt(var), 1.5)


if __name__ == "__main__":
    unittest.main()
