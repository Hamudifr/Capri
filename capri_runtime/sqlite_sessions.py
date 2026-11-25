"""Private durable SQLite session persistence.

Conversation messages are stored as plaintext JSON inside a private SQLite database.
Hosts must protect the parent directory, backups, and device; this module does not
provide encryption or retention policy.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import stat
import tempfile
import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from .atomic_publish import publish_no_replace
from .runtime import (
    Message,
    Session,
    SessionClosedError,
    SessionConflictError,
    SessionLimitError,
    SessionNotFoundError,
    SessionStore,
    ValidationError,
    _contains_surrogate,
    _validate_turn_messages,
)


class SQLiteSessionStore(SessionStore):
    """SessionStore-compatible durable store with cross-process optimistic commits.

    The database must be placed in an existing directory private to the current
    user (0700 or stricter on POSIX). The database file is kept at 0600.
    """

    def __init__(
        self,
        path: str,
        max_session_messages: int = 200,
        max_input_chars: int = 16_000,
        max_output_chars: int = 64_000,
        max_tool_chars: int = 131_072,
    ) -> None:
        super().__init__(
            max_session_messages=max_session_messages,
            max_input_chars=max_input_chars,
            max_output_chars=max_output_chars,
            max_tool_chars=max_tool_chars,
        )
        if not isinstance(path, str) or not path.strip():
            raise ValidationError("database path must be non-empty text")
        absolute = os.path.abspath(path)
        parent = os.path.dirname(absolute)
        if not os.path.isdir(parent) or os.path.realpath(parent) != parent:
            raise ValidationError("database parent must be an existing non-symlink directory")
        parent_stat = os.stat(parent, follow_symlinks=False)
        if not stat.S_ISDIR(parent_stat.st_mode):
            raise ValidationError("database parent must be a directory")
        if os.name == "posix":
            if parent_stat.st_uid != os.geteuid() or stat.S_IMODE(parent_stat.st_mode) & 0o077:
                raise ValidationError("database parent must be owned by the current user and private")

        if os.path.lexists(absolute):
            existing = os.lstat(absolute)
            if not stat.S_ISREG(existing.st_mode):
                raise ValidationError("database path must be a regular non-symlink file")
            if os.name == "posix" and (
                existing.st_uid != os.geteuid() or existing.st_nlink != 1
            ):
                raise ValidationError("database file ownership or link count is unsafe")

        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(absolute, flags, 0o600)
        except OSError:
            raise ValidationError("database file could not be opened safely") from None
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise ValidationError("database path must be a regular file")
            if os.name == "posix":
                if opened.st_uid != os.geteuid() or opened.st_nlink != 1:
                    raise ValidationError("database file ownership or link count is unsafe")
                os.fchmod(descriptor, 0o600)
        finally:
            os.close(descriptor)

        self.path = absolute
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        parent = os.path.dirname(self.path)
        if os.path.realpath(parent) != parent:
            raise ValidationError("database parent path changed to traverse a symlink")
        parent_stat = os.stat(parent, follow_symlinks=False)
        if not stat.S_ISDIR(parent_stat.st_mode):
            raise ValidationError("database parent changed to a non-directory")
        if os.name == "posix" and (
            parent_stat.st_uid != os.geteuid() or stat.S_IMODE(parent_stat.st_mode) & 0o077
        ):
            raise ValidationError("database parent ownership or privacy changed")
        current = os.lstat(self.path)
        if not stat.S_ISREG(current.st_mode):
            raise ValidationError("database file changed to a non-regular path")
        if os.name == "posix" and (
            current.st_uid != os.geteuid()
            or stat.S_IMODE(current.st_mode) != 0o600
            or current.st_nlink != 1
        ):
            raise ValidationError("database ownership, link count, or permissions changed")
        connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA recursive_triggers=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _initialize(self) -> None:
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS sessions (
                        session_id TEXT PRIMARY KEY,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        version INTEGER NOT NULL CHECK(version >= 0),
                        closed INTEGER NOT NULL CHECK(closed IN (0, 1)),
                        messages_json TEXT NOT NULL
                    )"""
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS sessions_updated_at ON sessions(updated_at)"
                )
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS session_turn_leases (
                        session_id TEXT PRIMARY KEY REFERENCES sessions(session_id) ON DELETE CASCADE,
                        owner_token TEXT NOT NULL,
                        expires_at TEXT NOT NULL
                    )"""
                )
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS session_owners (
                        session_id TEXT PRIMARY KEY REFERENCES sessions(session_id) ON DELETE CASCADE,
                        principal_id TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )"""
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS session_owners_principal_id ON session_owners(principal_id)"
                )
                connection.execute(
                    """CREATE TRIGGER IF NOT EXISTS session_owners_immutable_update
                    BEFORE UPDATE ON session_owners
                    BEGIN
                        SELECT RAISE(ABORT, 'session owner is immutable');
                    END"""
                )
                connection.execute(
                    """CREATE TRIGGER IF NOT EXISTS session_owners_immutable_delete
                    BEFORE DELETE ON session_owners
                    BEGIN
                        SELECT RAISE(ABORT, 'session owner is immutable');
                    END"""
                )
                connection.execute(
                    """CREATE TRIGGER IF NOT EXISTS session_owners_immutable_insert
                    BEFORE INSERT ON session_owners
                    WHEN EXISTS (
                        SELECT 1 FROM session_owners WHERE session_id = NEW.session_id
                    )
                    BEGIN
                        SELECT RAISE(ABORT, 'session owner is immutable');
                    END"""
                )
            finally:
                connection.close()

    def _decode(self, row: tuple) -> Session:
        try:
            session_id, created_at, updated_at, version, closed, encoded = row
            raw = json.loads(encoded)
            if not isinstance(raw, list):
                raise ValueError("messages must be a list")
            messages = tuple(
                Message(role=item["role"], content=item["content"])
                for item in raw
                if isinstance(item, dict)
                and set(item) == {"role", "content"}
                and isinstance(item["role"], str)
                and isinstance(item["content"], str)
            )
            if len(messages) != len(raw):
                raise ValueError("invalid message record")
            if any(
                not message.role
                or len(message.role) > 32
                or _contains_surrogate(message.role)
                or _contains_surrogate(message.content)
                for message in messages
            ):
                raise ValueError("invalid message text")
            if (
                not isinstance(session_id, str)
                or not session_id.strip()
                or len(session_id) > 256
                or _contains_surrogate(session_id)
                or not isinstance(created_at, str)
                or not created_at
                or len(created_at) > 64
                or _contains_surrogate(created_at)
                or not isinstance(updated_at, str)
                or not updated_at
                or len(updated_at) > 64
                or _contains_surrogate(updated_at)
                or isinstance(version, bool)
                or not isinstance(version, int)
                or version < 0
                or isinstance(closed, bool)
                or not isinstance(closed, int)
                or closed not in (0, 1)
                or len(messages) > self.max_session_messages
                or sum(message.role == "user" for message in messages) != version
            ):
                raise ValueError("invalid session metadata")
            if messages:
                turn_start = 0
                for index in range(1, len(messages)):
                    if messages[index].role == "user":
                        _validate_turn_messages(
                            messages[turn_start:index],
                            max_input_chars=self.max_input_chars,
                            max_output_chars=self.max_output_chars,
                            max_tool_chars=self.max_tool_chars,
                        )
                        turn_start = index
                _validate_turn_messages(
                    messages[turn_start:],
                    max_input_chars=self.max_input_chars,
                    max_output_chars=self.max_output_chars,
                    max_tool_chars=self.max_tool_chars,
                )
            elif version != 0:
                raise ValueError("nonzero session version requires transcript messages")
            return Session(
                session_id=session_id,
                created_at=created_at,
                updated_at=updated_at,
                version=version,
                closed=bool(closed),
                messages=messages,
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, ValidationError, SessionLimitError):
            raise ValidationError("persisted session record is invalid") from None

    def create(self) -> Session:
        now = self._now()
        session = Session(
            session_id=str(uuid4()),
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            connection = self._connect()
            try:
                connection.execute(
                    """INSERT INTO sessions
                    (session_id, created_at, updated_at, version, closed, messages_json)
                    VALUES (?, ?, ?, 0, 0, '[]')""",
                    (session.session_id, now, now),
                )
            finally:
                connection.close()
        return session

    @staticmethod
    def _validate_principal_id(principal_id: str) -> str:
        if (
            not isinstance(principal_id, str)
            or not principal_id.strip()
            or len(principal_id) > 256
            or _contains_surrogate(principal_id)
        ):
            raise ValidationError("principal_id must be bounded valid text")
        return principal_id

    def create_for_principal(self, principal_id: str) -> Session:
        """Atomically create a session and bind it to one authenticated principal."""
        principal_id = self._validate_principal_id(principal_id)
        now = self._now()
        session = Session(
            session_id=str(uuid4()),
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """INSERT INTO sessions
                    (session_id, created_at, updated_at, version, closed, messages_json)
                    VALUES (?, ?, ?, 0, 0, '[]')""",
                    (session.session_id, now, now),
                )
                connection.execute(
                    """INSERT INTO session_owners (session_id, principal_id, created_at)
                    VALUES (?, ?, ?)""",
                    (session.session_id, principal_id, now),
                )
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()
        return session

    def _require_owner(self, session_id: str, principal_id: str) -> None:
        self._validate_principal_id(principal_id)
        if (
            not isinstance(session_id, str)
            or not session_id.strip()
            or len(session_id) > 256
            or _contains_surrogate(session_id)
        ):
            raise ValidationError("session_id must be bounded valid text")
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute(
                    "SELECT 1 FROM session_owners WHERE session_id = ? AND principal_id = ?",
                    (session_id, principal_id),
                ).fetchone()
            finally:
                connection.close()
        if row is None:
            # Deliberately conceal whether the session exists for another principal.
            raise SessionNotFoundError("session does not exist")

    def get_for_principal(self, session_id: str, principal_id: str) -> Session:
        principal_id = self._validate_principal_id(principal_id)
        if (
            not isinstance(session_id, str)
            or not session_id.strip()
            or len(session_id) > 256
            or _contains_surrogate(session_id)
        ):
            raise ValidationError("session_id must be bounded valid text")
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute(
                    """SELECT s.session_id, s.created_at, s.updated_at, s.version,
                    s.closed, s.messages_json
                    FROM sessions AS s
                    JOIN session_owners AS o ON o.session_id = s.session_id
                    WHERE s.session_id = ? AND o.principal_id = ?""",
                    (session_id, principal_id),
                ).fetchone()
            finally:
                connection.close()
        if row is None:
            raise SessionNotFoundError("session does not exist")
        return self._decode(row)

    def close_for_principal(self, session_id: str, principal_id: str) -> Session:
        principal_id = self._validate_principal_id(principal_id)
        if (
            not isinstance(session_id, str)
            or not session_id.strip()
            or len(session_id) > 256
            or _contains_surrogate(session_id)
        ):
            raise ValidationError("session_id must be bounded valid text")
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """SELECT s.session_id, s.created_at, s.updated_at, s.version,
                    s.closed, s.messages_json
                    FROM sessions AS s
                    JOIN session_owners AS o ON o.session_id = s.session_id
                    WHERE s.session_id = ? AND o.principal_id = ?""",
                    (session_id, principal_id),
                ).fetchone()
                if row is None:
                    raise SessionNotFoundError("session does not exist")
                current = self._decode(row)
                if current.closed:
                    connection.execute("COMMIT")
                    return current
                updated_at = self._now()
                connection.execute(
                    "UPDATE sessions SET closed = 1, updated_at = ? WHERE session_id = ?",
                    (updated_at, session_id),
                )
                connection.execute("COMMIT")
                return replace(current, closed=True, updated_at=updated_at)
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    def commit_turn_messages_for_principal(
        self,
        session_id: str,
        principal_id: str,
        expected_version: int,
        turn_messages: tuple[Message, ...],
        *,
        lease_owner: str | None = None,
    ) -> Session:
        return self._commit_turn_messages(
            session_id, expected_version, turn_messages,
            lease_owner=lease_owner, principal_id=principal_id,
        )

    def claim_turn_lease_for_principal(
        self, session_id: str, principal_id: str, owner_token: str,
        lease_seconds: float = 30.0,
    ) -> str:
        return self._claim_turn_lease(
            session_id, owner_token, lease_seconds, principal_id=principal_id,
        )

    def renew_turn_lease_for_principal(
        self, session_id: str, principal_id: str, owner_token: str,
        lease_seconds: float = 30.0,
    ) -> str:
        return self._renew_turn_lease(
            session_id, owner_token, lease_seconds, principal_id=principal_id,
        )

    def release_turn_lease_for_principal(
        self, session_id: str, principal_id: str, owner_token: str,
    ) -> bool:
        return self._release_turn_lease(
            session_id, owner_token, principal_id=principal_id,
        )

    def get(self, session_id: str) -> Session:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValidationError("session_id must be a non-empty string")
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute(
                    """SELECT session_id, created_at, updated_at, version, closed, messages_json
                    FROM sessions WHERE session_id = ?""",
                    (session_id,),
                ).fetchone()
            finally:
                connection.close()
        if row is None:
            raise SessionNotFoundError("session does not exist")
        return self._decode(row)

    def close(self, session_id: str) -> Session:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValidationError("session_id must be a non-empty string")
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                if principal_id is None:
                    row = connection.execute(
                        """SELECT session_id, created_at, updated_at, version, closed, messages_json
                        FROM sessions WHERE session_id = ?""",
                        (session_id,),
                    ).fetchone()
                else:
                    row = connection.execute(
                        """SELECT s.session_id, s.created_at, s.updated_at, s.version,
                        s.closed, s.messages_json
                        FROM sessions AS s
                        JOIN session_owners AS o ON o.session_id = s.session_id
                        WHERE s.session_id = ? AND o.principal_id = ?""",
                        (session_id, principal_id),
                    ).fetchone()
                if row is None:
                    raise SessionNotFoundError("session does not exist")
                current = self._decode(row)
                if current.closed:
                    connection.execute("COMMIT")
                    return current
                updated_at = self._now()
                connection.execute(
                    "UPDATE sessions SET closed = 1, updated_at = ? WHERE session_id = ?",
                    (updated_at, session_id),
                )
                connection.execute("COMMIT")
                return replace(current, closed=True, updated_at=updated_at)
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()


    @staticmethod
    def _lease_parameters(owner_token: str, lease_seconds: float) -> tuple[str, float]:
        if (
            not isinstance(owner_token, str)
            or not owner_token
            or len(owner_token) > 128
            or _contains_surrogate(owner_token)
        ):
            raise ValidationError("lease owner token must be bounded valid text")
        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, (int, float)):
            raise ValidationError("lease_seconds must be between 3 and 3600 seconds")
        try:
            seconds = float(lease_seconds)
        except (OverflowError, TypeError, ValueError):
            raise ValidationError("lease_seconds must be between 3 and 3600 seconds") from None
        if not math.isfinite(seconds) or not 3 <= seconds <= 3600:
            raise ValidationError("lease_seconds must be between 3 and 3600 seconds")
        return owner_token, seconds

    @staticmethod
    def _lease_now() -> datetime:
        return datetime.now(timezone.utc)

    def claim_turn_lease(
        self,
        session_id: str,
        owner_token: str,
        lease_seconds: float = 30.0,
    ) -> str:
        return self._claim_turn_lease(session_id, owner_token, lease_seconds)

    def _claim_turn_lease(
        self,
        session_id: str,
        owner_token: str,
        lease_seconds: float = 30.0,
        *,
        principal_id: str | None = None,
    ) -> str:
        """Acquire a durable cross-process session-turn lease or fail if held."""
        owner_token, lease_seconds = self._lease_parameters(owner_token, lease_seconds)
        if principal_id is not None:
            principal_id = self._validate_principal_id(principal_id)
        if (
            not isinstance(session_id, str)
            or not session_id.strip()
            or len(session_id) > 256
            or _contains_surrogate(session_id)
        ):
            raise ValidationError("session_id must be bounded valid text")
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                now = self._lease_now()
                expires_at = (now + timedelta(seconds=lease_seconds)).isoformat()
                if principal_id is None:
                    session = connection.execute(
                        "SELECT closed FROM sessions WHERE session_id = ?",
                        (session_id,),
                    ).fetchone()
                else:
                    session = connection.execute(
                        """SELECT s.closed FROM sessions AS s
                        JOIN session_owners AS o ON o.session_id = s.session_id
                        WHERE s.session_id = ? AND o.principal_id = ?""",
                        (session_id, principal_id),
                    ).fetchone()
                if session is None:
                    raise SessionNotFoundError("session does not exist")
                if session[0] == 1:
                    raise SessionClosedError("session is closed")
                current = connection.execute(
                    "SELECT owner_token, expires_at FROM session_turn_leases WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                if current is not None:
                    try:
                        current_expiry = datetime.fromisoformat(current[1])
                    except (TypeError, ValueError):
                        raise ValidationError("persisted session lease is invalid") from None
                    if current_expiry.tzinfo is None or current_expiry.utcoffset() is None:
                        raise ValidationError("persisted session lease is invalid")
                    if current_expiry > now and current[0] != owner_token:
                        raise SessionConflictError("another worker holds the session turn lease")
                    if current_expiry <= now and current[0] == owner_token:
                        raise SessionConflictError("an expired lease token cannot be reused")
                    connection.execute(
                        """UPDATE session_turn_leases
                        SET owner_token = ?, expires_at = ? WHERE session_id = ?""",
                        (owner_token, expires_at, session_id),
                    )
                else:
                    connection.execute(
                        """INSERT INTO session_turn_leases (session_id, owner_token, expires_at)
                        VALUES (?, ?, ?)""",
                        (session_id, owner_token, expires_at),
                    )
                connection.execute("COMMIT")
                return expires_at
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    def renew_turn_lease(
        self,
        session_id: str,
        owner_token: str,
        lease_seconds: float = 30.0,
    ) -> str:
        return self._renew_turn_lease(session_id, owner_token, lease_seconds)

    def _renew_turn_lease(
        self,
        session_id: str,
        owner_token: str,
        lease_seconds: float = 30.0,
        *,
        principal_id: str | None = None,
    ) -> str:
        """Renew only a still-live lease owned by this exact worker token."""
        owner_token, lease_seconds = self._lease_parameters(owner_token, lease_seconds)
        if principal_id is not None:
            principal_id = self._validate_principal_id(principal_id)
        if (
            not isinstance(session_id, str)
            or not session_id.strip()
            or len(session_id) > 256
            or _contains_surrogate(session_id)
        ):
            raise ValidationError("session_id must be bounded valid text")
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                if principal_id is not None:
                    owner = connection.execute(
                        "SELECT 1 FROM session_owners WHERE session_id = ? AND principal_id = ?",
                        (session_id, principal_id),
                    ).fetchone()
                    if owner is None:
                        raise SessionNotFoundError("session does not exist")
                now = self._lease_now()
                expires_at = (now + timedelta(seconds=lease_seconds)).isoformat()
                current = connection.execute(
                    "SELECT owner_token, expires_at FROM session_turn_leases WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                if current is None or current[0] != owner_token:
                    raise SessionConflictError("session turn lease is no longer owned by this worker")
                try:
                    current_expiry = datetime.fromisoformat(current[1])
                except (TypeError, ValueError):
                    raise ValidationError("persisted session lease is invalid") from None
                if current_expiry.tzinfo is None or current_expiry.utcoffset() is None or current_expiry <= now:
                    raise SessionConflictError("expired session turn lease cannot be renewed")
                connection.execute(
                    "UPDATE session_turn_leases SET expires_at = ? WHERE session_id = ? AND owner_token = ?",
                    (expires_at, session_id, owner_token),
                )
                connection.execute("COMMIT")
                return expires_at
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    def release_turn_lease(self, session_id: str, owner_token: str) -> bool:
        return self._release_turn_lease(session_id, owner_token)

    def _release_turn_lease(
        self, session_id: str, owner_token: str, *,
        principal_id: str | None = None,
    ) -> bool:
        """Release only the lease still owned by the supplied worker token."""
        if principal_id is not None:
            principal_id = self._validate_principal_id(principal_id)
        if (
            not isinstance(session_id, str)
            or not session_id.strip()
            or len(session_id) > 256
            or _contains_surrogate(session_id)
            or not isinstance(owner_token, str)
            or not owner_token
            or len(owner_token) > 128
            or _contains_surrogate(owner_token)
        ):
            raise ValidationError("session_id and lease owner token must be bounded valid text")
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                if principal_id is not None:
                    owner = connection.execute(
                        "SELECT 1 FROM session_owners WHERE session_id = ? AND principal_id = ?",
                        (session_id, principal_id),
                    ).fetchone()
                    if owner is None:
                        raise SessionNotFoundError("session does not exist")
                current = connection.execute(
                    "SELECT owner_token, expires_at FROM session_turn_leases WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                if current is None or current[0] != owner_token:
                    connection.execute("COMMIT")
                    return False
                try:
                    current_expiry = datetime.fromisoformat(current[1])
                except (TypeError, ValueError):
                    raise ValidationError("persisted session lease is invalid") from None
                if current_expiry.tzinfo is None or current_expiry.utcoffset() is None:
                    raise ValidationError("persisted session lease is invalid")
                if current_expiry <= self._lease_now():
                    connection.execute("COMMIT")
                    return False
                cursor = connection.execute(
                    "DELETE FROM session_turn_leases WHERE session_id = ? AND owner_token = ?",
                    (session_id, owner_token),
                )
                connection.execute("COMMIT")
                return cursor.rowcount == 1
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    def commit_turn_messages(
        self,
        session_id: str,
        expected_version: int,
        turn_messages: tuple[Message, ...],
        *,
        lease_owner: str | None = None,
    ) -> Session:
        return self._commit_turn_messages(
            session_id, expected_version, turn_messages, lease_owner=lease_owner,
        )

    def _commit_turn_messages(
        self,
        session_id: str,
        expected_version: int,
        turn_messages: tuple[Message, ...],
        *,
        lease_owner: str | None = None,
        principal_id: str | None = None,
    ) -> Session:
        if principal_id is not None:
            principal_id = self._validate_principal_id(principal_id)
            if (
                not isinstance(session_id, str)
                or not session_id.strip()
                or len(session_id) > 256
                or _contains_surrogate(session_id)
            ):
                raise ValidationError("session_id must be bounded valid text")
        validated = _validate_turn_messages(
            turn_messages,
            max_input_chars=self.max_input_chars,
            max_output_chars=self.max_output_chars,
            max_tool_chars=self.max_tool_chars,
        )
        if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 0:
            raise ValidationError("expected_version must be a non-negative integer")

        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                if principal_id is None:
                    row = connection.execute(
                        """SELECT session_id, created_at, updated_at, version, closed, messages_json
                        FROM sessions WHERE session_id = ?""",
                        (session_id,),
                    ).fetchone()
                else:
                    row = connection.execute(
                        """SELECT s.session_id, s.created_at, s.updated_at, s.version,
                        s.closed, s.messages_json
                        FROM sessions AS s
                        JOIN session_owners AS o ON o.session_id = s.session_id
                        WHERE s.session_id = ? AND o.principal_id = ?""",
                        (session_id, principal_id),
                    ).fetchone()
                if row is None:
                    raise SessionNotFoundError("session does not exist")
                current = self._decode(row)
                if current.closed:
                    raise SessionClosedError("session is closed")
                if current.version != expected_version:
                    raise SessionConflictError("session changed during model execution")
                lease = connection.execute(
                    "SELECT owner_token, expires_at FROM session_turn_leases WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                now = self._lease_now()
                if lease is not None:
                    try:
                        lease_expiry = datetime.fromisoformat(lease[1])
                    except (TypeError, ValueError):
                        raise ValidationError("persisted session lease is invalid") from None
                    if lease_expiry.tzinfo is None or lease_expiry.utcoffset() is None:
                        raise ValidationError("persisted session lease is invalid")
                    if lease_expiry <= now:
                        raise SessionConflictError("expired session turn lease must be reclaimed before commit")
                    if not isinstance(lease_owner, str) or lease[0] != lease_owner:
                        raise SessionConflictError("an active session turn lease fences this commit")
                elif lease_owner is not None:
                    raise SessionConflictError("session turn lease does not exist")
                if len(current.messages) + len(validated) > self.max_session_messages:
                    raise SessionLimitError("session message limit reached")
                updated_at = self._now()
                messages = current.messages + validated
                encoded = json.dumps(
                    [{"role": item.role, "content": item.content} for item in messages],
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                )
                cursor = connection.execute(
                    """UPDATE sessions
                    SET updated_at = ?, version = version + 1, messages_json = ?
                    WHERE session_id = ? AND version = ? AND closed = 0""",
                    (updated_at, encoded, session_id, expected_version),
                )
                if cursor.rowcount != 1:
                    raise SessionConflictError("session changed during model execution")
                connection.execute("COMMIT")
                return replace(
                    current,
                    updated_at=updated_at,
                    version=current.version + 1,
                    messages=messages,
                )
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    def _validate_backup_snapshot(self, connection: sqlite3.Connection) -> None:
        """Validate session rows, immutable owners and durable turn leases."""
        check = connection.execute("PRAGMA integrity_check").fetchone()
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        if not check or check[0] != "ok":
            raise ValidationError("SQLite session backup integrity check failed")
        if foreign_key_errors:
            raise ValidationError("SQLite session backup foreign key check failed")

        rows = connection.execute(
            """SELECT session_id, created_at, updated_at, version, closed, messages_json
            FROM sessions ORDER BY created_at, session_id"""
        ).fetchall()
        for row in rows:
            self._decode(row)

        owners = connection.execute(
            "SELECT session_id, principal_id, created_at FROM session_owners"
        ).fetchall()
        for session_id, principal_id, created_at in owners:
            if (
                not isinstance(session_id, str)
                or not session_id.strip()
                or len(session_id) > 256
                or _contains_surrogate(session_id)
            ):
                raise ValidationError("SQLite session backup contains invalid ownership data")
            self._validate_principal_id(principal_id)
            try:
                created = datetime.fromisoformat(created_at)
            except (TypeError, ValueError):
                raise ValidationError("SQLite session backup contains an invalid owner timestamp") from None
            if created.tzinfo is None or created.utcoffset() is None:
                raise ValidationError("SQLite session backup contains an invalid owner timestamp")

        leases = connection.execute(
            "SELECT session_id, owner_token, expires_at FROM session_turn_leases"
        ).fetchall()
        for session_id, owner_token, expires_at in leases:
            if (
                not isinstance(session_id, str)
                or not session_id.strip()
                or len(session_id) > 256
                or _contains_surrogate(session_id)
            ):
                raise ValidationError("SQLite session backup contains an invalid lease session ID")
            self._lease_parameters(owner_token, 30.0)
            try:
                expiry = datetime.fromisoformat(expires_at)
            except (TypeError, ValueError):
                raise ValidationError("SQLite session backup contains an invalid lease expiry") from None
            if expiry.tzinfo is None or expiry.utcoffset() is None:
                raise ValidationError("SQLite session backup contains an invalid lease expiry")

    def backup_to(self, destination_path: str) -> str:
        """Create a consistent private snapshot without overwriting an existing file.

        SQLite's online backup API captures committed WAL content. The destination
        directory must already exist and be private; live database sidecars are
        never copied directly.
        """
        if not isinstance(destination_path, str) or not destination_path.strip():
            raise ValidationError("backup destination must be a non-empty path")
        absolute = os.path.abspath(destination_path)
        if absolute == self.path:
            raise ValidationError("backup destination must differ from the live database")
        parent = os.path.dirname(absolute)
        if not os.path.isdir(parent) or os.path.realpath(parent) != parent:
            raise ValidationError("backup parent must be an existing non-symlink directory")
        parent_stat = os.stat(parent, follow_symlinks=False)
        if not stat.S_ISDIR(parent_stat.st_mode):
            raise ValidationError("backup parent must be a directory")
        if os.name == "posix" and (
            parent_stat.st_uid != os.geteuid()
            or stat.S_IMODE(parent_stat.st_mode) & 0o077
        ):
            raise ValidationError("backup parent must be owned by the current user and private")
        if os.path.lexists(absolute):
            raise ValidationError("backup destination already exists")

        descriptor, temporary_path = tempfile.mkstemp(
            prefix=".capri-session-backup-", suffix=".sqlite3", dir=parent
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
                self._validate_backup_snapshot(destination)
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
                    raise ValidationError("temporary session backup is not a regular file")
                if os.name == "posix":
                    if info.st_uid != os.geteuid() or info.st_nlink != 1:
                        raise ValidationError("temporary session backup ownership or link count is invalid")
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
                # Preserve a complete backup if only the final directory fsync failed.
                raise ValidationError(
                    "session backup was published but directory durability could not be confirmed"
                ) from None
            raise

    def integrity_check(self) -> str:
        with self._lock:
            connection = self._connect()
            try:
                try:
                    self._validate_backup_snapshot(connection)
                except ValidationError:
                    return "semantic validation failed"
                return "ok"
            finally:
                connection.close()
