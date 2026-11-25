"""Privacy-gated, outcome-based training-data curation for Capri.

This module prepares auditable JSONL examples. It does not train models or
change the weights of a hosted model. Raw task content is accepted only after
explicit consent and a human privacy review.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import tempfile
import threading
import uuid
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Literal

from capri_runtime.sqlite_backup import backup_sqlite_database

Outcome = Literal["verified_success", "verified_failure", "unverified"]
Split = Literal["train", "validation", "test"]


@dataclass(frozen=True)
class LearningConsent:
    """A bounded, revocable authorization for one narrowly defined learning use."""

    consent_id: str
    scope: str
    policy_version: str
    evidence_ref: str
    granted_at: str


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
    consent_id: str = ""


class LearningDataError(ValueError):
    """Raised when an example fails the learning-data admission contract."""


class LearningExportOutcomeUncertainError(RuntimeError):
    """Published a bundle, but could not confirm its final registry state."""

    def __init__(self, export_id: str, path: str | Path) -> None:
        self.export_id = export_id
        self.path = str(path)
        super().__init__(
            f"export {export_id} was published at {self.path}, "
            "but its final registry state could not be confirmed"
        )


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

    def __init__(
        self,
        database: str | Path,
        *,
        consent_verifier: Callable[[LearningConsent], bool] | None = None,
    ) -> None:
        if consent_verifier is not None and not callable(consent_verifier):
            raise LearningDataError("consent_verifier must be callable")
        self._backup_lock = threading.RLock()
        self._consent_verifier = consent_verifier
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
                    consent_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS learning_consents (
                    consent_id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    evidence_ref TEXT NOT NULL,
                    granted_at TEXT NOT NULL,
                    revoked_at TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS learning_exports (
                    export_id TEXT PRIMARY KEY,
                    bundle_sha256 TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN
                        ('publishing', 'active', 'invalidated', 'failed')),
                    created_at TEXT NOT NULL,
                    export_kind TEXT NOT NULL DEFAULT 'zip',
                    artifact_path TEXT NOT NULL DEFAULT '',
                    staging_path TEXT NOT NULL DEFAULT ''
                )
                """
            )
            export_columns = {
                row["name"] for row in connection.execute(
                    "PRAGMA table_info(learning_exports)"
                ).fetchall()
            }
            if "export_kind" not in export_columns:
                connection.execute(
                    "ALTER TABLE learning_exports "
                    "ADD COLUMN export_kind TEXT NOT NULL DEFAULT 'zip'"
                )
            if "artifact_path" not in export_columns:
                connection.execute(
                    "ALTER TABLE learning_exports "
                    "ADD COLUMN artifact_path TEXT NOT NULL DEFAULT ''"
                )
            if "staging_path" not in export_columns:
                connection.execute(
                    "ALTER TABLE learning_exports "
                    "ADD COLUMN staging_path TEXT NOT NULL DEFAULT ''"
                )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS learning_export_consents (
                    export_id TEXT NOT NULL REFERENCES learning_exports(export_id) ON DELETE CASCADE,
                    consent_id TEXT NOT NULL REFERENCES learning_consents(consent_id),
                    PRIMARY KEY (export_id, consent_id)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_learning_export_consent "
                "ON learning_export_consents(consent_id)"
            )
            # Migrate databases created before consent provenance was introduced.
            columns = {
                row["name"] for row in connection.execute(
                    "PRAGMA table_info(learning_examples)"
                ).fetchall()
            }
            if "consent_id" not in columns:
                connection.execute(
                    "ALTER TABLE learning_examples "
                    "ADD COLUMN consent_id TEXT NOT NULL DEFAULT ''"
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_learning_task ON learning_examples(task_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_learning_consent ON learning_examples(consent_id)"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _connection(self):
        with self._backup_lock:
            connection = self._connect()
            try:
                with connection:
                    yield connection
            finally:
                connection.close()

    @staticmethod
    def _validate_consent(consent: LearningConsent) -> None:
        if type(consent) is not LearningConsent:
            raise LearningDataError("a LearningConsent record is required")
        fields = (
            (consent.consent_id, 128, "consent_id"),
            (consent.scope, 64, "consent scope"),
            (consent.policy_version, 64, "consent policy_version"),
            (consent.evidence_ref, 256, "consent evidence_ref"),
            (consent.granted_at, 64, "consent granted_at"),
        )
        for value, limit, label in fields:
            if (
                not isinstance(value, str) or not value or len(value) > limit
                or any(0xD800 <= ord(ch) <= 0xDFFF for ch in value)
            ):
                raise LearningDataError(f"{label} must be bounded valid text")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", consent.consent_id):
            raise LearningDataError("consent_id must be a bounded identifier")
        if consent.scope != "curated_training_examples":
            raise LearningDataError("unsupported learning-consent scope")
        try:
            granted = datetime.fromisoformat(consent.granted_at.replace("Z", "+00:00"))
        except ValueError:
            raise LearningDataError("consent granted_at must be an ISO timestamp") from None
        if granted.tzinfo is None or granted.utcoffset() is None:
            raise LearningDataError("consent granted_at must include a timezone")

    def record_consent(self, consent: LearningConsent) -> None:
        """Persist a narrow consent record without storing subject identity or raw consent text."""
        self._validate_consent(consent)
        if self._consent_verifier is None:
            raise LearningDataError(
                "a trusted consent-evidence verifier is required to record consent"
            )
        try:
            verified = self._consent_verifier(consent)
        except Exception as exc:
            raise LearningDataError("consent evidence verification failed") from exc
        if verified is not True:
            raise LearningDataError("consent evidence was not authenticated")
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO learning_consents
                (consent_id, scope, policy_version, evidence_ref, granted_at, revoked_at)
                VALUES (?, ?, ?, ?, ?, NULL)""",
                (
                    consent.consent_id, consent.scope, consent.policy_version,
                    consent.evidence_ref, consent.granted_at,
                ),
            )

    def revoke_consent(self, consent_id: str, revoked_at: str) -> int:
        """Revoke a consent and delete its source examples in one SQLite transaction.

        Previously exported files cannot be recalled by this local store; their
        consent_id provenance lets downstream holders identify affected artifacts.
        """
        if (
            not isinstance(consent_id, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", consent_id)
        ):
            raise LearningDataError("consent_id must be a bounded identifier")
        if not isinstance(revoked_at, str) or not revoked_at or len(revoked_at) > 64:
            raise LearningDataError("revoked_at must be a bounded ISO timestamp")
        try:
            revoked = datetime.fromisoformat(revoked_at.replace("Z", "+00:00"))
        except ValueError:
            raise LearningDataError("revoked_at must be an ISO timestamp") from None
        if revoked.tzinfo is None or revoked.utcoffset() is None:
            raise LearningDataError("revoked_at must include a timezone")
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT granted_at, revoked_at FROM learning_consents WHERE consent_id=?",
                (consent_id,),
            ).fetchone()
            if row is None:
                raise LearningDataError("learning consent was not found")
            if row["revoked_at"] is not None:
                return 0
            try:
                granted = datetime.fromisoformat(row["granted_at"].replace("Z", "+00:00"))
            except (AttributeError, TypeError, ValueError):
                raise LearningDataError("stored learning consent timestamp is invalid") from None
            if granted.tzinfo is None or granted.utcoffset() is None or revoked < granted:
                raise LearningDataError("revocation must be timezone-aware and not precede consent")
            connection.execute(
                "UPDATE learning_consents SET revoked_at=? WHERE consent_id=? AND revoked_at IS NULL",
                (revoked.isoformat(), consent_id),
            )
            connection.execute(
                """
                UPDATE learning_exports SET status='invalidated'
                WHERE export_id IN (
                    SELECT export_id FROM learning_export_consents WHERE consent_id=?
                ) AND status IN ('publishing', 'active')
                """,
                (consent_id,),
            )
            cursor = connection.execute(
                "DELETE FROM learning_examples WHERE consent_id=?", (consent_id,)
            )
            return cursor.rowcount

    @staticmethod
    def _validate(example: LearningExample) -> None:
        if type(example) is not LearningExample:
            raise LearningDataError("a LearningExample record is required")
        if (
            not isinstance(example.consent_id, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", example.consent_id)
        ):
            raise LearningDataError("an explicit consent_id is required")
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
            connection.execute("BEGIN IMMEDIATE")
            consent = connection.execute(
                """SELECT scope FROM learning_consents
                WHERE consent_id=? AND revoked_at IS NULL""",
                (example.consent_id,),
            ).fetchone()
            if consent is None or consent["scope"] != "curated_training_examples":
                raise LearningDataError("an active matching learning consent is required")
            connection.execute(
                """
                INSERT INTO learning_examples (
                    example_id, task_id, capability, prompt, completion, outcome,
                    evidence_ref, quality_score, consent, privacy_reviewed,
                    sensitive, source, schema_version, content_hash, consent_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    example.example_id, example.task_id, example.capability,
                    example.prompt, example.completion, example.outcome,
                    example.evidence_ref, float(example.quality_score),
                    int(example.consent), int(example.privacy_reviewed),
                    int(example.sensitive), example.source, example.schema_version,
                    content_hash, example.consent_id,
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

    def _stage_jsonl(
        self,
        destination: str | Path,
        *,
        minimum_quality: float = 0.9,
        allowed_capabilities: Iterable[str] | None = None,
    ) -> tuple[Path, dict[str, int], list[str], list[str], int]:
        """Create a private, fsynced JSONL staging file and its consent dependencies."""
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
                SELECT learning_examples.*, learning_consents.policy_version
                FROM learning_examples
                JOIN learning_consents
                  ON learning_consents.consent_id = learning_examples.consent_id
                WHERE learning_examples.outcome = 'verified_success'
                  AND learning_examples.consent = 1
                  AND learning_examples.privacy_reviewed = 1
                  AND learning_examples.sensitive = 0
                  AND learning_examples.quality_score >= ?
                  AND learning_consents.scope = 'curated_training_examples'
                  AND learning_consents.revoked_at IS NULL
                ORDER BY learning_examples.created_at, learning_examples.example_id
                """,
                (minimum_quality,),
            ).fetchall()

        target = Path(destination)
        _require_private_directory(target.parent)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".jsonl.tmp", dir=target.parent
        )
        counts = {"train": 0, "validation": 0, "test": 0, "excluded_duplicate": 0}
        seen_hashes: set[str] = set()
        consent_ids: set[str] = set()
        policy_versions: set[str] = set()
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
                        "consent_id": row["consent_id"],
                        "consent_policy_version": row["policy_version"],
                        "split": split,
                    }
                    stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
                    counts[split] += 1
                    consent_ids.add(row["consent_id"])
                    policy_versions.add(row["policy_version"])
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise
        return (
            Path(temporary_name), counts, sorted(consent_ids),
            sorted(policy_versions), sum(counts[key] for key in ("train", "validation", "test")),
        )

    def export_jsonl(
        self,
        destination: str | Path,
        *,
        minimum_quality: float = 0.9,
        allowed_capabilities: Iterable[str] | None = None,
    ) -> dict[str, object]:
        """Publish a registered JSONL artifact whose validity follows consent revocation."""
        target = Path(destination)
        _require_private_directory(target.parent)
        if target.exists() or target.is_symlink():
            raise FileExistsError(target)
        staged_path, counts, consent_ids, policy_versions, row_count = self._stage_jsonl(
            target,
            minimum_quality=minimum_quality,
            allowed_capabilities=allowed_capabilities,
        )
        export_id = str(uuid.uuid4())
        registered = False
        published = False
        try:
            created_at = datetime.now().astimezone().isoformat()
            artifact_digest = hashlib.sha256()
            with staged_path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    artifact_digest.update(chunk)
            artifact_sha256 = artifact_digest.hexdigest()
            manifest = {
                "manifest_version": 1,
                "export_id": export_id,
                "artifact_kind": "jsonl",
                "created_at": created_at,
                "artifact_sha256": artifact_sha256,
                "row_count": row_count,
                "split_counts": {key: counts[key] for key in ("train", "validation", "test")},
                "consent_ids": consent_ids,
                "consent_policy_versions": policy_versions,
            }
            manifest_json = json.dumps(
                manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            )
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                if consent_ids:
                    placeholders = ",".join("?" for _ in consent_ids)
                    active = {
                        row["consent_id"] for row in connection.execute(
                            f"""SELECT consent_id FROM learning_consents
                                WHERE consent_id IN ({placeholders})
                                  AND scope='curated_training_examples'
                                  AND revoked_at IS NULL""",
                            consent_ids,
                        ).fetchall()
                    }
                    if active != set(consent_ids):
                        raise LearningDataError("consent changed during JSONL creation; export aborted")
                connection.execute(
                    """INSERT INTO learning_exports
                    (export_id, bundle_sha256, manifest_json, status, created_at,
                     export_kind, artifact_path, staging_path)
                    VALUES (?, ?, ?, 'publishing', ?, 'jsonl', ?, ?)""",
                    (
                        export_id, artifact_sha256, manifest_json, created_at,
                        str(target.absolute()), str(staged_path.absolute()),
                    ),
                )
                connection.executemany(
                    "INSERT INTO learning_export_consents(export_id, consent_id) VALUES (?, ?)",
                    [(export_id, consent_id) for consent_id in consent_ids],
                )
            registered = True
            os.link(staged_path, target)
            published = True
            staged_path.unlink()
            _fsync_directory(target.parent)
            with self._connection() as connection:
                connection.execute(
                    """UPDATE learning_exports
                    SET status='active', staging_path=''
                    WHERE export_id=? AND status='publishing'""",
                    (export_id,),
                )
                status_row = connection.execute(
                    "SELECT status FROM learning_exports WHERE export_id=?",
                    (export_id,),
                ).fetchone()
            status = status_row["status"]
            if status != "active":
                raise LearningExportOutcomeUncertainError(export_id, target)
            return {
                **counts,
                "export_id": export_id,
                "status": status,
                "path": str(target),
                "artifact_sha256": artifact_sha256,
                "row_count": row_count,
            }
        except Exception as exc:
            if registered and not published:
                with self._connection() as connection:
                    connection.execute(
                        """UPDATE learning_exports
                        SET status='failed', staging_path=''
                        WHERE export_id=? AND status='publishing'""",
                        (export_id,),
                    )
            elif registered and published:
                if isinstance(exc, LearningExportOutcomeUncertainError):
                    raise
                raise LearningExportOutcomeUncertainError(export_id, target) from exc
            raise
        finally:
            try:
                staged_path.unlink()
            except FileNotFoundError:
                pass

    def counts(self) -> dict[str, int]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT outcome, COUNT(*) AS n FROM learning_examples GROUP BY outcome"
            ).fetchall()
        return {row["outcome"]: row["n"] for row in rows}

    def _validate_backup_snapshot(self, connection: sqlite3.Connection) -> None:
        """Validate all four Learning Engine tables before a backup is published."""
        connection.row_factory = sqlite3.Row
        required_columns = {
            "learning_examples": {
                "example_id", "task_id", "capability", "prompt", "completion",
                "outcome", "evidence_ref", "quality_score", "consent",
                "privacy_reviewed", "sensitive", "source", "schema_version",
                "content_hash", "consent_id", "created_at",
            },
            "learning_consents": {
                "consent_id", "scope", "policy_version", "evidence_ref",
                "granted_at", "revoked_at",
            },
            "learning_exports": {
                "export_id", "bundle_sha256", "manifest_json", "status",
                "created_at", "export_kind", "artifact_path", "staging_path",
            },
            "learning_export_consents": {"export_id", "consent_id"},
        }
        for table, expected in required_columns.items():
            actual = {
                row["name"] for row in connection.execute(
                    f"PRAGMA table_info({table})"
                ).fetchall()
            }
            if not expected.issubset(actual):
                raise LearningDataError("backup is missing required Learning Engine columns")

        def parse_timestamp(value: object, label: str, *, aware: bool) -> datetime:
            if not isinstance(value, str) or not value or len(value) > 64:
                raise LearningDataError(f"backup contains an invalid {label}")
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                raise LearningDataError(f"backup contains an invalid {label}") from None
            if aware and (parsed.tzinfo is None or parsed.utcoffset() is None):
                raise LearningDataError(f"backup {label} must be timezone-aware")
            return parsed

        consents: dict[str, dict[str, object]] = {}
        for row in connection.execute(
            """SELECT consent_id, scope, policy_version, evidence_ref, granted_at, revoked_at
               FROM learning_consents"""
        ).fetchall():
            consent = LearningConsent(
                row["consent_id"], row["scope"], row["policy_version"],
                row["evidence_ref"], row["granted_at"],
            )
            self._validate_consent(consent)
            granted = parse_timestamp(row["granted_at"], "consent grant timestamp", aware=True)
            revoked_at = row["revoked_at"]
            if revoked_at is not None:
                revoked = parse_timestamp(revoked_at, "consent revocation timestamp", aware=True)
                if revoked < granted:
                    raise LearningDataError("backup contains a revocation before its consent grant")
            consents[consent.consent_id] = {
                "scope": consent.scope,
                "policy_version": consent.policy_version,
                "revoked_at": revoked_at,
            }

        for row in connection.execute(
            """SELECT example_id, task_id, capability, prompt, completion, outcome,
                      evidence_ref, quality_score, consent, privacy_reviewed, sensitive,
                      source, schema_version, content_hash, consent_id, created_at
               FROM learning_examples"""
        ).fetchall():
            flags = (row["consent"], row["privacy_reviewed"], row["sensitive"])
            if any(type(flag) is not int or flag not in (0, 1) for flag in flags):
                raise LearningDataError("backup contains invalid Learning Engine consent flags")
            consent_id = row["consent_id"]
            if not isinstance(consent_id, str):
                raise LearningDataError("backup contains an invalid example consent reference")
            example_record = LearningExample(
                example_id=row["example_id"],
                task_id=row["task_id"],
                capability=row["capability"],
                prompt=row["prompt"],
                completion=row["completion"],
                outcome=row["outcome"],
                evidence_ref=row["evidence_ref"],
                quality_score=row["quality_score"],
                consent=row["consent"] == 1,
                privacy_reviewed=row["privacy_reviewed"] == 1,
                sensitive=row["sensitive"] == 1,
                source=row["source"],
                schema_version=row["schema_version"],
                # Empty IDs are retained only for legacy rows. They are excluded
                # from export because the consent join cannot match them.
                consent_id=consent_id or "legacy-unlinked",
            )
            self._validate(example_record)
            parse_timestamp(row["created_at"], "example creation timestamp", aware=False)
            content_hash = row["content_hash"]
            if not isinstance(content_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", content_hash):
                raise LearningDataError("backup contains an invalid example content hash")
            if consent_id:
                consent = consents.get(consent_id)
                if consent is None or consent["scope"] != "curated_training_examples":
                    raise LearningDataError("backup contains an example without matching consent")
                if consent["revoked_at"] is not None:
                    raise LearningDataError("backup retains examples after consent revocation")
                normalized = json.dumps(
                    [example_record.prompt.strip(), example_record.completion.strip()],
                    ensure_ascii=False, separators=(",", ":"),
                )
                expected_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
                if content_hash != expected_hash:
                    raise LearningDataError("backup contains an example content-hash mismatch")

        exports: dict[str, dict[str, object]] = {}
        for row in connection.execute(
            """SELECT export_id, bundle_sha256, manifest_json, status, created_at,
                      export_kind, artifact_path, staging_path
               FROM learning_exports"""
        ).fetchall():
            export_id = row["export_id"]
            status = row["status"]
            export_kind = row["export_kind"]
            if not isinstance(export_id, str) or not re.fullmatch(
                r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                export_id,
            ):
                raise LearningDataError("backup contains an invalid export ID")
            if status not in {"publishing", "active", "invalidated", "failed"}:
                raise LearningDataError("backup contains an unsupported export status")
            if export_kind not in {"jsonl", "zip"}:
                raise LearningDataError("backup contains an unsupported export kind")
            bundle_hash = row["bundle_sha256"]
            if not isinstance(bundle_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", bundle_hash):
                raise LearningDataError("backup contains an invalid export hash")
            created_at = row["created_at"]
            parse_timestamp(created_at, "export creation timestamp", aware=True)
            artifact_path = row["artifact_path"]
            staging_path = row["staging_path"]
            for value, label in ((artifact_path, "artifact path"), (staging_path, "staging path")):
                if not isinstance(value, str) or len(value) > 4096:
                    raise LearningDataError(f"backup contains an invalid {label}")
                if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
                    raise LearningDataError(f"backup contains an invalid {label}")
                if value and not Path(value).is_absolute():
                    raise LearningDataError(f"backup contains a non-absolute {label}")
            if status == "active" and (not artifact_path or staging_path):
                raise LearningDataError("active export has an incomplete publication record")
            if artifact_path and staging_path:
                artifact = Path(artifact_path)
                staging = Path(staging_path)
                if (
                    artifact.parent != staging.parent
                    or not staging.name.startswith(f".{artifact.name}.")
                ):
                    raise LearningDataError("backup contains an unsafe export staging relationship")

            try:
                manifest = json.loads(row["manifest_json"])
            except (TypeError, ValueError, json.JSONDecodeError):
                raise LearningDataError("backup contains an invalid export manifest") from None
            if type(manifest) is not dict:
                raise LearningDataError("backup contains an invalid export manifest")
            if "export_id" in manifest and manifest["export_id"] != export_id:
                raise LearningDataError("backup export manifest identity does not match its registry row")

            if status in {"active", "publishing"}:
                if (
                    type(manifest.get("manifest_version")) is not int
                    or manifest.get("manifest_version") != 1
                    or manifest.get("export_id") != export_id
                    or manifest.get("created_at") != created_at
                ):
                    raise LearningDataError("backup contains an incomplete active export manifest")
                row_count = manifest.get("row_count")
                split_counts = manifest.get("split_counts")
                consent_ids = manifest.get("consent_ids")
                policy_versions = manifest.get("consent_policy_versions")
                if type(row_count) is not int or row_count < 0:
                    raise LearningDataError("backup contains an invalid export row count")
                if type(split_counts) is not dict or set(split_counts) != {
                    "train", "validation", "test"
                }:
                    raise LearningDataError("backup contains invalid export split counts")
                if any(type(value) is not int or value < 0 for value in split_counts.values()):
                    raise LearningDataError("backup contains invalid export split counts")
                if sum(split_counts.values()) != row_count:
                    raise LearningDataError("backup export split counts do not match its row count")
                for values, label in (
                    (consent_ids, "consent IDs"),
                    (policy_versions, "consent policy versions"),
                ):
                    if (
                        type(values) is not list
                        or any(not isinstance(value, str) or not value for value in values)
                        or values != sorted(set(values))
                    ):
                        raise LearningDataError(f"backup contains invalid export {label}")
                if export_kind == "jsonl":
                    if (
                        manifest.get("artifact_kind") != "jsonl"
                        or manifest.get("artifact_sha256") != bundle_hash
                    ):
                        raise LearningDataError("backup JSONL manifest does not match its artifact hash")
                elif (
                    manifest.get("dataset_file") != "dataset.jsonl"
                    or not isinstance(manifest.get("dataset_sha256"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", manifest["dataset_sha256"])
                ):
                    raise LearningDataError("backup ZIP manifest is incomplete")
                if row_count > 0 and not consent_ids:
                    raise LearningDataError("non-empty export has no consent dependencies")
                manifest_ids = set(consent_ids)
                manifest_versions = set(policy_versions)
            else:
                manifest_ids = set()
                manifest_versions = set()

            exports[export_id] = {
                "status": status,
                "manifest_ids": manifest_ids,
                "manifest_versions": manifest_versions,
            }

        dependencies: dict[str, set[str]] = {}
        for row in connection.execute(
            "SELECT export_id, consent_id FROM learning_export_consents"
        ).fetchall():
            export_id = row["export_id"]
            consent_id = row["consent_id"]
            if export_id not in exports or consent_id not in consents:
                raise LearningDataError("backup contains an orphaned export-consent dependency")
            dependencies.setdefault(export_id, set()).add(consent_id)

        for export_id, record in exports.items():
            if record["status"] not in {"active", "publishing"}:
                continue
            dependency_ids = dependencies.get(export_id, set())
            if dependency_ids != record["manifest_ids"]:
                raise LearningDataError("backup export consent dependencies do not match its manifest")
            policy_versions = {
                str(consents[consent_id]["policy_version"]) for consent_id in dependency_ids
            }
            if policy_versions != record["manifest_versions"]:
                raise LearningDataError("backup export consent policies do not match its manifest")
            if record["status"] == "active" and any(
                consents[consent_id]["revoked_at"] is not None
                for consent_id in dependency_ids
            ):
                raise LearningDataError("backup contains an active export with revoked consent")

    def backup_to(self, destination_path: str | Path) -> str:
        """Create a private, consistent snapshot of all four Learning Engine tables.

        The SQLite registry and source examples are included. Published JSONL/ZIP
        artifacts are separate files and must be backed up independently; after
        restore, verify every artifact against the restored authoritative registry
        before allowing it to be consumed.
        """
        return backup_sqlite_database(
            self.database,
            str(destination_path),
            lock=self._backup_lock,
            connect=self._connect,
            validate_snapshot=self._validate_backup_snapshot,
            error_type=LearningDataError,
            prefix=".capri-learning-backup-",
        )

    def integrity_check(self) -> str:
        """Return a generic integrity result without exposing stored learning content."""
        with self._backup_lock:
            connection = self._connect()
            try:
                integrity = connection.execute("PRAGMA integrity_check").fetchone()
                if not integrity or integrity[0] != "ok":
                    return "SQLite integrity check failed"
                if connection.execute("PRAGMA foreign_key_check").fetchall():
                    return "foreign key check failed"
                try:
                    self._validate_backup_snapshot(connection)
                except LearningDataError:
                    return "semantic validation failed"
                return "ok"
            except sqlite3.Error:
                return "SQLite integrity check failed"
            finally:
                connection.close()


    def export_bundle(
        self,
        destination: str | Path,
        *,
        minimum_quality: float = 0.9,
        allowed_capabilities: Iterable[str] | None = None,
    ) -> dict[str, object]:
        """Publish a content-hashed ZIP bundle and register its consent dependencies.

        The registry is authoritative for revocation status. A bundle is usable
        only while verify_export reports valid; copying the ZIP does not copy
        this registry or make revocation checks portable. If publication succeeds
        but final registry state cannot be confirmed, the method raises
        LearningExportOutcomeUncertainError with the export ID and path so the
        caller can reconcile without blindly retrying.
        """
        target = Path(destination)
        _require_private_directory(target.parent)
        if target.exists() or target.is_symlink():
            raise FileExistsError(target)
        export_id = str(uuid.uuid4())
        dataset_path = target.parent / f".{target.name}.{export_id}.jsonl"
        descriptor, archive_name = tempfile.mkstemp(
            prefix=f".{target.name}.{export_id}.", suffix=".tmp", dir=target.parent
        )
        # Keep the original O_RDWR descriptor for the archive inode open so the
        # completed ZIP can be fsynced before its name is published.
        registered = False
        published = False
        try:
            staged_path, counts, staged_consent_ids, staged_policy_versions, staged_row_count = (
                self._stage_jsonl(
                    dataset_path,
                    minimum_quality=minimum_quality,
                    allowed_capabilities=allowed_capabilities,
                )
            )
            dataset_path = staged_path
            dataset_digest = hashlib.sha256()
            consent_ids_set: set[str] = set()
            policy_versions_set: set[str] = set()
            row_count = 0
            with dataset_path.open("rb") as stream:
                for line in stream:
                    dataset_digest.update(line)
                    if line.strip():
                        row = json.loads(line.decode("utf-8"))
                        consent_ids_set.add(row["consent_id"])
                        policy_versions_set.add(row["consent_policy_version"])
                        row_count += 1
            dataset_sha256 = dataset_digest.hexdigest()
            consent_ids = sorted(consent_ids_set)
            policy_versions = sorted(policy_versions_set)
            created_at = datetime.now().astimezone().isoformat()
            manifest = {
                "manifest_version": 1,
                "export_id": export_id,
                "created_at": created_at,
                "dataset_file": "dataset.jsonl",
                "dataset_sha256": dataset_sha256,
                "row_count": row_count,
                "split_counts": {key: counts[key] for key in ("train", "validation", "test")},
                "consent_ids": consent_ids,
                "consent_policy_versions": policy_versions,
            }
            manifest_bytes = (
                json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            ).encode("utf-8")
            with zipfile.ZipFile(archive_name, "w", compression=zipfile.ZIP_STORED) as archive:
                archive.write(dataset_path, "dataset.jsonl")
                archive.writestr("manifest.json", manifest_bytes)
            # ZipFile has closed its writer. Flush the complete archive inode to
            # stable storage before hashing, registering, or publishing its name.
            os.fsync(descriptor)
            bundle_digest = hashlib.sha256()
            with open(archive_name, "rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    bundle_digest.update(chunk)
            bundle_sha256 = bundle_digest.hexdigest()

            # Reserve the registry row only if every referenced consent is still active.
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                if consent_ids:
                    placeholders = ",".join("?" for _ in consent_ids)
                    active = {
                        row["consent_id"] for row in connection.execute(
                            f"""SELECT consent_id FROM learning_consents
                                WHERE consent_id IN ({placeholders})
                                  AND scope='curated_training_examples'
                                  AND revoked_at IS NULL""",
                            consent_ids,
                        ).fetchall()
                    }
                    if active != set(consent_ids):
                        raise LearningDataError("consent changed during bundle creation; export aborted")
                connection.execute(
                    """INSERT INTO learning_exports
                    (export_id, bundle_sha256, manifest_json, status, created_at,
                     export_kind, artifact_path, staging_path)
                    VALUES (?, ?, ?, 'publishing', ?, 'zip', ?, ?)""",
                    (
                        export_id, bundle_sha256, manifest_bytes.decode("utf-8"), created_at,
                        str(target.absolute()), str(Path(archive_name).absolute()),
                    ),
                )
                connection.executemany(
                    "INSERT INTO learning_export_consents(export_id, consent_id) VALUES (?, ?)",
                    [(export_id, consent_id) for consent_id in consent_ids],
                )
            registered = True

            # Same-directory hard-link publication is atomic and never overwrites.
            os.link(archive_name, target)
            published = True
            os.unlink(archive_name)
            _fsync_directory(target.parent)
            with self._connection() as connection:
                connection.execute(
                    """UPDATE learning_exports
                    SET status='active', staging_path=''
                    WHERE export_id=? AND status='publishing'""",
                    (export_id,),
                )
                status = connection.execute(
                    "SELECT status FROM learning_exports WHERE export_id=?",
                    (export_id,),
                ).fetchone()["status"]
            if status != "active":
                raise LearningExportOutcomeUncertainError(export_id, target)
            return {
                "export_id": export_id,
                "bundle_sha256": bundle_sha256,
                "status": status,
                "path": str(target),
                "row_count": row_count,
                "split_counts": manifest["split_counts"],
            }
        except Exception as exc:
            if registered and not published:
                with self._connection() as connection:
                    connection.execute(
                        """UPDATE learning_exports
                        SET status='failed', staging_path=''
                        WHERE export_id=? AND status='publishing'""",
                        (export_id,),
                    )
            elif registered and published:
                raise LearningExportOutcomeUncertainError(export_id, target) from exc
            raise
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            for temporary in (dataset_path, Path(archive_name)):
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass

    def get_export_status(self, export_id: str) -> dict[str, str] | None:
        """Return the local registry status for a known export, or None."""
        if not isinstance(export_id, str) or not re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            export_id,
        ):
            raise LearningDataError("export_id must be a UUID")
        with self._connection() as connection:
            row = connection.execute(
                """SELECT export_id, bundle_sha256, status, created_at,
                          export_kind, artifact_path, staging_path, manifest_json
                   FROM learning_exports WHERE export_id=?""",
                (export_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def _inspect_export_artifact(
        self,
        record: sqlite3.Row | dict[str, str],
        export_id: str,
        artifact_path: str | Path,
    ) -> dict[str, object]:
        """Verify an artifact's bytes and registry manifest without changing state."""
        path = Path(artifact_path)
        try:
            _require_private_directory(path.parent)
            if path.is_symlink() or not path.is_file():
                return {"valid": False, "reason": "missing_or_unsafe_artifact"}
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            actual_hash = digest.hexdigest()
            if actual_hash != record["bundle_sha256"]:
                reason = (
                    "artifact_hash_mismatch"
                    if record["export_kind"] == "jsonl"
                    else "bundle_hash_mismatch"
                )
                return {"valid": False, "reason": reason}
            stored_manifest = json.loads(record["manifest_json"])
            if not isinstance(stored_manifest, dict):
                return {"valid": False, "reason": "invalid_manifest"}
            if stored_manifest.get("export_id") != export_id:
                return {"valid": False, "reason": "manifest_identity_mismatch"}

            with self._connection() as connection:
                dependencies = {
                    row["consent_id"] for row in connection.execute(
                        "SELECT consent_id FROM learning_export_consents WHERE export_id=?",
                        (export_id,),
                    ).fetchall()
                }
            if record["export_kind"] == "jsonl":
                if stored_manifest.get("artifact_kind") != "jsonl":
                    return {"valid": False, "reason": "manifest_type_mismatch"}
                consent_ids: set[str] = set()
                policy_versions: set[str] = set()
                row_count = 0
                split_counts = {"train": 0, "validation": 0, "test": 0}
                with path.open("r", encoding="utf-8") as stream:
                    for line in stream:
                        if not line.strip():
                            return {"valid": False, "reason": "invalid_jsonl"}
                        row = json.loads(line)
                        if not isinstance(row, dict):
                            return {"valid": False, "reason": "invalid_jsonl"}
                        consent_id = row.get("consent_id")
                        policy_version = row.get("consent_policy_version")
                        if not isinstance(consent_id, str) or not isinstance(policy_version, str):
                            return {"valid": False, "reason": "missing_consent_provenance"}
                        split = row.get("split")
                        if split not in split_counts:
                            return {"valid": False, "reason": "invalid_split"}
                        split_counts[split] += 1
                        consent_ids.add(consent_id)
                        policy_versions.add(policy_version)
                        row_count += 1
                if (
                    stored_manifest.get("artifact_sha256") != actual_hash
                    or split_counts != stored_manifest.get("split_counts")
                    or row_count != stored_manifest.get("row_count")
                    or sorted(consent_ids) != stored_manifest.get("consent_ids")
                    or sorted(policy_versions) != stored_manifest.get("consent_policy_versions")
                    or consent_ids != dependencies
                ):
                    return {"valid": False, "reason": "jsonl_manifest_mismatch"}
                return {
                    "valid": True, "reason": "ok", "artifact_sha256": actual_hash,
                    "row_count": row_count,
                }

            if record["export_kind"] != "zip":
                return {"valid": False, "reason": "unsupported_artifact_type"}
            with zipfile.ZipFile(path, "r") as archive:
                if set(archive.namelist()) != {"dataset.jsonl", "manifest.json"}:
                    return {"valid": False, "reason": "unexpected_bundle_members"}
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                if not isinstance(manifest, dict):
                    return {"valid": False, "reason": "invalid_manifest"}
                if manifest != stored_manifest:
                    return {"valid": False, "reason": "manifest_registry_mismatch"}
                if manifest.get("export_id") != export_id:
                    return {"valid": False, "reason": "manifest_identity_mismatch"}
                dataset_digest = hashlib.sha256()
                consent_ids: set[str] = set()
                policy_versions: set[str] = set()
                row_count = 0
                with archive.open("dataset.jsonl", "r") as dataset_stream:
                    for line in dataset_stream:
                        dataset_digest.update(line)
                        if line.strip():
                            row = json.loads(line.decode("utf-8"))
                            consent_ids.add(row["consent_id"])
                            policy_versions.add(row["consent_policy_version"])
                            row_count += 1
            if (
                dataset_digest.hexdigest() != manifest.get("dataset_sha256")
                or row_count != manifest.get("row_count")
                or sorted(consent_ids) != manifest.get("consent_ids")
                or sorted(policy_versions) != manifest.get("consent_policy_versions")
                or consent_ids != dependencies
            ):
                return {"valid": False, "reason": "dataset_manifest_mismatch"}
            return {
                "valid": True, "reason": "ok", "artifact_sha256": actual_hash,
                "row_count": row_count,
            }
        except (OSError, ValueError, TypeError, KeyError, zipfile.BadZipFile, UnicodeDecodeError):
            return {"valid": False, "reason": "unreadable_artifact"}

    def verify_export(self, export_id: str, bundle_path: str | Path) -> dict[str, object]:
        """Verify artifact bytes and the latest consent-registry state."""
        record = self.get_export_status(export_id)
        if record is None:
            return {"valid": False, "reason": "unregistered"}
        artifact = self._inspect_export_artifact(record, export_id, bundle_path)
        if not artifact["valid"]:
            return {**artifact, "status": record["status"]}
        latest_record = self.get_export_status(export_id)
        if latest_record is None:
            return {"valid": False, "reason": "unregistered"}
        latest_status = latest_record["status"]
        valid = latest_status == "active"
        return {
            **artifact,
            "valid": valid,
            "reason": "ok" if valid else latest_status,
            "status": latest_status,
        }

    @staticmethod
    def _cleanup_staging_file(staging_path: str, artifact_path: str) -> bool:
        """Remove only a private staging sibling whose name matches its artifact."""
        if not staging_path:
            return True
        staged = Path(staging_path)
        artifact = Path(artifact_path) if artifact_path else None
        if artifact is None or staged.parent != artifact.parent:
            return False
        if not staged.name.startswith(f".{artifact.name}.") or staged.is_symlink():
            return False
        try:
            if staged.exists():
                if not staged.is_file():
                    return False
                staged.unlink()
            _fsync_directory(staged.parent)
            return True
        except OSError:
            return False

    def reconcile_pending_exports(self) -> dict[str, object]:
        """Idempotently recover verifiable publishing artifacts; fail closed otherwise."""
        with self._connection() as connection:
            stale_staging = connection.execute(
                """SELECT export_id, artifact_path, staging_path
                   FROM learning_exports
                   WHERE status IN ('invalidated', 'failed') AND staging_path <> ''"""
            ).fetchall()
            pending = connection.execute(
                """SELECT export_id, bundle_sha256, manifest_json, status, created_at,
                          export_kind, artifact_path, staging_path
                   FROM learning_exports WHERE status='publishing'
                   ORDER BY created_at, export_id"""
            ).fetchall()
        cleaned_staging = 0
        for stale in stale_staging:
            if self._cleanup_staging_file(stale["staging_path"], stale["artifact_path"]):
                with self._connection() as connection:
                    connection.execute(
                        "UPDATE learning_exports SET staging_path='' "
                        "WHERE export_id=? AND status IN ('invalidated', 'failed')",
                        (stale["export_id"],),
                    )
                cleaned_staging += 1
        result: dict[str, object] = {
            "examined": len(pending), "cleaned_staging": cleaned_staging,
            "activated": [], "invalidated": [], "failed": [], "still_pending": [],
        }
        for record in pending:
            export_id = record["export_id"]
            artifact_path = record["artifact_path"]
            staging_path = record["staging_path"]
            if not artifact_path:
                with self._connection() as connection:
                    if staging_path:
                        connection.execute(
                            "UPDATE learning_exports SET status='failed' "
                            "WHERE export_id=? AND status='publishing'",
                            (export_id,),
                        )
                    else:
                        connection.execute(
                            "UPDATE learning_exports SET status='failed', staging_path='' "
                            "WHERE export_id=? AND status='publishing'",
                            (export_id,),
                        )
                result["failed"].append(export_id)
                continue
            artifact = self._inspect_export_artifact(record, export_id, artifact_path)
            if not artifact["valid"]:
                staging_cleaned = self._cleanup_staging_file(staging_path, artifact_path)
                with self._connection() as connection:
                    if staging_cleaned:
                        connection.execute(
                            "UPDATE learning_exports SET status='failed', staging_path='' "
                            "WHERE export_id=? AND status='publishing'",
                            (export_id,),
                        )
                    else:
                        connection.execute(
                            "UPDATE learning_exports SET status='failed' "
                            "WHERE export_id=? AND status='publishing'",
                            (export_id,),
                        )
                result["failed"].append(export_id)
                continue
            try:
                _fsync_directory(Path(artifact_path).parent)
                if staging_path and not self._cleanup_staging_file(staging_path, artifact_path):
                    raise OSError("unable to safely clean export staging file")
            except OSError:
                result["still_pending"].append(export_id)
                continue
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                current = connection.execute(
                    "SELECT status FROM learning_exports WHERE export_id=?",
                    (export_id,),
                ).fetchone()
                if current is None or current["status"] != "publishing":
                    continue
                revoked = connection.execute(
                    """SELECT 1 FROM learning_export_consents ec
                       JOIN learning_consents c ON c.consent_id=ec.consent_id
                       WHERE ec.export_id=?
                         AND (c.revoked_at IS NOT NULL OR c.scope <> 'curated_training_examples')
                       LIMIT 1""",
                    (export_id,),
                ).fetchone()
                if revoked is not None:
                    connection.execute(
                        "UPDATE learning_exports SET status='invalidated', staging_path='' "
                        "WHERE export_id=? AND status='publishing'",
                        (export_id,),
                    )
                    result["invalidated"].append(export_id)
                else:
                    connection.execute(
                        "UPDATE learning_exports SET status='active', staging_path='' "
                        "WHERE export_id=? AND status='publishing'",
                        (export_id,),
                    )
                    result["activated"].append(export_id)
        return result

