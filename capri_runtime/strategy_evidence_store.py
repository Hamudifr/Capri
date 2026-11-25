"""Private append-only host evidence manifests for strategy evaluation.

This store persists only bounded StrategyObservation metadata, not prompts,
model outputs, secrets, or raw user content. Host callbacks authenticate source
events and classify task families before a manifest is accepted.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import asdict, replace
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Callable, Mapping
from uuid import uuid4

from capri_core.strategy import (
    StrategyEvaluationError,
    StrategyObservation,
    evaluate_strategies,
)
from .strategy_store import StrategyAuthorizationError, StrategyEvidenceContext, StrategyStoreError
from .tasks import SQLiteTaskStore

_ALLOWED_TASK_FAMILIES = frozenset({
    "coding", "formatting", "general_qa", "research",
    "retrieval", "summarization", "writing",
})
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}$")
_OPAQUE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COHORT_SCHEMA = re.compile(r"^capri[.]strategy-cohort[.]v[0-9]+$")
_MANIFEST_REF = re.compile(r"^sqlite-strategy-manifest:([0-9a-f]{64})$")
_DIGEST_REF = re.compile(r"^sha256:([0-9a-f]{64})$")
_MANIFEST_SCHEMA = "capri.strategy-evidence-manifest.v1"
_MAX_MANIFEST_BYTES = 16_000_000
_OBSERVATION_FIELDS = frozenset({
    "task_id", "scenario", "strategy_id", "strategy_version", "outcome",
    "evidence_ref", "safety_violation", "tool_calls", "context_tokens",
    "estimated_cost_units", "latency_ms",
})


def _text(value: object, label: str, limit: int = 256) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > limit:
        raise StrategyAuthorizationError(f"{label} is invalid")
    if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise StrategyAuthorizationError(f"{label} is invalid")
    return value


def _canonical(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    )


def _decode_manifest_blob(
    manifest_sha256: str,
    manifest_json: str,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate canonical manifest bytes and every duplicated row binding."""
    if type(manifest_sha256) is not str or not _SHA256.fullmatch(manifest_sha256):
        raise StrategyStoreError("strategy evidence manifest digest is invalid")
    if type(manifest_json) is not str:
        raise StrategyStoreError("strategy evidence manifest payload is invalid")
    try:
        encoded = manifest_json.encode("utf-8", errors="strict")
        if len(encoded) > _MAX_MANIFEST_BYTES:
            raise StrategyStoreError("strategy evidence manifest exceeds the configured size limit")
        if hashlib.sha256(encoded).hexdigest() != manifest_sha256:
            raise StrategyStoreError("strategy evidence manifest digest does not match its payload")
        manifest = json.loads(manifest_json)
        if type(manifest) is not dict:
            raise StrategyStoreError("strategy evidence manifest is not an object")
        expected_keys = {
            "manifest_schema", "principal_id", "strategy_class", "baseline_id",
            "baseline_version", "candidate_id", "candidate_version",
            "cohort_sha256", "cohort_schema", "matched_pairs", "task_family",
            "observations",
        }
        if set(manifest) != expected_keys or _canonical(manifest) != manifest_json:
            raise StrategyStoreError("strategy evidence manifest is not canonical")
    except StrategyStoreError:
        raise
    except Exception:
        raise StrategyStoreError("strategy evidence manifest payload is malformed") from None

    principal = _text(manifest["principal_id"], "principal_id", 128)
    category = _text(manifest["strategy_class"], "strategy_class", 64)
    baseline = _text(manifest["baseline_id"], "baseline_id", 64)
    candidate = _text(manifest["candidate_id"], "candidate_id", 64)
    baseline_version = _text(manifest["baseline_version"], "baseline_version", 64)
    candidate_version = _text(manifest["candidate_version"], "candidate_version", 64)
    cohort_sha256 = manifest["cohort_sha256"]
    cohort_schema = manifest["cohort_schema"]
    matched_pairs = manifest["matched_pairs"]
    task_family = manifest["task_family"]
    if (
        manifest["manifest_schema"] != _MANIFEST_SCHEMA
        or not _IDENTIFIER.fullmatch(category)
        or not _IDENTIFIER.fullmatch(baseline)
        or not _IDENTIFIER.fullmatch(candidate)
        or baseline == candidate
        or not _VERSION.fullmatch(baseline_version)
        or not _VERSION.fullmatch(candidate_version)
        or baseline_version == "unversioned"
        or candidate_version == "unversioned"
        or type(cohort_sha256) is not str or not _SHA256.fullmatch(cohort_sha256)
        or type(cohort_schema) is not str or not _COHORT_SCHEMA.fullmatch(cohort_schema)
        or type(matched_pairs) is not int or not 20 <= matched_pairs <= 20_000
        or type(task_family) is not str or task_family not in _ALLOWED_TASK_FAMILIES
        or type(manifest["observations"]) is not list
        or not 40 <= len(manifest["observations"]) <= 40_000
    ):
        raise StrategyStoreError("strategy evidence manifest metadata is invalid")
    expected_metadata = {
        "principal_id": principal,
        "strategy_class": category,
        "baseline_id": baseline,
        "baseline_version": baseline_version,
        "candidate_id": candidate,
        "candidate_version": candidate_version,
        "cohort_sha256": cohort_sha256,
        "cohort_schema": cohort_schema,
        "matched_pairs": matched_pairs,
        "task_family": task_family,
    }
    if any(metadata.get(key) != value for key, value in expected_metadata.items()):
        raise StrategyStoreError("strategy evidence manifest metadata does not match its immutable row")
    for item in manifest["observations"]:
        if type(item) is not dict or set(item) != _OBSERVATION_FIELDS:
            raise StrategyStoreError("strategy evidence manifest observation schema is invalid")
    return manifest


