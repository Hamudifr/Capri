"""Shared private SQLite online-backup primitive for Capri stores."""
from __future__ import annotations

import errno
import os
import sqlite3
import stat
import tempfile
from typing import Callable, Type


def backup_sqlite_database(
    source_path: str,
    destination_path: str,
    *,
    lock,
    connect: Callable[[], sqlite3.Connection],
    validate_snapshot: Callable[[sqlite3.Connection], None],
    error_type: Type[Exception],
    prefix: str,
) -> str:
    """Create a consistent, private SQLite snapshot without overwriting a target.

    The source connection factory must apply the source store's normal security
    checks. The validator runs against the completed destination before publish.
    SQLite's online backup API includes committed WAL content; no live sidecars
    are copied. The parent directory must already exist and be private.
    """
    def fail(message: str) -> None:
        raise error_type(message)

    if not isinstance(destination_path, str) or not destination_path.strip():
        fail("backup destination must be a non-empty path")
    absolute = os.path.abspath(destination_path)
    if absolute == os.path.abspath(source_path):
        fail("backup destination must differ from the live database")
    parent = os.path.dirname(absolute)
    try:
        if not os.path.isdir(parent) or os.path.realpath(parent) != parent:
            fail("backup parent must be an existing non-symlink directory")
        parent_stat = os.stat(parent, follow_symlinks=False)
    except OSError:
        fail("backup parent is unavailable")
    if not stat.S_ISDIR(parent_stat.st_mode):
        fail("backup parent must be a directory")
    if os.name == "posix" and (
        parent_stat.st_uid != os.geteuid()
        or stat.S_IMODE(parent_stat.st_mode) & 0o077
    ):
        fail("backup parent must be owned by the current user and private")
    if os.path.lexists(absolute):
        fail("backup destination already exists")

    try:
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=prefix, suffix=".sqlite3", dir=parent
        )
        os.close(descriptor)
    except OSError:
        fail("private temporary backup could not be created")

    source = None
    destination = None
    published = False
    fallback_destination_identity = None
    try:
        with lock:
            source = connect()
            destination = sqlite3.connect(
                temporary_path, timeout=5.0, isolation_level=None
            )
            destination.execute("PRAGMA foreign_keys=ON")
            destination.execute("PRAGMA trusted_schema=OFF")
            destination.execute("PRAGMA synchronous=FULL")
            source.backup(destination, pages=128, sleep=0.05)
            integrity = destination.execute("PRAGMA integrity_check").fetchone()
            foreign_key_errors = destination.execute("PRAGMA foreign_key_check").fetchall()
            if not integrity or integrity[0] != "ok" or foreign_key_errors:
                fail("SQLite backup integrity or foreign-key check failed")
            validate_snapshot(destination)
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
                fail("temporary backup is not a regular file")
            if os.name == "posix":
                if info.st_uid != os.geteuid() or info.st_nlink != 1:
                    fail("temporary backup ownership or link count is invalid")
                os.fchmod(backup_fd, 0o600)
            os.fsync(backup_fd)
        finally:
            os.close(backup_fd)

        # Prefer an atomic no-replace hard-link publication. Some sandboxed
        # POSIX builds (including Termux Python) omit os.link entirely. In
        # that case reserve the destination with O_EXCL while its mode is
        # 000, copy and fsync the completed snapshot, then make it readable
        # as a private 0600 file. A crash during fallback leaves an unreadable
        # reservation rather than exposing a partial database or overwriting
        # an existing destination.
        link = getattr(os, "link", None)
        if callable(link):
            try:
                link(temporary_path, absolute, follow_symlinks=False)
            except (AttributeError, NotImplementedError, TypeError):
                link = None
            except OSError as exc:
                unsupported = {
                    errno.ENOSYS,
                    getattr(errno, "EOPNOTSUPP", errno.ENOSYS),
                    getattr(errno, "ENOTSUP", errno.ENOSYS),
                }
                if exc.errno in unsupported:
                    link = None
                else:
                    raise

        if callable(link):
            published = True
        else:
            destination_flags = (
                os.O_WRONLY | os.O_CREAT | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            destination_fd = os.open(
                absolute, destination_flags, 0 if os.name == "posix" else 0o600
            )
            try:
                destination_info = os.fstat(destination_fd)
                if not stat.S_ISREG(destination_info.st_mode):
                    fail("backup destination is not a regular file")
                if os.name == "posix" and destination_info.st_uid != os.geteuid():
                    fail("backup destination ownership is invalid")
                fallback_destination_identity = (
                    destination_info.st_dev, destination_info.st_ino
                )
                source_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                source_fd = os.open(temporary_path, source_flags)
                try:
                    while True:
                        chunk = os.read(source_fd, 1024 * 1024)
                        if not chunk:
                            break
                        view = memoryview(chunk)
                        while view:
                            written = os.write(destination_fd, view)
                            if written <= 0:
                                raise OSError("backup copy made no forward progress")
                            view = view[written:]
                finally:
                    os.close(source_fd)
                # Persist the complete copy while the reservation is still
                # unreadable. Only then grant owner read access and persist that
                # metadata change, so a crash cannot expose an unflushed snapshot.
                os.fsync(destination_fd)
                if os.name == "posix":
                    os.fchmod(destination_fd, 0o600)
                    os.fsync(destination_fd)
                published = True
            finally:
                os.close(destination_fd)

        os.unlink(temporary_path)
        if os.name == "posix":
            directory_fd = os.open(
                parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            )
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        return absolute
    except Exception as exc:
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
        if fallback_destination_identity is not None and not published:
            try:
                current = os.stat(absolute, follow_symlinks=False)
                if (current.st_dev, current.st_ino) == fallback_destination_identity:
                    os.unlink(absolute)
            except OSError:
                pass
        if published:
            fail("backup was published but directory durability could not be confirmed")
        if isinstance(exc, error_type):
            raise
        fail("SQLite backup failed; detailed filesystem or database errors were suppressed")
    raise error_type("SQLite backup failed")
