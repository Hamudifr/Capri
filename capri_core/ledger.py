"""Append-only JSONL ledger with a verifiable SHA-256 hash chain."""
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from threading import RLock
from typing import Any

from .models import EvaluationRecord
from .validation import RecordValidationError, validate_record


class LedgerIntegrityError(ValueError):
    pass


_LOCK = RLock()
_ZERO_HASH = "0" * 64
_ENTRY_KEYS = {"previous_hash", "record", "hash"}
_UNCERTAIN_PATHS: set[str] = set()


def _absolute_path(path: str | Path) -> Path:
    candidate = Path(path)
    if ".." in candidate.parts:
        raise LedgerIntegrityError("ledger paths must not contain parent-traversal components")
    try:
        return Path(os.path.abspath(os.fspath(candidate)))
    except (OSError, TypeError, ValueError) as exc:
        raise LedgerIntegrityError("ledger path is invalid") from exc


def _path_key(path: str | Path) -> str:
    return os.fspath(_absolute_path(path))


def _assert_not_uncertain(path: str | Path) -> None:
    if _path_key(path) in _UNCERTAIN_PATHS:
        raise LedgerIntegrityError(
            "a previous append failed after writing began; preserve the ledger and inspect a copy before further use"
        )


def _close_fd(descriptor: int | None) -> None:
    if descriptor is None:
        return
    try:
        os.close(descriptor)
    except OSError:
        pass


def _supports_secure_dirfd_walk() -> bool:
    supported = getattr(os, "supports_dir_fd", set())
    return (
        os.name == "posix"
        and hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "O_DIRECTORY")
        and os.open in supported
        and os.mkdir in supported
    )


def _open_parent_directory(path: Path, *, create: bool) -> int:
    """Open every parent component without following symlinks where supported."""
    absolute = _absolute_path(path)
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)

    if _supports_secure_dirfd_walk():
        current_fd: int | None = None
        try:
            current_fd = os.open(absolute.anchor, directory_flags)
            for component in absolute.parts[1:]:
                flags = directory_flags | os.O_NOFOLLOW
                created_child = False
                try:
                    child_fd = os.open(component, flags, dir_fd=current_fd)
                except FileNotFoundError:
                    if not create:
                        raise
                    try:
                        os.mkdir(component, 0o700, dir_fd=current_fd)
                        created_child = True
                    except FileExistsError:
                        pass
                    try:
                        child_fd = os.open(component, flags, dir_fd=current_fd)
                    except OSError as exc:
                        raise LedgerIntegrityError(
                            "ledger parent path contains a symlink or is not a safe directory"
                        ) from exc
                except OSError as exc:
                    raise LedgerIntegrityError(
                        "ledger parent path contains a symlink or is not a safe directory"
                    ) from exc

                try:
                    if not stat.S_ISDIR(os.fstat(child_fd).st_mode):
                        raise LedgerIntegrityError("ledger parent path is not a directory")
                    if created_child:
                        # Persist both the new directory's metadata and its name
                        # in the parent before relying on it for ledger creation.
                        os.fsync(child_fd)
                        os.fsync(current_fd)
                except BaseException:
                    _close_fd(child_fd)
                    raise
                previous_fd = current_fd
                current_fd = child_fd
                _close_fd(previous_fd)

            result = current_fd
            current_fd = None
            return result
        finally:
            _close_fd(current_fd)

    # Fallback for platforms without atomic dir_fd/O_NOFOLLOW traversal. lstat
    # rejects observed symlinks, but a concurrent path swap cannot be excluded.
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current = current / component
        created_child = False
        try:
            info = current.lstat()
        except FileNotFoundError:
            if not create:
                raise
            try:
                current.mkdir(mode=0o700)
                created_child = True
            except FileExistsError:
                pass
            info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise LedgerIntegrityError("ledger parent path must contain only real directories")
        if created_child:
            child_fd = os.open(current, directory_flags)
            parent_fd = os.open(current.parent, directory_flags)
            try:
                os.fsync(child_fd)
                os.fsync(parent_fd)
            finally:
                _close_fd(child_fd)
                _close_fd(parent_fd)

    descriptor = os.open(current, directory_flags)
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        _close_fd(descriptor)
        raise LedgerIntegrityError("ledger parent path is not a directory")
    return descriptor


def _open_ledger_file(
    path: Path, parent_fd: int, *, create: bool, writable: bool
) -> tuple[int, bool]:
    """Open a regular ledger file and report whether this call created it."""
    absolute = _absolute_path(path)
    flags = (os.O_RDWR | os.O_APPEND) if writable else os.O_RDONLY
    flags |= getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is not None:
        flags |= nofollow

    # Without O_NOFOLLOW, reject observed symlinks before opening. This fallback
    # is deliberately documented as weaker because it cannot close a TOCTOU race.
    if nofollow is None:
        try:
            info = absolute.lstat()
        except FileNotFoundError:
            if not create:
                raise
        else:
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                raise LedgerIntegrityError("ledger path must be a regular file, not a symlink")

    use_dir_fd = os.open in getattr(os, "supports_dir_fd", set())
    target: str | Path = absolute.name if use_dir_fd else absolute
    open_kwargs = {"dir_fd": parent_fd} if use_dir_fd else {}
    created = False

    if create:
        try:
            descriptor = os.open(target, flags | os.O_CREAT | os.O_EXCL, 0o600, **open_kwargs)
            created = True
        except FileExistsError:
            if nofollow is None:
                try:
                    info = absolute.lstat()
                except FileNotFoundError:
                    raise
                if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                    raise LedgerIntegrityError("ledger path must be a regular file, not a symlink")
            descriptor = os.open(target, flags, **open_kwargs)
    else:
        descriptor = os.open(target, flags, **open_kwargs)

    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise LedgerIntegrityError("ledger path is not an existing regular file")
        return descriptor, created
    except BaseException:
        _close_fd(descriptor)
        raise