class SQLiteStrategyEvidenceManifestStore:
    """Append-only manifest backend sharing the private SQLiteTaskStore database.

    All three callbacks are mandatory host trust boundaries:
    authenticate_collector derives the principal from credentials;
    classify_task_family derives an allow-listed family from trusted task metadata;
    validate_source_events verifies every opaque evidence reference and observation
    against genuine host execution records. They must never trust model assertions.
    """

    def __init__(
        self,
        task_store: SQLiteTaskStore,
        authenticate_collector: Callable[[Any], str | None],
        classify_task_family: Callable[[str, str], str | None],
        validate_source_events: Callable[
            [str, str, tuple[StrategyObservation, ...], Mapping[str, str]], bool
        ],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if type(task_store) is not SQLiteTaskStore:
            raise StrategyStoreError("an exact SQLiteTaskStore is required")
        if not all(callable(item) for item in (
            authenticate_collector, classify_task_family, validate_source_events,
        )):
            raise StrategyStoreError("trusted host authentication, classification, and source validation are required")
        if clock is not None and not callable(clock):
            raise StrategyStoreError("clock must be callable")
        self._tasks = task_store
        self._authenticate = authenticate_collector
        self._classify = classify_task_family
        self._validate_sources = validate_source_events
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._initialize()

    def _initialize(self) -> None:
        with self._tasks._lock:
            connection = self._tasks._connect()
            try:
                connection.execute("""CREATE TABLE IF NOT EXISTS strategy_evidence_manifests (
                    manifest_sha256 TEXT PRIMARY KEY,
                    principal_id TEXT NOT NULL,
                    strategy_class TEXT NOT NULL,
                    baseline_id TEXT NOT NULL,
                    baseline_version TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    candidate_version TEXT NOT NULL,
                    cohort_sha256 TEXT NOT NULL,
                    cohort_schema TEXT NOT NULL,
                    matched_pairs INTEGER NOT NULL,
                    task_family TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(principal_id,strategy_class,cohort_sha256)
                )""")
                connection.execute("""CREATE TRIGGER IF NOT EXISTS strategy_evidence_immutable_update
                    BEFORE UPDATE ON strategy_evidence_manifests
                    BEGIN SELECT RAISE(ABORT, 'strategy evidence manifests are append-only'); END""")
                connection.execute("""CREATE TRIGGER IF NOT EXISTS strategy_evidence_immutable_delete
                    BEFORE DELETE ON strategy_evidence_manifests
                    BEGIN SELECT RAISE(ABORT, 'strategy evidence manifests are append-only'); END""")
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS strategy_evidence_owner_idx "
                    "ON strategy_evidence_manifests(principal_id,strategy_class,manifest_sha256)"
                )
            finally:
                connection.close()

    @staticmethod
    def _validate_observations(
        baseline_id: str,
        candidate_id: str,
        observations: object,
    ) -> tuple[StrategyObservation, ...]:
        if type(observations) not in {tuple, list}:
            raise StrategyAuthorizationError("observations must be a tuple or list")
        if not 40 <= len(observations) <= 40_000:
            raise StrategyAuthorizationError("at least 20 matched task pairs are required")
        records = tuple(observations)
        try:
            evaluation = evaluate_strategies(
                baseline_id, candidate_id, records, min_pairs=20,
            )
        except StrategyEvaluationError:
            raise StrategyAuthorizationError("strategy observations are invalid") from None
        if not evaluation.eligible_for_manual_review:
            raise StrategyAuthorizationError("strategy cohort is not eligible for manual review")
        seen_references: set[tuple[str, str]] = set()
        baseline_references: set[str] = set()
        candidate_references: set[str] = set()
        for record in records:
            if (
                not _IDENTIFIER.fullmatch(record.task_id)
                or not _IDENTIFIER.fullmatch(record.scenario)
                or not _IDENTIFIER.fullmatch(record.strategy_id)
                or not _VERSION.fullmatch(record.strategy_version)
                or record.strategy_version == "unversioned"
                or not _OPAQUE_REF.fullmatch(record.evidence_ref)
            ):
                raise StrategyAuthorizationError("observation identifiers must be bounded opaque host references")
            reference_key = (record.strategy_id, record.evidence_ref)
            if reference_key in seen_references:
                raise StrategyAuthorizationError("evidence references must be unique within each strategy")
            seen_references.add(reference_key)
            if record.strategy_id == baseline_id:
                baseline_references.add(record.evidence_ref)
            else:
                candidate_references.add(record.evidence_ref)
        if baseline_references & candidate_references:
            raise StrategyAuthorizationError("baseline and candidate evidence references must be disjoint")
        return records

    def register_manifest(
        self,
        credential: Any,
        *,
        strategy_class: str,
        baseline_id: str,
        candidate_id: str,
        observations: tuple[StrategyObservation, ...] | list[StrategyObservation],
    ) -> StrategyEvidenceContext:
        """Authenticate, classify, validate, and persist a complete cohort manifest."""
        if not _IDENTIFIER.fullmatch(_text(strategy_class, "strategy_class", 64)):
            raise StrategyAuthorizationError("strategy_class is invalid")
        if not _IDENTIFIER.fullmatch(_text(baseline_id, "baseline_id", 64)):
            raise StrategyAuthorizationError("baseline_id is invalid")
        if not _IDENTIFIER.fullmatch(_text(candidate_id, "candidate_id", 64)) or baseline_id == candidate_id:
            raise StrategyAuthorizationError("candidate_id is invalid")
        try:
            principal_id = self._authenticate(credential)
        except Exception:
            raise StrategyAuthorizationError("evidence collector authentication failed") from None
        principal_id = _text(principal_id, "authenticated principal", 128)
        records = self._validate_observations(baseline_id, candidate_id, observations)
        evaluation = evaluate_strategies(baseline_id, candidate_id, records, min_pairs=20)
        baseline_version = evaluation.baseline_version
        candidate_version = evaluation.candidate_version
        if (
            not _VERSION.fullmatch(baseline_version)
            or not _VERSION.fullmatch(candidate_version)
            or baseline_version == "unversioned"
            or candidate_version == "unversioned"
        ):
            raise StrategyAuthorizationError("explicit strategy versions are required")

        families: dict[str, str] = {}
        for task_id in sorted({record.task_id for record in records}):
            try:
                family = self._classify(principal_id, task_id)
            except Exception:
                raise StrategyAuthorizationError("trusted task-family classification failed") from None
            if type(family) is not str or family not in _ALLOWED_TASK_FAMILIES:
                raise StrategyAuthorizationError("task family is not allow-listed")
            families[task_id] = family
        unique_families = set(families.values())
        if len(unique_families) != 1:
            raise StrategyAuthorizationError("one manifest must contain exactly one task family")
        task_family = next(iter(unique_families))
        family_snapshot = MappingProxyType(dict(families))
        try:
            valid_sources = self._validate_sources(
                principal_id, strategy_class, records, family_snapshot,
            )
        except Exception:
            raise StrategyAuthorizationError("source execution evidence validation failed") from None
        if valid_sources is not True:
            raise StrategyAuthorizationError("source execution evidence is not authenticated")

        observation_data = [asdict(record) for record in sorted(
            records, key=lambda item: (item.strategy_id, item.task_id),
        )]
        manifest = {
            "manifest_schema": _MANIFEST_SCHEMA,
            "principal_id": principal_id,
            "strategy_class": strategy_class,
            "baseline_id": baseline_id,
            "baseline_version": baseline_version,
            "candidate_id": candidate_id,
            "candidate_version": candidate_version,
            "cohort_sha256": evaluation.cohort_sha256,
            "cohort_schema": evaluation.cohort_schema,
            "matched_pairs": evaluation.matched_pairs,
            "task_family": task_family,
            "observations": observation_data,
        }
        manifest_json = _canonical(manifest)
        manifest_bytes = manifest_json.encode("utf-8")
        if len(manifest_bytes) > _MAX_MANIFEST_BYTES:
            raise StrategyAuthorizationError("evidence manifest exceeds the configured size limit")
        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        try:
            now = self._clock()
            if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
                raise ValueError("clock must be timezone-aware")
            created_at = now.astimezone(timezone.utc).isoformat()
        except Exception:
            raise StrategyAuthorizationError("manifest clock is invalid") from None

        with self._tasks._lock:
            connection = self._tasks._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """INSERT OR IGNORE INTO strategy_evidence_manifests(
                    manifest_sha256,principal_id,strategy_class,baseline_id,baseline_version,
                    candidate_id,candidate_version,cohort_sha256,cohort_schema,matched_pairs,
                    task_family,manifest_json,created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        manifest_sha256, principal_id, strategy_class, baseline_id,
                        baseline_version, candidate_id, candidate_version,
                        evaluation.cohort_sha256, evaluation.cohort_schema,
                        evaluation.matched_pairs, task_family, manifest_json, created_at,
                    ),
                )
                existing = connection.execute(
                    "SELECT manifest_json,principal_id FROM strategy_evidence_manifests WHERE manifest_sha256=?",
                    (manifest_sha256,),
                ).fetchone()
                if not existing or existing[0] != manifest_json or existing[1] != principal_id:
                    raise StrategyStoreError("immutable evidence manifest digest collision")
                connection.execute("COMMIT")
            except Exception:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                connection.close()

        return StrategyEvidenceContext(
            principal_id=principal_id,
            strategy_class=strategy_class,
            baseline_id=baseline_id,
            baseline_version=baseline_version,
            candidate_id=candidate_id,
            candidate_version=candidate_version,
            cohort_sha256=evaluation.cohort_sha256,
            cohort_schema=evaluation.cohort_schema,
            evidence_manifest_ref=f"sqlite-strategy-manifest:{manifest_sha256}",
            matched_pairs=evaluation.matched_pairs,
        )

    def attest_manifest(self, context: StrategyEvidenceContext) -> str | None:
        """Callback for HostStrategyEvidenceAuthority.issue."""
        match = _MANIFEST_REF.fullmatch(context.evidence_manifest_ref) if (
            type(context) is StrategyEvidenceContext
            and type(context.evidence_manifest_ref) is str
        ) else None
        if match is None:
            return None
        digest = match.group(1)
        verified_context = replace(context, evidence_manifest_ref=f"sha256:{digest}")
        return digest if self.verify_manifest(verified_context, digest) is True else None

    def verify_manifest(self, context: StrategyEvidenceContext, manifest_sha256: str) -> bool:
        """Callback for HostStrategyEvidenceAuthority.verify; rechecks immutable source records."""
        try:
            if type(context) is not StrategyEvidenceContext or not _SHA256.fullmatch(manifest_sha256):
                return False
            match = _DIGEST_REF.fullmatch(context.evidence_manifest_ref)
            if match is None or match.group(1) != manifest_sha256:
                return False
            with self._tasks._lock:
                connection = self._tasks._connect()
                try:
                    row = connection.execute(
                        """SELECT principal_id,strategy_class,baseline_id,baseline_version,
                        candidate_id,candidate_version,cohort_sha256,cohort_schema,
                        matched_pairs,task_family,manifest_json
                        FROM strategy_evidence_manifests WHERE manifest_sha256=?""",
                        (manifest_sha256,),
                    ).fetchone()
                finally:
                    connection.close()
            if row is None:
                return False
            (
                principal, category, baseline, baseline_version, candidate,
                candidate_version, cohort_sha256, cohort_schema, matched_pairs,
                task_family, manifest_json,
            ) = row
            manifest = _decode_manifest_blob(
                manifest_sha256,
                manifest_json,
                {
                    "principal_id": principal,
                    "strategy_class": category,
                    "baseline_id": baseline,
                    "baseline_version": baseline_version,
                    "candidate_id": candidate,
                    "candidate_version": candidate_version,
                    "cohort_sha256": cohort_sha256,
                    "cohort_schema": cohort_schema,
                    "matched_pairs": matched_pairs,
                    "task_family": task_family,
                },
            )
            if (
                context.principal_id != principal
                or context.strategy_class != category
                or context.baseline_id != baseline
                or context.baseline_version != baseline_version
                or context.candidate_id != candidate
                or context.candidate_version != candidate_version
                or context.cohort_sha256 != cohort_sha256
                or context.cohort_schema != cohort_schema
                or context.matched_pairs != matched_pairs
            ):
                return False
            raw_observations = manifest["observations"]
            records: list[StrategyObservation] = []
            for item in raw_observations:
                if type(item) is not dict or set(item) != _OBSERVATION_FIELDS:
                    return False
                records.append(StrategyObservation(**item))
            validated_records = self._validate_observations(baseline, candidate, tuple(records))
            canonical_observations = [asdict(record) for record in sorted(
                validated_records, key=lambda item: (item.strategy_id, item.task_id),
            )]
            if canonical_observations != raw_observations:
                return False
            evaluation = evaluate_strategies(baseline, candidate, validated_records, min_pairs=20)
            if (
                not evaluation.eligible_for_manual_review
                or evaluation.cohort_sha256 != cohort_sha256
                or evaluation.cohort_schema != cohort_schema
                or evaluation.matched_pairs != matched_pairs
                or evaluation.baseline_version != baseline_version
                or evaluation.candidate_version != candidate_version
            ):
                return False
            families: dict[str, str] = {}
            for task_id in sorted({record.task_id for record in records}):
                family = self._classify(principal, task_id)
                if type(family) is not str or family != task_family or family not in _ALLOWED_TASK_FAMILIES:
                    return False
                families[task_id] = family
            if self._validate_sources(
                principal, category, tuple(records), MappingProxyType(dict(families)),
            ) is not True:
                return False
            return True
        except Exception:
            return False

def validate_strategy_evidence_snapshot(connection: sqlite3.Connection) -> None:
    """Validate optional strategy evidence manifests during task-store backup/restore."""
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='strategy_evidence_manifests'"
    ).fetchone()
    if table is None:
        return
    column_info = connection.execute("PRAGMA table_info(strategy_evidence_manifests)").fetchall()
    columns = {row[1] for row in column_info}
    required_columns = {
        "manifest_sha256", "principal_id", "strategy_class", "baseline_id",
        "baseline_version", "candidate_id", "candidate_version", "cohort_sha256",
        "cohort_schema", "matched_pairs", "task_family", "manifest_json", "created_at",
    }
    if not required_columns.issubset(columns):
        raise StrategyStoreError("strategy evidence manifest schema is incomplete")
    primary_key = [row[1] for row in column_info if row[5]]
    if primary_key != ["manifest_sha256"]:
        raise StrategyStoreError("strategy evidence manifest primary key is invalid")
    triggers = {
        row[0]: (row[1] or "").upper()
        for row in connection.execute(
            "SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='strategy_evidence_manifests'"
        ).fetchall()
    }
    if (
        "BEFORE UPDATE ON STRATEGY_EVIDENCE_MANIFESTS" not in triggers.get("strategy_evidence_immutable_update", "")
        or "RAISE(ABORT" not in triggers.get("strategy_evidence_immutable_update", "")
        or "BEFORE DELETE ON STRATEGY_EVIDENCE_MANIFESTS" not in triggers.get("strategy_evidence_immutable_delete", "")
        or "RAISE(ABORT" not in triggers.get("strategy_evidence_immutable_delete", "")
    ):
        raise StrategyStoreError("strategy evidence append-only protections are missing")
    unique_cohort_index = False
    for index in connection.execute("PRAGMA index_list(strategy_evidence_manifests)").fetchall():
        if index[2] != 1:
            continue
        index_name = str(index[1]).replace('"', '""')
        indexed_columns = [
            row[2] for row in connection.execute(f'PRAGMA index_info("{index_name}")').fetchall()
        ]
        if indexed_columns == ["principal_id", "strategy_class", "cohort_sha256"]:
            unique_cohort_index = True
            break
    if not unique_cohort_index:
        raise StrategyStoreError("strategy evidence cohort uniqueness constraint is missing")

    rows = connection.execute(
        """SELECT manifest_sha256,principal_id,strategy_class,baseline_id,baseline_version,
        candidate_id,candidate_version,cohort_sha256,cohort_schema,matched_pairs,
        task_family,manifest_json,created_at FROM strategy_evidence_manifests"""
    )
    for row in rows:
        (
            digest, principal, category, baseline, baseline_version, candidate,
            candidate_version, cohort_sha256, cohort_schema, matched_pairs,
            task_family, manifest_json, created_at,
        ) = row
        manifest = _decode_manifest_blob(
            digest,
            manifest_json,
            {
                "principal_id": principal,
                "strategy_class": category,
                "baseline_id": baseline,
                "baseline_version": baseline_version,
                "candidate_id": candidate,
                "candidate_version": candidate_version,
                "cohort_sha256": cohort_sha256,
                "cohort_schema": cohort_schema,
                "matched_pairs": matched_pairs,
                "task_family": task_family,
            },
        )
        records = tuple(StrategyObservation(**item) for item in manifest["observations"])
        validated_records = SQLiteStrategyEvidenceManifestStore._validate_observations(
            baseline, candidate, records,
        )
        canonical_observations = [asdict(record) for record in sorted(
            validated_records, key=lambda item: (item.strategy_id, item.task_id),
        )]
        if canonical_observations != manifest["observations"]:
            raise StrategyStoreError("strategy evidence observation ordering is invalid")
        evaluation = evaluate_strategies(baseline, candidate, validated_records, min_pairs=20)
        if (
            not evaluation.eligible_for_manual_review
            or evaluation.cohort_sha256 != cohort_sha256
            or evaluation.cohort_schema != cohort_schema
            or evaluation.matched_pairs != matched_pairs
            or evaluation.baseline_version != baseline_version
            or evaluation.candidate_version != candidate_version
        ):
            raise StrategyStoreError("strategy evidence cohort fingerprint is invalid")
        created_text = _text(created_at, "manifest created_at", 64)
        try:
            created = datetime.fromisoformat(created_text)
        except ValueError:
            raise StrategyStoreError("strategy evidence manifest timestamp is invalid") from None
        if (
            created.tzinfo is None or created.utcoffset() is None
            or created.astimezone(timezone.utc).isoformat() != created_text
        ):
            raise StrategyStoreError("strategy evidence manifest timestamp is invalid")

