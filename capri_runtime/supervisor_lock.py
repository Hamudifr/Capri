"""Secure, opt-in single-host exclusion for worker-supervisor operations."""

from __future__ import annotations

import math
import os
import stat
import threading
import time


class PosixSupervisorLock:
    """Re-entrant POSIX file lock shared by every supervisor on one host.

    The lock path must be identical for all processes protecting the same worker
    registry and lifecycle-audit stores. This is single-host exclusion, not a
    distributed lease or a cryptographic fencing token. Create one lock object
    per process after fork; never share an inherited open descriptor. The caller
    owns the lock object's lifetime and must close it after the runtime stops.
    """

    def __init__(self, path: str, *, timeout_seconds: float = 5.0) -> None:
        if os.name != "posix":
            raise OSError("POSIX supervisor locking is unavailable on this platform")
        if type(path) is not str or not path or "\x00" in path:
            raise ValueError("supervisor lock path must be a non-empty string")
        if type(timeout_seconds) not in (int, float):
            raise ValueError("supervisor lock timeout must be a finite number")
        try:
            timeout = float(timeout_seconds)
        except (OverflowError, ValueError):
            raise ValueError("supervisor lock timeout must be finite") from None
        if not math.isfinite(timeout) or timeout <= 0 or timeout > 60:
            raise ValueError("supervisor lock timeout must be finite and between 0 and 60 seconds")

        try:
            import fcntl
        except ImportError:
            raise OSError("POSIX flock is unavailable") from None

        absolute = os.path.abspath(path)
        parent = os.path.dirname(absolute)
        if os.path.realpath(parent) != parent:
            raise PermissionError("supervisor lock parent must not traverse symlinks")
        parent_stat = os.stat(parent, follow_symlinks=False)
        if (
            not stat.S_ISDIR(parent_stat.st_mode)
            or parent_stat.st_uid != os.geteuid()
            or stat.S_IMODE(parent_stat.st_mode) & 0o077
        ):
            raise PermissionError("supervisor lock parent must be an owner-private directory")

        no_follow = getattr(os, "O_NOFOLLOW", None)
        if no_follow is None:
            raise OSError("safe no-follow lock-file open is unavailable")
        flags = os.O_CREAT | os.O_RDWR | no_follow | getattr(os, "O_CLOEXEC", 0)
        fd = os.open(absolute, flags, 0o600)
        try:
            os.set_inheritable(fd, False)
            file_stat = os.fstat(fd)
            path_stat = os.stat(absolute, follow_symlinks=False)
            if (
                not stat.S_ISREG(file_stat.st_mode)
                or file_stat.st_uid != os.geteuid()
                or stat.S_IMODE(file_stat.st_mode) != 0o600
                or file_stat.st_nlink != 1
                or (file_stat.st_dev, file_stat.st_ino)
                    != (path_stat.st_dev, path_stat.st_ino)
            ):
                raise PermissionError(
                    "supervisor lock file must be owner-owned, mode 0600, regular and single-link"
                )
        except Exception:
            os.close(fd)
            raise

        self.path = absolute
        self._fd = fd
        self._fcntl = fcntl
        self._timeout_seconds = timeout
        self._owner_pid = os.getpid()
        self._thread_lock = threading.RLock()
        self._local = threading.local()
        self._closed = False

    def __enter__(self) -> "PosixSupervisorLock":
        if not self._thread_lock.acquire(timeout=self._timeout_seconds):
            raise TimeoutError("timed out waiting for the local supervisor lock")
        try:
            if self._closed:
                raise RuntimeError("supervisor lock is closed")
            if os.getpid() != self._owner_pid:
                raise RuntimeError("open a separate supervisor lock descriptor after fork")
            depth = getattr(self._local, "depth", 0)
            if depth == 0:
                deadline = time.monotonic() + self._timeout_seconds
                while True:
                    try:
                        self._fcntl.flock(
                            self._fd,
                            self._fcntl.LOCK_EX | self._fcntl.LOCK_NB,
                        )
                        break
                    except BlockingIOError:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError("timed out waiting for the host supervisor lock")
                        time.sleep(min(0.01, remaining))
            self._local.depth = depth + 1
            return self
        except Exception:
            self._thread_lock.release()
            raise

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        if os.getpid() != self._owner_pid:
            raise RuntimeError("an inherited supervisor lock cannot release the parent process lock")
        depth = getattr(self._local, "depth", 0)
        if depth < 1:
            raise RuntimeError("supervisor lock context is unbalanced")
        try:
            if depth == 1:
                del self._local.depth
                self._fcntl.flock(self._fd, self._fcntl.LOCK_UN)
            else:
                self._local.depth = depth - 1
        finally:
            self._thread_lock.release()
        return False

    def close(self) -> None:
        """Close the descriptor after all runtime operations have stopped."""
        if getattr(self._local, "depth", 0):
            raise RuntimeError("cannot close a supervisor lock while it is held")
        with self._thread_lock:
            if self._closed:
                return
            os.close(self._fd)
            self._closed = True
