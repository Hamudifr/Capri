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
from research.training.info.theory import (
    shannon_entropy, joint_entropy, marginal_probs,
    conditional_entropy, mutual_information,
    normalized_mutual_information, information_gain,
    kl_divergence_bits, cross_entropy_bits, entropy_from_counts,
    HuffmanNode, HuffmanCoder, mutual_information_feature,
)
from research.training.retrieval.core import (
    tokenize, remove_stop_words, DEFAULT_STOP_WORDS,
    term_frequency, document_frequency, inverse_document_frequency,
    tfidf_weights, cosine_similarity, dot_product_sparse,
    retrieval_vector_norm as vector_norm_retrieval,
    InvertedIndex, BM25Ranker,
    precision_score, recall_score, f1_score, mean_average_precision,
)
from research.training.crypto.numbers import (
    mod_pow, modular_inverse, euler_phi,
    fermat_little_theorem, euler_theorem,
    gcd, extended_gcd,
    is_prime_trial, miller_rabin, find_prime,
    tonelli_shanks, RSA, baby_step_giant_step,
    diffie_hellman_shared, fnv1a_32, fnv1a_64,
    sha256_hex, sha256_int,
)
from research.training.signals.processing import (
    dft, idft, fft, ifft, next_power_of_two,
    fft_magnitude, convolve, convolve_fft,
    circular_convolve, moving_average_filter, fir_filter,
    cross_correlation, auto_correlation,
    freq_bins, dominant_frequency,
)
from research.training.graph.algorithms import (
    UnionFind, kruskal, kruskal_total_weight,
    prim, prim_total_weight,
    bellman_ford, bellman_ford_path,
    floyd_warshall, floyd_warshall_has_negative_cycle,
    edmonds_karp, min_cut_edges,
    kosaraju_scc, greedy_graph_coloring, chromatic_number,
    is_bipartite,
)
from research.training.lambd.calculus import (
    var as lc_var, abs as lc_abs, app as lc_app,
    is_var as lc_is_var, is_abs as lc_is_abs, is_app as lc_is_app,
    free_vars, alpha_convert, beta_reduce,
    beta_normal_form, beta_reduce_all, eta_reduce,
    beta_eta_normal_form,
    church_true, church_false, church_if,
    church_and, church_or, church_not,
    church_zero, church_one, church_succ,
    church_add, church_multiply, church_pred,
    church_to_int, int_to_church,
    base_type, arrow_type, type_equals, type_pretty,
    t_var, t_abs, t_app, infer_type, check_type,
    type_of,
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
    # info
    "shannon_entropy", "joint_entropy", "marginal_probs",
    "conditional_entropy", "mutual_information",
    "normalized_mutual_information", "information_gain",
    "kl_divergence_bits", "cross_entropy_bits", "entropy_from_counts",
    "HuffmanNode", "HuffmanCoder", "mutual_information_feature",
    # retrieval
    "tokenize", "remove_stop_words", "DEFAULT_STOP_WORDS",
    "term_frequency", "document_frequency", "inverse_document_frequency",
    "tfidf_weights", "cosine_similarity", "dot_product_sparse",
    "vector_norm_retrieval", "InvertedIndex", "BM25Ranker",
    "precision_score", "recall_score", "f1_score",
    "mean_average_precision",
    # crypto
    "mod_pow", "modular_inverse", "euler_phi",
    "fermat_little_theorem", "euler_theorem",
    "gcd", "extended_gcd",
    "is_prime_trial", "miller_rabin", "find_prime",
    "tonelli_shanks", "RSA", "baby_step_giant_step",
    "diffie_hellman_shared", "fnv1a_32", "fnv1a_64",
    "sha256_hex", "sha256_int",
    # signals
    "dft", "idft", "fft", "ifft", "next_power_of_two",
    "fft_magnitude", "convolve", "convolve_fft",
    "circular_convolve", "moving_average_filter", "fir_filter",
    "cross_correlation", "auto_correlation",
    "freq_bins", "dominant_frequency",
    # graph
    "UnionFind", "kruskal", "kruskal_total_weight",
    "prim", "prim_total_weight",
    "bellman_ford", "bellman_ford_path",
    "floyd_warshall", "floyd_warshall_has_negative_cycle",
    "edmonds_karp", "min_cut_edges",
    "kosaraju_scc", "greedy_graph_coloring", "chromatic_number",
    "is_bipartite",
    # lambda
    "lc_var", "lc_abs", "lc_app", "lc_is_var", "lc_is_abs", "lc_is_app",
    "free_vars", "alpha_convert", "beta_reduce",
    "beta_normal_form", "beta_reduce_all", "eta_reduce",
    "beta_eta_normal_form",
    "church_true", "church_false", "church_if",
    "church_and", "church_or", "church_not",
    "church_zero", "church_one", "church_succ",
    "church_add", "church_multiply", "church_pred",
    "church_to_int", "int_to_church",
    "base_type", "arrow_type", "type_equals", "type_pretty",
    "t_var", "t_abs", "t_app", "infer_type", "check_type",
    "type_of",
]
