"""Point-in-time event and quantitative primitives for market research.

This module deliberately has no network, broker, model, or third-party dependency.
It provides data contracts and calculations; provider adapters and forecasting
models belong in later, separately tested layers.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Iterable, Sequence
from urllib.parse import urlsplit


_ALLOWED_SOURCE_TIERS = {
    "primary",
    "official_secondary",
    "reputable_secondary",
    "community",
    "unverified",
}


def parse_utc_timestamp(value: str | datetime) -> datetime:
    """Parse an aware timestamp and normalize it to UTC; reject naive values."""
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("timestamp must be ISO-8601 with an explicit timezone") from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise TypeError("timestamp must be a string or datetime")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include an explicit timezone")
    return parsed.astimezone(timezone.utc)


def _finite_number(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


@dataclass(frozen=True)
class MarketEvent:
    """One immutable version of an event, with point-in-time availability.

    A correction is a new record with the same source_event_id and a later
    available_at, not an in-place mutation. available_at is when this exact
    version became public to the market; observed_at is when our collector
    captured it. Keeping them separate prevents ingestion time being mistaken
    for publication time.
    """

    event_id: str
    source_event_id: str
    instrument: str
    category: str
    headline: str
    source_name: str
    source_url: str
    source_tier: str
    published_at: datetime
    available_at: datetime
    observed_at: datetime
    source_updated_at: datetime | None = None

    def __post_init__(self) -> None:
        for name in (
            "event_id",
            "source_event_id",
            "instrument",
            "category",
            "headline",
            "source_name",
            "source_url",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
            if value != value.strip():
                raise ValueError(f"{name} must not contain surrounding whitespace")

        if self.source_tier not in _ALLOWED_SOURCE_TIERS:
            raise ValueError(
                f"source_tier must be one of {sorted(_ALLOWED_SOURCE_TIERS)}"
            )
        parsed_url = urlsplit(self.source_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("source_url must be an absolute HTTP(S) URL")

        for name in ("published_at", "available_at", "observed_at"):
            normalized = parse_utc_timestamp(getattr(self, name))
            object.__setattr__(self, name, normalized)
        if self.source_updated_at is not None:
            object.__setattr__(
                self, "source_updated_at", parse_utc_timestamp(self.source_updated_at)
            )

        if self.published_at > self.available_at:
            raise ValueError("available_at cannot precede published_at")
        if self.source_updated_at is not None:
            if self.source_updated_at < self.published_at:
                raise ValueError("source_updated_at cannot precede published_at")
            if self.source_updated_at > self.available_at:
                raise ValueError("available_at cannot precede source_updated_at")
        if self.available_at > self.observed_at:
            raise ValueError("observed_at cannot precede available_at")


@dataclass(frozen=True)
class Surprise:
    """Raw and direction-adjusted surprise for a reported numeric indicator."""

    actual: float
    consensus: float
    raw: float
    z_score: float
    favorable: float
    favorable_z_score: float


def compute_surprise(
    actual: float,
    consensus: float,
    historical_std: float,
    favorable_direction: int = 1,
) -> Surprise:
    """Compute actual-minus-consensus and its historical standardized surprise.

    favorable_direction is +1 when higher values are favorable and -1 when
    lower values are favorable. It changes interpretation, not the raw data.
    """
    actual_value = _finite_number("actual", actual)
    consensus_value = _finite_number("consensus", consensus)
    dispersion = _finite_number("historical_std", historical_std)
    if dispersion <= 0:
        raise ValueError("historical_std must be greater than zero")
    if favorable_direction not in (-1, 1):
        raise ValueError("favorable_direction must be -1 or 1")
    raw = actual_value - consensus_value
    z_score = raw / dispersion
    return Surprise(
        actual=actual_value,
        consensus=consensus_value,
        raw=raw,
        z_score=z_score,
        favorable=raw * favorable_direction,
        favorable_z_score=z_score * favorable_direction,
    )


def events_as_of(
    events: Iterable[MarketEvent], decision_at: str | datetime
) -> list[MarketEvent]:
    """Return the latest public version of each source event at decision time.

    The caller must supply versioned records and a trustworthy available_at.
    A historical scrape timestamp is not a substitute for market availability.
    """
    cutoff = parse_utc_timestamp(decision_at)
    latest: dict[str, MarketEvent] = {}
    seen_ids: dict[str, MarketEvent] = {}
    for item in events:
        if not isinstance(item, MarketEvent):
            raise TypeError("events must contain MarketEvent records")
        prior_id = seen_ids.get(item.event_id)
        if prior_id is not None and prior_id != item:
            raise ValueError(f"conflicting records share event_id {item.event_id!r}")
        seen_ids[item.event_id] = item
        if item.available_at > cutoff:
            continue
        current = latest.get(item.source_event_id)
        if current is None or (
            item.available_at,
            item.event_id,
        ) > (
            current.available_at,
            current.event_id,
        ):
            latest[item.source_event_id] = item
    return sorted(
        latest.values(),
        key=lambda item: (item.available_at, item.source_event_id, item.event_id),
    )


def expected_return(scenarios: Iterable[tuple[float, float]]) -> float:
    """Calculate probability-weighted return; probabilities must sum to one."""
    pairs = list(scenarios)
    if not pairs:
        raise ValueError("at least one scenario is required")
    total_probability = 0.0
    weighted_return = 0.0
    for probability, outcome in pairs:
        probability_value = _finite_number("probability", probability)
        outcome_value = _finite_number("scenario return", outcome)
        if not 0.0 <= probability_value <= 1.0:
            raise ValueError("scenario probabilities must be between zero and one")
        total_probability += probability_value
        weighted_return += probability_value * outcome_value
    if not math.isclose(total_probability, 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError("scenario probabilities must sum to one")
    return weighted_return


def abnormal_return(asset_return: float, benchmark_return: float) -> float:
    """Compute simple-return abnormal performance versus a benchmark."""
    return _finite_number("asset_return", asset_return) - _finite_number(
        "benchmark_return", benchmark_return
    )


def simple_return(start_price: float, end_price: float) -> float:
    """Compute end/start - 1 after validating positive finite prices."""
    start = _finite_number("start_price", start_price)
    end = _finite_number("end_price", end_price)
    if start <= 0 or end <= 0:
        raise ValueError("prices must be greater than zero")
    return end / start - 1.0
