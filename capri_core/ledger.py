"""Append-only JSONL ledger with a verifiable SHA-256 hash chain."""
import hashlib
import json
import os
import re
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

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _scan(self, collect_entries: bool = False) -> tuple[list[dict[str, Any]], set[str], str, int]:
        """Validate the complete chain while retaining only IDs unless requested.

        Iterating the file avoids holding both its full text and all decoded
        entries in memory. The ID set remains O(number of records) because
        duplicate and parent-lineage checks require historical membership.
        """
        entries: list[dict[str, Any]] = []
        seen_runs: set[str] = set()
        previous = _ZERO_HASH
        count = 0
        if not self.path.exists():
            return entries, seen_runs, previous, count

        try:
            with self.path.open("r", encoding="utf-8", newline="") as stream:
                for line_number, line in enumerate(stream, 1):
                    # Accept the same LF/CRLF line endings as splitlines(), but
                    # do not silently skip blank records.
                    line = line.rstrip("\\r\\n")
                    try:
                        entry = json.loads(
                            line, object_pairs_hook=_unique_object, parse_constant=_reject_constant
                        )
                        if not isinstance(entry, dict) or set(entry) != _ENTRY_KEYS:
                            raise LedgerIntegrityError(f"invalid entry shape at line {line_number}")
                        payload = entry["record"]
                        digest = entry["hash"]
                        prev = entry["previous_hash"]
                        if not isinstance(payload, dict):
                            raise LedgerIntegrityError(f"record payload must be an object at line {line_number}")
                        if not _is_sha256(prev) or not _is_sha256(digest):
                            raise LedgerIntegrityError(f"invalid hash encoding at line {line_number}")
                        if prev != previous:
                            raise LedgerIntegrityError(f"broken previous-hash link at line {line_number}")
                        expected = hashlib.sha256(bytes.fromhex(previous) + _canonical(payload)).hexdigest()
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
                    except (json.JSONDecodeError, KeyError, TypeError, ValueError, RecordValidationError) as exc:
                        raise LedgerIntegrityError(f"invalid ledger entry at line {line_number}") from exc

                    seen_runs.add(run_id)
                    previous = digest
                    count += 1
                    if collect_entries:
                        entries.append(entry)
        except UnicodeDecodeError as exc:
            raise LedgerIntegrityError("ledger is not valid UTF-8") from exc
        return entries, seen_runs, previous, count

    def append(self, record: EvaluationRecord) -> str:
        validate_record(record)
        with _LOCK:
            _, existing_ids, previous, _ = self._scan()
            payload = record.to_dict()
            if payload["run_id"] in existing_ids:
                raise LedgerIntegrityError("run_id already exists; ledger is append-only")
            if payload["parent_run_id"] is not None and payload["parent_run_id"] not in existing_ids:
                raise LedgerIntegrityError("parent_run_id does not reference an earlier run")
            digest = hashlib.sha256(bytes.fromhex(previous) + _canonical(payload)).hexdigest()
            entry = {"previous_hash": previous, "record": payload, "hash": digest}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\\n") as stream:
                stream.write(json.dumps(entry, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\\n")
                stream.flush()
                os.fsync(stream.fileno())
            return digest

    def verify(self) -> dict[str, Any]:
        _, _, head_hash, count = self._scan()
        return {"valid": True, "records": count, "head_hash": head_hash if count else None}

    def records(self) -> list[EvaluationRecord]:
        entries, _, _, _ = self._scan(collect_entries=True)
        return [EvaluationRecord.from_dict(entry["record"]) for entry in entries]
