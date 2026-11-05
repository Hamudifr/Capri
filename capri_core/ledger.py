"""Append-only JSONL ledger with a verifiable SHA-256 hash chain."""
import hashlib
import json
import os
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
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        bytes.fromhex(value)
    except ValueError:
        return False
    return True


class HashChainLedger:
    """Append immutable records; each entry commits to the previous entry hash.

    This implementation serializes threads in one process. Deployments must use
    exactly one writer process per ledger file; it does not provide distributed
    or cross-process locking.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _read_entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        entries: list[dict[str, Any]] = []
        previous = _ZERO_HASH
        seen_runs: set[str] = set()
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                entry = json.loads(line)
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
            entries.append(entry)
        return entries

    def append(self, record: EvaluationRecord) -> str:
        validate_record(record)
        with _LOCK:
            entries = self._read_entries()
            payload = record.to_dict()
            existing_ids = {entry["record"]["run_id"] for entry in entries}
            if payload["run_id"] in existing_ids:
                raise LedgerIntegrityError("run_id already exists; ledger is append-only")
            if payload["parent_run_id"] is not None and payload["parent_run_id"] not in existing_ids:
                raise LedgerIntegrityError("parent_run_id does not reference an earlier run")
            previous = entries[-1]["hash"] if entries else _ZERO_HASH
            digest = hashlib.sha256(bytes.fromhex(previous) + _canonical(payload)).hexdigest()
            entry = {"previous_hash": previous, "record": payload, "hash": digest}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            return digest

    def verify(self) -> dict[str, Any]:
        entries = self._read_entries()
        return {
            "valid": True,
            "records": len(entries),
            "head_hash": entries[-1]["hash"] if entries else None,
        }

    def records(self) -> list[EvaluationRecord]:
        return [EvaluationRecord.from_dict(entry["record"]) for entry in self._read_entries()]
