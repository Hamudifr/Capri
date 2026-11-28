"""Contract tests for append-only, versioned market event storage."""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1] / "research"
sys.path.insert(0, str(RESEARCH_ROOT))

from market_intelligence.core import MarketEvent  # noqa: E402
from market_intelligence.storage import (  # noqa: E402
    EventStore,
    deserialize_event,
    load_events,
    serialize_event,
    to_jsonl,
)


def stamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def event(
    event_id: str,
    *,
    available_at: str = "2026-11-28T10:00:00Z",
    observed_at: str = "2026-11-28T10:01:00Z",
    headline: str = "Quarterly results released",
    source_event_id: str = "wire-123",
) -> MarketEvent:
    return MarketEvent(
        event_id=event_id,
        source_event_id=source_event_id,
        instrument="NASDAQ:NVDA",
        category="earnings",
        headline=headline,
        source_name="Issuer IR",
        source_url="https://investor.example.com/news/123",
        source_tier="primary",
        published_at=stamp("2026-11-28T10:00:00Z"),
        available_at=stamp(available_at),
        observed_at=stamp(observed_at),
    )


class SerializationTests(unittest.TestCase):
    def test_serialize_is_deterministic(self):
        first = serialize_event(event("v1"))
        second = serialize_event(event("v1"))
        self.assertEqual(first, second)

    def test_serialize_rejects_non_event(self):
        with self.assertRaises(TypeError):
            serialize_event("not an event")

    def test_roundtrip_preserves_event(self):
        original = event("v1", headline="Acquisition announced")
        record = serialize_event(original)
        restored = deserialize_event(record)
        self.assertEqual(restored, original)

    def test_deserialize_detects_tampered_content(self):
        record = serialize_event(event("v1"))
        record["event"]["headline"] = "Tampered headline"
        with self.assertRaises(ValueError):
            deserialize_event(record)

    def test_deserialize_rejects_wrong_version(self):
        record = serialize_event(event("v1"))
        record["version"] = 999
        with self.assertRaises(ValueError):
            deserialize_event(record)

    def test_to_jsonl_is_line_per_event(self):
        document = to_jsonl([event("v1"), event("v2", source_event_id="wire-456")])
        lines = [line for line in document.splitlines() if line.strip()]
        self.assertEqual(len(lines), 2)


class EventStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "events.jsonl"
        self.store = EventStore(self.path)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_load_empty_store_is_empty(self):
        self.assertEqual(self.store.load(), [])

    def test_append_and_load_roundtrip(self):
        original = event("v1")
        self.store.append(original)
        loaded = self.store.load()
        self.assertEqual(loaded, [original])

    def test_append_many_preserves_order(self):
        first = event("v1")
        second = event("v2", source_event_id="wire-456")
        third = event("v3", source_event_id="wire-789")
        self.assertEqual(self.store.append_many([first, second, third]), 3)
        self.assertEqual(
            [item.event_id for item in self.store.load()], ["v1", "v2", "v3"]
        )

    def test_correction_is_appended_not_overwritten(self):
        original = event("v1")
        correction = event(
            "v2",
            available_at="2026-11-28T10:05:00Z",
            observed_at="2026-11-28T10:06:00Z",
            headline="Quarterly results corrected",
            source_event_id="wire-123",
        )
        self.store.append(original)
        self.store.append(correction)
        loaded = self.store.load()
        self.assertEqual(len(loaded), 2)
        self.assertEqual({item.event_id for item in loaded}, {"v1", "v2"})

    def test_integrity_check_passes_for_clean_store(self):
        self.store.append(event("v1"))
        self.store.append(event("v2", source_event_id="wire-456"))
        ok, message = self.store.integrity_check()
        self.assertTrue(ok)
        self.assertIn("intact", message)

    def test_integrity_check_detects_tampered_line(self):
        self.store.append(event("v1"))
        self.store.append(event("v2", source_event_id="wire-456"))
        # Corrupt the first line's headline after writing.
        lines = self.path.read_text(encoding="utf-8").splitlines()
        import json

        record = json.loads(lines[0])
        record["event"]["headline"] = "Tampered"
        lines[0] = json.dumps(record)
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        ok, message = self.store.integrity_check()
        self.assertFalse(ok)

    def test_integrity_check_detects_chain_break(self):
        self.store.append(event("v1"))
        self.store.append(event("v2", source_event_id="wire-456"))
        lines = self.path.read_text(encoding="utf-8").splitlines()
        # Drop the first line to break the predecessor linkage.
        self.path.write_text("\n".join(lines[1:]) + "\n", encoding="utf-8")
        ok, message = self.store.integrity_check()
        self.assertFalse(ok)

    def test_load_events_convenience_loader(self):
        self.store.append(event("v1"))
        self.assertEqual(load_events(self.path), self.store.load())


if __name__ == "__main__":
    unittest.main()
