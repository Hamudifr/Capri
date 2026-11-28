"""Tests for the probability training module."""

import unittest
import math
import random

from research.training.probability.foundations import (
    conditional_probability, bayes_theorem, total_probability,
    are_independent, expectation, variance_rv, covariance_rv,
    beta_update, beta_mean, beta_variance, normal_update,
    transition_matrix_from_counts, apply_transition, steady_state,
    markov_chain_simulate, monte_carlo_estimate, monte_carlo_pi,
    law_of_large_numbers, central_limit_theorem, gibbs_sampler,
)


class TestBayes(unittest.TestCase):

    def test_conditional_probability(self):
        # P(A|B) = P(A and B) / P(B)
        self.assertAlmostEqual(
            conditional_probability(0.3, 0.5), 0.6, places=8
        )

    def test_conditional_probability_zero(self):
        # P(B) = 0 → returns 0.0
        self.assertEqual(conditional_probability(0.1, 0.0), 0.0)

    def test_bayes_theorem(self):
        # P(A|B) = P(B|A) * P(A) / P(B)
        result = bayes_theorem(prior=0.2, likelihood=0.8, evidence=0.3)
        self.assertAlmostEqual(result, (0.8 * 0.2) / 0.3, places=8)

    def test_total_probability(self):
        result = total_probability(
            p_b_given_a=0.6, p_a=0.3,
            p_b_given_not_a=0.2, p_not_a=0.7,
        )
        self.assertAlmostEqual(result, 0.6 * 0.3 + 0.2 * 0.7, places=8)

    def test_are_independent_false(self):
        # 0.3 * 0.4 = 0.12 != 0.15
        self.assertFalse(are_independent(p_a=0.3, p_b=0.4, p_ab=0.15))

    def test_are_independent_true(self):
        # 0.2 * 0.3 = 0.06
        self.assertTrue(are_independent(p_a=0.2, p_b=0.3, p_ab=0.06))


class TestRandomVariables(unittest.TestCase):

    def test_expectation_weighted(self):
        values = [1, 2, 3, 4, 5]
        weights = [0.1, 0.1, 0.1, 0.3, 0.4]
        # (1*0.1 + 2*0.1 + 3*0.1 + 4*0.3 + 5*0.4) / 1.0 = 3.8
        self.assertAlmostEqual(expectation(values, weights), 3.8, places=8)

    def test_expectation_uniform(self):
        values = [1, 2, 3, 4]
        self.assertAlmostEqual(expectation(values), 2.5, places=8)

    def test_variance_rv(self):
        values = [1, 2, 3]
        weights = [0.2, 0.5, 0.3]
        m = expectation(values, weights)
        v = variance_rv(values, weights)
        e_x2 = sum(x * x * p for x, p in zip(values, weights))
        self.assertAlmostEqual(v, e_x2 - m * m, places=8)

    def test_covariance_rv_independent(self):
        # When weights are uniform, covariance of independent variables ≈ 0
        x = [1, 2, 3]
        y = [2, 1, 4]
        cov = covariance_rv(x, y, weights=[1/3, 1/3, 1/3])
        # Not exactly zero but should be small for this data
        self.assertLess(abs(cov), 1.0)


class TestConjugatePriors(unittest.TestCase):

    def test_beta_update(self):
        # Beta(2,3) prior, 3 successes, 2 failures
        a_post, b_post = beta_update(2, 3, 3, 2)
        self.assertEqual(a_post, 5)
        self.assertEqual(b_post, 5)

    def test_beta_mean(self):
        self.assertAlmostEqual(beta_mean(2, 6), 2 / 8, places=8)

    def test_beta_variance(self):
        a, b = 2, 6
        var = (a * b) / ((a + b) ** 2 * (a + b + 1))
        self.assertAlmostEqual(beta_variance(a, b), var, places=8)

    def test_normal_update_shrinks(self):
        mean_post, var_post = normal_update(
            mu0=0.0, sigma0=4.0, mu_data=1.0, sigma_data=1.0, n=2
        )
        # Posterior variance should be less than prior variance (16)
        self.assertLess(var_post, 16.0)
        self.assertGreater(var_post, 0.0)
        # Posterior mean should be pulled toward the data mean
        self.assertGreater(mean_post, 0.0)
        self.assertLess(mean_post, 1.0)


class TestMarkovChains(unittest.TestCase):

    def test_transition_matrix_from_counts(self):
        counts = [[100]]
        result = transition_matrix_from_counts(counts)
        self.assertAlmostEqual(result[0][0], 1.0, places=8)

    def test_apply_transition(self):
        T = [[0.5, 0.5], [0.2, 0.8]]
        dist = apply_transition(T, [1.0, 0.0])
        self.assertAlmostEqual(dist[0], 0.5, places=8)
        self.assertAlmostEqual(dist[1], 0.5, places=8)

    def test_steady_state(self):
        T = [[0.7, 0.3], [0.4, 0.6]]
        ss = steady_state(T)
        self.assertAlmostEqual(sum(ss), 1.0, places=8)
        dist = apply_transition(T, ss)
        for i in range(len(ss)):
            self.assertAlmostEqual(dist[i], ss[i], places=8)

    def test_markov_chain_simulate(self):
        T = [[0.5, 0.5], [0.5, 0.5]]
        path = markov_chain_simulate(T, initial_state=0, steps=20)
        self.assertEqual(len(path), 21)
        self.assertEqual(path[0], 0)


class TestMonteCarlo(unittest.TestCase):

    def test_monte_carlo_estimate(self):
        f = lambda x: x ** 2
        rng = random.Random(42)
        result = monte_carlo_estimate(f, 100000, (0, 1), rng=rng)
        # True integral of x^2 on [0,1] = 1/3
        self.assertAlmostEqual(result, 1 / 3, places=2)

    def test_monte_carlo_pi(self):
        rng = random.Random(42)
        result = monte_carlo_pi(200000, rng=rng)
        self.assertAlmostEqual(result, math.pi, places=1)


class TestLLN_CLT(unittest.TestCase):

    def test_law_of_large_numbers(self):
        rng = random.Random(42)
        results = law_of_large_numbers(100000, rng=rng)
        # Final value should be close to 0.5
        self.assertAlmostEqual(results[-1], 0.5, places=2)

    def test_central_limit_theorem(self):
        rng = random.Random(42)
        means = central_limit_theorem(5000, 50, rng=rng)
        self.assertEqual(len(means), 5000)
        # Sample mean should be near 0 (Gaussian with mean 0)
        sample_mean = sum(means) / len(means)
        self.assertAlmostEqual(sample_mean, 0.0, places=1)
        # Standard deviation should be ~1/sqrt(50) ≈ 0.141
        sample_std = math.sqrt(
            sum((m - sample_mean) ** 2 for m in means) / len(means)
        )
        self.assertAlmostEqual(sample_std, 1 / math.sqrt(50), places=2)


class TestGibbs(unittest.TestCase):

    def test_gibbs_sampler(self):
        # 2-dimensional Gaussian sampler
        def log_prob(state):
            x, y = state
            return -(x ** 2 + y ** 2) / 2

        rng = random.Random(42)
        samples = gibbs_sampler(log_prob, [1.0, 1.0], 100, rng=rng)
        self.assertEqual(len(samples), 101)  # includes initial
        for s in samples:
            self.assertEqual(len(s), 2)


if __name__ == "__main__":
    unittest.main()
