"""Private SQLite-backed audit, approval replay, and challenge storage.

Approval challenge records contain bounded identity/operation metadata and signed
grant material. Raw tool arguments, results, prompts, credentials, and transcripts
are not stored. The database is private but not encrypted at rest.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import threading
import tempfile
from datetime import datetime, timezone
from uuid import uuid4
from typing import Any

from capri_core.validation import contains_surrogate

from .atomic_publish import publish_no_replace
from .tools import ApprovalGrant, ApprovalStore, AuditEvent, AuditSink, ToolValidationError

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_NAME_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_OPERATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def _valid_text(value: object, limit: int) -> bool:
    return (
        isinstance(value, str) and 0 < len(value) <= limit
        and not contains_surrogate(value)
    )


def _aware_timestamp(value: object) -> datetime | None:
    if not _valid_text(value, 64):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed



_AUDIT_CHAIN_DOMAIN = b"capri:security-store:lifecycle-audit:v1\0"
_AUDIT_CHAIN_ZERO = "0" * 64
_AUDIT_CHAIN_COLUMNS = {"sequence", "previous_hash", "event_hash"}


def _audit_chain_payload(sequence: int, fields: tuple[Any, ...]) -> str:
    (
        event_id, timestamp, principal_id, tool_name, argument_digest, status,
        error_code, resource_type, resource_id, task_id, metadata_json,
    ) = fields
    payload = {
        "sequence": sequence,
        "event_id": event_id,
        "timestamp": timestamp,
        "principal_id": principal_id,
        "event_type": tool_name,
        "argument_digest": argument_digest,
        "status": status,
        "error_code": error_code,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "task_id": task_id,
        "metadata_sha256": (
            hashlib.sha256(metadata_json.encode("utf-8")).hexdigest()
            if isinstance(metadata_json, str) else None
        ),
    }
    try:
        return json.dumps(
            payload, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        )
    except (TypeError, ValueError, UnicodeError):
        raise ToolValidationError("audit event cannot be encoded for lifecycle chaining") from None


def _audit_chain_hash(previous_hash: str, payload_json: str) -> str:
    if not isinstance(previous_hash, str) or not _DIGEST_RE.fullmatch(previous_hash):
        raise ToolValidationError("lifecycle audit chain predecessor is invalid")
    return hashlib.sha256(
        _AUDIT_CHAIN_DOMAIN
        + bytes.fromhex(previous_hash)
        + payload_json.encode("utf-8")
    ).hexdigest()


def _append_audit_event(connection: sqlite3.Connection, fields: tuple[Any, ...]) -> None:
    """Append the audit row and its chain position inside the caller's transaction."""
    state = connection.execute(
        """SELECT schema_version, last_sequence, head_hash
        FROM audit_chain_state WHERE singleton_id = 1"""
    ).fetchone()
    if (
        state is None or state[0] != 1 or type(state[1]) is not int
        or state[1] < 0 or not isinstance(state[2], str)
        or not _DIGEST_RE.fullmatch(state[2])
    ):
        raise ToolValidationError("lifecycle audit chain state is invalid")
    sequence = state[1] + 1
    previous_hash = state[2]
    payload_json = _audit_chain_payload(sequence, fields)
    event_hash = _audit_chain_hash(previous_hash, payload_json)
    connection.execute(
        """INSERT INTO audit_events
        (event_id, timestamp, principal_id, tool_name, argument_digest, status,
         error_code, resource_type, resource_id, task_id, metadata_json,
         sequence, previous_hash, event_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (*fields, sequence, previous_hash, event_hash),
    )
    cursor = connection.execute(
        """UPDATE audit_chain_state
        SET last_sequence = ?, head_hash = ?
        WHERE singleton_id = 1 AND schema_version = 1 AND last_sequence = ?
          AND head_hash = ?""",
        (sequence, event_hash, state[1], previous_hash),
    )
    if cursor.rowcount != 1:
        raise ToolValidationError("lifecycle audit chain head changed during append")


def _validate_audit_chain(connection: sqlite3.Connection) -> None:
    """Verify one-to-one event coverage, sequence continuity, and the rolling digest."""
    objects = {
        row[0]: row[1] for row in connection.execute(
            "SELECT name, type FROM sqlite_master WHERE name IN "
            "('audit_chain_state', 'audit_events_sequence_unique', "
            "'audit_events_immutable_update', 'audit_events_immutable_delete')"
        )
    }
    if objects.get("audit_chain_state") != "table":
        raise ToolValidationError("security store is missing lifecycle audit chain state")
    if objects.get("audit_events_sequence_unique") != "index":
        raise ToolValidationError("security store is missing the lifecycle audit sequence index")
    if (
        objects.get("audit_events_immutable_update") != "trigger"
        or objects.get("audit_events_immutable_delete") != "trigger"
    ):
        raise ToolValidationError("security store is missing immutable audit event triggers")
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(audit_events)")
    }
    if not _AUDIT_CHAIN_COLUMNS.issubset(columns):
        raise ToolValidationError("security store is missing lifecycle audit chain columns")
    state_rows = connection.execute(
        """SELECT singleton_id, schema_version, last_sequence, head_hash
        FROM audit_chain_state ORDER BY singleton_id"""
    ).fetchall()
    if (
        len(state_rows) != 1 or state_rows[0][0] != 1 or state_rows[0][1] != 1
        or type(state_rows[0][2]) is not int or state_rows[0][2] < 0
        or not isinstance(state_rows[0][3], str)
        or not _DIGEST_RE.fullmatch(state_rows[0][3])
    ):
        raise ToolValidationError("security store lifecycle audit chain state is malformed")
    expected_sequence = 0
    previous_hash = _AUDIT_CHAIN_ZERO
    rows = connection.execute(
        """SELECT event_id, timestamp, principal_id, tool_name, argument_digest,
        status, error_code, resource_type, resource_id, task_id, metadata_json,
        sequence, previous_hash, event_hash
        FROM audit_events ORDER BY sequence"""
    )
    for row in rows:
        fields = tuple(row[:11])
        sequence, stored_previous, stored_hash = row[11:]
        expected_sequence += 1
        if (
            type(sequence) is not int or sequence != expected_sequence
            or stored_previous != previous_hash
            or not isinstance(stored_hash, str) or not _DIGEST_RE.fullmatch(stored_hash)
        ):
            raise ToolValidationError("security store lifecycle audit sequence is discontinuous")
        payload_json = _audit_chain_payload(sequence, fields)
        calculated = _audit_chain_hash(previous_hash, payload_json)
        if calculated != stored_hash:
            raise ToolValidationError("security store lifecycle audit chain digest mismatch")
        previous_hash = stored_hash
    state = state_rows[0]
    if state[2] != expected_sequence or state[3] != previous_hash:
        raise ToolValidationError("security store lifecycle audit chain head does not match its events")


def _migrate_lifecycle_audit_chain(connection: sqlite3.Connection) -> None:
    """One-time local consistency-chain bootstrap for pre-chain audit databases."""
    state_object = connection.execute(
        "SELECT type FROM sqlite_master WHERE name='audit_chain_state'"
    ).fetchone()
    if state_object is not None and state_object[0] != "table":
        raise ToolValidationError("security store lifecycle audit state object is invalid")
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(audit_events)")
    }
    present = columns & _AUDIT_CHAIN_COLUMNS
    if state_object is not None:
        if present != _AUDIT_CHAIN_COLUMNS:
            raise ToolValidationError("security store lifecycle audit chain schema is incomplete")
        return
    if present:
        raise ToolValidationError("security store lifecycle audit chain state is missing")
    connection.execute("ALTER TABLE audit_events ADD COLUMN sequence INTEGER")
    connection.execute("ALTER TABLE audit_events ADD COLUMN previous_hash TEXT")
    connection.execute("ALTER TABLE audit_events ADD COLUMN event_hash TEXT")
    connection.execute(
        """CREATE TABLE audit_chain_state (
            singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
            schema_version INTEGER NOT NULL CHECK(schema_version = 1),
            last_sequence INTEGER NOT NULL CHECK(last_sequence >= 0),
            head_hash TEXT NOT NULL
        )"""
    )
    connection.execute(
        """INSERT INTO audit_chain_state
        (singleton_id, schema_version, last_sequence, head_hash)
        VALUES (1, 1, 0, ?)""",
        (_AUDIT_CHAIN_ZERO,),
    )
    sequence = 0
    previous_hash = _AUDIT_CHAIN_ZERO
    rows = connection.execute(
        """SELECT rowid, event_id, timestamp, principal_id, tool_name,
        argument_digest, status, error_code, resource_type, resource_id,
        task_id, metadata_json FROM audit_events ORDER BY rowid"""
    ).fetchall()
    for row in rows:
        sequence += 1
        fields = tuple(row[1:])
        payload_json = _audit_chain_payload(sequence, fields)
        event_hash = _audit_chain_hash(previous_hash, payload_json)
        connection.execute(
            """UPDATE audit_events
            SET sequence = ?, previous_hash = ?, event_hash = ?
            WHERE rowid = ?""",
            (sequence, previous_hash, event_hash, row[0]),
        )
        previous_hash = event_hash
    connection.execute(
        """UPDATE audit_chain_state SET last_sequence = ?, head_hash = ?
        WHERE singleton_id = 1""",
        (sequence, previous_hash),
    )
    connection.execute(
        "CREATE UNIQUE INDEX audit_events_sequence_unique ON audit_events(sequence)"
    )


def _validate_backup_semantics(connection: sqlite3.Connection) -> None:
    """Reject logically malformed security rows even when SQLite is structurally sound."""
    audit_rows = connection.execute(
        """SELECT event_id, timestamp, principal_id, tool_name,
        argument_digest, status, error_code, resource_type, resource_id,
        task_id, metadata_json FROM audit_events"""
    ).fetchall()
    for (
        event_id, timestamp, principal_id, tool_name, digest, status, error_code,
        resource_type, resource_id, task_id, metadata_json,
    ) in audit_rows:
        if not all((
            _valid_text(event_id, 64), _valid_text(timestamp, 64),
            _valid_text(principal_id, 256), _valid_text(tool_name, 64),
            _valid_text(status, 64),
            isinstance(digest, str) and _DIGEST_RE.fullmatch(digest),
            error_code is None or (
                isinstance(error_code, str) and len(error_code) <= 128
                and not contains_surrogate(error_code)
            ),
        )):
            raise ToolValidationError("security backup contains an invalid audit event")
        resource_fields = (resource_type, resource_id, task_id)
        if metadata_json is None:
            if any(value is not None for value in resource_fields):
                raise ToolValidationError("security backup contains incomplete audit resource metadata")
        else:
            if not all((
                _valid_text(resource_type, 64), _valid_text(resource_id, 256),
                task_id is None or _valid_text(task_id, 128),
                _valid_text(metadata_json, 16_384),
                len(metadata_json.encode("utf-8")) <= 16_384,
            )):
                raise ToolValidationError("security backup contains invalid audit resource metadata")
            try:
                metadata = json.loads(metadata_json)
                canonical_metadata = json.dumps(
                    metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
                )
            except (TypeError, ValueError, json.JSONDecodeError):
                raise ToolValidationError("security backup contains invalid audit metadata JSON") from None
            if (
                not isinstance(metadata, dict)
                or canonical_metadata != metadata_json
                or hashlib.sha256(metadata_json.encode("utf-8")).hexdigest() != digest
            ):
                raise ToolValidationError("security backup contains an invalid audit metadata digest")

    _validate_audit_chain(connection)

    approval_rows = connection.execute(
        """SELECT grant_id, principal_id, tool_name, argument_digest,
        expires_at, consumed_at FROM consumed_approvals"""
    ).fetchall()
    for grant_id, principal_id, tool_name, digest, expires_at, consumed_at in approval_rows:
        expiry = _aware_timestamp(expires_at)
        consumed = _aware_timestamp(consumed_at)
        if not all((
            _valid_text(grant_id, 128), _valid_text(principal_id, 256),
            _valid_text(tool_name, 64) and _NAME_RE.fullmatch(tool_name),
            isinstance(digest, str) and _DIGEST_RE.fullmatch(digest),
            expiry is not None, consumed is not None,
            expiry is not None and consumed is not None and expiry > consumed,
        )):
            raise ToolValidationError("security backup contains an invalid approval replay record")
    _validate_approval_challenges(connection)


def _validate_approval_challenges(connection: sqlite3.Connection) -> None:
    """Validate optional challenge state included in the shared security database."""
    object_row = connection.execute(
        "SELECT type FROM sqlite_master WHERE name='approval_challenges'"
    ).fetchone()
    if object_row is None:
        return
    if object_row[0] != "table":
        raise ToolValidationError(
            "security backup contains an invalid approval challenge object"
        )
    try:
        rows = connection.execute(
            """SELECT challenge_id, operation_id, principal_id, tool_name,
            argument_digest, created_at, expires_at, status, approver_id, grant_json
            FROM approval_challenges"""
        )
    except sqlite3.Error:
        raise ToolValidationError(
            "security backup contains an invalid approval challenge table"
        ) from None

    challenge_ids: set[str] = set()
    operation_ids: set[str] = set()
    grant_ids: set[str] = set()
    allowed_grant_keys = {
        "grant_id", "principal_id", "tool_name", "argument_digest",
        "expires_at", "signature", "key_id", "operation_id",
    }
    required_grant_keys = allowed_grant_keys - {"operation_id"}

    for (challenge_id, operation_id, principal_id, tool_name, digest,
         created_at, expires_at, status, approver_id, grant_json) in rows:
        created = _aware_timestamp(created_at)
        expiry = _aware_timestamp(expires_at)
        if not all((
            _valid_text(challenge_id, 64),
            _valid_text(operation_id, 128) and _OPERATION_RE.fullmatch(operation_id),
            _valid_text(principal_id, 256) and principal_id.strip(),
            _valid_text(tool_name, 64) and _NAME_RE.fullmatch(tool_name),
            isinstance(digest, str) and _DIGEST_RE.fullmatch(digest),
            created is not None, expiry is not None,
            created is not None and expiry is not None and expiry > created,
            status in {"pending", "approved", "rejected", "expired"},
            approver_id is None or (
                _valid_text(approver_id, 256) and approver_id.strip()
            ),
            challenge_id not in challenge_ids,
            operation_id not in operation_ids,
        )):
            raise ToolValidationError(
                "security backup contains an invalid approval challenge"
            )
        challenge_ids.add(challenge_id)
        operation_ids.add(operation_id)

        if status != "approved":
            if grant_json is not None:
                raise ToolValidationError(
                    "security backup contains a grant on a non-approved challenge"
                )
            continue

        if not (_valid_text(approver_id, 256) and approver_id.strip()
                and _valid_text(grant_json, 2048)):
            raise ToolValidationError(
                "security backup contains an incomplete approved challenge"
            )
        try:
            grant = json.loads(grant_json)
        except (TypeError, ValueError, json.JSONDecodeError):
            raise ToolValidationError(
                "security backup contains invalid approval grant JSON"
            ) from None
        if not isinstance(grant, dict) or not required_grant_keys.issubset(grant) or set(grant) - allowed_grant_keys:
            raise ToolValidationError(
                "security backup contains an invalid approval grant shape"
            )
        grant_expiry = _aware_timestamp(grant.get("expires_at"))
        grant_id = grant.get("grant_id")
        key_id = grant.get("key_id")
        if not all((
            _valid_text(grant_id, 128),
            grant_id not in grant_ids,
            grant.get("principal_id") == principal_id,
            grant.get("tool_name") == tool_name,
            grant.get("argument_digest") == digest,
            grant_expiry is not None,
            created is not None and grant_expiry is not None and grant_expiry > created,
            isinstance(grant.get("signature"), str)
                and _DIGEST_RE.fullmatch(grant["signature"]),
            key_id is None or _valid_text(key_id, 128),
            "operation_id" not in grant or (
                _valid_text(grant["operation_id"], 128)
                and grant["operation_id"] == operation_id
            ),
        )):
            raise ToolValidationError(
                "security backup contains a mismatched approval grant"
            )
        grant_ids.add(grant_id)

    worker_state_rows = connection.execute(
        "SELECT singleton_id, pending_operations FROM worker_audit_state"
    ).fetchall()
    if (
        len(worker_state_rows) != 1
        or worker_state_rows[0][0] != 1
        or type(worker_state_rows[0][1]) is not int
        or worker_state_rows[0][1] < 0
    ):
        raise ToolValidationError("security backup contains invalid worker audit state")


def _decode_audit_metadata(metadata_json: str | None, digest: str | None) -> dict[str, Any] | None:
    if not isinstance(metadata_json, str) or not isinstance(digest, str):
        return None
    if not _DIGEST_RE.fullmatch(digest):
        return None
    try:
        metadata = json.loads(metadata_json)
        canonical = json.dumps(
            metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if (
        not isinstance(metadata, dict)
        or canonical != metadata_json
        or hashlib.sha256(metadata_json.encode("utf-8")).hexdigest() != digest
    ):
        return None
    return metadata


def _outstanding_worker_reservations(connection: sqlite3.Connection) -> int:
    rows = connection.execute(
        """SELECT tool_name, argument_digest, metadata_json
        FROM audit_events ORDER BY rowid"""
    ).fetchall()
    last_ack = -1
    for index, (event_type, digest, metadata_json) in enumerate(rows):
        if event_type == "worker.reconciliation.acknowledged":
            if _decode_audit_metadata(metadata_json, digest) is None:
                return 1
            last_ack = index
    states: dict[str, str] = {}
    closed_events = {
        "worker.reservation.released",
        "worker.reservation.denied",
        "worker.reservation.commit_missing",
        "worker.reservation.commit_rejected",
        "worker.reservation.release_missing",
        "worker.reservation.collision_released",
        "worker.reservation.expired",
        "worker.reservation.revoked",
    }
    for event_type, digest, metadata_json in rows[last_ack + 1:]:
        if not isinstance(event_type, str) or not event_type.startswith("worker.reservation."):
            continue
        metadata = _decode_audit_metadata(metadata_json, digest)
        if metadata is None:
            return 1
        token_hash = metadata.get("reservation_token_sha256")
        if not isinstance(token_hash, str) or len(token_hash) != 64:
            return 1
        if event_type == "worker.reservation.created":
            states[token_hash] = "pending"
        elif event_type == "worker.reservation.committed":
            states[token_hash] = "committed"
        elif event_type in closed_events:
            states[token_hash] = "closed"
    return sum(state in {"pending", "committed"} for state in states.values())


class SQLiteSecurityStore(AuditSink, ApprovalStore):
    """Durable, cross-process audit sink and one-use approval replay store.

    The database must live in an existing private directory. On POSIX the directory
    must be owned by the current user and have no group/other permission bits; the
    database file is forced to mode 0600. SQLite WAL transactions coordinate writers.
    """

    def __init__(self, path: str) -> None:
        if not isinstance(path, str) or not path.strip():
            raise ToolValidationError("database path must be a non-empty string")
        absolute = os.path.abspath(path)
        parent = os.path.dirname(absolute)
        if not os.path.isdir(parent):
            raise ToolValidationError("database parent directory must already exist")
        if os.path.realpath(parent) != parent:
            raise ToolValidationError("database parent path must not traverse symlinks")
        parent_stat = os.stat(parent, follow_symlinks=False)
        if not stat.S_ISDIR(parent_stat.st_mode):
            raise ToolValidationError("database parent must be a directory")
        if os.name == "posix":
            if parent_stat.st_uid != os.geteuid():
                raise ToolValidationError("database parent must be owned by the current user")
            if stat.S_IMODE(parent_stat.st_mode) & 0o077:
                raise ToolValidationError("database parent directory must be private (0700 or stricter)")

        if os.path.lexists(absolute):
            existing = os.lstat(absolute)
            if not stat.S_ISREG(existing.st_mode):
                raise ToolValidationError("database path must be a regular non-symlink file")
            if os.name == "posix" and existing.st_uid != os.geteuid():
                raise ToolValidationError("database file must be owned by the current user")
            if os.name == "posix" and existing.st_nlink != 1:
                raise ToolValidationError("database file must not have hard-link aliases")

        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(absolute, flags, 0o600)
        except OSError:
            raise ToolValidationError("database file could not be opened safely") from None
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise ToolValidationError("database path must be a regular file")
            if os.name == "posix":
                if opened.st_uid != os.geteuid():
                    raise ToolValidationError("database file must be owned by the current user")
                if opened.st_nlink != 1:
                    raise ToolValidationError("database file must not have hard-link aliases")
                os.fchmod(descriptor, 0o600)
        finally:
            os.close(descriptor)

        self.path = absolute
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        parent = os.path.dirname(self.path)
        if os.path.realpath(parent) != parent:
            raise ToolValidationError("database parent path changed to traverse a symlink")
        parent_stat = os.stat(parent, follow_symlinks=False)
        if not stat.S_ISDIR(parent_stat.st_mode):
            raise ToolValidationError("database parent changed to a non-directory")
        if os.name == "posix":
            if parent_stat.st_uid != os.geteuid() or stat.S_IMODE(parent_stat.st_mode) & 0o077:
                raise ToolValidationError("database parent ownership or privacy changed")
        current = os.lstat(self.path)
        if not stat.S_ISREG(current.st_mode):
            raise ToolValidationError("database file changed to a non-regular path")
        if os.name == "posix":
            if current.st_uid != os.geteuid() or stat.S_IMODE(current.st_mode) != 0o600 or current.st_nlink != 1:
                raise ToolValidationError("database ownership, link count, or permissions changed")
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
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS audit_events (
                        event_id TEXT PRIMARY KEY,
                        timestamp TEXT NOT NULL,
                        principal_id TEXT NOT NULL,
                        tool_name TEXT NOT NULL,
                        argument_digest TEXT NOT NULL,
                        status TEXT NOT NULL,
                        error_code TEXT,
                        resource_type TEXT,
                        resource_id TEXT,
                        task_id TEXT,
                        metadata_json TEXT
                    )"""
                )
                existing_audit_columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(audit_events)")
                }
                for column in ("resource_type", "resource_id", "task_id", "metadata_json"):
                    if column not in existing_audit_columns:
                        connection.execute(f"ALTER TABLE audit_events ADD COLUMN {column} TEXT")
                _migrate_lifecycle_audit_chain(connection)
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS worker_audit_state (
                        singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
                        pending_operations INTEGER NOT NULL CHECK(pending_operations >= 0)
                    )"""
                )
                connection.execute(
                    "INSERT OR IGNORE INTO worker_audit_state(singleton_id, pending_operations) VALUES (1, 0)"
                )
                connection.execute(
                    """CREATE TRIGGER IF NOT EXISTS audit_events_immutable_update
                    BEFORE UPDATE ON audit_events
                    BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END"""
                )
                connection.execute(
                    """CREATE TRIGGER IF NOT EXISTS audit_events_immutable_delete
                    BEFORE DELETE ON audit_events
                    BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END"""
                )
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS consumed_approvals (
                        grant_id TEXT PRIMARY KEY,
                        principal_id TEXT NOT NULL,
                        tool_name TEXT NOT NULL,
                        argument_digest TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        consumed_at TEXT NOT NULL
                    )"""
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
        with self._lock:
            connection = self._connect()
            try:
                _validate_audit_chain(connection)
            finally:
                connection.close()

    def write(self, event: AuditEvent) -> None:
        if not isinstance(event, AuditEvent):
            raise ToolValidationError("audit sink accepts AuditEvent records only")
        text_fields = (
            (event.event_id, 64), (event.timestamp, 64), (event.principal_id, 256),
            (event.tool_name, 64), (event.status, 64),
        )
        if any(not isinstance(value, str) or not value or len(value) > limit
               or contains_surrogate(value)
               for value, limit in text_fields):
            raise ToolValidationError("audit event contains invalid or oversized metadata")
        if not isinstance(event.argument_digest, str) or not _DIGEST_RE.fullmatch(event.argument_digest):
            raise ToolValidationError("audit event argument digest must be SHA-256 hex")
        if event.error_code is not None and (
            not isinstance(event.error_code, str) or len(event.error_code) > 128
            or contains_surrogate(event.error_code)
        ):
            raise ToolValidationError("audit event error code is invalid")
        optional_fields = (
            (event.resource_type, 64), (event.resource_id, 256), (event.task_id, 128),
        )
        if any(
            value is not None and (
                not isinstance(value, str) or not value or len(value) > limit
                or contains_surrogate(value)
            )
            for value, limit in optional_fields
        ):
            raise ToolValidationError("audit event resource metadata is invalid")
        if event.metadata_json is None:
            if any(value is not None for value, _ in optional_fields):
                raise ToolValidationError("audit resource fields require canonical metadata JSON")
        else:
            if (
                not isinstance(event.metadata_json, str)
                or len(event.metadata_json.encode("utf-8")) > 16_384
                or contains_surrogate(event.metadata_json)
                or event.resource_type is None or event.resource_id is None
            ):
                raise ToolValidationError("audit event metadata JSON is invalid")
            try:
                metadata = json.loads(event.metadata_json)
                canonical_metadata = json.dumps(
                    metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
                )
            except (TypeError, ValueError, json.JSONDecodeError):
                raise ToolValidationError("audit event metadata JSON is invalid") from None
            if (
                not isinstance(metadata, dict)
                or canonical_metadata != event.metadata_json
                or hashlib.sha256(event.metadata_json.encode("utf-8")).hexdigest()
                    != event.argument_digest
            ):
                raise ToolValidationError("audit event metadata digest or canonical form is invalid")
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                _append_audit_event(connection, (
                    event.event_id, event.timestamp, event.principal_id,
                    event.tool_name, event.argument_digest, event.status,
                    event.error_code, event.resource_type, event.resource_id,
                    event.task_id, event.metadata_json,
                ))
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def consume(self, grant: ApprovalGrant, now: datetime) -> bool:
        if not isinstance(grant, ApprovalGrant):
            return False
        if (not isinstance(grant.grant_id, str) or not grant.grant_id or len(grant.grant_id) > 128
                or not isinstance(grant.principal_id, str) or not grant.principal_id or len(grant.principal_id) > 256
                or not isinstance(grant.tool_name, str) or not _NAME_RE.fullmatch(grant.tool_name)
                or not isinstance(grant.argument_digest, str) or not _DIGEST_RE.fullmatch(grant.argument_digest)
                or not isinstance(grant.expires_at, str) or len(grant.expires_at) > 64
                or any(contains_surrogate(value) for value in (grant.grant_id, grant.principal_id, grant.tool_name, grant.argument_digest, grant.expires_at))):
            return False
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ToolValidationError("approval consumption requires a timezone-aware time")
        try:
            expiry = datetime.fromisoformat(grant.expires_at.replace("Z", "+00:00"))
        except (AttributeError, TypeError, ValueError):
            return False
        if expiry.tzinfo is None or expiry.utcoffset() is None or expiry <= now:
            return False
        if not isinstance(grant.grant_id, str) or not grant.grant_id:
            return False
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    """INSERT OR IGNORE INTO consumed_approvals
                    (grant_id, principal_id, tool_name, argument_digest, expires_at, consumed_at)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        grant.grant_id,
                        grant.principal_id,
                        grant.tool_name,
                        grant.argument_digest,
                        expiry.isoformat(),
                        now.isoformat(),
                    ),
                )
                connection.execute("COMMIT")
                return cursor.rowcount == 1
            except Exception:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                connection.close()

    def begin_worker_lifecycle_operation(self) -> None:
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    """UPDATE worker_audit_state
                    SET pending_operations = pending_operations + 1
                    WHERE singleton_id = 1"""
                )
                if cursor.rowcount != 1:
                    raise ToolValidationError("worker audit state is unavailable")
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def finish_worker_lifecycle_operation(self) -> None:
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    """UPDATE worker_audit_state
                    SET pending_operations = pending_operations - 1
                    WHERE singleton_id = 1 AND pending_operations > 0"""
                )
                if cursor.rowcount != 1:
                    raise ToolValidationError("no worker lifecycle operation is pending")
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def worker_lifecycle_reconciliation_required(self) -> bool:
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute(
                    "SELECT pending_operations FROM worker_audit_state WHERE singleton_id = 1"
                ).fetchone()
                if row is None or type(row[0]) is not int or row[0] < 0:
                    raise ToolValidationError("worker audit state is invalid")
                return row[0] > 0 or _outstanding_worker_reservations(connection) > 0
            finally:
                connection.close()

    def acknowledge_worker_lifecycle_reconciliation(self, note: str) -> bool:
        if (
            not isinstance(note, str) or not note or len(note) > 1024
            or contains_surrogate(note)
        ):
            raise ToolValidationError("worker lifecycle reconciliation note is invalid")
        event_id = uuid4().hex
        timestamp = datetime.now(timezone.utc).isoformat()
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT pending_operations FROM worker_audit_state WHERE singleton_id = 1"
                ).fetchone()
                if row is None or type(row[0]) is not int or row[0] < 0:
                    raise ToolValidationError("worker audit state is invalid")
                pending = row[0]
                outstanding = _outstanding_worker_reservations(connection)
                if pending == 0 and outstanding == 0:
                    connection.rollback()
                    return False
                metadata_json = json.dumps(
                    {
                        "pending_operations": pending,
                        "outstanding_reservations": outstanding,
                        "reconciliation_note": note,
                    },
                    sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
                )
                digest = hashlib.sha256(metadata_json.encode("utf-8")).hexdigest()
                _append_audit_event(connection, (
                    event_id, timestamp, "host", "worker.reconciliation.acknowledged",
                    digest, "success", None, "worker_registry", "registry", None,
                    metadata_json,
                ))
                connection.execute(
                    """UPDATE worker_audit_state SET pending_operations = 0
                    WHERE singleton_id = 1"""
                )
                connection.commit()
                return True
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def events(self) -> tuple[AuditEvent, ...]:
        with self._lock:
            connection = self._connect()
            try:
                rows = connection.execute(
                    """SELECT event_id, timestamp, principal_id, tool_name,
                    argument_digest, status, error_code, resource_type, resource_id,
                    task_id, metadata_json FROM audit_events ORDER BY rowid"""
                ).fetchall()
                return tuple(AuditEvent(*row) for row in rows)
            finally:
                connection.close()

    def backup_to(self, destination_path: str) -> str:
        """Create a consistent, private, standalone SQLite backup atomically.

        The destination directory must already exist and be private. Existing
        destinations are never overwritten. SQLite's online backup API captures
        a consistent snapshot, including committed WAL content, without copying
        live database sidecar files.
        """
        if not isinstance(destination_path, str) or not destination_path.strip():
            raise ToolValidationError("backup destination must be a non-empty path")
        absolute = os.path.abspath(destination_path)
        if absolute == self.path:
            raise ToolValidationError("backup destination must differ from the live database")
        parent = os.path.dirname(absolute)
        if not os.path.isdir(parent) or os.path.realpath(parent) != parent:
            raise ToolValidationError("backup parent must be an existing non-symlink directory")
        parent_stat = os.stat(parent, follow_symlinks=False)
        if not stat.S_ISDIR(parent_stat.st_mode):
            raise ToolValidationError("backup parent must be a directory")
        if os.name == "posix" and (
            parent_stat.st_uid != os.geteuid()
            or stat.S_IMODE(parent_stat.st_mode) & 0o077
        ):
            raise ToolValidationError("backup parent must be owned by the current user and private")
        if os.path.lexists(absolute):
            raise ToolValidationError("backup destination already exists")

        descriptor, temporary_path = tempfile.mkstemp(
            prefix=".capri-security-backup-", suffix=".sqlite3", dir=parent
        )
        os.close(descriptor)
        source = None
        destination = None
        published = False
        try:
            with self._lock:
                source = self._connect()
                destination = sqlite3.connect(
                    temporary_path, timeout=5.0, isolation_level=None
                )
                destination.execute("PRAGMA foreign_keys=ON")
                destination.execute("PRAGMA trusted_schema=OFF")
                destination.execute("PRAGMA synchronous=FULL")
                source.backup(destination)
                check = destination.execute("PRAGMA integrity_check").fetchone()
                if not check or check[0] != "ok":
                    raise ToolValidationError("SQLite backup integrity check failed")
                _validate_backup_semantics(destination)
                destination.close()
                destination = None
                source.close()
                source = None

            flags = os.O_RDONLY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            backup_fd = os.open(temporary_path, flags)
            try:
                info = os.fstat(backup_fd)
                if not stat.S_ISREG(info.st_mode):
                    raise ToolValidationError("temporary backup is not a regular file")
                if os.name == "posix":
                    if info.st_uid != os.geteuid() or info.st_nlink != 1:
                        raise ToolValidationError("temporary backup ownership or link count is invalid")
                    os.fchmod(backup_fd, 0o600)
                os.fsync(backup_fd)
            finally:
                os.close(backup_fd)

            # Publish atomically without replacing a destination created in a race.
            publication_method = publish_no_replace(temporary_path, absolute)
            published = True
            if publication_method == "hard-link":
                os.unlink(temporary_path)
            if os.name == "posix":
                directory_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            return absolute
        except Exception:
            if destination is not None:
                destination.close()
            if source is not None:
                source.close()
            for candidate in (
                temporary_path, temporary_path + "-journal",
                temporary_path + "-wal", temporary_path + "-shm",
            ):
                try:
                    os.unlink(candidate)
                except FileNotFoundError:
                    pass
                except OSError:
                    pass
            if published:
                # Publication succeeded but a later durability step failed. Keep
                # the complete backup: deleting it could destroy the only copy.
                raise ToolValidationError(
                    "backup was published but directory durability could not be confirmed"
                ) from None
            raise

    def integrity_check(self) -> str:
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute("PRAGMA integrity_check").fetchone()
                if not row or row[0] != "ok":
                    return str(row[0]) if row else "no result"
                _validate_backup_semantics(connection)
                return "ok"
            finally:
                connection.close()
