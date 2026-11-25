"""Tiny exact model of a truth-table-dependent anti-checker selector.

The candidate class consists of all Boolean functions depending only on the
first k input bits. A hard target is any function that varies inside at least
one fiber of the projection to those k bits. Two points in that fiber with
opposite target labels refute every candidate simultaneously.

This is a combinatorial toy, not the OPS selector circuit or a circuit lower
bound. It illustrates why an adaptive selector can succeed while any fixed
sample of fewer than 2^n points fails on some hard target.
"""
from __future__ import annotations

from typing import Sequence


def truth_table_bit(table: int, x: int) -> int:
    return (table >> x) & 1


def subcube_function_class(n: int, k: int) -> list[int]:
    """All truth tables on n bits that depend only on the low k bits."""
    if not (0 <= k < n):
        raise ValueError("require 0 <= k < n")
    size = 1 << n
    fiber_mask = (1 << k) - 1
    return [
        sum(((g >> (x & fiber_mask)) & 1) << x for x in range(size))
        for g in range(1 << (1 << k))
    ]


def find_two_point_antichecker(target: int, n: int, k: int) -> tuple[int, int]:
    """Find same-prefix inputs with opposite target labels, if they exist."""
    if not (0 <= k < n):
        raise ValueError("require 0 <= k < n")
    first_by_prefix: dict[int, int] = {}
    for x in range(1 << n):
        prefix = x & ((1 << k) - 1)
        if prefix not in first_by_prefix:
            first_by_prefix[prefix] = x
        elif truth_table_bit(target, first_by_prefix[prefix]) != truth_table_bit(target, x):
            return first_by_prefix[prefix], x
    raise ValueError("target belongs to the subcube-constant class")


def verify_antichecker(target: int, candidates: Sequence[int], sample: Sequence[int]) -> bool:
    return all(
        any(truth_table_bit(target, x) != truth_table_bit(candidate, x) for x in sample)
        for candidate in candidates
    )


def fixed_sample_counterexample(sample: Sequence[int], n: int, k: int) -> int:
    """Build a hard target agreeing with the constant-zero candidate on sample."""
    size = 1 << n
    if not (0 <= k < n):
        raise ValueError("require 0 <= k < n")
    if len(set(sample)) >= size:
        raise ValueError("a full-domain sample cannot be defeated")
    if any(x < 0 or x >= size for x in sample):
        raise ValueError("sample point outside domain")
    selected = set(sample)
    x = next(x for x in range(size) if x not in selected)
    # One unqueried 1 and zeros everywhere else: every queried point agrees
    # with the constant-zero candidate, but the target varies inside a fiber.
    return 1 << x


def demo() -> None:
    n, k = 8, 4
    size = 1 << n
    target = 0
    for x in range(size):
        if x.bit_count() & 1:
            target |= 1 << x
    candidates = subcube_function_class(n, k)
    sample = find_two_point_antichecker(target, n, k)
    print(f"candidate functions: {len(candidates)}")
    print(f"adaptive two-point sample: {sample}")
    print(f"sample refutes every candidate: {verify_antichecker(target, candidates, sample)}")

    fixed = (0, 1, 2)
    counterexample = fixed_sample_counterexample(fixed, n, k)
    print(
        "fixed sample defeated by a hard target: "
        f"{all(truth_table_bit(counterexample, x) == 0 for x in fixed)}; "
        f"target outside class: {counterexample not in candidates}"
    )


if __name__ == "__main__":
    demo()
