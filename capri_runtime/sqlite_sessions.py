"""Private durable SQLite session persistence.

Conversation messages are stored as plaintext JSON inside a private SQLite database.
Hosts must protect the parent directory, backups, and device; this module does not
provide encryption or retention policy.
"""
from __future__ import annotations

import json
import os
import sqlite3
import stat
import threading
from dataclasses import replace
from uuid import uuid4

from .runtime import (
    Message,
    Session,
    SessionClosedError,
    SessionConflictError,
    SessionLimitError,
    SessionNotFoundError,
    SessionStore,
    SessionLimitError,
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
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
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
                row = connection.execute(
                    """SELECT session_id, created_at, updated_at, version, closed, messages_json
                    FROM sessions WHERE session_id = ?""",
                    (session_id,),
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

    def commit_turn_messages(
        self,
        session_id: str,
        expected_version: int,
        turn_messages: tuple[Message, ...],
    ) -> Session:
        validated = _validate_turn_messages(
            turn_messages,
            max_input_chars=self.max_input_chars,
            max_output_chars=self.max_output_chars,
        )
        if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 0:
            raise ValidationError("expected_version must be a non-negative integer")

        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """SELECT session_id, created_at, updated_at, version, closed, messages_json
                    FROM sessions WHERE session_id = ?""",
                    (session_id,),
                ).fetchone()
                if row is None:
                    raise SessionNotFoundError("session does not exist")
                current = self._decode(row)
                if current.closed:
                    raise SessionClosedError("session is closed")
                if current.version != expected_version:
                    raise SessionConflictError("session changed during model execution")
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
