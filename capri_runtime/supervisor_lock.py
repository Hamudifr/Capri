"""Secure, opt-in single-host exclusion for worker-supervisor operations."""

from __future__ import annotations

import math
import os
import stat
import threading
import time
import weakref


_LOCK_REGISTRY_LOCK = threading.RLock()
_LOCK_REGISTRY: list[weakref.ReferenceType] = []
_FORK_HOOKS_AVAILABLE = hasattr(os, "register_at_fork")


def _before_fork() -> None:
    _LOCK_REGISTRY_LOCK.acquire()


def _after_fork_parent() -> None:
    _LOCK_REGISTRY_LOCK.release()


def _after_fork_child() -> None:
    try:
        for reference in tuple(_LOCK_REGISTRY):
            lock = reference()
            if lock is not None:
                lock._after_fork_in_child()
    finally:
        _LOCK_REGISTRY_LOCK.release()


if _FORK_HOOKS_AVAILABLE:
    os.register_at_fork(
        before=_before_fork,
        after_in_parent=_after_fork_parent,
        after_in_child=_after_fork_child,
    )


def _supports_secure_dirfd_walk() -> bool:
    dir_fd_support = getattr(os, "supports_dir_fd", set())
    follow_symlink_support = getattr(os, "supports_follow_symlinks", set())
    return (
        os.name == "posix"
        and hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "O_DIRECTORY")
        and os.open in dir_fd_support
        and os.stat in dir_fd_support
        and os.stat in follow_symlink_support
    )


def _open_parent_directory(path: str) -> tuple[int, str]:
    """Open every parent component without following symlinks or path fallbacks."""
    if not _supports_secure_dirfd_walk():
        raise OSError("secure POSIX directory-descriptor traversal is unavailable")

    absolute = os.path.abspath(path)
    name = os.path.basename(absolute)
    if not name or name in (".", ".."):
        raise ValueError("supervisor lock path must name a file")

    directory_flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | getattr(os, "O_CLOEXEC", 0)
    )
    current_fd = os.open(os.sep, directory_flags)
    try:
        os.set_inheritable(current_fd, False)
        components = [part for part in absolute.split(os.sep) if part]
        for component in components[:-1]:
            child_fd = os.open(
                component,
                directory_flags | os.O_NOFOLLOW,
                dir_fd=current_fd,
            )
            try:
                os.set_inheritable(child_fd, False)
                info = os.fstat(child_fd)
                if not stat.S_ISDIR(info.st_mode):
                    raise PermissionError("supervisor lock parent path contains a non-directory")
                if info.st_uid not in (0, os.geteuid()):
                    raise PermissionError("supervisor lock parent path contains an untrusted owner")
                if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                    root_sticky_directory = (
                        info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
                    )
                    if not root_sticky_directory:
                        raise PermissionError(
                            "supervisor lock parent path contains a directory writable by untrusted principals"
                        )
            except BaseException:
                os.close(child_fd)
                raise

            previous_fd = current_fd
            current_fd = child_fd
            os.close(previous_fd)

        parent_info = os.fstat(current_fd)
        if (
            not stat.S_ISDIR(parent_info.st_mode)
            or parent_info.st_uid != os.geteuid()
            or stat.S_IMODE(parent_info.st_mode) & 0o077
        ):
            raise PermissionError(
                "supervisor lock parent must be an owner-private directory"
            )

        result = current_fd
        current_fd = -1
        return result, name
    finally:
        if current_fd >= 0:
            os.close(current_fd)


