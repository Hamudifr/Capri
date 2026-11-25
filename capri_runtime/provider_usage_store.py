"""Append-only, privacy-minimized provider usage telemetry for Capri hosts."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from .orchestration import ProviderUsage
from .tasks import SQLiteTaskStore


_PROVIDER_RE = re.compile(r"^[a-z][a-z0-9._-]{0,31}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TABLE = "provider_usage_events"
_COLUMNS = {
    "provider", "response_id", "principal_id", "session_id", "model",
    "input_tokens", "output_tokens", "total_tokens", "cached_input_tokens",
    "cache_write_tokens", "reasoning_tokens", "provider_latency_ms",
    "recorded_at", "event_sha256",
}


class ProviderUsageJournalError(Exception):
    """Provider usage could not be safely recorded or read."""


class ProviderUsageConflictError(ProviderUsageJournalError):
    """A provider response ID was reused with different immutable usage data."""


@dataclass(frozen=True, slots=True)
class ProviderUsageRecord:
    principal_id: str
    session_id: str
    usage: ProviderUsage
    recorded_at: str
    event_sha256: str


@dataclass(frozen=True, slots=True)
class ProviderUsageAggregate:
    provider: str
    model: str
    requests: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cached_input_tokens: int
    cache_write_tokens: int
    reasoning_tokens: int
    average_latency_ms: float | None


def _safe_text(value: object, name: str, maximum: int = 128) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > maximum
        or value != value.strip()
        or any(ord(char) < 0x20 or 0xD800 <= ord(char) <= 0xDFFF for char in value)
    ):
        raise ProviderUsageJournalError(f"{name} is invalid")
    return value


def _canonical(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    )


def _event_payload(
    principal_id: str, session_id: str, usage: ProviderUsage, recorded_at: str,
) -> dict[str, object]:
    return {
        "event_schema": "capri.provider-usage-event.v1",
        "recorded_at": recorded_at,
        "provider": usage.provider,
        "response_id": usage.response_id,
        "principal_id": principal_id,
        "session_id": session_id,
        "model": usage.model,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
        "cached_input_tokens": usage.cached_input_tokens,
        "cache_write_tokens": usage.cache_write_tokens,
        "reasoning_tokens": usage.reasoning_tokens,
        "provider_latency_ms": usage.provider_latency_ms,
    }


def _event_digest(
    principal_id: str, session_id: str, usage: ProviderUsage, recorded_at: str,
) -> str:
    return hashlib.sha256(
        _canonical(_event_payload(principal_id, session_id, usage, recorded_at)).encode("utf-8")
    ).hexdigest()


def _validate_recorded_at(value: object) -> str:
    timestamp = _safe_text(value, "recorded_at", 64)
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        raise ProviderUsageJournalError("provider usage timestamp is invalid") from None
    if (
        parsed.tzinfo is None or parsed.utcoffset() is None
        or parsed.astimezone(timezone.utc).isoformat() != timestamp
    ):
        raise ProviderUsageJournalError("provider usage timestamp is invalid")
    return timestamp


def _validate_provider_usage_identity(
    principal_id: object, session_id: object, usage: object,
) -> tuple[str, str, ProviderUsage]:
    principal = _safe_text(principal_id, "principal_id")
    session = _safe_text(session_id, "session_id")
    if type(usage) is not ProviderUsage:
        raise ProviderUsageJournalError("usage must be a validated ProviderUsage record")
    if not _PROVIDER_RE.fullmatch(_safe_text(usage.provider, "provider", 32)):
        raise ProviderUsageJournalError("provider identifier is invalid")
    _safe_text(usage.model, "model", 128)
    _safe_text(usage.response_id, "response_id", 128)
    return principal, session, usage


def _utc_timestamp(value: object) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ProviderUsageJournalError("clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc).isoformat()


class SQLiteProviderUsageJournal:
    """Append-only provider usage store sharing a private SQLiteTaskStore database.

    record_usage(session_id, principal_id, usage) is directly compatible with
    ToolOrchestrator's host-owned usage_observer callback.
    """

    def __init__(
        self,
        task_store: SQLiteTaskStore,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if type(task_store) is not SQLiteTaskStore:
            raise ProviderUsageJournalError("task_store must be a SQLiteTaskStore")
        if clock is not None and not callable(clock):
            raise ProviderUsageJournalError("clock must be callable")
        self._tasks = task_store
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._initialize()
        with self._tasks._lock:
            connection = self._tasks._connect()
            try:
                validate_provider_usage_snapshot(connection)
            except Exception:
                raise ProviderUsageJournalError(
                    "provider usage journal failed integrity validation"
                ) from None
            finally:
                connection.close()

    def _initialize(self) -> None:
        with self._tasks._lock:
            connection = self._tasks._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS provider_usage_events (
                        provider TEXT NOT NULL,
                        response_id TEXT NOT NULL,
                        principal_id TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        model TEXT NOT NULL,
                        input_tokens INTEGER NOT NULL CHECK(input_tokens >= 0),
                        output_tokens INTEGER NOT NULL CHECK(output_tokens >= 0),
                        total_tokens INTEGER NOT NULL CHECK(total_tokens = input_tokens + output_tokens),
                        cached_input_tokens INTEGER NOT NULL CHECK(cached_input_tokens >= 0),
                        cache_write_tokens INTEGER NOT NULL CHECK(cache_write_tokens >= 0),
                        reasoning_tokens INTEGER NOT NULL CHECK(reasoning_tokens >= 0),
                        provider_latency_ms INTEGER CHECK(
                            provider_latency_ms IS NULL OR provider_latency_ms BETWEEN 0 AND 600000
                        ),
                        recorded_at TEXT NOT NULL,
                        event_sha256 TEXT NOT NULL,
                        PRIMARY KEY(provider, response_id),
                        CHECK(cached_input_tokens + cache_write_tokens <= input_tokens),
                        CHECK(reasoning_tokens <= output_tokens)
                    )"""
                )
                connection.execute(
                    """CREATE INDEX IF NOT EXISTS provider_usage_owner_session_idx
                    ON provider_usage_events(principal_id, session_id, recorded_at)"""
                )
                connection.execute(
                    """CREATE TRIGGER IF NOT EXISTS provider_usage_immutable_update
                    BEFORE UPDATE ON provider_usage_events
                    BEGIN SELECT RAISE(ABORT, 'provider usage events are append-only'); END"""
                )
                connection.execute(
                    """CREATE TRIGGER IF NOT EXISTS provider_usage_immutable_delete
                    BEFORE DELETE ON provider_usage_events
                    BEGIN SELECT RAISE(ABORT, 'provider usage events are append-only'); END"""
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise ProviderUsageJournalError("provider usage journal initialization failed") from None
            finally:
                connection.close()

    def record_usage(
        self, session_id: str, principal_id: str, usage: ProviderUsage,
    ) -> None:
        """Persist one provider response; safe for direct use as usage_observer."""
        principal, session, validated = _validate_provider_usage_identity(
            principal_id, session_id, usage,
        )
        recorded_at = _utc_timestamp(self._clock())
        digest = _event_digest(principal, session, validated, recorded_at)
        values = (
            validated.provider, validated.response_id, principal, session,
            validated.model, validated.input_tokens, validated.output_tokens,
            validated.total_tokens, validated.cached_input_tokens,
            validated.cache_write_tokens, validated.reasoning_tokens,
            validated.provider_latency_ms, recorded_at, digest,
        )
        with self._tasks._lock:
            connection = self._tasks._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    """INSERT OR IGNORE INTO provider_usage_events (
                        provider,response_id,principal_id,session_id,model,
                        input_tokens,output_tokens,total_tokens,cached_input_tokens,
                        cache_write_tokens,reasoning_tokens,provider_latency_ms,
                        recorded_at,event_sha256
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    values,
                )
                if cursor.rowcount == 0:
                    existing = connection.execute(
                        """SELECT principal_id,session_id,model,input_tokens,output_tokens,
                        total_tokens,cached_input_tokens,cache_write_tokens,reasoning_tokens,
                        provider_latency_ms,recorded_at,event_sha256
                        FROM provider_usage_events WHERE provider=? AND response_id=?""",
                        (validated.provider, validated.response_id),
                    ).fetchone()
                    expected = (
                        principal, session, validated.model, validated.input_tokens,
                        validated.output_tokens, validated.total_tokens,
                        validated.cached_input_tokens, validated.cache_write_tokens,
                        validated.reasoning_tokens, validated.provider_latency_ms,
                    )
                    if existing is None or tuple(existing[:10]) != expected:
                        raise ProviderUsageConflictError(
                            "provider response ID conflicts with an existing immutable usage record"
                        )
                    existing_timestamp = _validate_recorded_at(existing[10])
                    if _event_digest(principal, session, validated, existing_timestamp) != existing[11]:
                        raise ProviderUsageJournalError(
                            "existing provider usage record integrity check failed"
                        )
                connection.commit()
            except ProviderUsageConflictError:
                connection.rollback()
                raise
            except Exception:
                connection.rollback()
                raise ProviderUsageJournalError("provider usage record could not be persisted") from None
            finally:
                connection.close()

    def usage_for_session(
        self, principal_id: str, session_id: str,
    ) -> tuple[ProviderUsageRecord, ...]:
        principal = _safe_text(principal_id, "principal_id")
        session = _safe_text(session_id, "session_id")
        with self._tasks._lock:
            connection = self._tasks._connect()
            try:
                rows = connection.execute(
                    """SELECT provider,response_id,model,input_tokens,output_tokens,total_tokens,
                    cached_input_tokens,cache_write_tokens,reasoning_tokens,provider_latency_ms,
                    recorded_at,event_sha256
                    FROM provider_usage_events
                    WHERE principal_id=? AND session_id=?
                    ORDER BY recorded_at,provider,response_id""",
                    (principal, session),
                ).fetchall()
            finally:
                connection.close()
        records: list[ProviderUsageRecord] = []
        for row in rows:
            usage = ProviderUsage(
                provider=row[0], model=row[2], response_id=row[1],
                input_tokens=row[3], output_tokens=row[4], total_tokens=row[5],
                cached_input_tokens=row[6], cache_write_tokens=row[7],
                reasoning_tokens=row[8], provider_latency_ms=row[9],
            )
            timestamp = _validate_recorded_at(row[10])
            if _event_digest(principal, session, usage, timestamp) != row[11]:
                raise ProviderUsageJournalError("provider usage record integrity check failed")
            records.append(ProviderUsageRecord(principal, session, usage, timestamp, row[11]))
        return tuple(records)

    def summary_for_principal(
        self, principal_id: str,
    ) -> tuple[ProviderUsageAggregate, ...]:
        principal = _safe_text(principal_id, "principal_id")
        with self._tasks._lock:
            connection = self._tasks._connect()
            try:
                rows = connection.execute(
                    """SELECT provider,model,COUNT(*),SUM(input_tokens),SUM(output_tokens),
                    SUM(total_tokens),SUM(cached_input_tokens),SUM(cache_write_tokens),
                    SUM(reasoning_tokens),AVG(provider_latency_ms)
                    FROM provider_usage_events WHERE principal_id=?
                    GROUP BY provider,model ORDER BY provider,model""",
                    (principal,),
                ).fetchall()
            finally:
                connection.close()
        return tuple(
            ProviderUsageAggregate(
                provider=row[0], model=row[1], requests=row[2],
                input_tokens=row[3], output_tokens=row[4], total_tokens=row[5],
                cached_input_tokens=row[6], cache_write_tokens=row[7],
                reasoning_tokens=row[8],
                average_latency_ms=None if row[9] is None else float(row[9]),
            )
            for row in rows
        )


def validate_provider_usage_snapshot(connection: sqlite3.Connection) -> None:
    """Validate the optional provider usage journal during task-store backup/integrity checks."""
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='provider_usage_events'"
    ).fetchone()
    if table is None:
        return
    column_info = connection.execute("PRAGMA table_info(provider_usage_events)").fetchall()
    columns = {row[1] for row in column_info}
    if columns != _COLUMNS:
        raise ProviderUsageJournalError("provider usage journal schema is invalid")
    column_map = {row[1]: row for row in column_info}
    expected_types = {
        "provider": "TEXT", "response_id": "TEXT", "principal_id": "TEXT",
        "session_id": "TEXT", "model": "TEXT", "input_tokens": "INTEGER",
        "output_tokens": "INTEGER", "total_tokens": "INTEGER",
        "cached_input_tokens": "INTEGER", "cache_write_tokens": "INTEGER",
        "reasoning_tokens": "INTEGER", "provider_latency_ms": "INTEGER",
        "recorded_at": "TEXT", "event_sha256": "TEXT",
    }
    if any(column_map[name][2].upper() != kind for name, kind in expected_types.items()):
        raise ProviderUsageJournalError("provider usage journal column types are invalid")
    if any(column_map[name][3] != 1 for name in _COLUMNS - {"provider_latency_ms"}):
        raise ProviderUsageJournalError("provider usage journal required columns are nullable")
    if column_map["provider_latency_ms"][3] != 0:
        raise ProviderUsageJournalError("provider usage latency must remain nullable")
    primary_key = [row[1] for row in sorted(
        (row for row in column_info if row[5]), key=lambda item: item[5],
    )]
    if primary_key != ["provider", "response_id"]:
        raise ProviderUsageJournalError("provider usage journal primary key is invalid")
    triggers = {
        row[0]: re.sub(r"\s+", " ", (row[1] or "")).strip().upper()
        for row in connection.execute(
            "SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='provider_usage_events'"
        ).fetchall()
    }
    update_expected = (
        "BEFORE UPDATE ON PROVIDER_USAGE_EVENTS BEGIN SELECT RAISE(ABORT, "
        "'PROVIDER USAGE EVENTS ARE APPEND-ONLY'); END"
    )
    delete_expected = (
        "BEFORE DELETE ON PROVIDER_USAGE_EVENTS BEGIN SELECT RAISE(ABORT, "
        "'PROVIDER USAGE EVENTS ARE APPEND-ONLY'); END"
    )
    if (
        update_expected not in triggers.get("provider_usage_immutable_update", "")
        or delete_expected not in triggers.get("provider_usage_immutable_delete", "")
    ):
        raise ProviderUsageJournalError("provider usage append-only protections are missing")
    index_found = False
    for index in connection.execute("PRAGMA index_list(provider_usage_events)").fetchall():
        if index[2] != 0 or index[4] != 0:
            continue
        name = str(index[1]).replace('"', '""')
        indexed = [
            row[2] for row in connection.execute(f'PRAGMA index_info("{name}")').fetchall()
        ]
        if indexed == ["principal_id", "session_id", "recorded_at"]:
            index_found = True
            break
    if not index_found:
        raise ProviderUsageJournalError("provider usage owner/session index is missing")
    rows = connection.execute(
        """SELECT provider,response_id,principal_id,session_id,model,input_tokens,
        output_tokens,total_tokens,cached_input_tokens,cache_write_tokens,reasoning_tokens,
        provider_latency_ms,recorded_at,event_sha256 FROM provider_usage_events"""
    )
    for row in rows:
        principal, session = _safe_text(row[2], "principal_id"), _safe_text(row[3], "session_id")
        usage = ProviderUsage(
            provider=row[0], model=row[4], response_id=row[1],
            input_tokens=row[5], output_tokens=row[6], total_tokens=row[7],
            cached_input_tokens=row[8], cache_write_tokens=row[9],
            reasoning_tokens=row[10], provider_latency_ms=row[11],
        )
        if not _PROVIDER_RE.fullmatch(_safe_text(usage.provider, "provider", 32)):
            raise ProviderUsageJournalError("provider identifier is invalid")
        _safe_text(usage.model, "model", 128)
        _safe_text(usage.response_id, "response_id", 128)
        timestamp = _validate_recorded_at(row[12])
        if type(row[13]) is not str or not _SHA256_RE.fullmatch(row[13]):
            raise ProviderUsageJournalError("provider usage event digest is invalid")
        if _event_digest(principal, session, usage, timestamp) != row[13]:
            raise ProviderUsageJournalError("provider usage event digest does not match")
