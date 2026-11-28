"""Research-only market intelligence primitives."""

from .core import (
    MarketEvent,
    Surprise,
    abnormal_return,
    compute_surprise,
    events_as_of,
    expected_return,
    parse_utc_timestamp,
    simple_return,
)

__all__ = [
    "MarketEvent",
    "Surprise",
    "abnormal_return",
    "compute_surprise",
    "events_as_of",
    "expected_return",
    "parse_utc_timestamp",
    "simple_return",
]
