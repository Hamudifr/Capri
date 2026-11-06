"""User-controlled, non-sensitive durable project memory.

The store is provider-neutral and local-first. Host adapters may synchronize records
with external providers; credentials and provider clients are deliberately excluded.
Retrieved content is untrusted data and must never grant authority or tool permissions.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import stat
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

class MemoryErrorBase(Exception):
    """Base class for expected memory failures."""

class MemoryValidationError(MemoryErrorBase):
    """A memory record or query violates the bounded contract."""

class MemoryNotFoundError(MemoryErrorBase):
    """The requested memory record does not exist."""

class MemoryProvider(Protocol):
    """Provider adapter contract; implementations own credentials and transport."""
    def create(self, **fields: str) -> "MemoryRecord": ...
    def get(self, memory_id: str) -> "MemoryRecord": ...
    def search(self, query: str, *, limit: int = 20, offset: int = 0) -> tuple["MemoryRecord", ...]: ...
    def correct(self, memory_id: str, **changes: str) -> "MemoryRecord": ...
    def archive(self, memory_id: str) -> "MemoryRecord": ...
    def delete(self, memory_id: str) -> None: ...
    def export_json(self) -> str: ...
    def expire(self, *, now: datetime | None = None) -> tuple[str, ...]: ...

@dataclass(frozen=True, slots=True)
class MemoryRecord:
    memory_id: str
    title: str
    content: str
    record_type: str
    scope: str
    source: str
    confidence: str
    retention: str
    created_at: str
    updated_at: str
    expires_at: str | None = None
    status: str = "active"
    supersedes_id: str | None = None

_ALLOWED_TYPES = {"operating_directive", "architecture_decision", "project_fact", "security_boundary", "user_preference"}
_ALLOWED_CONFIDENCE = {"user_directed", "verified", "inferred", "unverified"}
_ALLOWED_RETENTION = {"keep", "expire_30d", "expire_90d", "archive_when_superseded"}
_MAX_TITLE = 200
_MAX_CONTENT = 20_000
_MAX_SOURCE = 2_048
_MAX_SCOPE = 100
_MAX_QUERY = 500
_MAX_RECORDS = 10_000
_SURROGATE = re.compile("[\\ud800-\\udfff]")

def _now() -> datetime:
    return datetime.now(timezone.utc)

def _iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise MemoryValidationError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()

def _validate_text(value: str, field: str, maximum: int, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()) or len(value) > maximum or _SURROGATE.search(value):
        raise MemoryValidationError(f"{field} must be valid bounded Unicode text")
    return value

def _validate_expiry(value: str | None) -> str | None:
    if value is None:
        return None
    _validate_text(value, "expires_at", 64)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise MemoryValidationError("expires_at must be an ISO-8601 timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MemoryValidationError("expires_at must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()

class SQLiteMemoryStore:
    """Private SQLite store for non-sensitive project memory.

    Records are bounded and explicitly non-sensitive. Corrections create a new
    record linked to the prior record; archive and delete are distinct operations.
    """

    def __init__(self, path: str) -> None:
        _validate_text(path, "database path", 4_096)
        absolute = os.path.abspath(path)
        parent = os.path.dirname(absolute)
        if not os.path.isdir(parent) or os.path.realpath(parent) != parent:
            raise MemoryValidationError("database parent must be an existing non-symlink directory")
        parent_stat = os.stat(parent, follow_symlinks=False)
        if not stat.S_ISDIR(parent_stat.st_mode):
            raise MemoryValidationError("database parent must be a directory")
        if os.name == "posix" and (parent_stat.st_uid != os.geteuid() or stat.S_IMODE(parent_stat.st_mode) & 0o077):
            raise MemoryValidationError("database parent must be owned by the current user and private")
        if os.path.lexists(absolute):
            info = os.lstat(absolute)
            if not stat.S_ISREG(info.st_mode):
                raise MemoryValidationError("database path must be a regular non-symlink file")
            if os.name == "posix" and (info.st_uid != os.geteuid() or info.st_nlink != 1):
                raise MemoryValidationError("database file ownership or link count is unsafe")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(absolute, flags, 0o600)
        except OSError:
            raise MemoryValidationError("database could not be opened safely") from None
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise MemoryValidationError("database descriptor is not a regular file")
            if os.name == "posix":
                if info.st_uid != os.geteuid() or info.st_nlink != 1:
                    raise MemoryValidationError("database descriptor ownership or link count is unsafe")
                os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        self.path = absolute
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        parent = os.path.dirname(self.path)
        if os.path.realpath(parent) != parent:
            raise MemoryValidationError("database parent path changed")
        parent_stat = os.stat(parent, follow_symlinks=False)
        if os.name == "posix" and (parent_stat.st_uid != os.geteuid() or stat.S_IMODE(parent_stat.st_mode) & 0o077):
            raise MemoryValidationError("database parent ownership or privacy changed")
        info = os.lstat(self.path)
        if not stat.S_ISREG(info.st_mode):
            raise MemoryValidationError("database path changed to a non-regular file")
        if os.name == "posix" and (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
            raise MemoryValidationError("database ownership, permissions, or link count changed")
        connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _initialize(self) -> None:
        with self._lock:
            db = self._connect()
            try:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("""CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY, title TEXT NOT NULL, content TEXT NOT NULL,
                    record_type TEXT NOT NULL, scope TEXT NOT NULL, source TEXT NOT NULL,
                    confidence TEXT NOT NULL, retention TEXT NOT NULL, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, expires_at TEXT, status TEXT NOT NULL,
                    supersedes_id TEXT REFERENCES memories(memory_id)
                )""")
                db.execute("CREATE INDEX IF NOT EXISTS memories_status_expiry ON memories(status, expires_at)")
                db.execute("CREATE INDEX IF NOT EXISTS memories_supersedes ON memories(supersedes_id)")
                db.execute("""CREATE TABLE IF NOT EXISTS memory_events (
                    event_id TEXT PRIMARY KEY, memory_id TEXT NOT NULL, event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL
                )""")
            finally:
                db.close()

    @staticmethod
    def _record(row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord(**dict(row))

    def create(
        self, *, title: str, content: str, record_type: str, scope: str,
        source: str, confidence: str, retention: str = "keep",
        expires_at: str | None = None,
    ) -> MemoryRecord:
        _validate_text(title, "title", _MAX_TITLE)
        _validate_text(content, "content", _MAX_CONTENT)
        _validate_text(scope, "scope", _MAX_SCOPE)
        _validate_text(source, "source", _MAX_SOURCE)
        if not isinstance(record_type, str) or record_type not in _ALLOWED_TYPES:
            raise MemoryValidationError("unsupported record_type")
        if not isinstance(confidence, str) or confidence not in _ALLOWED_CONFIDENCE:
            raise MemoryValidationError("unsupported confidence")
        if not isinstance(retention, str) or retention not in _ALLOWED_RETENTION:
            raise MemoryValidationError("unsupported retention")
        expiry = _validate_expiry(expires_at)
        if retention in {"expire_30d", "expire_90d"} and expiry is None:
            raise MemoryValidationError("expiring retention requires expires_at")
        now = _iso(_now())
        record = MemoryRecord(str(uuid4()), title, content, record_type, scope, source,
                              confidence, retention, now, now, expiry)
        with self._lock:
            db = self._connect()
            try:
                db.execute("BEGIN IMMEDIATE")
                count = db.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
                if count >= _MAX_RECORDS:
                    raise MemoryValidationError("memory record capacity reached")
                db.execute("INSERT INTO memories VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           tuple(asdict(record).values()))
                self._event(db, record.memory_id, "created", now)
                db.execute("COMMIT")
            except Exception:
                try:
                    db.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                db.close()
        return record

    @staticmethod
    def _event(db: sqlite3.Connection, memory_id: str, event_type: str, timestamp: str) -> None:
        db.execute("INSERT INTO memory_events VALUES (?, ?, ?, ?)",
                   (str(uuid4()), memory_id, event_type, timestamp))

    def get(self, memory_id: str) -> MemoryRecord:
        _validate_text(memory_id, "memory_id", 64)
        with self._lock:
            db = self._connect()
            try:
                row = db.execute("SELECT * FROM memories WHERE memory_id=?", (memory_id,)).fetchone()
                if row is None:
                    raise MemoryNotFoundError("memory record not found")
                return self._record(row)
            finally:
                db.close()

    def search(self, query: str, *, limit: int = 20, offset: int = 0) -> tuple[MemoryRecord, ...]:
        _validate_text(query, "query", _MAX_QUERY)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise MemoryValidationError("limit must be between 1 and 100")
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= _MAX_RECORDS:
            raise MemoryValidationError("offset is outside the supported range")
        terms = tuple(dict.fromkeys(part.casefold() for part in query.split() if part))
        if not terms:
            raise MemoryValidationError("query must contain at least one search term")
        now = _iso(_now())
        with self._lock:
            db = self._connect()
            try:
                rows = db.execute(
                    "SELECT * FROM memories WHERE status IN ('active','review') AND (expires_at IS NULL OR expires_at > ?)",
                    (now,),
                ).fetchall()
                ranked = []
                for row in rows:
                    haystack = (row["title"] + "\n" + row["content"] + "\n" + row["scope"]).casefold()
                    matched = sum(term in haystack for term in terms)
                    if matched == len(terms):
                        exact = int(row["title"].casefold() == query.casefold())
                        ranked.append((exact, matched, row["updated_at"], self._record(row)))
                ranked.sort(key=lambda item: (-item[0], -item[1], item[2], item[3].memory_id))
                return tuple(item[3] for item in ranked[offset:offset + limit])
            finally:
                db.close()

    def correct(self, memory_id: str, **changes: str) -> MemoryRecord:
        allowed = {"title", "content", "record_type", "scope", "source", "confidence", "retention", "expires_at"}
        if not changes or set(changes) - allowed:
            raise MemoryValidationError("correction must contain only supported fields")
        old = self.get(memory_id)
        values = {key: getattr(old, key) for key in allowed}
        values.update(changes)
        _validate_text(values["title"], "title", _MAX_TITLE)
        _validate_text(values["content"], "content", _MAX_CONTENT)
        _validate_text(values["scope"], "scope", _MAX_SCOPE)
        _validate_text(values["source"], "source", _MAX_SOURCE)
        if not isinstance(values["record_type"], str) or values["record_type"] not in _ALLOWED_TYPES:
            raise MemoryValidationError("unsupported record_type")
        if not isinstance(values["confidence"], str) or values["confidence"] not in _ALLOWED_CONFIDENCE:
            raise MemoryValidationError("unsupported confidence")
        if not isinstance(values["retention"], str) or values["retention"] not in _ALLOWED_RETENTION:
            raise MemoryValidationError("unsupported retention")
        expiry = _validate_expiry(values["expires_at"])
        if values["retention"] in {"expire_30d", "expire_90d"} and expiry is None:
            raise MemoryValidationError("expiring retention requires expires_at")
        now = _iso(_now())
        corrected = MemoryRecord(
            str(uuid4()), values["title"], values["content"], values["record_type"],
            values["scope"], values["source"], values["confidence"], values["retention"],
            now, now, expiry, "active", memory_id,
        )
        with self._lock:
            db = self._connect()
            try:
                db.execute("BEGIN IMMEDIATE")
                current = db.execute("SELECT status FROM memories WHERE memory_id=?", (memory_id,)).fetchone()
                if current is None:
                    raise MemoryNotFoundError("memory record not found")
                count = db.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
                if count >= _MAX_RECORDS:
                    raise MemoryValidationError("memory record capacity reached")
                db.execute(
                    "INSERT INTO memories VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    tuple(asdict(corrected).values()),
                )
                db.execute("UPDATE memories SET status='archived', updated_at=? WHERE memory_id=?",
                           (now, memory_id))
                self._event(db, memory_id, "superseded", now)
                self._event(db, corrected.memory_id, "correction_created", now)
                db.execute("COMMIT")
            except Exception:
                try:
                    db.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                db.close()
        return self.get(corrected.memory_id)

    def archive(self, memory_id: str) -> MemoryRecord:
        _validate_text(memory_id, "memory_id", 64)
        now = _iso(_now())
        with self._lock:
            db = self._connect()
            try:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT 1 FROM memories WHERE memory_id=?", (memory_id,)).fetchone()
                if row is None:
                    raise MemoryNotFoundError("memory record not found")
                db.execute("UPDATE memories SET status='archived', updated_at=? WHERE memory_id=?",
                           (now, memory_id))
                self._event(db, memory_id, "archived", now)
                db.execute("COMMIT")
            except Exception:
                try:
                    db.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                db.close()
        return self.get(memory_id)

    def delete(self, memory_id: str) -> None:
        _validate_text(memory_id, "memory_id", 64)
        now = _iso(_now())
        with self._lock:
            db = self._connect()
            try:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT 1 FROM memories WHERE memory_id=?", (memory_id,)).fetchone()
                if row is None:
                    raise MemoryNotFoundError("memory record not found")
                db.execute("DELETE FROM memories WHERE memory_id=?", (memory_id,))
                self._event(db, memory_id, "deleted", now)
                db.execute("COMMIT")
            except Exception:
                try:
                    db.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                db.close()

    def expire(self, *, now: datetime | None = None) -> tuple[str, ...]:
        instant = _iso(now or _now())
        with self._lock:
            db = self._connect()
            try:
                db.execute("BEGIN IMMEDIATE")
                rows = db.execute(
                    "SELECT memory_id FROM memories WHERE status IN ('active','review') AND expires_at IS NOT NULL AND expires_at <= ? ORDER BY memory_id",
                    (instant,),
                ).fetchall()
                ids = tuple(row["memory_id"] for row in rows)
                db.executemany("UPDATE memories SET status='archived', updated_at=? WHERE memory_id=?",
                               ((instant, item) for item in ids))
                for item in ids:
                    self._event(db, item, "expired", instant)
                db.execute("COMMIT")
                return ids
            except Exception:
                try: db.execute("ROLLBACK")
                except sqlite3.Error: pass
                raise
            finally:
                db.close()

    def export_json(self) -> str:
        with self._lock:
            db = self._connect()
            try:
                rows = db.execute("SELECT * FROM memories ORDER BY created_at, memory_id").fetchall()
                payload = [asdict(self._record(row)) for row in rows]
                return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            finally:
                db.close()

    def events(self, memory_id: str) -> tuple[tuple[str, str], ...]:
        _validate_text(memory_id, "memory_id", 64)
        with self._lock:
            db = self._connect()
            try:
                rows = db.execute(
                    "SELECT event_type, occurred_at FROM memory_events WHERE memory_id=? ORDER BY rowid",
                    (memory_id,),
                ).fetchall()
                return tuple((row["event_type"], row["occurred_at"]) for row in rows)
            finally:
                db.close()
