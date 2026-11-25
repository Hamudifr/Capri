"""Finite-game diagnostics for P-vs-NP antichecker research.

Experimental checker only; not a proof of an asymptotic circuit lower bound.
Requires NumPy and SciPy (scipy.optimize.linprog).
"""
from __future__ import annotations

from dataclasses import dataclass
from math import log
from typing import Callable, Hashable, Sequence

import numpy as np
from scipy.optimize import linprog


@dataclass(frozen=True)
class GameSolution:
    value: float
    row_strategy: tuple[float, ...]


def solve_row_strategy(payoff: Sequence[Sequence[float]]) -> GameSolution:
    """Solve max_q min_j sum_i q_i A[i,j] for a finite zero-sum game."""
    a = np.asarray(payoff, dtype=float)
    if a.ndim != 2 or not a.shape[0] or not a.shape[1]:
        raise ValueError("payoff must be a non-empty rectangular matrix")
    m, n = a.shape
    objective = np.r_[np.zeros(m), -1.0]
    inequalities = np.c_[-a.T, np.ones(n)]
    equality = np.array([[1.0] * m + [0.0]])
    result = linprog(
        objective,
        A_ub=inequalities,
        b_ub=np.zeros(n),
        A_eq=equality,
        b_eq=np.ones(1),
        bounds=[(0.0, None)] * m + [(0.0, 1.0)],
        method="highs",
    )
    if not result.success:
        raise RuntimeError(f"linear program failed: {result.message}")
    return GameSolution(float(result.x[-1]), tuple(float(x) for x in result.x[:-1]))


def disagreement_game(target: Sequence[int], circuits: Sequence[Sequence[int]]) -> np.ndarray:
    """Rows are singleton input challenges; columns are circuits."""
    f = np.asarray(target, dtype=int)
    c = np.asarray(circuits, dtype=int)
    if c.ndim != 2 or c.shape[1] != len(f):
        raise ValueError("circuits must be a rectangular list of truth tables")
    if not np.isin(f, [0, 1]).all() or not np.isin(c, [0, 1]).all():
        raise ValueError("truth tables must be binary")
    return (c != f[None, :]).astype(float).T


def deterministic_response_information(
    circuit_probabilities: Sequence[float], response_indices: Sequence[int]
) -> float:
    """Compute I(C;T) in nats when T is a deterministic function of C."""
    p = np.asarray(circuit_probabilities, dtype=float)
    if len(p) != len(response_indices) or np.any(p < 0) or not np.isclose(p.sum(), 1):
        raise ValueError("probabilities must be normalized and match responses")
    buckets: dict[int, float] = {}
    for mass, response in zip(p, response_indices):
        buckets[response] = buckets.get(response, 0.0) + float(mass)
    return sum(
        float(mass) * log(1.0 / buckets[response])
        for mass, response in zip(p, response_indices)
        if mass
    )


def extract_terminal_package(
    universe: Sequence[Hashable],
    package_for_history: Callable[[int, tuple[Hashable, ...]], set[Hashable]],
    rounds: int,
) -> tuple[int, tuple[Hashable, ...], set[Hashable]]:
    """Follow evading challenges in a finite KPT-style causal game.

    A package at round i depends only on earlier challenges. If every full
    challenge sequence is guaranteed to hit at least one package, this
    adversarial path must terminate at a package covering the whole universe.
    """
    history: list[Hashable] = []
    for stage in range(rounds):
        package = set(package_for_history(stage, tuple(history)))
        evaders = [circuit for circuit in universe if circuit not in package]
        if not evaders:
            return stage, tuple(history), package
        history.append(evaders[0])
    raise AssertionError(
        "no universal package found: the supplied causal strategy does not "
        "satisfy the KPT all-sequences success condition"
    )


def demo() -> None:
    target = (0, 1, 1, 0)  # XOR on two input bits
    circuits = [
        (0, 0, 0, 0), (1, 1, 1, 1),
        (0, 0, 1, 1), (1, 1, 0, 0),
        (0, 1, 0, 1), (1, 0, 1, 0),
    ]
    direct = solve_row_strategy(disagreement_game(target, circuits))
    m = 12
    restricted = solve_row_strategy(np.eye(m))
    information = deterministic_response_information([1.0 / m] * m, list(range(m)))

    universe = tuple(range(4))

    def package(stage: int, history: tuple[int, ...]) -> set[int]:
        if stage == 0:
            return {0}
        if stage == 1:
            return {1} if history[0] == 1 else {2}
        return set(universe)

    terminal = extract_terminal_package(universe, package, 3)
    print(f"direct example-game value: {direct.value:.6f}")
    print(f"direct-game optimal support: {sum(p > 1e-8 for p in direct.row_strategy)}")
    print(f"restricted identity-game value: {restricted.value:.6f} (=1/{m})")
    print(f"identity response mutual information: {information:.6f} nats")
    print(
        f"KPT-style terminal package: stage={terminal[0] + 1}, "
        f"history={terminal[1]}, covers={sorted(terminal[2])}"
    )


if __name__ == "__main__":
    demo()