def _write_entry(stream: Any, data: bytes) -> None:
    written = stream.write(data)
    if written != len(data):
        raise OSError("short write while appending ledger entry")


def _flush_entry(stream: Any) -> None:
    stream.flush()


def _fsync_file(descriptor: int) -> None:
    os.fsync(descriptor)


def _fsync_directory(descriptor: int) -> None:
    os.fsync(descriptor)


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate JSON keys instead of silently accepting the last value."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


class HashChainLedger:
    """Append immutable records; each entry commits to the previous entry hash.

    This implementation serializes threads in one process. Deployments must use
    exactly one writer process per ledger file; it does not provide distributed
    or cross-process locking.
    """

    def __init__(self, path: str | Path, *, max_entry_bytes: int = 1_048_576):
        if isinstance(max_entry_bytes, bool) or not isinstance(max_entry_bytes, int) or max_entry_bytes < 1:
            raise ValueError("max_entry_bytes must be a positive integer")
        self.path = _absolute_path(path)
        if not self.path.name:
            raise ValueError("ledger path must name a file")
        self.max_entry_bytes = max_entry_bytes

    def _scan(
        self, collect_entries: bool = False, *, descriptor: int | None = None, missing_ok: bool = True
    ) -> tuple[list[dict[str, Any]], set[str], str, int]:
        """Validate a bounded JSONL stream, retaining IDs and optionally entries.

        Binary bounded reads enforce the per-entry byte ceiling before UTF-8
        decoding or JSON parsing. The ID set remains O(number of records)
        because duplicate and parent-lineage checks require historical membership.
        """
        entries: list[dict[str, Any]] = []
        seen_runs: set[str] = set()
        previous = _ZERO_HASH
        count = 0
        owned_parent_fd: int | None = None
        owned_file_fd: int | None = None

        try:
            if descriptor is None:
                _assert_not_uncertain(self.path)
                try:
                    owned_parent_fd = _open_parent_directory(self.path.parent, create=False)
                    owned_file_fd, _ = _open_ledger_file(
                        self.path, owned_parent_fd, create=False, writable=False
                    )
                    descriptor = owned_file_fd
                except FileNotFoundError as exc:
                    if missing_ok:
                        return entries, seen_runs, previous, count
                    raise LedgerIntegrityError("ledger is not an existing regular file") from exc

            with os.fdopen(os.dup(descriptor), "rb") as stream:
                line_number = 0
                while True:
                    raw_line = stream.readline(self.max_entry_bytes + 3)
                    if not raw_line:
                        break
                    line_number += 1
                    # Permit at most max bytes plus CRLF. The extra byte makes
                    # an oversized line detectable without unbounded readline().
                    if len(raw_line) > self.max_entry_bytes + 2:
                        raise LedgerIntegrityError(
                            f"entry exceeds {self.max_entry_bytes} bytes at line {line_number}"
                        )
                    if not raw_line.endswith(b"\n"):
                        raise LedgerIntegrityError(f"unterminated ledger entry at line {line_number}")
                    raw_line = raw_line[:-1]
                    if raw_line.endswith(b"\r"):
                        raw_line = raw_line[:-1]
                    if len(raw_line) > self.max_entry_bytes:
                        raise LedgerIntegrityError(
                            f"entry exceeds {self.max_entry_bytes} bytes at line {line_number}"
                        )
                    try:
                        line = raw_line.decode("utf-8")
                        entry = json.loads(
                            line, object_pairs_hook=_unique_object, parse_constant=_reject_constant
                        )
                        if not isinstance(entry, dict) or set(entry) != _ENTRY_KEYS:
                            raise LedgerIntegrityError(f"invalid entry shape at line {line_number}")
                        payload = entry["record"]
                        digest = entry["hash"]
                        prev = entry["previous_hash"]
                        if not isinstance(payload, dict):
                            raise LedgerIntegrityError(
                                f"record payload must be an object at line {line_number}"
                            )
                        if not _is_sha256(prev) or not _is_sha256(digest):
                            raise LedgerIntegrityError(f"invalid hash encoding at line {line_number}")
                        if prev != previous:
                            raise LedgerIntegrityError(
                                f"broken previous-hash link at line {line_number}"
                            )
                        expected = hashlib.sha256(
                            bytes.fromhex(previous) + _canonical(payload)
                        ).hexdigest()
                        if digest != expected:
                            raise LedgerIntegrityError(f"hash mismatch at line {line_number}")

                        record = EvaluationRecord.from_dict(payload)
                        validate_record(record)
                        run_id = record.run_id
                        if run_id in seen_runs:
                            raise LedgerIntegrityError(f"duplicate run_id at line {line_number}")
                        if record.parent_run_id is not None and record.parent_run_id not in seen_runs:
                            raise LedgerIntegrityError(f"unknown parent_run_id at line {line_number}")
                    except LedgerIntegrityError:
                        raise
                    except (
                        UnicodeDecodeError,
                        json.JSONDecodeError,
                        KeyError,
                        TypeError,
                        ValueError,
                        RecordValidationError,
                        RecursionError,
                    ) as exc:
                        raise LedgerIntegrityError(f"invalid ledger entry at line {line_number}") from exc

                    seen_runs.add(run_id)
                    previous = digest
                    count += 1
                    if collect_entries:
                        entries.append(entry)
        except LedgerIntegrityError:
            raise
        except OSError as exc:
            raise LedgerIntegrityError("ledger could not be read completely") from exc
        finally:
            _close_fd(owned_file_fd)
            _close_fd(owned_parent_fd)

        return entries, seen_runs, previous, count

    def append(self, record: EvaluationRecord) -> str:
        validate_record(record)
        with _LOCK:
            key = _path_key(self.path)
            _assert_not_uncertain(self.path)
            parent_fd: int | None = None
            descriptor: int | None = None
            stream: Any = None
            write_started = False
            try:
                parent_fd = _open_parent_directory(self.path.parent, create=True)
                # Inspect an existing file without creating a new one. This keeps
                # validation failures (including an oversized first record) from
                # leaving an empty ledger behind.
                try:
                    descriptor, created = _open_ledger_file(
                        self.path, parent_fd, create=False, writable=True
                    )
                except FileNotFoundError:
                    descriptor = None
                    created = True
                    existing_ids: set[str] = set()
                    previous = _ZERO_HASH
                else:
                    _, existing_ids, previous, _ = self._scan(descriptor=descriptor)

                payload = record.to_dict()

                def build_entry(previous_hash: str, known_ids: set[str]) -> tuple[str, bytes]:
                    if payload["run_id"] in known_ids:
                        raise LedgerIntegrityError("run_id already exists; ledger is append-only")
                    if payload["parent_run_id"] is not None and payload["parent_run_id"] not in known_ids:
                        raise LedgerIntegrityError("parent_run_id does not reference an earlier run")
                    entry_hash = hashlib.sha256(
                        bytes.fromhex(previous_hash) + _canonical(payload)
                    ).hexdigest()
                    entry = {
                        "previous_hash": previous_hash,
                        "record": payload,
                        "hash": entry_hash,
                    }
                    serialized = json.dumps(
                        entry, sort_keys=True, ensure_ascii=False, allow_nan=False
                    )
                    encoded_entry = serialized.encode("utf-8")
                    if len(encoded_entry) > self.max_entry_bytes:
                        raise LedgerIntegrityError(
                            f"new entry exceeds {self.max_entry_bytes} bytes"
                        )
                    return entry_hash, encoded_entry

                digest, encoded = build_entry(previous, existing_ids)

                if descriptor is None:
                    # Create only after the first entry has passed size and lineage
                    # validation. Re-scan after opening in case a file appeared
                    # between the initial no-follow lookup and exclusive creation.
                    descriptor, created = _open_ledger_file(
                        self.path, parent_fd, create=True, writable=True
                    )
                    _, existing_ids, previous, _ = self._scan(descriptor=descriptor)
                    digest, encoded = build_entry(previous, existing_ids)

                # Tighten an existing file only after integrity, lineage, and size checks pass.
                if os.name == "posix" and hasattr(os, "fchmod"):
                    os.fchmod(descriptor, 0o600)

                stream = os.fdopen(descriptor, "ab")
                descriptor = None
                write_started = True
                _write_entry(stream, encoded + b"\n")
                _flush_entry(stream)
                _fsync_file(stream.fileno())
                stream.close()
                stream = None
                if created and os.name == "posix":
                    _fsync_directory(parent_fd)
                return digest
            except BaseException as exc:
                if write_started:
                    _UNCERTAIN_PATHS.add(key)
                if isinstance(exc, OSError):
                    raise LedgerIntegrityError(
                        "ledger append failed after opening the file; preserve it and inspect a copy before retrying"
                    ) from exc
                raise
            finally:
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        if write_started:
                            _UNCERTAIN_PATHS.add(key)
                _close_fd(descriptor)
                _close_fd(parent_fd)

    def verify(self) -> dict[str, Any]:
        with _LOCK:
            _, _, head_hash, count = self._scan(missing_ok=False)
            return {"valid": True, "records": count, "head_hash": head_hash if count else None}

    def records(self) -> list[EvaluationRecord]:
        with _LOCK:
            entries, _, _, _ = self._scan(collect_entries=True, missing_ok=False)
            return [EvaluationRecord.from_dict(entry["record"]) for entry in entries]
