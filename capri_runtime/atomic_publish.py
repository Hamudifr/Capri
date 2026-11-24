"""Atomic filesystem publication primitives with no-overwrite semantics."""
from __future__ import annotations

import ctypes
import errno
import os
import sys
from typing import Callable

_AT_FDCWD = -100
_RENAME_NOREPLACE = 1
_HARD_LINK_FALLBACK_ERRNOS = frozenset(
    code for code in (
        getattr(errno, "EINVAL", None),
        getattr(errno, "ENOSYS", None),
        getattr(errno, "ENOTSUP", None),
        getattr(errno, "EOPNOTSUPP", None),
        getattr(errno, "EMLINK", None),
    ) if code is not None
)


def _load_renameat2() -> Callable | None:
    """Return libc renameat2 when the host exports it, otherwise None."""
    if os.name != "posix" or not sys.platform.startswith(("linux", "android")):
        return None
    try:
        function = getattr(ctypes.CDLL(None, use_errno=True), "renameat2", None)
    except (OSError, AttributeError):
        return None
    if function is None:
        return None
    function.argtypes = [
        ctypes.c_int, ctypes.c_char_p,
        ctypes.c_int, ctypes.c_char_p,
        ctypes.c_uint,
    ]
    function.restype = ctypes.c_int
    return function


def publish_no_replace(source_path: str, destination_path: str) -> str:
    """Atomically publish source without replacing an existing destination.

    Returns the primitive used: hard-link or renameat2. The hard-link path leaves
    source cleanup to the caller so publication state can be recorded first.
    """
    link = getattr(os, "link", None)
    link_error = None
    if callable(link):
        try:
            link(source_path, destination_path, follow_symlinks=False)
            return "hard-link"
        except NotImplementedError:
            pass
        except OSError as error:
            if error.errno not in _HARD_LINK_FALLBACK_ERRNOS:
                raise
            link_error = error

    renameat2 = _load_renameat2()
    if renameat2 is None:
        if link_error is not None:
            raise link_error
        raise OSError(
            errno.ENOTSUP,
            "atomic no-replace publication is unavailable on this platform",
            destination_path,
        )

    result = renameat2(
        _AT_FDCWD, os.fsencode(source_path),
        _AT_FDCWD, os.fsencode(destination_path),
        _RENAME_NOREPLACE,
    )
    if result != 0:
        error_number = ctypes.get_errno() or errno.EIO
        raise OSError(error_number, os.strerror(error_number), destination_path)
    return "renameat2"
