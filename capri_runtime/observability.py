"""Bounded, fail-closed observability primitives for the non-X5 runtime.

This module records structured metric events and small bounded attribute
payloads. It is an observability primitive, not a network metrics exporter, a
profiler, or a logging framework. Hosts own delivery to external systems; this
module performs no network, subprocess, or filesystem access beyond the single
explicit database path. Event attributes must never contain credentials,
secrets, or sensitive personal data.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import stat
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

MAX_NAME_LENGTH = 64
MAX_ATTRIBUTE_BYTES = 4096
MAX_NAMES = 256
MAX_EVENTS = 10_000
MAX_RETAINED_EVENTS = 1_000_000
MAX_QUERY_LIMIT = 1_000
MAX_ABS_VALUE = 1e12


class ObservabilityError(Exception):
    """Base class for expected observability failures."""


class ObservabilityValidationError(ObservabilityError):
    """An event, metric, or persisted observability value is invalid."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ObservabilityValidationError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        raise ObservabilityValidationError("persisted timestamp is invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ObservabilityValidationError("persisted timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _assert_json_value(value: Any, depth: int = 0) -> None:
    if depth > 16:
        raise ObservabilityValidationError("JSON nesting exceeds 16 levels")
    if value is None or isinstance(value, (bool, int, float)):
        return
    if isinstance(value, str):
        if any(0xD800 <= ord(ch) <= 0xDFFF for ch in value):
            raise ObservabilityValidationError("JSON strings must contain Unicode scalar values")
        return
    if isinstance(value, list):
        for child in value:
            _assert_json_value(child, depth + 1)
        return
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ObservabilityValidationError("JSON object keys must be strings")
            _assert_json_value(key, depth + 1)
            _assert_json_value(child, depth + 1)
        return
    raise ObservabilityValidationError("value contains a non-JSON type")


def _attributes(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    _assert_json_value(value)
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True,
            separators=(",", ":"),
        )
        raw = encoded.encode("utf-8", errors="strict")
        decoded = json.loads(encoded)
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        raise ObservabilityValidationError(
            "attributes must be valid JSON with Unicode scalar values"
        ) from None
    if len(raw) > MAX_ATTRIBUTE_BYTES:
        raise ObservabilityValidationError("attributes exceed the configured byte limit")
    if not isinstance(decoded, dict):
        raise ObservabilityValidationError("attributes must be a JSON object")
    return decoded


def _name(value: Any) -> str:
    if (not isinstance(value, str) or not value or len(value) > MAX_NAME_LENGTH
            or any(0xD800 <= ord(ch) <= 0xDFFF for ch in value)):
        raise ObservabilityValidationError("metric name is invalid")
    if not value.replace("_", "").replace("-", "").replace(".", "").isalnum():
        raise ObservabilityValidationError("metric name is invalid")
    return value


def _value(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ObservabilityValidationError("metric value must be a number")
    if not math.isfinite(value) or abs(value) > MAX_ABS_VALUE:
        raise ObservabilityValidationError("metric value must be finite and bounded")
    return value


def _export(events: Any) -> str:
    try:
        return json.dumps(
            list(events), ensure_ascii=False, allow_nan=False, sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise ObservabilityValidationError("events could not be exported") from error


@dataclass(frozen=True, slots=True)
class MetricEvent:
    sequence: int
    name: str
    timestamp: str
    value: float
    attributes: dict[str, Any]


def _event_dict(event: MetricEvent) -> dict[str, Any]:
    return {
        "sequence": event.sequence,
        "name": event.name,
        "timestamp": event.timestamp,
        "value": event.value,
        "attributes": event.attributes,
    }


def _check_window(since: datetime | None, until: datetime | None) -> tuple[str | None, str | None]:
    since_iso = _iso(since) if since is not None else None
    until_iso = _iso(until) if until is not None else None
    if since_iso is not None and until_iso is not None and since_iso > until_iso:
        raise ObservabilityValidationError("since must not be later than until")
    return since_iso, until_iso


def _check_limit(limit: int | None) -> int:
    if limit is None:
        return MAX_QUERY_LIMIT
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_QUERY_LIMIT:
        raise ObservabilityValidationError("limit must be between 1 and 1000")
    return limit


class InMemoryEventLog:
    """Thread-safe bounded in-process event log with deterministic export.

    Retains only the newest ``max_events`` events (ring eviction) and at most
    ``max_names`` distinct metric names; a new name beyond the cardinality
    bound fails closed instead of growing silently.
    """

    def __init__(self, max_events: int = MAX_EVENTS, max_names: int = MAX_NAMES) -> None:
        if (isinstance(max_events, bool) or not isinstance(max_events, int)
                or not 1 <= max_events <= MAX_RETAINED_EVENTS):
            raise ObservabilityValidationError("max_events must be between 1 and 1000000")
        if (isinstance(max_names, bool) or not isinstance(max_names, int)
                or not 1 <= max_names <= MAX_NAMES):
            raise ObservabilityValidationError("max_names must be between 1 and 256")
        self._events: deque[MetricEvent] = deque(maxlen=max_events)
        self._names: set[str] = set()
        self._max_names = max_names
        self._lock = threading.RLock()
        self._sequence = 0

    def record(self, name: str, value: float = 1.0, attributes: Any = None,
               now: datetime | None = None) -> MetricEvent:
        name = _name(name)
        number = _value(value)
        attrs = _attributes(attributes)
        stamp = _iso(now or _now())
        with self._lock:
            if name not in self._names:
                if len(self._names) >= self._max_names:
                    raise ObservabilityValidationError("metric name cardinality exceeded")
                self._names.add(name)
            self._sequence += 1
            event = MetricEvent(self._sequence, name, stamp, number, attrs)
            self._events.append(event)
        return event

    def snapshot(self, name: str | None = None, since: datetime | None = None,
                 until: datetime | None = None, limit: int | None = None) -> tuple[MetricEvent, ...]:
        if name is not None:
            name = _name(name)
        since_iso, until_iso = _check_window(since, until)
        bound = _check_limit(limit)
        with self._lock:
            events = tuple(self._events)
        selected = []
        for event in events:
            if name is not None and event.name != name:
                continue
            if since_iso is not None and event.timestamp < since_iso:
                continue
            if until_iso is not None and event.timestamp > until_iso:
                continue
            selected.append(event)
            if len(selected) >= bound:
                break
        return tuple(selected)

    def count(self, name: str | None = None) -> int:
        if name is not None:
            name = _name(name)
        with self._lock:
            if name is None:
                return len(self._events)
            return sum(1 for event in self._events if event.name == name)

    def export_json(self, name: str | None = None, since: datetime | None = None,
                    until: datetime | None = None, limit: int | None = None) -> str:
        return _export(_event_dict(event) for event in self.snapshot(name, since, until, limit))


class SQLiteEventLog:
    """Private SQLite append-only event log with bounded retention.

    The parent directory must already exist and be private. Attributes are
    persisted as bounded JSON; callers must not put secrets or sensitive
    personal data in them. Recording keeps only the newest ``max_events``
    events; ``prune_before`` and ``keep_last`` implement explicit retention.
    """

    def __init__(self, path: str, max_events: int = MAX_EVENTS) -> None:
        if (isinstance(max_events, bool) or not isinstance(max_events, int)
                or not 1 <= max_events <= MAX_RETAINED_EVENTS):
            raise ObservabilityValidationError("max_events must be between 1 and 1000000")
        if not isinstance(path, str) or not path or len(path) > 4096:
            raise ObservabilityValidationError("database path is invalid")
        absolute = os.path.abspath(path)
        parent = os.path.dirname(absolute)
        if not os.path.isdir(parent) or os.path.realpath(parent) != parent:
            raise ObservabilityValidationError("database parent must be an existing non-symlink directory")
        parent_stat = os.stat(parent, follow_symlinks=False)
        if not stat.S_ISDIR(parent_stat.st_mode):
            raise ObservabilityValidationError("database parent must be a directory")
        if os.name == "posix" and (
            parent_stat.st_uid != os.geteuid() or stat.S_IMODE(parent_stat.st_mode) & 0o077
        ):
            raise ObservabilityValidationError("database parent must be owned by the current user and private")
        if os.path.lexists(absolute):
            existing = os.lstat(absolute)
            if not stat.S_ISREG(existing.st_mode):
                raise ObservabilityValidationError("database path must be a regular non-symlink file")
            if os.name == "posix" and (existing.st_uid != os.geteuid() or existing.st_nlink != 1):
                raise ObservabilityValidationError("database file ownership or link count is unsafe")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(absolute, flags, 0o600)
        except OSError:
            raise ObservabilityValidationError("database file could not be opened safely") from None
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise ObservabilityValidationError("database path must be a regular file")
            if os.name == "posix":
                if opened.st_uid != os.geteuid() or opened.st_nlink != 1:
                    raise ObservabilityValidationError("database ownership or link count is unsafe")
                os.fchmod(descriptor, 0o600)
        finally:
            os.close(descriptor)
        self.path = absolute
        self.max_events = max_events
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        parent = os.path.dirname(self.path)
        if os.path.realpath(parent) != parent:
            raise ObservabilityValidationError("database parent path changed")
        parent_stat = os.stat(parent, follow_symlinks=False)
        if not stat.S_ISDIR(parent_stat.st_mode):
            raise ObservabilityValidationError("database parent changed")
        if os.name == "posix" and (
            parent_stat.st_uid != os.geteuid() or stat.S_IMODE(parent_stat.st_mode) & 0o077
        ):
            raise ObservabilityValidationError("database parent privacy changed")
        current = os.lstat(self.path)
        if not stat.S_ISREG(current.st_mode):
            raise ObservabilityValidationError("database path changed")
        if os.name == "posix" and (
            current.st_uid != os.geteuid() or stat.S_IMODE(current.st_mode) != 0o600
            or current.st_nlink != 1
        ):
            raise ObservabilityValidationError("database ownership, permissions, or link count changed")
        connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _initialize(self) -> None:
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("""CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    name TEXT NOT NULL,
                    value REAL NOT NULL,
                    attributes_json TEXT NOT NULL
                )""")
                connection.execute("CREATE INDEX IF NOT EXISTS events_name_idx ON events(name, event_id)")
                connection.execute("CREATE INDEX IF NOT EXISTS events_time_idx ON events(timestamp)")
            finally:
                connection.close()

    @staticmethod
    def _record(row: tuple[Any, ...]) -> MetricEvent:
        sequence, stamp, name, value, attributes_json = row
        name = _name(name)
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
            raise ObservabilityValidationError("persisted event sequence is corrupt")
        timestamp = _parse_time(stamp).isoformat()
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or abs(value) > MAX_ABS_VALUE):
            raise ObservabilityValidationError("persisted event value is corrupt")
        try:
            parsed = json.loads(attributes_json)
        except (TypeError, ValueError):
            raise ObservabilityValidationError("persisted attributes are corrupt") from None
        if not isinstance(parsed, dict):
            raise ObservabilityValidationError("persisted attributes are corrupt")
        return MetricEvent(sequence, name, timestamp, _value(value), parsed)

    def record(self, name: str, value: float = 1.0, attributes: Any = None,
               now: datetime | None = None) -> MetricEvent:
        name = _name(name)
        number = _value(value)
        attrs = _attributes(attributes)
        stamp = _iso(now or _now())
        encoded = json.dumps(
            attrs, ensure_ascii=False, allow_nan=False, sort_keys=True,
            separators=(",", ":"),
        )
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    "INSERT INTO events(timestamp,name,value,attributes_json) VALUES(?,?,?,?)",
                    (stamp, name, number, encoded),
                )
                sequence = int(cursor.lastrowid)
                connection.execute(
                    "DELETE FROM events WHERE event_id NOT IN "
                    "(SELECT event_id FROM events ORDER BY event_id DESC LIMIT ?)",
                    (self.max_events,),
                )
                connection.execute("COMMIT")
                return MetricEvent(sequence, name, stamp, number, attrs)
            except Exception:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                connection.close()

    def query(self, name: str | None = None, since: datetime | None = None,
              until: datetime | None = None, limit: int | None = None) -> tuple[MetricEvent, ...]:
        if name is not None:
            name = _name(name)
        since_iso, until_iso = _check_window(since, until)
        bound = _check_limit(limit)
        clauses = []
        params: list[Any] = []
        if name is not None:
            clauses.append("name=?")
            params.append(name)
        if since_iso is not None:
            clauses.append("timestamp>=?")
            params.append(since_iso)
        if until_iso is not None:
            clauses.append("timestamp<=?")
            params.append(until_iso)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(bound)
        with self._lock:
            connection = self._connect()
            try:
                rows = connection.execute(
                    "SELECT event_id,timestamp,name,value,attributes_json FROM events"
                    f"{where} ORDER BY event_id LIMIT ?",
                    params,
                ).fetchall()
                return tuple(self._record(row) for row in rows)
            finally:
                connection.close()

    def count(self, name: str | None = None) -> int:
        if name is not None:
            name = _name(name)
        with self._lock:
            connection = self._connect()
            try:
                if name is None:
                    row = connection.execute("SELECT COUNT(*) FROM events").fetchone()
                else:
                    row = connection.execute(
                        "SELECT COUNT(*) FROM events WHERE name=?", (name,)
                    ).fetchone()
                return int(row[0])
            finally:
                connection.close()

    def prune_before(self, now: datetime) -> int:
        stamp = _iso(now)
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    "DELETE FROM events WHERE timestamp<?", (stamp,)
                )
                deleted = cursor.rowcount
                connection.execute("COMMIT")
                return int(deleted)
            except Exception:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                connection.close()

    def keep_last(self, count: int) -> int:
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_RETAINED_EVENTS:
            raise ObservabilityValidationError("count must be between 1 and 1000000")
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    "DELETE FROM events WHERE event_id NOT IN "
                    "(SELECT event_id FROM events ORDER BY event_id DESC LIMIT ?)",
                    (count,),
                )
                deleted = cursor.rowcount
                connection.execute("COMMIT")
                return int(deleted)
            except Exception:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                connection.close()

    def export_json(self, name: str | None = None, since: datetime | None = None,
                    until: datetime | None = None, limit: int | None = None) -> str:
        return _export(_event_dict(event) for event in self.query(name, since, until, limit))

    def integrity_check(self) -> str:
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute("PRAGMA integrity_check").fetchone()
                return str(row[0]) if row else "no result"
            finally:
                connection.close()


