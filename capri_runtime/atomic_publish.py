"""Atomic filesystem publication primitives with no-overwrite semantics."""
from __future__ import annotations

import ctypes
import errno
import os
import sys
from typing import Callable

_AT_FDCWD = -100
_RENAME_NOREPLACE = 1


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
    if callable(link):
        link(source_path, destination_path, follow_symlinks=False)
        return "hard-link"

    renameat2 = _load_renameat2()
    if renameat2 is None:
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
