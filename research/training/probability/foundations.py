"""Probability theory study modules.

Implements core probability concepts: conditional probability,
Bayes' theorem, independence, Markov chains, and Monte Carlo methods.
Pure stdlib, no dependencies.

Topics covered:
- Conditional probability and Bayes' theorem
- Independence and conditional independence
- Random variables: expectation, variance, covariance
- Bayesian inference (conjugate priors)
- Markov chains: transition matrices, stationary distributions
- Monte Carlo estimation
- Gibbs sampling
- The law of large numbers and central limit theorem (simulation)
"""

from __future__ import annotations

import math
import random


# ===========================================================================
# Conditional probability and Bayes
# ===========================================================================

def conditional_probability(p_ab: float, p_b: float) -> float:
    """P(A|B) = P(A and B) / P(B)."""
    if p_b == 0:
        return 0.0
    return p_ab / p_b


def bayes_theorem(prior: float, likelihood: float, evidence: float) -> float:
    """Bayes' theorem: P(A|B) = P(B|A) * P(A) / P(B).

    prior: P(A)
    likelihood: P(B|A)
    evidence: P(B)
    """
    if evidence == 0:
        return 0.0
    return (likelihood * prior) / evidence


def total_probability(p_b_given_a: float, p_a: float,
                      p_b_given_not_a: float, p_not_a: float) -> float:
    """Law of total probability for two hypotheses."""
    return p_b_given_a * p_a + p_b_given_not_a * p_not_a


def are_independent(p_a: float, p_b: float, p_ab: float, tol: float = 1e-10) -> bool:
    """Check if A and B are independent: P(A and B) = P(A) * P(B)."""
    return abs(p_ab - p_a * p_b) < tol


# ===========================================================================
# Random variables
# ===========================================================================

def expectation(values: list[float], weights: list[float] | None = None) -> float:
    """Expected value E[X]."""
    if not values:
        return 0.0
    if weights is None:
        return sum(values) / len(values)
    w_sum = sum(weights)
    if w_sum == 0:
        return 0.0
    return sum(v * w for v, w in zip(values, weights)) / w_sum


def variance_rv(values: list[float], weights: list[float] | None = None) -> float:
    """Variance of a random variable."""
    mu = expectation(values, weights)
    if weights is None:
        return sum((v - mu) ** 2 for v in values) / len(values)
    w_sum = sum(weights)
    if w_sum == 0:
        return 0.0
    return sum((v - mu) ** 2 * w for v, w in zip(values, weights)) / w_sum


def covariance_rv(x: list[float], y: list[float],
                  weights: list[float] | None = None) -> float:
    """Covariance Cov(X, Y)."""
    mu_x = expectation(x, weights)
    mu_y = expectation(y, weights)
    if weights is None:
        n = len(x)
        return sum((xi - mu_x) * (yi - mu_y) for xi, yi in zip(x, y)) / n
    w_sum = sum(weights)
    if w_sum == 0:
        return 0.0
    return sum((xi - mu_x) * (yi - mu_y) * w
               for xi, yi, w in zip(x, y, weights)) / w_sum


# ===========================================================================
# Bayesian inference: conjugate priors
# ===========================================================================

def beta_prior(alpha: float, beta: float) -> float:
    """Beta distribution prior (as a function value for study)."""
    return math.exp(
        (alpha - 1) * math.log(0.5) + (beta - 1) * math.log(0.5)
    )  # Simplified for study — real implementation uses lgamma


def beta_update(alpha: float, beta: float, successes: int, failures: int) -> tuple[float, float]:
    """Posterior Beta parameters after observing data.

    Conjugate update for Bernoulli/Binomial likelihood.
    """
    return alpha + successes, beta + failures


def beta_mean(alpha: float, beta: float) -> float:
    return alpha / (alpha + beta) if (alpha + beta) > 0 else 0.0


def beta_variance(alpha: float, beta: float) -> float:
    denom = (alpha + beta) ** 2 * (alpha + beta + 1)
    if denom == 0:
        return 0.0
    return alpha * beta / denom


def normal_update(mu0: float, sigma0: float, mu_data: float, sigma_data: float,
                  n: int = 1) -> tuple[float, float]:
    """Conjugate normal-normal update.

    Returns (posterior_mean, posterior_variance).
    """
    sigma0_sq = sigma0 ** 2
    sigma_data_sq = sigma_data ** 2
    posterior_var = 1.0 / (1.0 / sigma0_sq + n / sigma_data_sq)
    posterior_mean = posterior_var * (mu0 / sigma0_sq + n * mu_data / sigma_data_sq)
    return posterior_mean, posterior_var


# ===========================================================================
# Markov chains
# ===========================================================================

