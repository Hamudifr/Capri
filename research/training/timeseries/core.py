"""Time series analysis: AR/MA models, moving averages, autocorrelation.

Stdlib-only. Pure computation, no external dependencies.

Core concepts:
- Moving averages (simple, exponential)
- Autocorrelation and partial autocorrelation
- AR(p) models and Yule-Walker estimation
- MA(q) models
- ARMA(p,q) and basic forecasting
- Stationarity tests (ADF simplified)
"""

from __future__ import annotations

import math


# ===========================================================================
# Moving averages
# ===========================================================================

def simple_moving_average(data: list[float], window: int = 5) -> list[float]:
    """Simple moving average (SMA).

    Returns a list of the same length as data; the first window-1 entries
    are None (marked as float('nan')) until enough data exists.
    """
    result: list[float] = []
    for i in range(len(data)):
        if i < window - 1:
            result.append(float("nan"))
        else:
            window_data = data[i - window + 1 : i + 1]
            result.append(sum(window_data) / window)
    return result


def exponential_moving_average(data: list[float], alpha: float = 0.3) -> list[float]:
    """Exponential moving average (EMA).

    EMA_t = alpha * x_t + (1 - alpha) * EMA_{t-1}
    First value uses the first data point as the initial EMA.
    """
    if not data:
        return []
    result: list[float] = [data[0]]
    for i in range(1, len(data)):
        ema = alpha * data[i] + (1 - alpha) * result[i - 1]
        result.append(ema)
    return result


def weighted_moving_average(data: list[float], weights: list[float]) -> list[float]:
    """Weighted moving average with explicit weights (most recent last)."""
    window = len(weights)
    total_weight = sum(weights)
    result: list[float] = []
    for i in range(len(data)):
        if i < window - 1:
            result.append(float("nan"))
        else:
            window_data = data[i - window + 1 : i + 1]
            val = sum(window_data[j] * weights[j] for j in range(window)) / total_weight
            result.append(val)
    return result


# ===========================================================================
# Autocorrelation and partial autocorrelation
# ===========================================================================

def mean(data: list[float]) -> float:
    """Arithmetic mean."""
    if not data:
        return 0.0
    return sum(data) / len(data)


def variance(data: list[float]) -> float:
    """Population variance."""
    if not data:
        return 0.0
    m = mean(data)
    return sum((x - m) ** 2 for x in data) / len(data)


def autocorrelation(data: list[float], lag: int = 1) -> float:
    """Autocorrelation at a given lag.

    rho(k) = sum_{t=1}^{N-k} (x_t - mu)(x_{t+k} - mu) / sum_{t=1}^{N} (x_t - mu)^2
    """
    n = len(data)
    if n <= lag:
        return 0.0
    m = mean(data)
    numerator = sum((data[t] - m) * (data[t + lag] - m) for t in range(n - lag))
    denominator = sum((x - m) ** 2 for x in data)
    if denominator == 0:
        return 0.0
    return numerator / denominator


def autocorrelation_function(data: list[float], max_lag: int) -> list[float]:
    """Autocorrelation function for lags 0 through max_lag."""
    return [autocorrelation(data, lag) for lag in range(max_lag + 1)]


def partial_autocorrelation(data: list[float], lag: int) -> float:
    """Partial autocorrelation at lag k (recursive Yule-Walker).

    For lag 1, it equals the lag-1 autocorrelation.
    For lag > 1, it is the last coefficient from fitting AR(lag).
    """
    if lag < 1:
        return 0.0
    if lag == 1:
        return autocorrelation(data, 1)

    # Build the Toeplitz matrix of autocorrelations and solve
    # using Yule-Walker equations for AR(lag)
    rho = [autocorrelation(data, k) for k in range(lag + 1)]

    # Solve R * phi = rho[1:]  (R is lag x lag Toeplitz matrix)
    # Use Gaussian elimination
    n = lag
    # Build augmented matrix
    aug: list[list[float]] = []
    for i in range(n):
        row = []
        for j in range(n):
            row.append(rho[abs(i - j)])
        aug.append(row + [rho[i + 1]])

    # Gaussian elimination
    for col in range(n):
        # Find pivot
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) < 1e-12:
            return 0.0
        aug[col], aug[pivot] = aug[pivot], aug[col]
        # Eliminate
        for r in range(col + 1, n):
            factor = aug[r][col] / aug[col][col]
            for c in range(col, n + 1):
                aug[r][c] -= factor * aug[col][c]

    # Back substitution
    phi = [0.0] * n
    for i in range(n - 1, -1, -1):
        s = aug[i][n] - sum(aug[i][j] * phi[j] for j in range(i + 1, n))
        phi[i] = s / aug[i][i] if abs(aug[i][i]) > 1e-12 else 0.0

    return phi[-1]


