"""Leakage-aware directional labels for XAUUSD research."""
from __future__ import annotations

import numpy as np


def make_direction_labels(
    close: np.ndarray,
    horizons: tuple[int, ...] = (1, 4, 16, 96),
    lookback: int = 96,
    volatility_multiplier: float = 0.5,
    minimum_return: float = 0.0005,
) -> tuple[np.ndarray, np.ndarray]:
    """Return labels and validity mask. Labels: 0=DOWN, 1=FLAT, 2=UP.

    The threshold at time t uses only trailing log-return volatility known at t:
    max(minimum_return, multiplier * rolling_std * sqrt(horizon)).
    Future returns are used only to create targets, never input features.
    Invalid rows receive -1 and must be excluded from loss/evaluation.
    """
    prices = np.asarray(close, dtype=np.float64)
    if prices.ndim != 1 or prices.size < lookback + max(horizons) + 2:
        raise ValueError("close must be 1-D and long enough for lookback/horizons")
    if not np.isfinite(prices).all() or np.any(prices <= 0):
        raise ValueError("close prices must be finite and positive")
    if not horizons or any(h <= 0 for h in horizons):
        raise ValueError("horizons must contain positive bar counts")
    if lookback < 2 or volatility_multiplier < 0 or minimum_return < 0:
        raise ValueError("invalid threshold configuration")
    returns = np.full(prices.size, np.nan, dtype=np.float64)
    returns[1:] = np.diff(np.log(prices))
    labels = np.full((prices.size, len(horizons)), -1, dtype=np.int64)
    valid = np.zeros_like(labels, dtype=bool)
    for col, horizon in enumerate(horizons):
        for t in range(lookback, prices.size - horizon):
            past = returns[t - lookback + 1:t + 1]
            sigma = float(np.std(past, ddof=1))
            threshold = max(
                minimum_return,
                volatility_multiplier * sigma * np.sqrt(horizon),
            )
            future = float(np.log(prices[t + horizon] / prices[t]))
            labels[t, col] = 2 if future > threshold else 0 if future < -threshold else 1
            valid[t, col] = True
    return labels, valid
