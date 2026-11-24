"""Dependency-free Python reference benchmark for the CCEL synthesis task."""
from functools import reduce
from itertools import product
from statistics import median
from time import perf_counter

OPERATIONS = ("rotate_cw", "rotate_ccw", "flip_h", "flip_v", "transpose")


def apply(grid, operation):
    height, width = len(grid), len(grid[0])
    if operation == "rotate_cw":
        return tuple(tuple(grid[height - 1 - r][c] for r in range(height)) for c in range(width))
    if operation == "rotate_ccw":
        return tuple(tuple(grid[r][width - 1 - c] for r in range(height)) for c in range(width))
    if operation == "flip_h":
        return tuple(tuple(reversed(row)) for row in grid)
    if operation == "flip_v":
        return tuple(reversed(grid))
    if operation == "transpose":
        return tuple(tuple(grid[r][c] for r in range(height)) for c in range(width))
    raise ValueError("unknown operation")


def synthesize(examples, max_depth=1):
    for depth in range(max_depth + 1):
        sequences = [()] if depth == 0 else product(OPERATIONS, repeat=depth)
        matches = []
        for sequence in sequences:
            if all(
                reduce(apply, sequence, source) == target
                for source, target in examples
            ):
                matches.append(sequence)
        if matches:
            return tuple(matches)
    raise ValueError("no consistent model")


def main():
    rows = tuple(tuple((r * 7 + c * 3 + r * c) % 10 for c in range(20)) for r in range(20))
    target = apply(rows, "rotate_cw")
    examples = ((rows, target),)

    for _ in range(100):
        synthesize(examples)

    rounds = 10_000
    samples = []
    for _ in range(5):
        start = perf_counter()
        for _ in range(rounds):
            synthesize(examples)
        samples.append(perf_counter() - start)
    elapsed = median(samples)
    print(
        f"Python CCEL reference: median of 5 x {rounds} rounds = "
        f"{elapsed:.6f}s ({rounds / elapsed:.2f} ops/s)"
    )


if __name__ == "__main__":
    main()