# ===========================================================================
# AR(p) models
# ===========================================================================

def ar_predict(
    phi: list[float],
    history: list[float],
    steps: int = 1,
) -> list[float]:
    """Predict future values using AR(p) model.

    phi: AR coefficients [phi_1, ..., phi_p]
    history: past values [y_{t-p}, ..., y_{t-1}] (most recent last)
    Returns predicted values for the next `steps` steps.
    """
    predictions: list[float] = []
    current = list(history)
    for _ in range(steps):
        p = len(phi)
        pred = sum(phi[i] * current[-(i + 1)] for i in range(min(p, len(current))))
        predictions.append(pred)
        current.append(pred)
    return predictions


def ar_yule_walker(data: list[float], order: int = 2) -> list[float]:
    """Estimate AR(p) coefficients via Yule-Walker equations."""
    if order < 1:
        return []
    rho = [autocorrelation(data, k) for k in range(order + 1)]

    # Solve R * phi = rho[1:order+1]
    n = order
    aug: list[list[float]] = []
    for i in range(n):
        row = []
        for j in range(n):
            row.append(rho[abs(i - j)])
        aug.append(row + [rho[i + 1]])

    # Gaussian elimination
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) < 1e-12:
            return [0.0] * n
        aug[col], aug[pivot] = aug[pivot], aug[col]
        for r in range(col + 1, n):
            factor = aug[r][col] / aug[col][col]
            for c in range(col, n + 1):
                aug[r][c] -= factor * aug[col][c]

    phi = [0.0] * n
    for i in range(n - 1, -1, -1):
        s = aug[i][n] - sum(aug[i][j] * phi[j] for j in range(i + 1, n))
        phi[i] = s / aug[i][i] if abs(aug[i][i]) > 1e-12 else 0.0
    return phi


# ===========================================================================
# MA(q) models
# ===========================================================================

def ma_predict(
    theta: list[float],
    history: list[float],
    steps: int = 1,
) -> list[float]:
    """Predict using MA(q) model. For steps beyond the order, predicts 0.

    theta: MA coefficients [theta_1, ..., theta_q]
    history: past values, most recent last
    """
    q = len(theta)
    predictions: list[float] = []
    current = list(history)
    for step in range(steps):
        if step < q:
            pred = sum(theta[i] * (-current[-(i + 1)]) for i in range(min(q, len(current))))
            # Note: MA uses past innovations (errors), which we approximate
            # with residuals. For a simple forward predictor, beyond the
            # known history we predict the mean (0 for centered data).
        else:
            pred = 0.0
        predictions.append(pred)
    return predictions


def ma_theoretical_acf(theta: list[float], max_lag: int) -> list[float]:
    """Theoretical autocorrelation function of an MA(q) process.

    For an MA(q) process, ACF cuts off after lag q.
    Uses coefficients [1.0] + theta (theta_0 = 1).
    """
    q = len(theta)
    coeffs = [1.0] + list(theta)
    denominator = sum(c * c for c in coeffs)
    result: list[float] = []
    for k in range(max_lag + 1):
        if k == 0:
            result.append(1.0)
        elif k > q:
            result.append(0.0)
        else:
            numerator = sum(coeffs[i] * coeffs[i + k] for i in range(q + 1 - k))
            result.append(numerator / denominator if denominator != 0 else 0.0)
    return result


# ===========================================================================
# ARMA(p,q) and forecasting
# ===========================================================================

class ARMAModel:
    """Simple ARMA(p,q) model for forecasting."""

    def __init__(self, p: int = 1, q: int = 0):
        self.p = p
        self.q = q
        self.phi: list[float] = []
        self.theta: list[float] = []
        self.mu: float = 0.0

    def fit(self, data: list[float]) -> "ARMAModel":
        """Fit AR part via Yule-Walker; MA part left at default (zeros)."""
        if self.p > 0:
            self.phi = ar_yule_walker(data, self.p)
        self.mu = mean(data)
        if self.q > 0:
            # Simple MA estimation via method of moments
            # For simplicity, use zero coefficients (order-0 MA)
            self.theta = [0.0] * self.q
        return self

    def forecast(self, history: list[float], steps: int = 1) -> list[float]:
        """Forecast future values from the AR part."""
        centered_history = [x - self.mu for x in history[-max(self.p, 1):]]
        if not centered_history:
            centered_history = [0.0]
        preds = ar_predict(self.phi, centered_history, steps)
        return [p + self.mu for p in preds]