class PosixSupervisorLock:
    """Re-entrant POSIX file lock shared by every supervisor on one host.

    The lock path must be identical for all processes protecting the same worker
    registry and lifecycle-audit stores. This is single-host exclusion, not a
    distributed lease or a cryptographic fencing token. The final parent
    directory must be service-owned and private; the lock file is persistent
    and must never be unlinked or replaced while a supervisor may be running.

    Create one lock object per process after fork. A Python at-fork hook closes
    inherited descriptors in the child and makes the inherited object unusable.
    The caller owns the lock object's lifetime and must close it after the
    runtime stops. Use a local filesystem, not a network-mounted lock path.
    """

    def __init__(self, path: str, *, timeout_seconds: float = 5.0) -> None:
        if os.name != "posix":
            raise OSError("POSIX supervisor locking is unavailable on this platform")
        if not _FORK_HOOKS_AVAILABLE:
            raise OSError("safe inherited-descriptor cleanup after fork is unavailable")
        if not _supports_secure_dirfd_walk():
            raise OSError("secure POSIX directory-descriptor traversal is unavailable")
        if type(path) is not str or not path or "\x00" in path:
            raise ValueError("supervisor lock path must be a non-empty string")
        if type(timeout_seconds) not in (int, float):
            raise ValueError("supervisor lock timeout must be a finite number")
        try:
            timeout = float(timeout_seconds)
        except (OverflowError, ValueError):
            raise ValueError("supervisor lock timeout must be finite") from None
        if not math.isfinite(timeout) or timeout <= 0 or timeout > 60:
            raise ValueError(
                "supervisor lock timeout must be finite and between 0 and 60 seconds"
            )

        try:
            import fcntl
        except ImportError:
            raise OSError("POSIX flock is unavailable") from None

        absolute = os.path.abspath(path)
        _LOCK_REGISTRY_LOCK.acquire()
        parent_fd: int | None = None
        fd: int | None = None
        try:
            parent_fd, name = _open_parent_directory(absolute)
            flags = os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
            fd = os.open(name, flags, 0o600, dir_fd=parent_fd)
            os.set_inheritable(fd, False)

            file_stat = os.fstat(fd)
            path_stat = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
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

            self.path = absolute
            self._name = name
            self._fd = fd
            self._parent_fd = parent_fd
            self._fcntl = fcntl
            self._timeout_seconds = timeout
            self._owner_pid = os.getpid()
            self._thread_lock = threading.RLock()
            self._local = threading.local()
            self._closed = False
            self._file_identity = (file_stat.st_dev, file_stat.st_ino)
            self._assert_path_identity()

            _LOCK_REGISTRY[:] = [
                reference for reference in _LOCK_REGISTRY if reference() is not None
            ]
            _LOCK_REGISTRY.append(weakref.ref(self))
            fd = None
            parent_fd = None
        finally:
            if fd is not None:
                os.close(fd)
            if parent_fd is not None:
                os.close(parent_fd)
            _LOCK_REGISTRY_LOCK.release()

    def _assert_path_identity(self) -> None:
        with _LOCK_REGISTRY_LOCK:
            current_parent_fd, current_name = _open_parent_directory(self.path)
            try:
                original_parent = os.fstat(self._parent_fd)
                current_parent = os.fstat(current_parent_fd)
                if (
                    current_name != self._name
                    or (original_parent.st_dev, original_parent.st_ino)
                    != (current_parent.st_dev, current_parent.st_ino)
                ):
                    raise PermissionError("supervisor lock parent path was replaced")
            finally:
                os.close(current_parent_fd)

            try:
                file_stat = os.fstat(self._fd)
                path_stat = os.stat(
                    self._name,
                    dir_fd=self._parent_fd,
                    follow_symlinks=False,
                )
            except OSError:
                raise PermissionError("supervisor lock path was removed or replaced") from None

            if (
                not stat.S_ISREG(file_stat.st_mode)
                or file_stat.st_uid != os.geteuid()
                or stat.S_IMODE(file_stat.st_mode) != 0o600
                or file_stat.st_nlink != 1
                or (file_stat.st_dev, file_stat.st_ino) != self._file_identity
                or (file_stat.st_dev, file_stat.st_ino)
                != (path_stat.st_dev, path_stat.st_ino)
            ):
                raise PermissionError("supervisor lock file identity or security properties changed")

    def __enter__(self) -> "PosixSupervisorLock":
        deadline = time.monotonic() + self._timeout_seconds
        if not self._thread_lock.acquire(timeout=self._timeout_seconds):
            raise TimeoutError("timed out waiting for the local supervisor lock")
        try:
            if os.getpid() != self._owner_pid:
                raise RuntimeError("open a separate supervisor lock descriptor after fork")
            if self._closed:
                raise RuntimeError("supervisor lock is closed")

            depth = getattr(self._local, "depth", 0)
            if depth == 0:
                self._assert_path_identity()
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("timed out waiting for the host supervisor lock")
                    try:
                        self._fcntl.flock(
                            self._fd,
                            self._fcntl.LOCK_EX | self._fcntl.LOCK_NB,
                        )
                        break
                    except BlockingIOError:
                        time.sleep(min(0.01, remaining))

                try:
                    self._assert_path_identity()
                except BaseException:
                    try:
                        self._fcntl.flock(self._fd, self._fcntl.LOCK_UN)
                    except OSError:
                        fd = self._fd
                        self._fd = -1
                        self._closed = True
                        try:
                            os.close(fd)
                        except OSError:
                            pass
                    raise

            self._local.depth = depth + 1
            return self
        except BaseException:
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
                try:
                    self._fcntl.flock(self._fd, self._fcntl.LOCK_UN)
                except OSError:
                    fd = self._fd
                    self._fd = -1
                    self._closed = True
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                    raise
            else:
                self._local.depth = depth - 1
        finally:
            self._thread_lock.release()
        return False

    def _after_fork_in_child(self) -> None:
        """Close inherited open-file descriptions without unlocking the parent."""
        descriptors = (self._fd, self._parent_fd)
        self._fd = -1
        self._parent_fd = -1
        self._closed = True
        self._thread_lock = threading.RLock()
        self._local = threading.local()
        for descriptor in descriptors:
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    def close(self) -> None:
        """Close descriptors after all runtime operations have stopped."""
        if os.getpid() != self._owner_pid:
            if self._closed:
                return
            raise RuntimeError("an inherited supervisor lock cannot close the parent process descriptors")
        if getattr(self._local, "depth", 0):
            raise RuntimeError("cannot close a supervisor lock while it is held")

        with self._thread_lock:
            _LOCK_REGISTRY_LOCK.acquire()
            try:
                if self._closed:
                    return
                descriptors = (self._fd, self._parent_fd)
                self._fd = -1
                self._parent_fd = -1
                self._closed = True

                close_error: OSError | None = None
                for descriptor in descriptors:
                    if descriptor >= 0:
                        try:
                            os.close(descriptor)
                        except OSError as exc:
                            if close_error is None:
                                close_error = exc

                retained = []
                for reference in _LOCK_REGISTRY:
                    target = reference()
                    if target is not None and target is not self:
                        retained.append(reference)
                _LOCK_REGISTRY[:] = retained
                if close_error is not None:
                    raise close_error
            finally:
                _LOCK_REGISTRY_LOCK.release()
