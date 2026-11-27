"""Tool-call idempotency: at-most-once execution with safe retry.

This is the missing piece between a demo tool runtime and a production one.
Without it, a retried or duplicated model action (network retry, fallback
model, crash recovery, a replayed batch) re-invokes the side-effecting handler
and double-sends the email / double-charges the card / double-writes the row.

Design (Stripe-style):

* An idempotency key is a caller-supplied, bounded, opaque string. It is
  namespaced by ``principal_id`` so two principals never collide on a key.
* The key is bound to a *fingerprint* = ``tool_name:sha256(arguments)``. A
  replay with the same key but different tool/arguments is rejected
  (``IdempotencyConflictError``) instead of silently executing the wrong thing.
* A live, completed record replays the original outcome without touching the
  handler. A live *in-progress* record (a concurrent execution of the same key)
  blocks the newcomer with ``IdempotencyInProgressError`` so the caller can
  back off and retry — this is what makes execution genuinely at-most-once under
  concurrency, not just across retries.
* Records expire (default 24h) so key space is bounded and keys can be reused
  after the window.

Only *completed* outcomes with real side effects (success, handler failure,
rejected result) are memoized. Pre-handler denials (permission, budget, invalid
arguments) have no side effects and are simply re-derived on replay, which is
itself idempotent.

No cryptography, no new runtime dependencies. The SQLite store is a standalone
file independent of the audit store so it can be placed on the same durable
volume without coupling schemas.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

__all__ = [
    "IdempotencyConflictError",
    "IdempotencyInProgressError",
    "IdempotencyReplay",
    "IdempotencyRecord",
    "IdempotencyStore",
    "InMemoryIdempotencyStore",
    "SQLiteIdempotencyStore",
]

# Keys and principals are bounded; exceeding these is a validation error.
_MAX_KEY_LENGTH = 256
_MAX_PRINCIPAL_LENGTH = 256
_DEFAULT_TTL_SECONDS = 86_400  # 24h


class IdempotencyConflictError(Exception):
    """The idempotency key was reused for a different tool/argument fingerprint."""


class IdempotencyInProgressError(Exception):
    """Another execution with this key is currently in progress; back off and retry."""


class IdempotencyReplay(Exception):
    """Raised by the executor to hand a memoized outcome back to the bridge.

    ``status`` is ``"succeeded"`` for a cached success (``result`` holds the
    parsed payload) or the terminal failure status otherwise (``error_code``
    holds the original code so the caller can reproduce the failure).
    """

    def __init__(self, *, result: object, status: str, error_code: str | None = None) -> None:
        self.result = result
        self.status = status
        self.error_code = error_code
        super().__init__(f"idempotency replay: status={status} error_code={error_code!r}")


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    principal_id: str
    key: str
    fingerprint: str
    status: str  # "" while reserved/in-progress, else terminal status
    result_json: str  # "" for non-success
    error_code: str | None
    created_at: str  # ISO-8601 UTC
    expires_at: str  # ISO-8601 UTC


@runtime_checkable
class IdempotencyStore(Protocol):
    """Host-provided durable idempotency ledger.

    Implementations MUST make ``check_or_reserve`` and ``complete`` atomic with
    respect to the same ``(principal_id, key)`` so concurrent callers cannot
    both proceed to the handler.
    """

    def check_or_reserve(
        self,
        principal_id: str,
        key: str,
        fingerprint: str,
        now_epoch: float,
        ttl_seconds: int,
    ) -> IdempotencyRecord | None:
        """Atomically inspect or reserve ``key``.

        Returns a completed record (replay it), raises
        ``IdempotencyInProgressError`` if a concurrent execution is reserved, or
        returns ``None`` after reserving the key for this caller.
        """
        ...

    def complete(
        self,
        principal_id: str,
        key: str,
        status: str,
        result_json: str,
        error_code: str | None,
        now_epoch: float,
    ) -> None:
        """Mark a reserved key as completed with its terminal outcome."""
        ...


def _validate_key(key: str) -> None:
    if not isinstance(key, str) or not key or len(key) > _MAX_KEY_LENGTH:
        raise IdempotencyConflictError("idempotency key must be non-empty text of at most 256 chars")


def _validate_principal(principal_id: str) -> None:
    if (
        not isinstance(principal_id, str)
        or not principal_id
        or len(principal_id) > _MAX_PRINCIPAL_LENGTH
    ):
        raise IdempotencyConflictError("idempotency principal must be valid non-empty text")


def _iso(epoch: float) -> str:
    import datetime

    return (
        datetime.datetime.fromtimestamp(epoch, tz=datetime.timezone.utc)
        .isoformat()
    )


class InMemoryIdempotencyStore:
    """Thread-safe in-process store for tests, benchmarks, and single-process hosts."""

    def __init__(self, clock: object | None = None) -> None:
        # clock allows injection of a callable returning epoch seconds.
        self._clock = clock if callable(clock) else time.time
        self._lock = threading.Lock()
        self._rows: dict[tuple[str, str], IdempotencyRecord] = {}

    def check_or_reserve(
        self,
        principal_id: str,
        key: str,
        fingerprint: str,
        now_epoch: float,
        ttl_seconds: int,
    ) -> IdempotencyRecord | None:
        _validate_principal(principal_id)
        _validate_key(key)
        with self._lock:
            rec = self._rows.get((principal_id, key))
            if rec is not None:
                if now_epoch >= _epoch_from_iso(rec.expires_at):
                    # expired: reclaim the slot
                    del self._rows[(principal_id, key)]
                elif rec.status == "":
                    raise IdempotencyInProgressError(key)
                else:
                    return rec
            self._rows[(principal_id, key)] = IdempotencyRecord(
                principal_id=principal_id,
                key=key,
                fingerprint=fingerprint,
                status="",
                result_json="",
                error_code=None,
                created_at=_iso(now_epoch),
                expires_at=_iso(now_epoch + ttl_seconds),
            )
            return None

    def complete(
        self,
        principal_id: str,
        key: str,
        status: str,
        result_json: str,
        error_code: str | None,
        now_epoch: float,
    ) -> None:
        _validate_principal(principal_id)
        _validate_key(key)
        with self._lock:
            rec = self._rows.get((principal_id, key))
            if rec is None:
                # Defensive: record may have been reclaimed by expiry; recreate.
                self._rows[(principal_id, key)] = IdempotencyRecord(
                    principal_id=principal_id,
                    key=key,
                    fingerprint="",
                    status=status,
                    result_json=result_json,
                    error_code=error_code,
                    created_at=_iso(now_epoch),
                    expires_at=_iso(now_epoch + _DEFAULT_TTL_SECONDS),
                )
                return
            self._rows[(principal_id, key)] = IdempotencyRecord(
                principal_id=principal_id,
                key=key,
                fingerprint=rec.fingerprint,
                status=status,
                result_json=result_json,
                error_code=error_code,
                created_at=rec.created_at,
                expires_at=rec.expires_at,
            )


def _epoch_from_iso(value: str) -> float:
    import datetime

    return datetime.datetime.fromisoformat(value).timestamp()


class SQLiteIdempotencyStore:
    """Durable file-backed store. Serializes writers via ``BEGIN IMMEDIATE``."""

    def __init__(self, path: str, *, clock: object | None = None) -> None:
        if not isinstance(path, str) or not path:
            raise IdempotencyConflictError("idempotency store path must be a non-empty string")
        self._path = path
        self._clock = clock if callable(clock) else time.time
        self._lock = threading.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def _initialize(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS idempotency_records (
                    principal_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    error_code TEXT,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    PRIMARY KEY (principal_id, key)
                )
                """
            )
            conn.commit()

    def check_or_reserve(
        self,
        principal_id: str,
        key: str,
        fingerprint: str,
        now_epoch: float,
        ttl_seconds: int,
    ) -> IdempotencyRecord | None:
        _validate_principal(principal_id)
        _validate_key(key)
        now_iso = _iso(now_epoch)
        expires_iso = _iso(now_epoch + ttl_seconds)
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT principal_id, key, fingerprint, status, result_json, "
                    "error_code, created_at, expires_at FROM idempotency_records "
                    "WHERE principal_id = ? AND key = ?",
                    (principal_id, key),
                ).fetchone()
                if row is not None:
                    rec = IdempotencyRecord(*row)
                    if now_epoch >= _epoch_from_iso(rec.expires_at):
                        conn.execute(
                            "DELETE FROM idempotency_records WHERE principal_id = ? AND key = ?",
                            (principal_id, key),
                        )
                        conn.commit()
                    elif rec.status == "":
                        conn.rollback()
                        raise IdempotencyInProgressError(key)
                    else:
                        conn.rollback()
                        return rec
                conn.execute(
                    "INSERT INTO idempotency_records "
                    "(principal_id, key, fingerprint, status, result_json, error_code, "
                    "created_at, expires_at) VALUES (?, ?, ?, '', '', NULL, ?, ?)",
                    (principal_id, key, fingerprint, now_iso, expires_iso),
                )
                conn.commit()
                return None
            except Exception:
                conn.rollback()
                raise

    def complete(
        self,
        principal_id: str,
        key: str,
        status: str,
        result_json: str,
        error_code: str | None,
        now_epoch: float,
    ) -> None:
        _validate_principal(principal_id)
        _validate_key(key)
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    "UPDATE idempotency_records SET status = ?, result_json = ?, "
                    "error_code = ? WHERE principal_id = ? AND key = ?",
                    (status, result_json, error_code, principal_id, key),
                )
                if conn.total_changes == 0:
                    # Defensive recreate (e.g. reclaimed by expiry mid-flight).
                    conn.execute(
                        "INSERT OR REPLACE INTO idempotency_records "
                        "(principal_id, key, fingerprint, status, result_json, error_code, "
                        "created_at, expires_at) VALUES (?, ?, '', ?, ?, ?, ?, ?)",
                        (
                            principal_id,
                            key,
                            status,
                            result_json,
                            error_code,
                            _iso(now_epoch),
                            _iso(now_epoch + _DEFAULT_TTL_SECONDS),
                        ),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