class MetricRegistry:
    """Thread-safe bounded named counters and gauges with a deterministic snapshot.

    Names are validated and bounded in cardinality; counter totals and gauge
    values are bounded numbers. This registry keeps aggregates only; use an
    event log for individual events.
    """

    def __init__(self, max_names: int = MAX_NAMES) -> None:
        if (isinstance(max_names, bool) or not isinstance(max_names, int)
                or not 1 <= max_names <= MAX_NAMES):
            raise ObservabilityValidationError("max_names must be between 1 and 256")
        self._lock = threading.RLock()
        self._counters: dict[str, int] = {}
        self._gauges: dict[str, float] = {}
        self._max_names = max_names

    def counter(self, name: str, delta: int = 1) -> int:
        name = _name(name)
        if (isinstance(delta, bool) or not isinstance(delta, int)
                or not 0 <= delta <= 1_000_000_000):
            raise ObservabilityValidationError("counter delta must be between 0 and 1000000000")
        with self._lock:
            total = self._counters.get(name, 0) + delta
            if total > 2 ** 53:
                raise ObservabilityValidationError("counter total exceeds the bounded range")
            if name not in self._counters and (
                len(self._counters) + len(self._gauges) >= self._max_names
            ):
                raise ObservabilityValidationError("metric name cardinality exceeded")
            self._counters[name] = total
            return total

    def gauge(self, name: str, value: float) -> None:
        name = _name(name)
        number = _value(value)
        with self._lock:
            if name not in self._counters and name not in self._gauges:
                if len(self._counters) + len(self._gauges) >= self._max_names:
                    raise ObservabilityValidationError("metric name cardinality exceeded")
            self._gauges[name] = number

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "counters": dict(sorted(self._counters.items())),
                "gauges": dict(sorted(self._gauges.items())),
            }

    def export_json(self) -> str:
        return _export([self.snapshot()])
