"""Append-only, principal-scoped outcome journal with explicit corrections.

Outcome records are durable observations, not instructions or tool permissions.
Corrections append a new record and preserve the original as historical evidence.
"""
from __future__ import annotations

import os
import sqlite3
import stat
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from capri_core.validation import contains_surrogate

from .sqlite_backup import backup_sqlite_database


class OutcomeError(Exception):
    """Base class for expected outcome-journal failures."""


class OutcomeNotFoundError(OutcomeError):
    """The requested outcome does not exist for this principal."""


class OutcomeConflictError(OutcomeError):
    """An outcome cannot be corrected in its current state."""


class OutcomeIdempotencyConflict(OutcomeError):
    """An idempotency key was reused with a different payload."""


class OutcomeValidationError(OutcomeError):
    """An outcome record or query violates the bounded contract."""


_ALLOWED_SUBJECTS = frozenset({"goal", "task", "workflow", "decision", "system"})
_ALLOWED_TYPES = frozenset({"execution", "verification", "user_feedback", "operational", "decision"})
_ALLOWED_STATUSES = frozenset({"succeeded", "partial", "failed", "uncertain", "observation"})
_ALLOWED_SOURCES = frozenset({
    "user_report", "host_observation", "tool_result", "verification",
    "system_reconciliation", "user_correction",
})
_ALLOWED_CONFIDENCE = frozenset({"high", "medium", "low", "unverified"})
_MAX_RECORDS = 100_000


