"""Finite counterexample to naive polynomial-floor multiplicative weights.

There are M=2^m experts. Expert 0 has zero loss on every round; every other
expert has unit loss. We compare ordinary exponential weights with a raw
per-expert floor lambda and a normalized-probability floor lambda/M.

This is not a lower bound against all soft-weight methods. It shows the basic
trade-off: a polynomial floor on every raw weight destroys concentration,
while a floor small enough to preserve regret is exponentially small per
expert and invisible to additive polynomial-precision counting.
"""
from __future__ import annotations

import math


def summarize(m: int = 20, rounds: int = 150, eta: float = 0.2, n: int = 10) -> dict[str, float]:
    M = 1 << m
    lam = 1.0 / (n * n)
    bad_weight = math.exp(-eta * rounds)

    # Standard exponential weights: one perfect expert, M-1 always-bad experts.
    standard_best_mass = 1.0 / (1.0 + (M - 1) * bad_weight)
    standard_expected_loss = 1.0 - standard_best_mass

    # Naive raw floor: each bad expert is forced to retain weight >= lambda.
    raw_floor_best_mass = 1.0 / (1.0 + (M - 1) * max(bad_weight, lam))
    raw_floor_expected_loss = 1.0 - raw_floor_best_mass

    # A normalized floor of lambda/M keeps total added mass O(lambda),
    # but the per-expert floor is exponentially small in m.
    normalized_floor_per_expert = lam / M
    return {
        "experts": float(M),
        "rounds": float(rounds),
        "lambda": lam,
        "standard_best_expert_mass": standard_best_mass,
        "standard_average_loss": standard_expected_loss,
        "raw_floor_best_expert_mass": raw_floor_best_mass,
        "raw_floor_average_loss": raw_floor_expected_loss,
        "normalized_floor_per_expert": normalized_floor_per_expert,
        "additive_precision_example": lam,
        "floor_below_precision_ratio": normalized_floor_per_expert / lam,
    }


def main() -> None:
    for key, value in summarize().items():
        print(f"{key}: {value:.12g}")


if __name__ == "__main__":
    main()
