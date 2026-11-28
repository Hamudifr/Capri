"""Differential equations training module (batch 5)."""

from .core import (
    euler,
    heun,
    rk4,
    rk45,
    rk4_system,
    euler_system,
    second_order_to_first,
    exponential_decay_solution,
    harmonic_oscillator_solution,
    logistic_growth_solution,
)

__all__ = [
    "euler",
    "heun",
    "rk4",
    "rk45",
    "rk4_system",
    "euler_system",
    "second_order_to_first",
    "exponential_decay_solution",
    "harmonic_oscillator_solution",
    "logistic_growth_solution",
]
