"""Differential equations: numerical ODE solvers.

Stdlib-only. Pure computation, no external dependencies.

Core concepts:
- Euler's method: simplest ODE solver (first-order, O(h))
- Heun's method (RK2): improved Euler / trapezoidal (second-order, O(h^2))
- Runge-Kutta 4 (RK4): standard fourth-order method (O(h^4))
- Adaptive step size (RK45 / Dormand-Prince simplified)
- Systems of ODEs and second-order ODEs (converted to first-order)
"""

from __future__ import annotations

from typing import Callable

Vector = list[float]


# ===========================================================================
# Scalar ODE solvers
# ===========================================================================

def euler(
    f: Callable[[float, float], float],
    t0: float,
    y0: float,
    t_end: float,
    h: float,
) -> list[tuple[float, float]]:
    """Euler's method for a scalar ODE: y' = f(t, y).

    Returns list of (t, y) points from t0 to t_end.
    """
    result: list[tuple[float, float]] = []
    t = t0
    y = y0
    result.append((t, y))

    while t < t_end - 1e-12:
        h_actual = min(h, t_end - t)
        y = y + h_actual * f(t, y)
        t = t + h_actual
        result.append((t, y))

    return result


def heun(
    f: Callable[[float, float], float],
    t0: float,
    y0: float,
    t_end: float,
    h: float,
) -> list[tuple[float, float]]:
    """Heun's method (RK2 / improved Euler) for y' = f(t, y)."""
    result: list[tuple[float, float]] = []
    t = t0
    y = y0
    result.append((t, y))

    while t < t_end - 1e-12:
        h_actual = min(h, t_end - t)
        k1 = f(t, y)
        k2 = f(t + h_actual, y + h_actual * k1)
        y = y + (h_actual / 2.0) * (k1 + k2)
        t = t + h_actual
        result.append((t, y))

    return result


def rk4(
    f: Callable[[float, float], float],
    t0: float,
    y0: float,
    t_end: float,
    h: float,
) -> list[tuple[float, float]]:
    """Classic 4th-order Runge-Kutta for y' = f(t, y)."""
    result: list[tuple[float, float]] = []
    t = t0
    y = y0
    result.append((t, y))

    while t < t_end - 1e-12:
        h_actual = min(h, t_end - t)
        k1 = f(t, y)
        k2 = f(t + h_actual / 2.0, y + h_actual / 2.0 * k1)
        k3 = f(t + h_actual / 2.0, y + h_actual / 2.0 * k2)
        k4 = f(t + h_actual, y + h_actual * k3)
        y = y + (h_actual / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)
        t = t + h_actual
        result.append((t, y))

    return result


def _rk4_step(
    f: Callable[[float, float], float], t: float, y: float, h: float
) -> float:
    """One RK4 step from (t, y) with step h. Returns the increment dy."""
    k1 = f(t, y)
    k2 = f(t + h / 2.0, y + h / 2.0 * k1)
    k3 = f(t + h / 2.0, y + h / 2.0 * k2)
    k4 = f(t + h, y + h * k3)
    return (h / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)


def rk45(
    f: Callable[[float, float], float],
    t0: float,
    y0: float,
    t_end: float,
    h0: float = 0.1,
    tol: float = 1e-6,
    max_steps: int = 10000,
) -> list[tuple[float, float]]:
    """Adaptive RK45 with Richardson extrapolation error control.

    Compares one full RK4 step against two half RK4 steps to estimate
    the error and adaptively adjust the step size.
    """
    result: list[tuple[float, float]] = []
    t = t0
    y = y0
    h = h0
    result.append((t, y))

    steps = 0
    while t < t_end - 1e-12 and steps < max_steps:
        h_actual = min(h, t_end - t)

        # Full step
        y_full = y + _rk4_step(f, t, y, h_actual)

        # Two half steps
        y_half1 = y + _rk4_step(f, t, y, h_actual / 2.0)
        y_half2 = y_half1 + _rk4_step(f, t + h_actual / 2.0, y_half1, h_actual / 2.0)

        # Error estimate (Richardson extrapolation)
        error = abs(y_half2 - y_full)

        # Accept step if error is within tolerance
        if error <= tol:
            t = t + h_actual
            y = y_half2  # Use the more accurate half-step result
            result.append((t, y))

        # Adjust step size (4th-order error scaling)
        if error > 0:
            h = h_actual * (tol / error) ** 0.25
        else:
            h = h_actual * 2.0
        h = max(h, 1e-10)
        h = min(h, t_end - t)

        steps += 1

    return result


# ===========================================================================
# Systems of ODEs
# ===========================================================================

def euler_system(
    f: Callable[[float, Vector], Vector],
    t0: float,
    y0: Vector,
    t_end: float,
    h: float,
) -> list[tuple[float, Vector]]:
    """Euler's method for a system of ODEs: y' = f(t, y)."""
    result: list[tuple[float, Vector]] = []
    t = t0
    y = list(y0)
    result.append((t, list(y)))

    while t < t_end - 1e-12:
        h_actual = min(h, t_end - t)
        derivative = f(t, y)
        y = [y[i] + h_actual * derivative[i] for i in range(len(y))]
        t = t + h_actual
        result.append((t, list(y)))

    return result


def rk4_system(
    f: Callable[[float, Vector], Vector],
    t0: float,
    y0: Vector,
    t_end: float,
    h: float,
) -> list[tuple[float, Vector]]:
    """RK4 for a system of ODEs."""
    result: list[tuple[float, Vector]] = []
    t = t0
    y = list(y0)
    result.append((t, list(y)))

    while t < t_end - 1e-12:
        h_actual = min(h, t_end - t)
        k1 = f(t, y)
        k2 = f(t + h_actual / 2.0, [y[i] + h_actual / 2.0 * k1[i] for i in range(len(y))])
        k3 = f(t + h_actual / 2.0, [y[i] + h_actual / 2.0 * k2[i] for i in range(len(y))])
        k4 = f(t + h_actual, [y[i] + h_actual * k3[i] for i in range(len(y))])
        y = [y[i] + (h_actual / 6.0) * (k1[i] + 2 * k2[i] + 2 * k3[i] + k4[i]) for i in range(len(y))]
        t = t + h_actual
        result.append((t, list(y)))

    return result


# ===========================================================================
# Second-order ODEs (converted to first-order systems)
# ===========================================================================

def second_order_to_first(
    f: Callable[[float, float, float], float],
) -> Callable[[float, Vector], Vector]:
    """Convert y'' = f(t, y, y') to a first-order system.

    State vector: [y, y']. Derivative: [y', f(t, y, y')].
    """
    def system(t: float, state: Vector) -> Vector:
        y, y_prime = state[0], state[1]
        return [y_prime, f(t, y, y_prime)]
    return system


# ===========================================================================
# Special solutions for testing
# ===========================================================================

def exponential_decay_solution(t: float, k: float = 1.0) -> float:
    """Analytical solution to y' = -k*y: y(t) = exp(-k*t)."""
    import math
    return math.exp(-k * t)


def harmonic_oscillator_solution(t: float, omega: float = 1.0) -> float:
    """Analytical solution to y'' + omega^2 * y = 0: y(t) = cos(omega*t)."""
    import math
    return math.cos(omega * t)


def logistic_growth_solution(t: float, r: float = 1.0, K: float = 1.0) -> float:
    """Analytical solution to logistic ODE: y' = r*y*(1 - y/K)."""
    import math
    if r * t < 1e-12:
        return 0.5 * K
    return K / (1.0 + math.exp(-r * t))
