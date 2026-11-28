"""Optimization study modules."""

from research.training.optimization.methods import (
    bisection_root, newtons_method, secant_method,
    golden_section_search, backtracking_line_search,
    conjugate_gradient, simulated_annealing, genetic_algorithm,
    step_decay, exponential_decay, cosine_annealing,
    linear_warmup, cosine_with_warmup, nelder_mead,
)

__all__ = [
    "bisection_root", "newtons_method", "secant_method",
    "golden_section_search", "backtracking_line_search",
    "conjugate_gradient", "simulated_annealing", "genetic_algorithm",
    "step_decay", "exponential_decay", "cosine_annealing",
    "linear_warmup", "cosine_with_warmup", "nelder_mead",
]
