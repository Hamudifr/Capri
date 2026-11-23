"""Private SQLite-backed audit, approval replay, and challenge storage.

Approval challenge records contain bounded identity/operation metadata and signed
grant material. Raw tool arguments, results, prompts, credentials, and transcripts
are not stored. The database is private but not encrypted at rest.
"""
from __future__ import annotations

import os
import re
import sqlite3
import stat
import threading
import tempfile
from datetime import datetime

from .atomic_publish import publish_no_replace
from .tools import ApprovalGrant, ApprovalStore, AuditEvent, AuditSink, ToolValidationError

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_NAME_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


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
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS audit_events (
                        event_id TEXT PRIMARY KEY,
                        timestamp TEXT NOT NULL,
                        principal_id TEXT NOT NULL,
                        tool_name TEXT NOT NULL,
                        argument_digest TEXT NOT NULL,
                        status TEXT NOT NULL,
                        error_code TEXT
                    )"""
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
               or any(0xD800 <= ord(ch) <= 0xDFFF for ch in value)
               for value, limit in text_fields):
            raise ToolValidationError("audit event contains invalid or oversized metadata")
        if not isinstance(event.argument_digest, str) or not _DIGEST_RE.fullmatch(event.argument_digest):
            raise ToolValidationError("audit event argument digest must be SHA-256 hex")
        if event.error_code is not None and (
            not isinstance(event.error_code, str) or len(event.error_code) > 128
            or any(0xD800 <= ord(ch) <= 0xDFFF for ch in event.error_code)
        ):
            raise ToolValidationError("audit event error code is invalid")
        with self._lock:
            connection = self._connect()
            try:
                connection.execute(
                    """INSERT INTO audit_events
                    (event_id, timestamp, principal_id, tool_name, argument_digest, status, error_code)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        event.event_id,
                        event.timestamp,
                        event.principal_id,
                        event.tool_name,
                        event.argument_digest,
                        event.status,
                        event.error_code,
                    ),
                )
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
                or any(0xD800 <= ord(ch) <= 0xDFFF for value in (grant.grant_id, grant.principal_id, grant.tool_name, grant.argument_digest, grant.expires_at) for ch in value)):
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

    def events(self) -> tuple[AuditEvent, ...]:
        with self._lock:
            connection = self._connect()
            try:
                rows = connection.execute(
                    """SELECT event_id, timestamp, principal_id, tool_name,
                    argument_digest, status, error_code FROM audit_events ORDER BY rowid"""
                ).fetchall()
                return tuple(AuditEvent(*row) for row in rows)
            finally:
                connection.close()

    @staticmethod
    def _validate_backup_snapshot(connection: sqlite3.Connection) -> None:
        """Reject persisted rows that violate the invariants enforced on writes.

        Audit timestamps intentionally remain bounded opaque text for backward
        compatibility. Approval timestamps are parsed because replay safety depends
        on their ordering and timezone awareness.
        """
        audit_rows = connection.execute(
            """SELECT event_id, timestamp, principal_id, tool_name,
            argument_digest, status, error_code FROM audit_events"""
        ).fetchall()
        for row in audit_rows:
            event_id, timestamp, principal_id, tool_name, digest, status, error_code = row
            text_fields = (
                (event_id, 64), (timestamp, 64), (principal_id, 256),
                (tool_name, 64), (status, 64),
            )
            if any(
                not isinstance(value, str) or not value or len(value) > limit
                or any(0xD800 <= ord(ch) <= 0xDFFF for ch in value)
                for value, limit in text_fields
            ):
                raise ToolValidationError(
                    "security-store backup contains invalid audit metadata"
                )
            if not isinstance(digest, str) or not _DIGEST_RE.fullmatch(digest):
                raise ToolValidationError(
                    "security-store backup contains an invalid audit digest"
                )
            if error_code is not None and (
                not isinstance(error_code, str) or len(error_code) > 128
                or any(0xD800 <= ord(ch) <= 0xDFFF for ch in error_code)
            ):
                raise ToolValidationError(
                    "security-store backup contains an invalid audit error code"
                )

        approval_rows = connection.execute(
            """SELECT grant_id, principal_id, tool_name, argument_digest,
            expires_at, consumed_at FROM consumed_approvals"""
        ).fetchall()
        for row in approval_rows:
            grant_id, principal_id, tool_name, digest, expires_at, consumed_at = row
            text_fields = (
                (grant_id, 128), (principal_id, 256), (tool_name, 64),
                (digest, 64), (expires_at, 64), (consumed_at, 64),
            )
            if any(
                not isinstance(value, str) or not value or len(value) > limit
                or any(0xD800 <= ord(ch) <= 0xDFFF for ch in value)
                for value, limit in text_fields
            ):
                raise ToolValidationError(
                    "security-store backup contains invalid approval metadata"
                )
            if not _NAME_RE.fullmatch(tool_name) or not _DIGEST_RE.fullmatch(digest):
                raise ToolValidationError(
                    "security-store backup contains invalid approval identity or digest"
                )
            try:
                expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                consumed = datetime.fromisoformat(consumed_at.replace("Z", "+00:00"))
            except ValueError:
                raise ToolValidationError(
                    "security-store backup contains invalid approval timestamps"
                ) from None
            if (
                expiry.tzinfo is None or expiry.utcoffset() is None
                or consumed.tzinfo is None or consumed.utcoffset() is None
                or consumed >= expiry
            ):
                raise ToolValidationError(
                    "security-store backup contains inconsistent approval timestamps"
                )

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
                foreign_key_errors = destination.execute(
                    "PRAGMA foreign_key_check"
                ).fetchall()
                if not check or check[0] != "ok" or foreign_key_errors:
                    raise ToolValidationError(
                        "SQLite backup integrity or foreign-key check failed"
                    )
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
                return str(row[0]) if row else "no result"
            finally:
                connection.close()