def _text(value: object, label: str, maximum: int, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if type(value) is not str or not value or value != value.strip():
        raise OutcomeValidationError(f"{label} must be a non-empty plain string")
    if contains_surrogate(value) or len(value.encode("utf-8")) > maximum:
        raise OutcomeValidationError(f"{label} exceeds its bound or contains invalid Unicode")
    return value


def _timestamp(value: object, *, label: str = "timestamp") -> str:
    if type(value) is not str:
        raise OutcomeValidationError(f"{label} must be a timezone-aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise OutcomeValidationError(f"{label} must be a timezone-aware ISO timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise OutcomeValidationError(f"{label} must be timezone-aware")
    return parsed.astimezone(timezone.utc).isoformat()


def _stamp(now: datetime | None) -> str:
    if now is None:
        return datetime.now(timezone.utc).isoformat()
    if type(now) is not datetime or now.tzinfo is None or now.utcoffset() is None:
        raise OutcomeValidationError("now must be a timezone-aware datetime")
    return now.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class OutcomeRecord:
    outcome_id: str
    principal_id: str
    subject_type: str
    subject_id: str
    outcome_type: str
    status: str
    summary: str
    source_type: str
    source_reference: str | None
    confidence: str
    recorded_at: str
    idempotency_key: str | None = None
    supersedes_id: str | None = None
    correction_reason: str | None = None


class SQLiteOutcomeStore:
    """Private SQLite outcome journal; updates and deletes are prohibited."""

    def __init__(self, path: str) -> None:
        _text(path, "database path", 4096)
        absolute = os.path.abspath(path)
        parent = os.path.dirname(absolute)
        if not os.path.isdir(parent) or os.path.realpath(parent) != parent:
            raise OutcomeValidationError("database parent must be an existing non-symlink directory")
        parent_stat = os.stat(parent, follow_symlinks=False)
        if not stat.S_ISDIR(parent_stat.st_mode):
            raise OutcomeValidationError("database parent must be a directory")
        if os.name == "posix" and (
            parent_stat.st_uid != os.geteuid() or stat.S_IMODE(parent_stat.st_mode) & 0o077
        ):
            raise OutcomeValidationError("database parent must be owned by the current user and private")
        if os.path.lexists(absolute):
            existing = os.lstat(absolute)
            if not stat.S_ISREG(existing.st_mode):
                raise OutcomeValidationError("database path must be a regular non-symlink file")
            if os.name == "posix" and (existing.st_uid != os.geteuid() or existing.st_nlink != 1):
                raise OutcomeValidationError("database file ownership or link count is unsafe")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(absolute, flags, 0o600)
        except OSError:
            raise OutcomeValidationError("database could not be opened safely") from None
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise OutcomeValidationError("database descriptor is not a regular file")
            if os.name == "posix":
                if info.st_uid != os.geteuid() or info.st_nlink != 1:
                    raise OutcomeValidationError("database descriptor ownership or link count is unsafe")
                os.fchmod(descriptor, 0o600)
        finally:
            os.close(descriptor)
        self.path = absolute
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        parent = os.path.dirname(self.path)
        if os.path.realpath(parent) != parent:
            raise OutcomeValidationError("database parent path changed")
        if os.name == "posix":
            parent_stat = os.stat(parent, follow_symlinks=False)
            if (not stat.S_ISDIR(parent_stat.st_mode)
                    or parent_stat.st_uid != os.geteuid()
                    or stat.S_IMODE(parent_stat.st_mode) & 0o077):
                raise OutcomeValidationError("database parent ownership or privacy changed")
            info = os.lstat(self.path)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600):
                raise OutcomeValidationError("database file identity or permissions changed")
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA recursive_triggers=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("""CREATE TABLE IF NOT EXISTS outcomes (
                    outcome_id TEXT PRIMARY KEY,
                    principal_id TEXT NOT NULL,
                    subject_type TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    outcome_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_reference TEXT,
                    confidence TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    idempotency_key TEXT,
                    supersedes_id TEXT REFERENCES outcomes(outcome_id) ON DELETE RESTRICT,
                    correction_reason TEXT,
                    UNIQUE(principal_id, idempotency_key)
                )""")
                connection.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS outcomes_single_successor "
                    "ON outcomes(supersedes_id) WHERE supersedes_id IS NOT NULL"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS outcomes_subject_order "
                    "ON outcomes(principal_id, subject_type, subject_id, recorded_at, outcome_id)"
                )
                connection.execute("""CREATE TRIGGER IF NOT EXISTS outcomes_immutable_update
                    BEFORE UPDATE ON outcomes
                    BEGIN SELECT RAISE(ABORT, 'outcome records are append-only'); END""")
                connection.execute("""CREATE TRIGGER IF NOT EXISTS outcomes_immutable_delete
                    BEFORE DELETE ON outcomes
                    BEGIN SELECT RAISE(ABORT, 'outcome records are append-only'); END""")
            finally:
                connection.close()

    @staticmethod
    def _record(row: sqlite3.Row) -> OutcomeRecord:
        record = OutcomeRecord(**dict(row))
        _text(record.outcome_id, "outcome_id", 64)
        _text(record.principal_id, "principal_id", 128)
        _text(record.subject_id, "subject_id", 128)
        _text(record.summary, "summary", 2000)
        if record.subject_type not in _ALLOWED_SUBJECTS:
            raise OutcomeValidationError("stored subject_type is invalid")
        if record.outcome_type not in _ALLOWED_TYPES:
            raise OutcomeValidationError("stored outcome_type is invalid")
        if record.status not in _ALLOWED_STATUSES:
            raise OutcomeValidationError("stored status is invalid")
        if record.source_type not in _ALLOWED_SOURCES:
            raise OutcomeValidationError("stored source_type is invalid")
        if record.confidence not in _ALLOWED_CONFIDENCE:
            raise OutcomeValidationError("stored confidence is invalid")
        if record.source_reference is not None:
            _text(record.source_reference, "source_reference", 512)
        if record.idempotency_key is not None:
            _text(record.idempotency_key, "idempotency_key", 128)
        if record.supersedes_id is not None:
            _text(record.supersedes_id, "supersedes_id", 64)
        if record.correction_reason is not None:
            _text(record.correction_reason, "correction_reason", 1000)
        _timestamp(record.recorded_at, label="recorded_at")
        if (record.source_type == "user_correction") != (record.supersedes_id is not None):
            raise OutcomeValidationError("stored correction lineage is inconsistent")
        if (record.supersedes_id is None) != (record.correction_reason is None):
            raise OutcomeValidationError("stored correction reason is inconsistent")
        return record

    @staticmethod
    def _validate_payload(
        principal_id: object, subject_type: object, subject_id: object,
        outcome_type: object, status: object, summary: object,
        source_type: object, source_reference: object, confidence: object,
        idempotency_key: object,
    ) -> tuple[str, ...]:
        principal = _text(principal_id, "principal_id", 128)
        subject = _text(subject_id, "subject_id", 128)
        summary_text = _text(summary, "summary", 2000)
        if type(subject_type) is not str or subject_type not in _ALLOWED_SUBJECTS:
            raise OutcomeValidationError("unsupported subject_type")
        if type(outcome_type) is not str or outcome_type not in _ALLOWED_TYPES:
            raise OutcomeValidationError("unsupported outcome_type")
        if type(status) is not str or status not in _ALLOWED_STATUSES:
            raise OutcomeValidationError("unsupported status")
        if type(source_type) is not str or source_type not in _ALLOWED_SOURCES:
            raise OutcomeValidationError("unsupported source_type")
        if type(confidence) is not str or confidence not in _ALLOWED_CONFIDENCE:
            raise OutcomeValidationError("unsupported confidence")
        reference = _text(source_reference, "source_reference", 512, optional=True)
        key = _text(idempotency_key, "idempotency_key", 128, optional=True)
        return (
            principal, subject_type, subject, outcome_type, status, summary_text,
            source_type, reference, confidence, key,
        )

    @staticmethod
    def _same_payload(record: OutcomeRecord, values: tuple[str, ...]) -> bool:
        return (
            record.principal_id, record.subject_type, record.subject_id,
            record.outcome_type, record.status, record.summary, record.source_type,
            record.source_reference, record.confidence, record.idempotency_key,
        ) == values

    def _existing_idempotent(
        self, connection: sqlite3.Connection, principal_id: str,
        idempotency_key: str | None, values: tuple[str, ...],
    ) -> OutcomeRecord | None:
        if idempotency_key is None:
            return None
        row = connection.execute(
            "SELECT * FROM outcomes WHERE principal_id=? AND idempotency_key=?",
            (principal_id, idempotency_key),
        ).fetchone()
        if row is None:
            return None
        existing = self._record(row)
        if not self._same_payload(existing, values):
            raise OutcomeIdempotencyConflict("idempotency key was already used for another outcome")
        return existing

    def append_for_principal(
        self, principal_id: str, *, subject_type: str, subject_id: str,
        outcome_type: str, status: str, summary: str, source_type: str,
        source_reference: str | None = None, confidence: str = "unverified",
        idempotency_key: str | None = None, now: datetime | None = None,
    ) -> OutcomeRecord:
        values = self._validate_payload(
            principal_id, subject_type, subject_id, outcome_type, status, summary,
            source_type, source_reference, confidence, idempotency_key,
        )
        if source_type == "user_correction":
            raise OutcomeValidationError("corrections must use correct_for_principal")
        stamp = _stamp(now)
        record = OutcomeRecord(
            str(uuid4()), *values[:9], stamp, values[9], None, None,
        )
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                existing = self._existing_idempotent(
                    connection, record.principal_id, record.idempotency_key, values,
                )
                if existing is not None:
                    connection.execute("COMMIT")
                    return existing
                count = connection.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0]
                if count >= _MAX_RECORDS:
                    raise OutcomeValidationError("outcome journal capacity reached")
                connection.execute(
                    """INSERT INTO outcomes (
                        outcome_id,principal_id,subject_type,subject_id,outcome_type,status,
                        summary,source_type,source_reference,confidence,recorded_at,
                        idempotency_key,supersedes_id,correction_reason
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    tuple(record.__getattribute__(field) for field in (
                        "outcome_id","principal_id","subject_type","subject_id","outcome_type",
                        "status","summary","source_type","source_reference","confidence",
                        "recorded_at","idempotency_key","supersedes_id","correction_reason",
                    )),
                )
                connection.execute("COMMIT")
            except Exception:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                connection.close()
        return record

    def correct_for_principal(
        self, principal_id: str, outcome_id: str, *, status: str, summary: str,
        reason: str, source_reference: str | None = None,
        confidence: str = "unverified", idempotency_key: str | None = None,
        now: datetime | None = None,
    ) -> OutcomeRecord:
        principal = _text(principal_id, "principal_id", 128)
        target_id = _text(outcome_id, "outcome_id", 64)
        reason_text = _text(reason, "correction reason", 1000)
        stamp = _stamp(now)
        if type(status) is not str or status not in _ALLOWED_STATUSES:
            raise OutcomeValidationError("unsupported status")
        _text(summary, "summary", 2000)
        _text(source_reference, "source_reference", 512, optional=True)
        if type(confidence) is not str or confidence not in _ALLOWED_CONFIDENCE:
            raise OutcomeValidationError("unsupported confidence")
        if idempotency_key is not None:
            _text(idempotency_key, "idempotency_key", 128)
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                if idempotency_key is not None:
                    key = _text(idempotency_key, "idempotency_key", 128)
                    prior = connection.execute(
                        "SELECT * FROM outcomes WHERE principal_id=? AND idempotency_key=?",
                        (principal, key),
                    ).fetchone()
                    if prior is not None:
                        existing = self._record(prior)
                        if (existing.supersedes_id == target_id
                                and existing.status == status and existing.summary == summary
                                and existing.correction_reason == reason_text
                                and existing.source_reference == source_reference
                                and existing.confidence == confidence):
                            connection.execute("COMMIT")
                            return existing
                        raise OutcomeIdempotencyConflict("idempotency key was already used for another outcome")
                row = connection.execute(
                    "SELECT * FROM outcomes WHERE outcome_id=? AND principal_id=?",
                    (target_id, principal),
                ).fetchone()
                if row is None:
                    raise OutcomeNotFoundError("outcome does not exist")
                original = self._record(row)
                if connection.execute(
                    "SELECT 1 FROM outcomes WHERE supersedes_id=?", (target_id,)
                ).fetchone():
                    raise OutcomeConflictError("outcome has already been superseded")
                values = self._validate_payload(
                    principal, original.subject_type, original.subject_id,
                    original.outcome_type, status, summary, "user_correction",
                    source_reference, confidence, idempotency_key,
                )
                count = connection.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0]
                if count >= _MAX_RECORDS:
                    raise OutcomeValidationError("outcome journal capacity reached")
                corrected = OutcomeRecord(
                    str(uuid4()), *values[:9], stamp, values[9], target_id, reason_text,
                )
                connection.execute(
                    """INSERT INTO outcomes (
                        outcome_id,principal_id,subject_type,subject_id,outcome_type,status,
                        summary,source_type,source_reference,confidence,recorded_at,
                        idempotency_key,supersedes_id,correction_reason
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    tuple(getattr(corrected, field) for field in (
                        "outcome_id","principal_id","subject_type","subject_id","outcome_type",
                        "status","summary","source_type","source_reference","confidence",
                        "recorded_at","idempotency_key","supersedes_id","correction_reason",
                    )),
                )
                connection.execute("COMMIT")
                return corrected
            except Exception:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                connection.close()

    def get_for_principal(self, outcome_id: str, principal_id: str) -> OutcomeRecord:
        _text(outcome_id, "outcome_id", 64)
        _text(principal_id, "principal_id", 128)
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute(
                    "SELECT * FROM outcomes WHERE outcome_id=? AND principal_id=?",
                    (outcome_id, principal_id),
                ).fetchone()
                if row is None:
                    raise OutcomeNotFoundError("outcome does not exist")
                return self._record(row)
            finally:
                connection.close()

    def list_for_principal(
        self, principal_id: str, *, subject_type: str | None = None,
        subject_id: str | None = None, include_superseded: bool = False,
        limit: int = 50, offset: int = 0,
    ) -> tuple[OutcomeRecord, ...]:
        _text(principal_id, "principal_id", 128)
        if subject_type is not None and (
            type(subject_type) is not str or subject_type not in _ALLOWED_SUBJECTS
        ):
            raise OutcomeValidationError("unsupported subject_type")
        if subject_id is not None:
            _text(subject_id, "subject_id", 128)
        if type(include_superseded) is not bool:
            raise OutcomeValidationError("include_superseded must be a boolean")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise OutcomeValidationError("limit must be between 1 and 100")
        if type(offset) is not int or not 0 <= offset <= _MAX_RECORDS:
            raise OutcomeValidationError("offset is outside the supported range")
        clauses = ["o.principal_id=?"]
        parameters: list[object] = [principal_id]
        if subject_type is not None:
            clauses.append("o.subject_type=?")
            parameters.append(subject_type)
        if subject_id is not None:
            clauses.append("o.subject_id=?")
            parameters.append(subject_id)
        if not include_superseded:
            clauses.append("NOT EXISTS (SELECT 1 FROM outcomes child WHERE child.supersedes_id=o.outcome_id)")
        parameters.extend((limit, offset))
        query = (
            "SELECT o.* FROM outcomes o WHERE " + " AND ".join(clauses)
            + " ORDER BY o.recorded_at DESC,o.outcome_id DESC LIMIT ? OFFSET ?"
        )
        with self._lock:
            connection = self._connect()
            try:
                rows = connection.execute(query, parameters).fetchall()
                return tuple(self._record(row) for row in rows)
            finally:
                connection.close()

    @staticmethod
    def _validate_backup_snapshot(connection: sqlite3.Connection) -> None:
        connection.row_factory = sqlite3.Row
        rows = connection.execute("SELECT * FROM outcomes ORDER BY recorded_at,outcome_id").fetchall()
        if len(rows) > _MAX_RECORDS:
            raise OutcomeValidationError("outcome backup exceeds journal capacity")
        records = {row["outcome_id"]: SQLiteOutcomeStore._record(row) for row in rows}
        successors: set[str] = set()
        for record in records.values():
            if record.supersedes_id is None:
                continue
            prior = records.get(record.supersedes_id)
            if prior is None:
                raise OutcomeValidationError("outcome backup has missing correction ancestry")
            if (prior.principal_id != record.principal_id
                    or prior.subject_type != record.subject_type
                    or prior.subject_id != record.subject_id
                    or prior.outcome_type != record.outcome_type):
                raise OutcomeValidationError("outcome backup has mismatched correction ancestry")
            if record.supersedes_id in successors:
                raise OutcomeValidationError("outcome backup has competing corrections")
            successors.add(record.supersedes_id)
        for record in records.values():
            seen: set[str] = set()
            current = record
            while current.supersedes_id is not None:
                if current.outcome_id in seen:
                    raise OutcomeValidationError("outcome backup contains a correction cycle")
                seen.add(current.outcome_id)
                current = records[current.supersedes_id]

    def integrity_check(self) -> str:
        with self._lock:
            connection = self._connect()
            try:
                integrity = connection.execute("PRAGMA integrity_check").fetchone()
                foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
                if not integrity or integrity[0] != "ok":
                    return "integrity check failed"
                if foreign_key_errors:
                    return "foreign key check failed"
                try:
                    self._validate_backup_snapshot(connection)
                except OutcomeValidationError:
                    return "outcome journal validation failed"
                return "ok"
            finally:
                connection.close()

    def backup_to(self, destination_path: str) -> str:
        return backup_sqlite_database(
            self.path, destination_path, lock=self._lock, connect=self._connect,
            validate_snapshot=self._validate_backup_snapshot,
            error_type=OutcomeValidationError, prefix=".capri-outcomes-backup-",
        )
