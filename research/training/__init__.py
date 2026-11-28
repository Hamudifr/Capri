"""Training modules — self-study packages for LLMs, logic, math, and more.

Pure stdlib, no dependencies. Each subpackage contains executable,
tested study code covering core concepts.
"""

from research.training.logic.propositional import (
    var, negate, conjoin, disjoin, imply, biconditional,
    TRUE, FALSE, variables, evaluate, truth_table,
    to_cnf, cnf_clauses, dpll_sat, resolve, resolution_refute,
    const, fvar, func, substitute, occurs_in, unify,
)
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
from research.training.llm.core import (
    softmax, log_softmax, gelu, relu,
    scaled_dot_product_attention, multi_head_attention,
    layer_norm, layer_norm_with_params,
    sinusoidal_positional_encoding, feed_forward, BPETokenizer,
    cross_entropy, kl_divergence, entropy,
    gradient_descent, momentum_descent, adam,
    TransformerBlock,
)
from research.training.probability.foundations import (
    conditional_probability, bayes_theorem, total_probability,
    are_independent, expectation, variance_rv, covariance_rv,
    beta_update, beta_mean, beta_variance, normal_update,
    transition_matrix_from_counts, apply_transition, steady_state,
    markov_chain_simulate, monte_carlo_estimate, monte_carlo_pi,
    law_of_large_numbers, central_limit_theorem, gibbs_sampler,
)
from research.training.theory.computation import (
    DFA, NFA, regex_match, TuringMachine,
    is_polynomial_time, bfs, dfs, dijkstra,
    topological_sort, fib_dp, longest_common_subsequence, knapsack,
)
from research.training.optimization.methods import (
    bisection_root, newtons_method, secant_method,
    golden_section_search, backtracking_line_search,
    conjugate_gradient, simulated_annealing, genetic_algorithm,
    step_decay, exponential_decay, cosine_annealing,
    linear_warmup, cosine_with_warmup, nelder_mead,
)

__all__ = [
    # logic
    "var", "negate", "conjoin", "disjoin", "imply", "biconditional",
    "TRUE", "FALSE", "variables", "evaluate", "truth_table",
    "to_cnf", "cnf_clauses", "dpll_sat", "resolve", "resolution_refute",
    "const", "fvar", "func", "substitute", "occurs_in", "unify",
    # math
    "dot", "vector_add", "vector_scale", "vector_norm",
    "mat_transpose", "mat_multiply", "mat_identity", "mat_determinant",
    "mat_inverse", "power_iteration", "svd_2x2",
    "numerical_derivative", "numerical_gradient", "numerical_jacobian",
    "mean", "variance", "stddev", "covariance", "correlation",
    "linear_regression", "r_squared",
    "binomial_pmf", "binomial_mean", "binomial_variance",
    "normal_pdf", "normal_cdf",
    "power_set", "cartesian_product", "factorial",
    "permutations_count", "combinations_count",
    # llm
    "softmax", "log_softmax", "gelu", "relu",
    "scaled_dot_product_attention", "multi_head_attention",
    "layer_norm", "layer_norm_with_params",
    "sinusoidal_positional_encoding", "feed_forward", "BPETokenizer",
    "cross_entropy", "kl_divergence", "entropy",
    "gradient_descent", "momentum_descent", "adam",
    "TransformerBlock",
    # probability
    "conditional_probability", "bayes_theorem", "total_probability",
    "are_independent", "expectation", "variance_rv", "covariance_rv",
    "beta_update", "beta_mean", "beta_variance", "normal_update",
    "transition_matrix_from_counts", "apply_transition", "steady_state",
    "markov_chain_simulate", "monte_carlo_estimate", "monte_carlo_pi",
    "law_of_large_numbers", "central_limit_theorem", "gibbs_sampler",
    # theory
    "DFA", "NFA", "regex_match", "TuringMachine",
    "is_polynomial_time", "bfs", "dfs", "dijkstra",
    "topological_sort", "fib_dp", "longest_common_subsequence", "knapsack",
    # optimization
    "bisection_root", "newtons_method", "secant_method",
    "golden_section_search", "backtracking_line_search",
    "conjugate_gradient", "simulated_annealing", "genetic_algorithm",
    "step_decay", "exponential_decay", "cosine_annealing",
    "linear_warmup", "cosine_with_warmup", "nelder_mead",
]
