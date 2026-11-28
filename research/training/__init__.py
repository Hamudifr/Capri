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

from research.training.geometry.core import (
    KDTree, KDNode,
    v_add as geo_v_add, v_sub as geo_v_sub, v_scale as geo_v_scale,
    v_dot as geo_v_dot, v_cross as geo_v_cross, v_norm as geo_v_norm,
    v_dist as geo_v_dist, v_dist_sq as geo_v_dist_sq,
    v_normalize as geo_v_normalize, v_angle as geo_v_angle,
    line_intersection as geo_line_intersection,
    segment_intersect as geo_segment_intersect,
    polygon_area as geo_polygon_area, polygon_perimeter as geo_polygon_perimeter,
    point_in_polygon as geo_point_in_polygon, polygon_centroid as geo_polygon_centroid,
    convex_hull as geo_convex_hull, is_convex as geo_is_convex,
    nearest_site as geo_nearest_site,
    voronoi_cell_bounds as geo_voronoi_cell_bounds,
    voronoi_diagram as geo_voronoi_diagram,
)
from research.training.rl.core import (
    GridWorld,
    epsilon_greedy, softmax_policy,
    q_learning_update as rl_q_learning_update,
    sarsa_update as rl_sarsa_update,
    value_iteration as rl_value_iteration,
    extract_policy as rl_extract_policy,
    policy_iteration as rl_policy_iteration,
    reinforce_update as rl_reinforce_update,
    train_q_learning, evaluate_q_policy,
)
from research.training.gp.core import (
    GaussianProcess as GP_Model,
    rbf_kernel as gp_rbf_kernel, linear_kernel as gp_linear_kernel,
    matern_kernel as gp_matern_kernel, periodic_kernel as gp_periodic_kernel,
    gram_matrix as gp_gram_matrix,
    cholesky_decompose as gp_cholesky_decompose,
    cholesky_solve as gp_cholesky_solve,
    optimize_hyperparameters as gp_optimize_hyperparameters,
)
from research.training.sat.solver import (
    CDCLSolver,
    solve_2sat, solve_sat_cdcl, dpll_solve,
    var_of as sat_var_of, neg as sat_neg,
)
from research.training.compilers.core import (
    Lexer, Parser, Compiler, VM as BytecodeVM,
    Token as CompilerToken, CodeObject,
    compile_and_run,
)
from research.training.game.core import (
    make_zero_sum_game, make_bimatrix_game,
    minimax as game_minimax,
    best_response as game_best_response,
    strictly_dominated as game_strictly_dominated,
    weakly_dominated as game_weakly_dominated,
    eliminate_dominated as game_eliminate_dominated,
    nash_equilibrium_2p, mixed_nash_equilibrium_2x2,
    zero_sum_game_value, zero_sum_game_optimal_mixed,
    fictitious_play_strategy,
    shapley_value, check_correlated_equilibrium,
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
    # geometry
    "KDTree", "KDNode",
    "geo_v_add", "geo_v_sub", "geo_v_scale",
    "geo_v_dot", "geo_v_cross", "geo_v_norm",
    "geo_v_dist", "geo_v_dist_sq",
    "geo_v_normalize", "geo_v_angle",
    "geo_line_intersection", "geo_segment_intersect",
    "geo_polygon_area", "geo_polygon_perimeter",
    "geo_point_in_polygon", "geo_polygon_centroid",
    "geo_convex_hull", "geo_is_convex",
    "geo_nearest_site",
    "geo_voronoi_cell_bounds", "geo_voronoi_diagram",
    # rl
    "GridWorld",
    "epsilon_greedy", "softmax_policy",
    "rl_q_learning_update", "rl_sarsa_update",
    "rl_value_iteration", "rl_extract_policy", "rl_policy_iteration",
    "rl_reinforce_update",
    "train_q_learning", "evaluate_q_policy",
    # gp
    "GP_Model",
    "gp_rbf_kernel", "gp_linear_kernel", "gp_matern_kernel", "gp_periodic_kernel",
    "gp_gram_matrix", "gp_cholesky_decompose", "gp_cholesky_solve",
    "gp_optimize_hyperparameters",
    # sat
    "CDCLSolver", "solve_2sat", "solve_sat_cdcl", "dpll_solve",
    "sat_var_of", "sat_neg",
    # compilers
    "Lexer", "Parser", "Compiler", "BytecodeVM",
    "CompilerToken", "CodeObject", "compile_and_run",
    # game
    "make_zero_sum_game", "make_bimatrix_game",
    "game_minimax", "game_best_response",
    "game_strictly_dominated", "game_weakly_dominated", "game_eliminate_dominated",
    "nash_equilibrium_2p", "mixed_nash_equilibrium_2x2",
    "zero_sum_game_value", "zero_sum_game_optimal_mixed",
    "fictitious_play_strategy", "shapley_value", "check_correlated_equilibrium",
]
