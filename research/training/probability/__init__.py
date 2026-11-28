"""Probability theory study modules."""

from research.training.probability.foundations import (
    conditional_probability, bayes_theorem, total_probability,
    are_independent, expectation, variance_rv, covariance_rv,
    beta_update, beta_mean, beta_variance, normal_update,
    transition_matrix_from_counts, apply_transition, steady_state,
    markov_chain_simulate, monte_carlo_estimate, monte_carlo_pi,
    law_of_large_numbers, central_limit_theorem, gibbs_sampler,
)

__all__ = [
    "conditional_probability", "bayes_theorem", "total_probability",
    "are_independent", "expectation", "variance_rv", "covariance_rv",
    "beta_update", "beta_mean", "beta_variance", "normal_update",
    "transition_matrix_from_counts", "apply_transition", "steady_state",
    "markov_chain_simulate", "monte_carlo_estimate", "monte_carlo_pi",
    "law_of_large_numbers", "central_limit_theorem", "gibbs_sampler",
]