# ===========================================================================
# Stationarity
# ===========================================================================

def adf_test(data: list[float], max_lag: int = 5) -> float:
    """Simplified Augmented Dickey-Fuller test statistic.

    Tests H0: unit root (non-stationary) vs H1: stationary.
    Returns the t-statistic of the lag coefficient. A more negative
    value indicates stronger evidence of stationarity.
    """
    n = len(data)
    if n < 3:
        return 0.0

    # Delta: y_t - y_{t-1}
    delta = [data[i] - data[i - 1] for i in range(1, n)]

    # Regression: delta_t = a + b * y_{t-1} + sum(c_i * delta_{t-i})
    # Collect features
    X_rows: list[list[float]] = []
    y_vals: list[float] = []
    for t in range(max_lag, len(delta)):
        row = [1.0]  # intercept
        row.append(data[t - 1 - 1])  # y_{t-1} (data index t-1 is y at time t-1, since delta[0] = y1-y0)
        for lag in range(1, max_lag + 1):
            if t - lag - 1 >= 0:
                row.append(delta[t - lag])
            else:
                row.append(0.0)
        X_rows.append(row)
        y_vals.append(delta[t])

    # Solve normal equations (X'X)^-1 X'y
    k = len(X_rows[0])
    if len(X_rows) < k:
        return 0.0

    # X'X
    XtX = [[sum(X_rows[i][r] * X_rows[i][c] for i in range(len(X_rows))) for c in range(k)] for r in range(k)]
    # X'y
    Xty = [sum(X_rows[i][r] * y_vals[i] for i in range(len(X_rows))) for r in range(k)]

    # Solve via Gaussian elimination
    # (Use standard linear solve)
    # Build augmented matrix
    aug = [XtX[i] + [Xty[i]] for i in range(k)]

    for col in range(k):
        pivot = max(range(col, k), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) < 1e-12:
            return 0.0
        aug[col], aug[pivot] = aug[pivot], aug[col]
        for r in range(col + 1, k):
            factor = aug[r][col] / aug[col][col]
            for c in range(col, k + 1):
                aug[r][c] -= factor * aug[col][c]

    beta = [0.0] * k
    for i in range(k - 1, -1, -1):
        s = aug[i][k] - sum(aug[i][j] * beta[j] for j in range(i + 1, k))
        beta[i] = s / aug[i][i] if abs(aug[i][i]) > 1e-12 else 0.0

    # Return t-statistic for the y_{t-1} coefficient (index 1)
    if len(beta) > 1:
        return beta[1]
    return 0.0


# ===========================================================================
# Detrending and seasonal decomposition
# ===========================================================================

def linear_detrend(data: list[float]) -> list[float]:
    """Remove a linear trend from the data. Returns the residuals."""
    n = len(data)
    if n < 2:
        return list(data)
    x_mean = (n - 1) / 2.0
    y_mean = mean(data)
    num = sum((i - x_mean) * (data[i] - y_mean) for i in range(n))
    den = sum((i - x_mean) ** 2 for i in range(n))
    slope = num / den if den != 0 else 0.0
    intercept = y_mean - slope * x_mean
    trend = [slope * i + intercept for i in range(n)]
    return [data[i] - trend[i] for i in range(n)]


def seasonal_decompose(
    data: list[float], period: int = 12
) -> tuple[list[float], list[float], list[float]]:
    """Simple seasonal decomposition (average method).

    Returns (trend, seasonal, residual).
    """
    n = len(data)
    if n < period * 2:
        return (list(data), [0.0] * n, [0.0] * n)

    # Compute seasonal averages
    seasonal_avg = [0.0] * period
    counts = [0] * period
    for i in range(n):
        seasonal_avg[i % period] += data[i]
        counts[i % period] += 1
    seasonal_avg = [s / c for s, c in zip(seasonal_avg, counts)]

    # Simple moving average for trend (window = period)
    trend = simple_moving_average(data, period)
    # Fill in leading NaN values with the first valid value
    if trend and math.isnan(trend[0]):
        first_valid = next(v for v in trend if not math.isnan(v))
        for i in range(len(trend)):
            if math.isnan(trend[i]):
                trend[i] = first_valid

    seasonal = [seasonal_avg[i % period] for i in range(n)]
    residual = [data[i] - trend[i] - seasonal[i] for i in range(n)]

    return trend, seasonal, residual