def transition_matrix_from_counts(counts: list[list[float]]) -> list[list[float]]:
    """Convert a count matrix to a transition matrix."""
    rows = []
    for row in counts:
        total = sum(row)
        if total == 0:
            rows.append([0.0] * len(row))
        else:
            rows.append([c / total for c in row])
    return rows


def apply_transition(transition: list[list[float]], state: list[float]) -> list[float]:
    """Apply one step of a Markov chain: state * transition."""
    result = [0.0] * len(state)
    for j in range(len(state)):
        result[j] = sum(state[i] * transition[i][j] for i in range(len(state)))
    return result


def steady_state(transition: list[list[float]], max_iters: int = 10000,
                 tol: float = 1e-12) -> list[float]:
    """Find the stationary distribution by power iteration."""
    n = len(transition)
    if n == 0:
        return []
    # Start from uniform
    state = [1.0 / n] * n
    for _ in range(max_iters):
        new_state = apply_transition(transition, state)
        diff = sum(abs(a - b) for a, b in zip(state, new_state))
        state = new_state
        if diff < tol:
            break
    return state


def markov_chain_simulate(transition: list[list[float]], initial_state: int,
                          steps: int, rng: random.Random | None = None) -> list[int]:
    """Simulate a Markov chain for a number of steps."""
    if rng is None:
        rng = random.Random(42)
    states = [initial_state]
    current = initial_state
    for _ in range(steps):
        row = transition[current]
        # Sample from row
        r = rng.random()
        cumulative = 0.0
        for j, prob in enumerate(row):
            cumulative += prob
            if r <= cumulative:
                current = j
                break
        states.append(current)
    return states


# ===========================================================================
# Monte Carlo methods
# ===========================================================================

def monte_carlo_estimate(f, n_samples: int, bounds: tuple[float, float],
                         rng: random.Random | None = None) -> float:
    """Estimate integral of f over [a, b] via Monte Carlo."""
    if rng is None:
        rng = random.Random(42)
    a, b = bounds
    width = b - a
    total = 0.0
    for _ in range(n_samples):
        x = rng.uniform(a, b)
        total += f(x)
    return (total / n_samples) * width


def monte_carlo_pi(n_samples: int, rng: random.Random | None = None) -> float:
    """Estimate pi by sampling inside a unit circle."""
    if rng is None:
        rng = random.Random(42)
    inside = 0
    for _ in range(n_samples):
        x = rng.uniform(-1, 1)
        y = rng.uniform(-1, 1)
        if x * x + y * y <= 1:
            inside += 1
    return 4 * inside / n_samples


def law_of_large_numbers(n: int, rng: random.Random | None = None) -> list[float]:
    """Simulate the law of large numbers for coin flips."""
    if rng is None:
        rng = random.Random(42)
    results = []
    heads = 0
    for i in range(n):
        if rng.random() < 0.5:
            heads += 1
        results.append(heads / (i + 1))
    return results


def central_limit_theorem(n_samples: int, sample_size: int,
                          rng: random.Random | None = None) -> list[float]:
    """Demonstrate CLT: averages of samples approach normal."""
    if rng is None:
        rng = random.Random(42)
    means = []
    for _ in range(n_samples):
        sample = [rng.gauss(0, 1) for _ in range(sample_size)]
        means.append(sum(sample) / sample_size)
    return means


# ===========================================================================
# Gibbs sampling
# ===========================================================================

def gibbs_sampler(target_log_prob, initial: list[float], n_iters: int,
                  rng: random.Random | None = None) -> list[list[float]]:
    """Basic Gibbs sampler.

    target_log_prob: function taking a state vector, returning log-probability
    initial: initial state
    n_iters: number of iterations
    Returns list of states.
    """
    if rng is None:
        rng = random.Random(42)
    state = initial[:]
    samples = [state[:]]
    for _ in range(n_iters):
        for i in range(len(state)):
            # In a real Gibbs sampler we'd sample from the conditional.
            # For study, we do a simple Metropolis-adjusted proposal.
            proposed = state[:]
            proposed[i] += rng.gauss(0, 1.0)
            current_log = target_log_prob(state)
            proposed_log = target_log_prob(proposed)
            log_ratio = proposed_log - current_log
            if math.log(rng.random() + 1e-15) < log_ratio:
                state = proposed
        samples.append(state[:])
    return samples


def __all__() -> list[str]:
    return [
        "conditional_probability", "bayes_theorem", "total_probability",
        "are_independent", "expectation", "variance_rv", "covariance_rv",
        "beta_update", "beta_mean", "beta_variance", "normal_update",
        "transition_matrix_from_counts", "apply_transition", "steady_state",
        "markov_chain_simulate", "monte_carlo_estimate", "monte_carlo_pi",
        "law_of_large_numbers", "central_limit_theorem", "gibbs_sampler",
    ]
