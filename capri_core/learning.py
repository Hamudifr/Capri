"""Privacy-gated, outcome-based training-data curation for Capri.

This module prepares auditable JSONL examples. It does not train models or
change the weights of a hosted model. Raw task content is accepted only after
explicit consent and a human privacy review.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

Outcome = Literal["verified_success", "verified_failure", "unverified"]
Split = Literal["train", "validation", "test"]


@dataclass(frozen=True)
class LearningExample:
    example_id: str
    task_id: str
    capability: str
    prompt: str
    completion: str
    outcome: Outcome
    evidence_ref: str
    quality_score: float
    consent: bool
    privacy_reviewed: bool
    sensitive: bool = False
    source: str = "capri_task"
    schema_version: int = 1


class LearningDataError(ValueError):
    """Raised when an example fails the learning-data admission contract."""


def _require_private_directory(directory: Path) -> None:
    """Create/check an owner-only POSIX directory without unsafe path ancestors."""
    if os.name != "posix":
        raise LearningDataError("learning-data storage requires verifiable POSIX permissions")
    absolute = Path(os.path.abspath(directory))
    if os.path.realpath(absolute) != str(absolute):
        raise LearningDataError("learning-data directory path must not contain symlinks")

    missing: list[Path] = []
    current = absolute
    while True:
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            missing.append(current)
            if current.parent == current:
                raise LearningDataError("unable to locate a safe parent directory")
            current = current.parent
            continue
        except OSError as exc:
            raise LearningDataError("unable to inspect learning-data directory path") from exc
        if not stat.S_ISDIR(info.st_mode):
            raise LearningDataError("learning-data directory path contains a symlink or non-directory")
        break

    owner = os.geteuid()
    for ancestor in (current, *current.parents):
        info = os.lstat(ancestor)
        mode = stat.S_IMODE(info.st_mode)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, owner):
            raise LearningDataError("learning-data path ancestors must be owned by root or the current user")
        if mode & 0o022 and not mode & stat.S_ISVTX:
            raise LearningDataError("learning-data path ancestor is group/other writable without sticky protection")

    for path in reversed(missing):
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
        except OSError as exc:
            raise LearningDataError("unable to create private learning-data directory") from exc
        info = os.lstat(path)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != owner or stat.S_IMODE(info.st_mode) != 0o700:
            raise LearningDataError("new learning-data directories must be owned and mode 0700")

    info = os.lstat(absolute)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != owner or stat.S_IMODE(info.st_mode) != 0o700:
        raise LearningDataError("learning-data directory must be owned by the current user with mode 0700")


def _ensure_private_database_file(path: Path) -> None:
    """Create a 0600 database or reject unsafe existing files and symlinks."""
    flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    created = False
    descriptor = -1
    try:
        try:
            descriptor = os.open(path, flags | os.O_CREAT | os.O_EXCL, 0o600)
            created = True
        except FileExistsError:
            descriptor = os.open(path, flags)
        info = os.fstat(descriptor)
        mode = stat.S_IMODE(info.st_mode)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
            raise LearningDataError("learning database must be an owned regular file")
        if created:
            os.fchmod(descriptor, 0o600)
        elif mode & 0o077 or mode & 0o600 != 0o600:
            raise LearningDataError("existing learning database must be owner-only (0600)")
    except OSError as exc:
        if created:
            try:
                os.unlink(path)
            except OSError:
                pass
        raise LearningDataError("unable to create or inspect learning database securely") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class LearningStore:
    """Local SQLite journal; raw content is stored only after explicit gates."""

    def __init__(self, database: str | Path) -> None:
        path = Path(database)
        _require_private_directory(path.parent)
        _ensure_private_database_file(path)
        self.database = str(path)
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS learning_examples (
                    example_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    completion TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    evidence_ref TEXT NOT NULL,
                    quality_score REAL NOT NULL,
                    consent INTEGER NOT NULL,
                    privacy_reviewed INTEGER NOT NULL,
                    sensitive INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_learning_task ON learning_examples(task_id)"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _validate(example: LearningExample) -> None:
        if type(example.schema_version) is not int or example.schema_version != 1:
            raise LearningDataError("unsupported schema_version")
        for name in ("example_id", "task_id", "capability", "prompt",
                     "completion", "evidence_ref", "source"):
            value = getattr(example, name)
            if not isinstance(value, str) or not value.strip():
                raise LearningDataError(f"{name} must be non-empty text")
        if example.consent is not True:
            raise LearningDataError("explicit boolean consent is required")
        if example.privacy_reviewed is not True:
            raise LearningDataError("explicit human privacy review is required")
        if example.sensitive is not False:
            raise LearningDataError("sensitive or unclassified examples are never admitted")
        if example.outcome not in ("verified_success", "verified_failure", "unverified"):
            raise LearningDataError("invalid outcome")
        if (
            isinstance(example.quality_score, bool)
            or not isinstance(example.quality_score, (int, float))
            or not 0.0 <= example.quality_score <= 1.0
        ):
            raise LearningDataError("quality_score must be a finite number between 0 and 1")

    def record(self, example: LearningExample) -> None:
        self._validate(example)
        normalized = json.dumps(
            [example.prompt.strip(), example.completion.strip()],
            ensure_ascii=False, separators=(",", ":"),
        )
        content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO learning_examples (
                    example_id, task_id, capability, prompt, completion, outcome,
                    evidence_ref, quality_score, consent, privacy_reviewed,
                    sensitive, source, schema_version, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    example.example_id, example.task_id, example.capability,
                    example.prompt, example.completion, example.outcome,
                    example.evidence_ref, float(example.quality_score),
                    int(example.consent), int(example.privacy_reviewed),
                    int(example.sensitive), example.source, example.schema_version,
                    content_hash,
                ),
            )

    @staticmethod
    def _split(task_id: str) -> Split:
        # Keep all examples from one task in the same partition to reduce leakage.
        bucket = int(hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:8], 16) % 100
        if bucket < 80:
            return "train"
        if bucket < 90:
            return "validation"
        return "test"

    def export_jsonl(
        self,
        destination: str | Path,
        *,
        minimum_quality: float = 0.9,
        allowed_capabilities: Iterable[str] | None = None,
    ) -> dict[str, int]:
        """Export only verified-success examples into disjoint stable splits."""
        if (
            isinstance(minimum_quality, bool)
            or not isinstance(minimum_quality, (int, float))
            or not 0.0 <= minimum_quality <= 1.0
        ):
            raise LearningDataError("minimum_quality must be a finite number between 0 and 1")
        allowed = set(allowed_capabilities) if allowed_capabilities is not None else None
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM learning_examples
                WHERE outcome = 'verified_success'
                  AND consent = 1 AND privacy_reviewed = 1 AND sensitive = 0
                  AND quality_score >= ?
                ORDER BY created_at, example_id
                """,
                (minimum_quality,),
            ).fetchall()

        seen_hashes: set[str] = set()
        counts = {"train": 0, "validation": 0, "test": 0, "excluded_duplicate": 0}
        target = Path(destination)
        _require_private_directory(target.parent)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        try:
            os.fchmod(descriptor, 0o600)
            stream = os.fdopen(descriptor, "w", encoding="utf-8", newline="\n")
            descriptor = -1
            with stream:
                for row in rows:
                    if allowed is not None and row["capability"] not in allowed:
                        continue
                    if row["content_hash"] in seen_hashes:
                        counts["excluded_duplicate"] += 1
                        continue
                    seen_hashes.add(row["content_hash"])
                    split = self._split(row["task_id"])
                    payload = {
                        "schema_version": 1,
                        "example_id": row["example_id"],
                        "task_id": row["task_id"],
                        "capability": row["capability"],
                        "prompt": row["prompt"],
                        "completion": row["completion"],
                        "evidence_ref": row["evidence_ref"],
                        "quality_score": row["quality_score"],
                        "split": split,
                    }
                    stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
                    counts[split] += 1
                stream.flush()
                os.fsync(stream.fileno())
            # Hard-link publication is atomic and refuses to replace any existing path.
            os.link(temporary_name, target)
            os.unlink(temporary_name)
            try:
                _fsync_directory(target.parent)
            except OSError as exc:
                raise OSError(
                    f"dataset was published at {target}, but directory durability is uncertain"
                ) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
        return counts

    def counts(self) -> dict[str, int]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT outcome, COUNT(*) AS n FROM learning_examples GROUP BY outcome"
            ).fetchall()
        return {row["outcome"]: row["n"] for row in rows}
