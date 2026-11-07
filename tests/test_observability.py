import json
import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from capri_runtime.observability import (
    InMemoryEventLog,
    MetricEvent,
    MetricRegistry,
    ObservabilityValidationError,
    SQLiteEventLog,
)

NOW = datetime(2026, 11, 7, 14, 0, tzinfo=timezone.utc)
LATER = NOW + timedelta(seconds=10)


class InMemoryEventLogTests(unittest.TestCase):
    def test_records_are_ordered_and_bounded_by_retention(self):
        log = InMemoryEventLog(max_events=3)
        for index in range(5):
            log.record("task.step", index, {"step": index}, now=NOW)
        events = log.snapshot()
        self.assertEqual(len(events), 3)
        self.assertEqual([event.sequence for event in events], [3, 4, 5])
        self.assertEqual(log.count(), 3)
        self.assertEqual(log.count("task.step"), 3)

    def test_name_cardinality_fails_closed(self):
        log = InMemoryEventLog(max_names=2)
        log.record("one", now=NOW)
        log.record("two", now=NOW)
        with self.assertRaises(ObservabilityValidationError):
            log.record("three", now=NOW)

    def test_snapshot_filters_name_window_and_limit(self):
        log = InMemoryEventLog()
        log.record("alpha", 1, now=NOW)
        log.record("beta", 2, now=NOW + timedelta(seconds=1))
        log.record("alpha", 3, now=NOW + timedelta(seconds=2))
        log.record("beta", 4, now=NOW + timedelta(seconds=3))
        only_alpha = log.snapshot(name="alpha")
        self.assertEqual([event.value for event in only_alpha], [1, 3])
        window = log.snapshot(since=NOW + timedelta(seconds=1), until=NOW + timedelta(seconds=2))
        self.assertEqual(sorted(event.value for event in window), [2, 3])
        limited = log.snapshot(limit=2)
        self.assertEqual([event.sequence for event in limited], [1, 2])
        with self.assertRaises(ObservabilityValidationError):
            log.snapshot(limit=0)
        with self.assertRaises(ObservabilityValidationError):
            log.snapshot(since=LATER, until=NOW)

    def test_invalid_names_values_and_attributes_fail_closed(self):
        log = InMemoryEventLog()
        invalid_names = ("", "has space", "dash-name!", "x" * 65, 7, None)
        for name in invalid_names:
            with self.subTest(name=name):
                with self.assertRaises(ObservabilityValidationError):
                    log.record(name, now=NOW)
        invalid_values = (True, "3", None, float("nan"), float("inf"), 1e13)
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ObservabilityValidationError):
                    log.record("metric", value, now=NOW)
        with self.assertRaises(ObservabilityValidationError):
            log.record("metric", 1, {"surrogate": "bad \ud800 pair"}, now=NOW)
        with self.assertRaises(ObservabilityValidationError):
            log.record("metric", 1, ["not", "an", "object"], now=NOW)
        with self.assertRaises(ObservabilityValidationError):
            log.record("metric", 1, {"blob": "x" * 5000}, now=NOW)

    def test_export_json_is_deterministic(self):
        first = InMemoryEventLog()
        second = InMemoryEventLog()
        for log in (first, second):
            log.record("alpha", 1, {"b": 2, "a": 1}, now=NOW)
            log.record("beta", 2.5, now=NOW)
        self.assertEqual(first.export_json(), second.export_json())
        decoded = json.loads(first.export_json())
        self.assertEqual(decoded[0]["attributes"], {"a": 1, "b": 2})
        self.assertEqual(decoded[1]["name"], "beta")


class SQLiteEventLogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        if os.name == "posix":
            os.chmod(self.temp.name, 0o700)
        self.path = os.path.join(self.temp.name, "events.sqlite3")
        self.log = SQLiteEventLog(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_record_persists_and_reopens(self):
        event = self.log.record("task.completed", 3, {"task_id": "t-1"}, now=NOW)
        reopened = SQLiteEventLog(self.path)
        events = reopened.query()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].name, "task.completed")
        self.assertEqual(events[0].value, 3)
        self.assertEqual(events[0].attributes, {"task_id": "t-1"})
        self.assertEqual(events[0].sequence, event.sequence)
        self.assertEqual(reopened.integrity_check(), "ok")

    def test_retention_prunes_oldest_events(self):
        log = SQLiteEventLog(self.path, max_events=3)
        for index in range(5):
            log.record("tick", index, now=NOW)
        events = log.query()
        self.assertEqual(len(events), 3)
        self.assertEqual([event.value for event in events], [2, 3, 4])
        self.assertEqual(log.count(), 3)

    def test_query_filters_and_limits(self):
        self.log.record("alpha", 1, now=NOW)
        self.log.record("beta", 2, now=NOW + timedelta(seconds=1))
        self.log.record("alpha", 3, now=NOW + timedelta(seconds=2))
        self.log.record("beta", 4, now=NOW + timedelta(seconds=3))
        only_alpha = self.log.query(name="alpha")
        self.assertEqual([event.value for event in only_alpha], [1, 3])
        window = self.log.query(since=NOW + timedelta(seconds=1), until=NOW + timedelta(seconds=2))
        self.assertEqual(sorted(event.value for event in window), [2, 3])
        limited = self.log.query(limit=2)
        self.assertEqual([event.value for event in limited], [1, 2])
        self.assertEqual(self.log.count("beta"), 2)
        with self.assertRaises(ObservabilityValidationError):
            self.log.query(limit=1001)

    def test_prune_before_removes_and_counts(self):
        for index in range(4):
            self.log.record("tick", index, now=NOW + timedelta(seconds=index))
        deleted = self.log.prune_before(NOW + timedelta(seconds=2))
        self.assertEqual(deleted, 2)
        self.assertEqual(self.log.count(), 2)
        self.assertEqual([event.value for event in self.log.query()], [2, 3])

    def test_keep_last_prunes_oldest(self):
        for index in range(4):
            self.log.record("tick", index, now=NOW)
        deleted = self.log.keep_last(2)
        self.assertEqual(deleted, 2)
        self.assertEqual([event.value for event in self.log.query()], [2, 3])
        with self.assertRaises(ObservabilityValidationError):
            self.log.keep_last(0)

    def test_invalid_input_fails_closed(self):
        with self.assertRaises(ObservabilityValidationError):
            self.log.record("bad name", now=NOW)
        with self.assertRaises(ObservabilityValidationError):
            self.log.record("metric", True, now=NOW)
        with self.assertRaises(ObservabilityValidationError):
            self.log.record("metric", 1, {"blob": "x" * 5000}, now=NOW)
        with self.assertRaises(ObservabilityValidationError):
            SQLiteEventLog(self.path, max_events=0)

    def test_database_rejects_symlink_path(self):
        if os.name != "posix":
            self.skipTest("POSIX symlink semantics required")
        target = os.path.join(self.temp.name, "target.db")
        with open(target, "w", encoding="utf-8") as stream:
            stream.write("not a database")
        link = os.path.join(self.temp.name, "link.db")
        os.symlink(target, link)
        with self.assertRaises(ObservabilityValidationError):
            SQLiteEventLog(link)

    def test_database_rechecks_directory_privacy(self):
        if os.name != "posix":
            self.skipTest("POSIX permissions required")
        os.chmod(self.temp.name, 0o755)
        try:
            with self.assertRaises(ObservabilityValidationError):
                self.log.record("metric", 1, now=NOW)
        finally:
            os.chmod(self.temp.name, 0o700)

    def test_corrupt_row_fails_closed_on_read(self):
        self.log.record("metric", 1, now=NOW)
        connection = sqlite3.connect(self.path)
        try:
            connection.execute("UPDATE events SET attributes_json='not json'")
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(ObservabilityValidationError):
            self.log.query()

    def test_concurrent_records_are_all_counted(self):
        def record_many(worker: int) -> None:
            log = SQLiteEventLog(self.path)
            for index in range(25):
                log.record(f"worker.{worker}", 1, {"index": index})
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(record_many, range(4)))
        self.assertEqual(SQLiteEventLog(self.path).count(), 100)

    def test_export_json_matches_query(self):
        self.log.record("alpha", 1, {"a": 1}, now=NOW)
        self.log.record("beta", 2, now=NOW)
        decoded = json.loads(self.log.export_json())
        self.assertEqual([item["name"] for item in decoded], ["alpha", "beta"])
        self.assertEqual(decoded[0]["attributes"], {"a": 1})


class MetricRegistryTests(unittest.TestCase):
    def test_counter_and_gauge_aggregates(self):
        registry = MetricRegistry()
        self.assertEqual(registry.counter("tasks.completed"), 1)
        self.assertEqual(registry.counter("tasks.completed", 4), 5)
        registry.gauge("queue.depth", 7)
        snapshot = registry.snapshot()
        self.assertEqual(snapshot["counters"], {"tasks.completed": 5})
        self.assertEqual(snapshot["gauges"], {"queue.depth": 7})
        self.assertEqual(json.loads(registry.export_json())[0], snapshot)

    def test_invalid_counters_and_gauges_fail_closed(self):
        registry = MetricRegistry()
        with self.assertRaises(ObservabilityValidationError):
            registry.counter("bad name")
        with self.assertRaises(ObservabilityValidationError):
            registry.counter("metric", -1)
        with self.assertRaises(ObservabilityValidationError):
            registry.counter("metric", True)
        with self.assertRaises(ObservabilityValidationError):
            registry.gauge("metric", float("nan"))

    def test_name_cardinality_fails_closed(self):
        registry = MetricRegistry(max_names=2)
        registry.counter("one")
        registry.gauge("two", 1.5)
        with self.assertRaises(ObservabilityValidationError):
            registry.counter("three")


if __name__ == "__main__":
    unittest.main()
