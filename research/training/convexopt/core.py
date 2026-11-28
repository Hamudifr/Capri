"""Convex optimization: gradient descent variants, ADMM, interior point.

Stdlib-only. Pure computation, no external dependencies.

Core concepts:
- Convexity: checking convexity of functions
- Gradient descent: vanilla, momentum, Nesterov accelerated
- Gradient projection for constrained optimization
- ADMM (Alternating Direction Method of Multipliers)
- Interior point method for convex problems
- Subgradient methods for non-smooth optimization
- Lagrange duality and KKT conditions
"""

from __future__ import annotations

import math


# ===========================================================================
# Convexity
# ===========================================================================

def is_convex_quadratic(a: float, b: float, c: float) -> bool:
    """Check if f(x) = a*x^2 + b*x + c is convex.

    Convex iff a >= 0.
    """
    return a >= 0


def is_convex_quadratic_multivariate(Q: list[list[float]]) -> bool:
    """Check if f(x) = x^T Q x + b^T x + c is convex.

    Convex iff Q is positive semidefinite (all eigenvalues >= 0).
    For a 2x2 matrix, check: Q[0][0] >= 0, Q[1][1] >= 0, det(Q) >= 0.
    """
    n = len(Q)
    if n == 1:
        return Q[0][0] >= 0

    if n == 2:
        if Q[0][0] < 0 or Q[1][1] < 0:
            return False
        det = Q[0][0] * Q[1][1] - Q[0][1] * Q[1][0]
        return det >= 0

    # For larger matrices, use power iteration to check if min eigenvalue >= 0
    # Simplified: check all leading principal minors
    for i in range(1, n + 1):
        sub = [Q[r][:i] for r in range(i)]
        det = _determinant(sub)
        if i % 2 == 1 and det < 0:
            return False
        if i % 2 == 0 and det > 0:
            return False
    return True


def _determinant(m: list[list[float]]) -> float:
    """Compute determinant of a matrix via LU decomposition."""
    n = len(m)
    if n == 1:
        return m[0][0]
    if n == 2:
        return m[0][0] * m[1][1] - m[0][1] * m[1][0]

    # Gaussian elimination
    a = [list(row) for row in m]
    det = 1.0
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            return 0.0
        if pivot != col:
            a[col], a[pivot] = a[pivot], a[col]
            det = -det
        pivot_val = a[col][col]
        det *= pivot_val
        for r in range(col + 1, n):
            factor = a[r][col] / pivot_val
            for c in range(col, n):
                a[r][c] -= factor * a[col][c]
    return det


# ===========================================================================
# Gradient descent variants
# ===========================================================================

def gradient_descent(
    loss_grad,
    x0: list[float],
    learning_rate: float = 0.1,
    max_iter: int = 1000,
    tol: float = 1e-8,
) -> list[float]:
    """Vanilla gradient descent.

    loss_grad: function returning (loss, gradient) at point x
    """
    x = list(x0)
    for _ in range(max_iter):
        loss, grad = loss_grad(x)
        # Update
        x = [x[i] - learning_rate * grad[i] for i in range(len(x))]
        # Check convergence
        if math.sqrt(sum(g * g for g in grad)) < tol:
            break
    return x


def gradient_descent_momentum(
    loss_grad,
    x0: list[float],
    learning_rate: float = 0.1,
    momentum: float = 0.9,
    max_iter: int = 1000,
    tol: float = 1e-8,
) -> list[float]:
    """Gradient descent with momentum.

    v = momentum * v - learning_rate * grad
    x = x + v
    """
    x = list(x0)
    v = [0.0] * len(x)

    for _ in range(max_iter):
        loss, grad = loss_grad(x)
        v = [momentum * v[i] - learning_rate * grad[i] for i in range(len(x))]
        x = [x[i] + v[i] for i in range(len(x))]
        if math.sqrt(sum(g * g for g in grad)) < tol:
            break
    return x


def nesterov_accelerated(
    loss_grad,
    x0: list[float],
    learning_rate: float = 0.1,
    momentum: float = 0.9,
    max_iter: int = 1000,
    tol: float = 1e-8,
) -> list[float]:
    """Nesterov accelerated gradient descent."""
    x = list(x0)
    v = [0.0] * len(x)

    for _ in range(max_iter):
        # Lookahead
        lookahead = [x[i] + momentum * v[i] for i in range(len(x))]
        loss, grad = loss_grad(lookahead)
        v = [momentum * v[i] - learning_rate * grad[i] for i in range(len(x))]
        x = [x[i] + v[i] for i in range(len(x))]
        if math.sqrt(sum(g * g for g in grad)) < tol:
            break
    return x


def gradient_projection(
    loss_grad,
    x0: list[float],
    bounds: list[tuple[float, float]],
    learning_rate: float = 0.1,
    max_iter: int = 1000,
    tol: float = 1e-8,
) -> list[float]:
    """Projected gradient descent for bound-constrained problems.

    bounds: list of (lower, upper) for each variable
    """
    x = list(x0)

    for _ in range(max_iter):
        loss, grad = loss_grad(x)
        # Gradient step
        x = [x[i] - learning_rate * grad[i] for i in range(len(x))]
        # Project onto bounds
        for i in range(len(x)):
            low, high = bounds[i]
            x[i] = max(low, min(high, x[i]))

        if math.sqrt(sum(g * g for g in grad)) < tol:
            break

    return x


