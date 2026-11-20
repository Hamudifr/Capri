"""Privacy-gated, outcome-based training-data curation for Capri.

This module prepares auditable JSONL examples. It does not train models or
change the weights of a hosted model. Raw task content is accepted only after
explicit consent and a human privacy review.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
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


class LearningStore:
    """Local SQLite journal; raw content is stored only after explicit gates."""

    def __init__(self, database: str | Path) -> None:
        self.database = str(database)
        Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
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

    @staticmethod
    def _validate(example: LearningExample) -> None:
        if example.schema_version != 1:
            raise LearningDataError("unsupported schema_version")
        for name in ("example_id", "task_id", "capability", "prompt",
                     "completion", "evidence_ref", "source"):
            value = getattr(example, name)
            if not isinstance(value, str) or not value.strip():
                raise LearningDataError(f"{name} must be non-empty text")
        if not example.consent:
            raise LearningDataError("explicit consent is required")
        if not example.privacy_reviewed:
            raise LearningDataError("human privacy review is required")
        if example.sensitive:
            raise LearningDataError("sensitive examples are never admitted")
        if example.outcome not in ("verified_success", "verified_failure", "unverified"):
            raise LearningDataError("invalid outcome")
        if (
            isinstance(example.quality_score, bool)
            or not isinstance(example.quality_score, (int, float))
            or not math.isfinite(example.quality_score)
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
        with self._connect() as connection:
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
        if not 0.0 <= minimum_quality <= 1.0:
            raise LearningDataError("minimum_quality must be between 0 and 1")
        allowed = set(allowed_capabilities) if allowed_capabilities is not None else None
        with self._connect() as connection:
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
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8", newline="\n") as stream:
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
        return counts

    def counts(self) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT outcome, COUNT(*) AS n FROM learning_examples GROUP BY outcome"
            ).fetchall()
        return {row["outcome"]: row["n"] for row in rows}
