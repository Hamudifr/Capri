"""Append-only, versioned JSONL storage for market events.

The event core (``core.py``) defines immutable data contracts. This module adds
durable, deterministic serialization and an append-only store so that a record,
once written, is never silently overwritten. A correction is a new record with
the same ``source_event_id`` and a later ``available_at`` — matching the
point-in-time rule that the latest public version at a decision time is the one
that matters.

The store is a hash-chained JSONL file: each line carries a content hash and the
hash of the previous line, so tampering or gaps are detectable on load. Only the
Python standard library is used; there is no network access.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable, Iterator

from .core import MarketEvent


_RECORD_VERSION = 1


def _stable_json(payload: object) -> str:
    """Serialize deterministically so equal records produce equal bytes."""
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _content_hash(event: MarketEvent) -> str:
    payload = {
        "event_id": event.event_id,
        "source_event_id": event.source_event_id,
        "instrument": event.instrument,
        "category": event.category,
        "headline": event.headline,
        "source_name": event.source_name,
        "source_url": event.source_url,
        "source_tier": event.source_tier,
        "published_at": event.published_at.isoformat(),
        "available_at": event.available_at.isoformat(),
        "observed_at": event.observed_at.isoformat(),
        "event_at": event.event_at.isoformat() if event.event_at else None,
        "source_updated_at": (
            event.source_updated_at.isoformat()
            if event.source_updated_at
            else None
        ),
    }
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def serialize_event(event: MarketEvent) -> dict[str, object]:
    """Return a deterministic, hash-tagged dict for one event record."""
    if not isinstance(event, MarketEvent):
        raise TypeError("event must be a MarketEvent")
    return {
        "version": _RECORD_VERSION,
        "event": {
            "event_id": event.event_id,
            "source_event_id": event.source_event_id,
            "instrument": event.instrument,
            "category": event.category,
            "headline": event.headline,
            "source_name": event.source_name,
            "source_url": event.source_url,
            "source_tier": event.source_tier,
            "published_at": event.published_at.isoformat(),
            "available_at": event.available_at.isoformat(),
            "observed_at": event.observed_at.isoformat(),
            "event_at": event.event_at.isoformat() if event.event_at else None,
            "source_updated_at": (
                event.source_updated_at.isoformat()
                if event.source_updated_at
                else None
            ),
        },
        "content_hash": _content_hash(event),
    }


def deserialize_event(record: dict[str, object]) -> MarketEvent:
    """Rebuild a validated ``MarketEvent`` from a serialized record dict."""
    if not isinstance(record, dict):
        raise TypeError("record must be a dict")
    version = record.get("version")
    if version != _RECORD_VERSION:
        raise ValueError(f"unsupported record version: {version!r}")
    event_payload = record.get("event")
    if not isinstance(event_payload, dict):
        raise ValueError("record is missing an 'event' object")
    expected_hash = record.get("content_hash")
    if not isinstance(expected_hash, str) or not expected_hash:
        raise ValueError("record is missing a content_hash")

    event = MarketEvent(**{k: v for k, v in event_payload.items()})
    actual_hash = _content_hash(event)
    if actual_hash != expected_hash:
        raise ValueError(
            "content_hash mismatch: record was modified after serialization"
        )
    return event


def to_jsonl(events: Iterable[MarketEvent]) -> str:
    """Serialize events to a deterministic JSONL document."""
    lines = [_stable_json(serialize_event(event)) for event in events]
    return "\n".join(lines) + ("\n" if lines else "")


class EventStore:
    """Append-only, hash-chained JSONL store for market events.

    Writes append a single line and never rewrite prior records. Loads verify
    the hash chain and reject records whose content does not match their hash or
    whose predecessor hash does not line up, so a gap or edit is detected.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _read_lines(self) -> list[str]:
        if not self.path.exists():
            return []
        text = self.path.read_text(encoding="utf-8")
        return [line for line in text.splitlines() if line.strip()]

    def load(self) -> list[MarketEvent]:
        """Load and validate every record, verifying the hash chain."""
        events: list[MarketEvent] = []
        previous_hash = "0" * 64
        for index, line in enumerate(self._read_lines()):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"line {index + 1} is not valid JSON") from exc
            if not isinstance(record, dict):
                raise ValueError(f"line {index + 1} is not a JSON object")
            record_hash = record.get("chain_hash")
            predecessor = record.get("previous_hash")
            if predecessor != previous_hash:
                raise ValueError(
                    f"hash chain broken at line {index + 1}: "
                    "previous_hash does not match predecessor"
                )
            event = deserialize_event(record)
            if record_hash is not None and record_hash != _content_hash(event):
                raise ValueError(
                    f"chain_hash mismatch at line {index + 1}"
                )
            previous_hash = _content_hash(event)
            events.append(event)
        return events

    def append(self, event: MarketEvent) -> None:
        """Append one event as a new, hash-chained record.

        Appending is the only mutation. To correct an event, append a new record
        with the same ``source_event_id`` and a later ``available_at``; never
        overwrite an existing line.
        """
        if not isinstance(event, MarketEvent):
            raise TypeError("event must be a MarketEvent")
        lines = self._read_lines()
        previous_hash = "0" * 64
        if lines:
            record = json.loads(lines[-1])
            previous_hash = _content_hash(deserialize_event(record))

        record = serialize_event(event)
        record["previous_hash"] = previous_hash
        record["chain_hash"] = _content_hash(event)
        line = _stable_json(record)

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def append_many(self, events: Iterable[MarketEvent]) -> int:
        """Append several events, preserving order; return the count written."""
        count = 0
        for event in events:
            self.append(event)
            count += 1
        return count

    def iter_events(self) -> Iterator[MarketEvent]:
        """Yield validated events one at a time (verifies the chain)."""
        yield from self.load()

    def integrity_check(self) -> tuple[bool, str]:
        """Return ``(ok, message)`` verifying the hash chain end to end."""
        try:
            self.load()
        except ValueError as exc:
            return False, str(exc)
        return True, "hash chain intact"


def load_events(path: str | Path) -> list[MarketEvent]:
    """Convenience loader for a JSONL event file."""
    return EventStore(path).load()
