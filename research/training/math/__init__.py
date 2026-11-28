"""Mathematics study modules."""

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

__all__ = [
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
]
