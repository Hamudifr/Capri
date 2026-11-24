"""Small, deterministic program-learning core for the CCEL research prototype.

This module is intentionally not an LLM and makes no AGI claim. It learns a
bounded family of grid transformations from examples, preserves ambiguity,
and selects informative probes to distinguish candidate models.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from math import log2
from typing import Iterable, Sequence

Grid = tuple[tuple[int, ...], ...]
Operation = str

_OPERATIONS: tuple[Operation, ...] = (
    "rotate_cw",
    "rotate_ccw",
    "flip_horizontal",
    "flip_vertical",
    "transpose",
)
_MAX_SIDE = 30
_MAX_CELLS = 900


class CCELValidationError(ValueError):
    """Input violates the bounded grid/program contract."""


class NoConsistentModelError(ValueError):
    """No candidate program in the configured DSL explains all examples."""


class SearchLimitExceeded(RuntimeError):
    """Bounded synthesis would exceed its explicit candidate budget."""


@dataclass(frozen=True)
class Example:
    source: Grid
    target: Grid

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", normalize_grid(self.source))
        object.__setattr__(self, "target", normalize_grid(self.target))


@dataclass(frozen=True)
class Program:
    operations: tuple[Operation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.operations, tuple):
            raise CCELValidationError("operations must be a tuple")
        if any(operation not in _OPERATIONS for operation in self.operations):
            raise CCELValidationError("program contains an unknown operation")
        if len(self.operations) > 5:
            raise CCELValidationError("program is too deep")

    @property
    def complexity(self) -> int:
        return len(self.operations)

    def apply(self, grid: Grid) -> Grid:
        result = normalize_grid(grid)
        for operation in self.operations:
            result = _apply_operation(result, operation)
        return result


@dataclass(frozen=True)
class SynthesisResult:
    programs: tuple[Program, ...]
    depth: int
    examples_seen: int


@dataclass(frozen=True)
class ProbeChoice:
    grid: Grid
    entropy_bits: float
    distinct_outcomes: int
    predictions: tuple[tuple[Grid, int], ...]


def normalize_grid(value: Sequence[Sequence[int]]) -> Grid:
    if not isinstance(value, (list, tuple)) or not value:
        raise CCELValidationError("grid must be a non-empty list or tuple")
    if len(value) > _MAX_SIDE:
        raise CCELValidationError("grid exceeds maximum height")
    rows: list[tuple[int, ...]] = []
    width: int | None = None
    for row in value:
        if not isinstance(row, (list, tuple)) or not row:
            raise CCELValidationError("grid rows must be non-empty lists or tuples")
        if width is None:
            width = len(row)
            if width > _MAX_SIDE:
                raise CCELValidationError("grid exceeds maximum width")
        elif len(row) != width:
            raise CCELValidationError("grid must be rectangular")
        normalized: list[int] = []
        for cell in row:
            if isinstance(cell, bool) or not isinstance(cell, int) or not 0 <= cell <= 9:
                raise CCELValidationError("grid cells must be integers from 0 to 9")
            normalized.append(cell)
        rows.append(tuple(normalized))
    assert width is not None
    if len(rows) * width > _MAX_CELLS:
        raise CCELValidationError("grid exceeds maximum cell count")
    return tuple(rows)


def _apply_operation(grid: Grid, operation: Operation) -> Grid:
    if operation == "rotate_cw":
        return tuple(tuple(row) for row in zip(*grid[::-1]))
    if operation == "rotate_ccw":
        return tuple(tuple(row) for row in zip(*grid))[::-1]
    if operation == "flip_horizontal":
        return tuple(row[::-1] for row in grid)
    if operation == "flip_vertical":
        return grid[::-1]
    if operation == "transpose":
        return tuple(tuple(row) for row in zip(*grid))
    raise CCELValidationError("unknown operation")


def synthesize(
    examples: Iterable[Example],
    *,
    max_depth: int = 3,
    max_candidates: int = 4096,
) -> SynthesisResult:
    """Find minimum-depth programs consistent with every supplied example.

    All equally simple consistent programs are retained. This is deliberate:
    one observed dataset may not identify a unique underlying rule.
    """
    if isinstance(max_depth, bool) or not isinstance(max_depth, int) or not 0 <= max_depth <= 5:
        raise CCELValidationError("max_depth must be an integer from 0 to 5")
    if isinstance(max_candidates, bool) or not isinstance(max_candidates, int) or not 1 <= max_candidates <= 10000:
        raise CCELValidationError("max_candidates must be an integer from 1 to 10000")
    rows = tuple(examples)
    if not rows or len(rows) > 100 or any(not isinstance(row, Example) for row in rows):
        raise CCELValidationError("provide between 1 and 100 Example objects")

    for depth in range(max_depth + 1):
        sequences = [()] if depth == 0 else product(_OPERATIONS, repeat=depth)
        matches: list[Program] = []
        for sequence in sequences:
            program = Program(tuple(sequence))
            if all(program.apply(row.source) == row.target for row in rows):
                matches.append(program)
                if len(matches) > max_candidates:
                    raise SearchLimitExceeded("consistent models exceed candidate budget")
        if matches:
            matches.sort(key=lambda item: item.operations)
            return SynthesisResult(tuple(matches), depth, len(rows))
    raise NoConsistentModelError("no program in the bounded DSL explains all examples")


def select_probe(programs: Sequence[Program], probes: Iterable[Grid]) -> ProbeChoice:
    """Choose the supplied safe probe with maximum predictive disagreement."""
    if not programs or any(not isinstance(program, Program) for program in programs):
        raise CCELValidationError("programs must contain at least one Program")
    candidates = tuple(normalize_grid(grid) for grid in probes)
    if not candidates:
        raise CCELValidationError("provide at least one candidate probe")

    best: ProbeChoice | None = None
    for grid in candidates:
        counts: dict[Grid, int] = {}
        for program in programs:
            prediction = program.apply(grid)
            counts[prediction] = counts.get(prediction, 0) + 1
        total = len(programs)
        entropy = -sum((count / total) * log2(count / total) for count in counts.values())
        predictions = tuple(sorted(counts.items()))
        choice = ProbeChoice(grid, entropy, len(counts), predictions)
        if best is None or (choice.entropy_bits, choice.distinct_outcomes) > (
            best.entropy_bits, best.distinct_outcomes
        ) or (
            choice.entropy_bits == best.entropy_bits
            and choice.distinct_outcomes == best.distinct_outcomes
            and choice.grid < best.grid
        ):
            best = choice
    assert best is not None
    return best


def predict(programs: Sequence[Program], grid: Grid) -> tuple[Grid, ...]:
    """Return unique predictions without hiding unresolved model disagreement."""
    if not programs or any(not isinstance(program, Program) for program in programs):
        raise CCELValidationError("programs must contain at least one Program")
    return tuple(sorted({program.apply(grid) for program in programs}))