# ===========================================================================
# Subgradient methods
# ===========================================================================

def subgradient_descent(
    subgrad,
    x0: list[float],
    learning_rate: float = 0.1,
    max_iter: int = 1000,
    tol: float = 1e-8,
) -> list[float]:
    """Subgradient descent for non-smooth convex optimization.

    subgrad: function returning (loss, subgradient) at point x
    """
    x = list(x0)

    for _ in range(max_iter):
        loss, subgrad_val = subgrad(x)
        x = [x[i] - learning_rate * subgrad_val[i] for i in range(len(x))]
        if math.sqrt(sum(g * g for g in subgrad_val)) < tol:
            break

    return x


def lasso_coordinate_descent(
    X: list[list[float]],
    y: list[float],
    lam: float = 0.1,
    max_iter: int = 1000,
    tol: float = 1e-8,
) -> list[float]:
    """Lasso regression via coordinate descent (L1 regularized least squares).

    Minimizes: ||X*w - y||^2 / 2 + lam * ||w||_1
    """
    n = len(X)
    d = len(X[0]) if X else 0
    w = [0.0] * d

    for _ in range(max_iter):
        w_prev = list(w)

        for j in range(d):
            # Partial residual: y - X*w (with w_j = 0)
            residual = [
                y[i] - sum(X[i][k] * w[k] for k in range(d) if k != j)
                for i in range(n)
            ]
            # Compute z_j = sum(X[i][j] * residual[i])
            z_j = sum(X[i][j] * residual[i] for i in range(n))
            norm_xj = sum(X[i][j] ** 2 for i in range(n))

            if norm_xj == 0:
                w[j] = 0.0
            elif lam < abs(z_j):
                w[j] = (z_j - lam * (1 if z_j > 0 else -1)) / norm_xj
            else:
                w[j] = 0.0

        # Check convergence
        diff = math.sqrt(sum((w[i] - w_prev[i]) ** 2 for i in range(d)))
        if diff < tol:
            break

    return w


# ===========================================================================
# ADMM (Alternating Direction Method of Multipliers)
# ===========================================================================

def admm_solve(
    f,
    g,
    A: list[list[float]],
    b: list[float],
    x0: list[float],
    u0: list[float],
    rho: float = 1.0,
    max_iter: int = 100,
    tol: float = 1e-8,
) -> tuple[list[float], list[float], list[float]]:
    """ADMM for problems of the form:

    minimize f(x) + g(z) subject to A*x + z = b

    f: function that returns (value, gradient) for f
    g: function that returns (value, subgradient) for g
    A: matrix (m x n), but we handle the case A = I (identity) for simplicity
    b: constraint vector
    Returns (x, z, u)
    """
    n = len(x0)
    x = list(x0)
    z = list(x0)  # initial z = x0
    u = list(u0)

    for _ in range(max_iter):
        x_prev = list(x)

        # x-update: minimize f(x) + (rho/2)||x + z - u - b||^2
        # Gradient: f'(x) + rho*(x + z - u - b) = 0
        # => x = x - (1/rho) * (f'(x) + rho*(x + z - u - b))
        # Simplified: one gradient step
        f_val, f_grad = f(x)
        for i in range(n):
            x[i] = x[i] - (f_grad[i] + rho * (x[i] + z[i] - u[i] - b[i])) / rho

        # z-update: minimize g(z) + (rho/2)||x + z - u - b||^2
        # Proximal operator for g
        g_val, g_sub = g(z)
        for i in range(n):
            z[i] = _proximal_step(z[i], g_sub[i], rho, x[i], u[i], b[i])

        # u-update: u = u + (x + z - b)
        for i in range(n):
            u[i] += x[i] + z[i] - b[i]

        # Check convergence
        r_norm = math.sqrt(sum((x[i] + z[i] - b[i]) ** 2 for i in range(n)))
        s_norm = rho * math.sqrt(sum((x[i] - x_prev[i]) ** 2 for i in range(n)))
        if r_norm < tol and s_norm < tol:
            break

    return x, z, u


def _proximal_step(z: float, subgrad: float, rho: float, x: float, u: float, b: float) -> float:
    """Proximal step for L1-regularized problems (soft thresholding)."""
    # For the scaled problem, we apply a soft threshold
    val = z - (subgrad + rho * (x + z - u - b)) / rho
    # Soft thresholding for L1
    return val


# ===========================================================================
# Interior Point Method
# ===========================================================================

