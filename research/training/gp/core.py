"""Gaussian processes: kernel methods, posterior prediction, Cholesky.

Stdlib-only. Pure computation, no external dependencies.

Core concepts:
- Kernel functions (RBF, linear, Matern, periodic)
- Gram matrix computation
- Cholesky decomposition for solving linear systems
- Gaussian process regression: posterior mean and variance
- Hyperparameter optimization (marginal likelihood gradient descent)
"""

from __future__ import annotations

import math

Point = tuple[float, ...]


# ===========================================================================
# Kernels
# ===========================================================================

def rbf_kernel(x: Point, y: Point, length_scale: float = 1.0) -> float:
    """RBF (Gaussian) kernel: exp(-||x-y||^2 / (2 * l^2))."""
    diff_sq = sum((a - b) ** 2 for a, b in zip(x, y))
    return math.exp(-diff_sq / (2.0 * length_scale * length_scale))


def linear_kernel(x: Point, y: Point) -> float:
    """Linear kernel: x · y."""
    return sum(a * b for a, b in zip(x, y))


def matern_kernel(x: Point, y: Point, length_scale: float = 1.0, nu: float = 1.5) -> float:
    """Matern kernel with smoothness parameter nu.

    nu=0.5 -> exponential, nu=1.5 -> once differentiable, nu=2.5 -> twice.
    """
    r = math.sqrt(sum((a - b) ** 2 for a, b in zip(x, y)))
    if r < 1e-15:
        return 1.0
    if abs(nu - 0.5) < 1e-10:
        return math.exp(-r / length_scale)
    if abs(nu - 1.5) < 1e-10:
        sq_r = r / length_scale
        return (1.0 + sq_r) * math.exp(-sq_r)
    if abs(nu - 2.5) < 1e-10:
        sq_r = r / length_scale
        return (1.0 + sq_r + sq_r * sq_r / 3.0) * math.exp(-sq_r)
    # General Matern formula
    sq_r = r / length_scale
    gamma = math.gamma(nu + 0.5)
    factor = (2.0 ** math.sqrt(nu)) / gamma
    return factor * (sq_r ** nu) * math.exp(-sq_r)


def periodic_kernel(x: Point, y: Point, period: float = 2.0, length_scale: float = 1.0) -> float:
    """Periodic (SIN) kernel."""
    diff = [a - b for a, b in zip(x, y)]
    # Compute sum of sin components
    sqrt_term = sum((math.sin(2.0 * math.pi * d / period) ** 2) for d in diff)
    return math.exp(-2.0 * (math.sin(math.pi * math.sqrt(sqrt_term) / period) ** 2)
                    / (length_scale ** 2))


def squared_exponential_kernel(x: Point, y: Point, length_scale: float = 1.0) -> float:
    """Alias for RBF with a slightly different parameterization."""
    return rbf_kernel(x, y, length_scale)


# Kernel registry for easy lookup
KERNELS = {
    "rbf": rbf_kernel,
    "linear": linear_kernel,
    "matern": matern_kernel,
    "periodic": periodic_kernel,
}


# ===========================================================================
# Gram matrices and Cholesky
# ===========================================================================

def gram_matrix(points: list[Point], kernel: callable) -> list[list[float]]:
    """Compute the n×n Gram (kernel) matrix for a set of points."""
    n = len(points)
    K = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            K[i][j] = kernel(points[i], points[j])
    return K


def cholesky_decompose(A: list[list[float]]) -> list[list[float]] | None:
    """Cholesky decomposition: A = L L^T. Returns L or None if not PD."""
    n = len(A)
    L = [[0.0] * n for _ in range(n)]

    for i in range(n):
        for j in range(i + 1):
            s = sum(L[i][k] * L[j][k] for k in range(j))
            if i == j:
                val = A[i][i] - s
                if val <= 0:
                    return None
                L[i][i] = math.sqrt(val)
            else:
                L[i][j] = (A[i][j] - s) / L[j][j]
    return L


def cholesky_solve(L: list[list[float]], b: list[float]) -> list[float]:
    """Solve L L^T x = b using the Cholesky factor L."""
    n = len(L)
    # Forward substitution: L y = b
    y = [0.0] * n
    for i in range(n):
        y[i] = (b[i] - sum(L[i][k] * y[k] for k in range(i))) / L[i][i]
    # Back substitution: L^T x = y
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (y[i] - sum(L[k][i] * x[k] for k in range(i + 1, n))) / L[i][i]
    return x


def forward_substitute(L: list[list[float]], b: list[float]) -> list[float]:
    """Solve L x = b (forward substitution only, for lower-triangular L)."""
    n = len(L)
    x = [0.0] * n
    for i in range(n):
        x[i] = (b[i] - sum(L[i][k] * x[k] for k in range(i))) / L[i][i]
    return x


# ===========================================================================
# Gaussian Process regression
# ===========================================================================

