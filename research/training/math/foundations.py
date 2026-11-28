"""Mathematics study modules.

Implements core math primitives: linear algebra, calculus,
statistics, and calculus-based optimization primitives.
Pure stdlib, no dependencies.

Topics covered:
- Vectors and matrices: dot product, matrix multiply, transpose,
  determinant, inverse (Gauss-Jordan), eigenvalues (power iteration)
- Calculus: numerical derivatives, gradients, Jacobians
- Statistics: mean, variance, covariance, correlation, linear regression
- Probability distributions: binomial, normal, uniform
- Set theory and combinatorics basics
"""

from __future__ import annotations

from typing import Iterable

import math


# ===========================================================================
# Linear algebra
# ===========================================================================

def dot(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError(f"Vector length mismatch: {len(a)} vs {len(b)}")
    return sum(x * y for x, y in zip(a, b))


def vector_add(a: list[float], b: list[float]) -> list[float]:
    if len(a) != len(b):
        raise ValueError(f"Vector length mismatch: {len(a)} vs {len(b)}")
    return [x + y for x, y in zip(a, b)]


def vector_scale(a: list[float], scalar: float) -> list[float]:
    return [x * scalar for x in a]


def vector_norm(a: list[float]) -> float:
    return math.sqrt(dot(a, a))


def mat_transpose(m: list[list[float]]) -> list[list[float]]:
    if not m:
        return []
    return [[m[i][j] for i in range(len(m))] for j in range(len(m[0]))]


def mat_multiply(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    if not a or not b:
        return []
    if len(a[0]) != len(b):
        raise ValueError(f"Matrix shapes incompatible: {len(a)}x{len(a[0])} * {len(b)}x{len(b[0])}")
    result = [[0.0] * len(b[0]) for _ in range(len(a))]
    for i in range(len(a)):
        for j in range(len(b[0])):
            result[i][j] = sum(a[i][k] * b[k][j] for k in range(len(a[0])))
    return result


def mat_identity(n: int) -> list[list[float]]:
    return [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]


def mat_determinant(m: list[list[float]]) -> float:
    """Determinant via LU decomposition with partial pivoting."""
    n = len(m)
    if n == 0:
        return 1.0
    if n == 1:
        return m[0][0]
    if n == 2:
        return m[0][0] * m[1][1] - m[0][1] * m[1][0]

    # Copy and pivot
    a = [row[:] for row in m]
    det = 1.0
    for col in range(n):
        # Find pivot
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-15:
            return 0.0
        if pivot != col:
            a[col], a[pivot] = a[pivot], a[col]
            det *= -1
        det *= a[col][col]
        # Eliminate below
        for row in range(col + 1, n):
            factor = a[row][col] / a[col][col]
            for c in range(col, n):
                a[row][c] -= factor * a[col][c]
    return det


def mat_inverse(m: list[list[float]]) -> list[list[float]]:
    """Matrix inverse via Gauss-Jordan elimination."""
    n = len(m)
    if n == 0:
        return []

    # Augment with identity
    a = [row[:] + mat_identity(n)[i] for i, row in enumerate(m)]

    for col in range(n):
        # Find pivot
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-15:
            raise ValueError("Matrix is singular — cannot invert")
        if pivot != col:
            a[col], a[pivot] = a[pivot], a[col]

        # Scale pivot row
        pivot_val = a[col][col]
        a[col] = [x / pivot_val for x in a[col]]

        # Eliminate other rows
        for row in range(n):
            if row == col:
                continue
            factor = a[row][col]
            if abs(factor) < 1e-15:
                continue
            a[row] = [a[row][c] - factor * a[col][c] for c in range(2 * n)]

    return [row[n:] for row in a]


def power_iteration(m: list[list[float]], max_iter: int = 100,
                    tol: float = 1e-10) -> tuple[float, list[float]]:
    """Approximate the dominant eigenvalue/eigenvector via power iteration.

    Returns (eigenvalue, eigenvector).
    """
    n = len(m)
    if n == 0:
        return 0.0, []

    # Random-ish starting vector (deterministic)
    b = [1.0 / math.sqrt(n)] * n

    eigenvalue = 0.0
    for _ in range(max_iter):
        # Multiply
        new_b = [sum(m[i][j] * b[j] for j in range(n)) for i in range(n)]
        norm = math.sqrt(sum(x * x for x in new_b))
        if norm < 1e-15:
            return 0.0, b
        b = [x / norm for x in new_b]

        new_eigenvalue = dot(b, [sum(m[i][j] * b[j] for j in range(n)) for i in range(n)])
        if abs(new_eigenvalue - eigenvalue) < tol:
            eigenvalue = new_eigenvalue
            break
        eigenvalue = new_eigenvalue

    return eigenvalue, b


def svd_2x2(m: list[list[float]]) -> tuple[list[float], list[list[float]], list[list[float]]]:
    """Singular Value Decomposition for 2x2 matrices.

    Returns (singular_values, U, V^T).
    """
    a, b, c, d = m[0][0], m[0][1], m[1][0], m[1][1]

    # A^T A
    at_a = [[a * a + c * c, a * b + c * d],
            [a * b + c * d, b * b + d * d]]

    # Eigenvalues of A^T A
    trace = at_a[0][0] + at_a[1][1]
    det = at_a[0][0] * at_a[1][1] - at_a[0][1] * at_a[1][0]
    disc = trace * trace - 4 * det
    if disc < 0:
        disc = 0.0
    sqrt_disc = math.sqrt(disc)
    lambda1 = (trace + sqrt_disc) / 2
    lambda2 = (trace - sqrt_disc) / 2

    s1 = math.sqrt(max(lambda1, 0))
    s2 = math.sqrt(max(lambda2, 0))

    # Eigenvectors of A^T A
    if abs(at_a[0][1]) < 1e-15:
        v1 = [1.0, 0.0] if at_a[0][0] >= at_a[1][1] else [0.0, 1.0]
        v2 = [0.0, 1.0] if at_a[0][0] >= at_a[1][1] else [1.0, 0.0]
    else:
        v1 = [at_a[0][1], lambda1 - at_a[0][0]]
        v2 = [at_a[0][1], lambda2 - at_a[0][0]]
    n1 = math.sqrt(sum(x * x for x in v1)) or 1.0
    n2 = math.sqrt(sum(x * x for x in v2)) or 1.0
    v1 = [x / n1 for x in v1]
    v2 = [x / n2 for x in v2]

    # U = A * V / sigma
    u1 = [m[0][0] * v1[0] + m[0][1] * v1[1], m[1][0] * v1[0] + m[1][1] * v1[1]]
    if s1 > 1e-15:
        n1u = math.sqrt(sum(x * x for x in u1))
        u1 = [x / n1u for x in u1]
    else:
        u1 = [1.0, 0.0]

    u2_cross = [-u1[1], u1[0]]

    U = [u1, u2_cross]
    Vt = [v1, v2]

    return [s1, s2], U, Vt


# ===========================================================================
# Calculus
# ===========================================================================

def numerical_derivative(f, x: float, h: float = 1e-6) -> float:
    """Central-difference derivative of a scalar function."""
    return (f(x + h) - f(x - h)) / (2 * h)


def numerical_gradient(f, point: list[float], h: float = 1e-6) -> list[float]:
    """Numerical gradient via central differences."""
    n = len(point)
    grad = []
    for i in range(n):
        p_plus = point[:]
        p_minus = point[:]
        p_plus[i] += h
        p_minus[i] -= h
        grad.append((f(p_plus) - f(p_minus)) / (2 * h))
    return grad


def numerical_jacobian(f: list, point: list[float], h: float = 1e-6) -> list[list[float]]:
    """Numerical Jacobian of a vector-valued function."""
    n = len(point)
    jac = []
    for i in range(n):
        p_plus = point[:]
        p_minus = point[:]
        p_plus[i] += h
        p_minus[i] -= h
        col = [(f_val(p_plus) - f_val(p_minus)) / (2 * h) for f_val in f]
        jac.append(col)
    return jac


# ===========================================================================
# Statistics
# ===========================================================================

def mean(data: Iterable[float]) -> float:
    values = list(data)
    if not values:
        return 0.0
    return sum(values) / len(values)


def variance(data: Iterable[float]) -> float:
    values = list(data)
    if len(values) < 2:
        return 0.0
    m = mean(values)
    return sum((x - m) ** 2 for x in values) / (len(values) - 1)


def stddev(data: Iterable[float]) -> float:
    return math.sqrt(variance(data))


def covariance(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or len(a) < 2:
        return 0.0
    ma, mb = mean(a), mean(b)
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (len(a) - 1)


def correlation(a: list[float], b: list[float]) -> float:
    sa, sb = stddev(a), stddev(b)
    if sa == 0 or sb == 0:
        return 0.0
    return covariance(a, b) / (sa * sb)


def linear_regression(x: list[float], y: list[float]) -> tuple[float, float]:
    """Simple linear regression: returns (slope, intercept)."""
    if len(x) < 2:
        return 0.0, mean(y) if y else 0.0
    mx, my = mean(x), mean(y)
    sxy = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    sxx = sum((xi - mx) ** 2 for xi in x)
    slope = sxy / sxx if sxx != 0 else 0.0
    intercept = my - slope * mx
    return slope, intercept


def r_squared(y_true: list[float], y_pred: list[float]) -> float:
    """Coefficient of determination."""
    if len(y_true) < 2:
        return 0.0
    m = mean(y_true)
    ss_tot = sum((y - m) ** 2 for y in y_true)
    ss_res = sum((yt - yp) ** 2 for yt, yp in zip(y_true, y_pred))
    if ss_tot == 0:
        return 0.0
    return 1.0 - ss_res / ss_tot


# ===========================================================================
# Probability distributions
# ===========================================================================

def binomial_pmf(n: int, k: int, p: float) -> float:
    if k < 0 or k > n:
        return 0.0
    return math.comb(n, k) * (p ** k) * ((1 - p) ** (n - k))


def binomial_mean(n: int, p: float) -> float:
    return n * p


def binomial_variance(n: int, p: float) -> float:
    return n * p * (1 - p)


def normal_pdf(x: float, mu: float = 0.0, sigma: float = 1.0) -> float:
    if sigma <= 0:
        return 0.0
    z = (x - mu) / sigma
    return math.exp(-0.5 * z * z) / (sigma * math.sqrt(2 * math.pi))


def normal_cdf(x: float, mu: float = 0.0, sigma: float = 1.0) -> float:
    """Approximate normal CDF via error function."""
    if sigma <= 0:
        return 0.0
    z = (x - mu) / sigma
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2)))


# ===========================================================================
# Set theory and combinatorics
# ===========================================================================

def power_set(s: Iterable) -> list[set]:
    elements = list(s)
    result = []
    for i in range(2 ** len(elements)):
        subset = set()
        for j in range(len(elements)):
            if i & (1 << j):
                subset.add(elements[j])
        result.append(subset)
    return result


def cartesian_product(*sets: Iterable) -> list[tuple]:
    """Cartesian product of multiple sets."""
    from itertools import product
    return list(product(*sets))


def factorial(n: int) -> int:
    if n < 0:
        raise ValueError("Factorial of negative number")
    return math.factorial(n)


def permutations_count(n: int, k: int = 0) -> int:
    if k == 0:
        k = n
    if k > n or k < 0:
        return 0
    return math.perm(n, k)


def combinations_count(n: int, k: int) -> int:
    if k < 0 or k > n:
        return 0
    return math.comb(n, k)


def __all__() -> list[str]:
    return [
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