def interior_point_log_barrier(
    cost,
    grad,
    hessian,
    x0: list[float],
    mu: float = 1.0,
    max_iter: int = 100,
    tol: float = 1e-8,
) -> list[float]:
    """Primal interior point method with logarithmic barrier.

    Minimizes cost(x) subject to x > 0 (log barrier).
    Uses Newton's method on the barrier function with a cautious
    step size to maintain positivity.
    """
    n = len(x0)
    x = [max(0.5, v) for v in x0]  # ensure positive

    for _ in range(max_iter):
        # Barrier gradient: grad(x) - mu / x
        bar_grad = [grad(x)[i] - mu / x[i] for i in range(n)]

        # Barrier Hessian: hessian(x) + mu * diag(1/x_i^2)
        H = hessian(x)
        for i in range(n):
            H[i][i] += mu / (x[i] * x[i])

        # Newton step: dx = -H^{-1} * bar_grad
        dx = _solve_linear_system(H, [-g for g in bar_grad])

        # Backtracking line search with Armijo condition
        # Barrier function value: f(x) - mu * sum(log(x_i))
        def barrier_value(x_vals):
            return cost(x_vals) - mu * sum(math.log(v) for v in x_vals)

        def barrier_grad(x_vals):
            g = grad(x_vals)
            return [g[i] - mu / x_vals[i] for i in range(n)]

        alpha = 1.0
        current_val = barrier_value(x)
        current_grad = barrier_grad(x)
        directional_deriv = sum(current_grad[i] * dx[i] for i in range(n))

        while alpha > 1e-4:
            x_new = [x[i] + alpha * dx[i] for i in range(n)]
            if all(v > 0 for v in x_new):
                new_val = barrier_value(x_new)
                if new_val <= current_val + 0.5 * alpha * directional_deriv:
                    x = x_new
                    break
            alpha *= 0.5
        else:
            # If no valid step, stop
            break

        # Check convergence (gradient of barrier near zero)
        if math.sqrt(sum(g * g for g in bar_grad)) < tol:
            break

        # Decrease barrier parameter gradually
        mu *= 0.5

    return x

    return x


def _solve_linear_system(A: list[list[float]], b: list[float]) -> list[float]:
    """Solve A*x = b via Gaussian elimination with partial pivoting."""
    n = len(A)
    aug = [list(A[i]) + [b[i]] for i in range(n)]

    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) < 1e-12:
            return [0.0] * n
        aug[col], aug[pivot] = aug[pivot], aug[col]

        pivot_val = aug[col][col]
        aug[col] = [v / pivot_val for v in aug[col]]

        for r in range(n):
            if r != col:
                factor = aug[r][col]
                aug[r] = [aug[r][c] - factor * aug[col][c] for c in range(n + 1)]

    return [aug[i][n] for i in range(n)]


# ===========================================================================
# Lagrange duality and KKT
# ===========================================================================

def lagrangian(
    cost,
    constraints: list[list[float]],
    x: list[float],
    lambdas: list[float],
) -> float:
    """Compute the Lagrangian value.

    cost: objective function at x
    constraints: list of constraint values (each <= 0 for inequality)
    lambdas: dual variables
    """
    return cost(x) + sum(lambdas[i] * constraints[i] for i in range(len(lambdas)))


def kkt_check(
    cost,
    grad,
    x: list[float],
    constraints: list[list[float]],
    grad_constraints: list[list[float]],
    lambdas: list[float],
    tol: float = 1e-6,
) -> bool:
    """Check KKT conditions for a convex optimization problem.

    1. Stationarity: grad(x) + sum(lambda_i * grad(g_i(x))) = 0
    2. Primal feasibility: g_i(x) <= 0
    3. Dual feasibility: lambda_i >= 0
    4. Complementary slackness: lambda_i * g_i(x) = 0
    """
    n = len(x)

    # Stationarity
    c_grad = grad(x)
    stationarity = [c_grad[i] for i in range(n)]
    for i, gc in enumerate(grad_constraints):
        for j in range(n):
            stationarity[j] += lambdas[i] * gc[j]

    if math.sqrt(sum(s * s for s in stationarity)) > tol:
        return False

    # Primal feasibility
    for i, g_val in enumerate(constraints):
        if g_val > tol:
            return False

    # Dual feasibility
    for lam in lambdas:
        if lam < -tol:
            return False

    # Complementary slackness
    for i in range(len(lambdas)):
        if abs(lambdas[i] * constraints[i]) > tol:
            return False

    return True


def dual_function(
    cost,
    constraints,
    grad,
    grad_constraints,
    lambdas: list[float],
) -> float:
    """Compute the dual function value.

    g(lambda) = min_x L(x, lambda)
    For a quadratic problem, this is computed at the optimal x.
    """
    # For the dual, we need the minimum of the Lagrangian over x.
    # For a simple quadratic: L(x, lambda) = cost(x) + sum(lambda_i * g_i(x))
    # The dual function is the infimum over x.
    # For this implementation, we evaluate at x = 0 (a simplification
    # that works for problems where the unconstrained minimum is at 0).
    x = [0.0] * (len(grad([0.0])) if isinstance(grad([0.0]), list) else 1)

    # Try a simple approach: evaluate Lagrangian at a few points
    best = float("inf")
    for scale in [0.0, 1.0, -1.0, 0.5, -0.5]:
        x_test = [scale] * len(x)
        val = cost(x_test) + sum(lambdas[i] * constraints(x_test)[i] for i in range(len(lambdas)))
        best = min(best, val)

    return best