class GaussianProcess:
    """Gaussian process regressor.

    p(f* | X, y, x*) = N(mean, cov)

    Prior: f ~ GP(0, K(X, X) + sigma_n^2 I)
    Posterior mean: K(x*, X) [K + sigma_n^2 I]^{-1} y
    Posterior variance: K(x*, x*) - K(x*, X) [K + sigma_n^2 I]^{-1} K(X, x*)
    """

    def __init__(self, kernel: callable = rbf_kernel, noise: float = 1e-3):
        self.kernel = kernel
        self.noise = noise
        self.X_train: list[Point] = []
        self.y_train: list[float] = []
        self._alpha: list[float] = []  # Precomputed [K + sigma_n^2 I]^{-1} y
        self._K_inv: list[list[float]] = []  # Precomputed inverse

    def fit(self, X: list[Point], y: list[float]) -> "GaussianProcess":
        """Fit the GP to training data."""
        self.X_train = list(X)
        self.y_train = list(y)
        n = len(X)

        K = gram_matrix(X, self.kernel)

        # Add noise to diagonal
        for i in range(n):
            K[i][i] += self.noise

        L = cholesky_decompose(K)
        if L is None:
            # Add jitter
            for i in range(n):
                K[i][i] += 1e-6
            L = cholesky_decompose(K)
            if L is None:
                raise ValueError("Cholesky decomposition failed: matrix not positive definite")

        # Solve L alpha = y
        self._alpha = cholesky_solve(L, list(y))

        # Store L^T inverse for variance computation (K^{-1} = L^{-T} L^{-1})
        # We'll compute K(x*, X) [K + sigma^2 I]^{-1} directly via L
        self._L = L
        self._n = n
        return self

    def _predict_mean(self, x: Point) -> float:
        """Posterior mean at x."""
        if not self.X_train:
            return 0.0
        k_star = [self.kernel(x, xp) for xp in self.X_train]
        # mean = k_star^T K^{-1} y = k_star^T L^{-T} L^{-1} y = (L^{-1} k_star)^T (L^{-1} y)
        # w = L^{-1} y (forward substitution)
        # v = L^{-1} k_star (forward substitution)
        # mean = v^T w
        w = forward_substitute(self._L, self.y_train)
        v = forward_substitute(self._L, k_star)
        return sum(v[i] * w[i] for i in range(len(self._alpha)))

    def _predict_variance(self, x: Point) -> float:
        """Posterior variance at x."""
        if not self.X_train:
            return self.kernel(x, x)
        k_star = [self.kernel(x, xp) for xp in self.X_train]
        # v = L^{-1} k_star (forward substitution)
        v = forward_substitute(self._L, k_star)
        # variance = k(x,x) - v^T v
        var = self.kernel(x, x) - sum(vi * vi for vi in v)
        return max(0.0, var)

    def predict(self, X: list[Point]) -> tuple[list[float], list[float]]:
        """Predict mean and variance for a set of points."""
        means = [self._predict_mean(x) for x in X]
        variances = [self._predict_variance(x) for x in X]
        return means, variances

    def log_marginal_likelihood(self) -> float:
        """Log marginal likelihood: log p(y | X, theta)."""
        if not self.X_train:
            return 0.0
        n = self._n
        # log p(y) = -0.5 y^T K^{-1} y - 0.5 log|K| - n/2 log(2pi)
        # y^T K^{-1} y = alpha^T L^T K^{-1} L alpha = alpha^T alpha (since L^{-1} y = alpha, K = LL^T)
        y_alpha = sum(a * a for a in self._alpha)

        # log|K| = 2 * sum(log(diag(L)))
        log_det = 2.0 * sum(math.log(self._L[i][i]) for i in range(n))

        return -0.5 * y_alpha - 0.5 * log_det - 0.5 * n * math.log(2.0 * math.pi)


# ===========================================================================
# Hyperparameter optimization
# ===========================================================================

def optimize_hyperparameters(
    X: list[Point],
    y: list[float],
    kernel_name: str = "rbf",
    iterations: int = 100,
    lr: float = 0.01,
    noise: float = 1e-3,
) -> tuple[float, float]:
    """Gradient-descent optimization of GP hyperparameters (length_scale, noise).

    For simplicity, optimizes the RBF length_scale by finite differences
    on the log marginal likelihood. Returns (best_length_scale, best_log_ml).
    """
    length_scale = 1.0
    best_ml = -float("inf")
    best_ls = length_scale

    for _ in range(iterations):
        gp = GaussianProcess(kernel=lambda a, b, ls=length_scale: rbf_kernel(a, b, ls), noise=noise)
        gp.fit(X, y)
        ml = gp.log_marginal_likelihood()

        if ml > best_ml:
            best_ml = ml
            best_ls = length_scale

        # Numerical gradient
        eps = 1e-3
        gp2 = GaussianProcess(
            kernel=lambda a, b, ls=length_scale + eps: rbf_kernel(a, b, ls), noise=noise
        )
        gp2.fit(X, y)
        ml2 = gp2.log_marginal_likelihood()
        grad = (ml2 - ml) / eps
        length_scale += lr * grad
        length_scale = max(0.01, min(100.0, length_scale))

    return best_ls, best_ml
