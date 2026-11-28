"""Gaussian processes: kernel methods, posterior prediction, Cholesky."""

from research.training.gp.core import (
    GaussianProcess,
    rbf_kernel, linear_kernel, matern_kernel, periodic_kernel,
    squared_exponential_kernel, KERNELS,
    gram_matrix, cholesky_decompose, cholesky_solve,
    optimize_hyperparameters,
)
