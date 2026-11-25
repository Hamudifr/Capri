"""Principal-scoped, approval-gated strategy registry with reversible history.

The registry stores data-only strategy configurations and evaluation summaries.
It never executes strategy code or changes tool permissions, safety policy, or
spend limits. Activation requires a trusted host-supplied approval verifier.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable
from uuid import uuid4

from capri_core.validation import contains_surrogate
from capri_core.strategy import StrategyEvaluation, StrategyObservation, evaluate_strategies
from capri_core.strategy_promotion import (
    PromotionCohort, StrategyPromotionAssessment, assess_strategy_canary,
    STRATEGY_PROMOTION_POLICY_VERSION,
)
from .tasks import SQLiteTaskStore


_ID = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RESERVED_CONFIG_KEYS = frozenset({
    "permissions", "allowed_tools", "tools", "budget", "spend_limit",
    "safety_policy", "system_prompt", "api_key", "token", "secret",
    "credential", "code", "script", "command",
})
_MAX_CONFIG_BYTES = 8192
_MAX_APPROVAL_TTL = 900


class StrategyStoreError(ValueError):
    """Base error for invalid strategy registry operations."""


class StrategyAuthorizationError(StrategyStoreError):
    """Activation or rollback lacks a valid host-authenticated approval."""


class StrategyConflictError(StrategyStoreError):
    """A strategy version, approval, or active generation conflicts."""


class StrategyNotFoundError(StrategyStoreError):
    """The requested principal-owned strategy record does not exist."""


class StrategyIntegrityError(StrategyStoreError):
    """The append-only strategy event history or active projection is inconsistent."""


@dataclass(frozen=True, slots=True)
class StrategyActivationGrant:
    """Host-authenticated, one-use approval bound to one exact state transition."""

    grant_id: str
    principal_id: str
    strategy_class: str
    strategy_id: str
    version: str
    evaluation_sha256: str | None
    config_sha256: str
    expected_generation: int
    action: str
    issued_at: str
    expires_at: str
    approver_id: str
    signature: str
    promotion_assessment_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class StrategyEvidenceContext:
    """Exact immutable binding a trusted host evidence verifier must authenticate."""

    principal_id: str
    strategy_class: str
    baseline_id: str
    baseline_version: str
    candidate_id: str
    candidate_version: str
    cohort_sha256: str
    cohort_schema: str
    evidence_manifest_ref: str
    matched_pairs: int
    cohort_id: str | None = None
    task_family: str | None = None


@dataclass(frozen=True, slots=True)
class StrategyVersionRecord:
    principal_id: str
    strategy_class: str
    strategy_id: str
    version: str
    config: dict[str, Any]
    config_sha256: str
    is_baseline: bool
    evaluation_sha256: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class ActiveStrategyRecord:
    principal_id: str
    strategy_class: str
    strategy_id: str
    version: str
    generation: int
    config: dict[str, Any]
    config_sha256: str
    activated_at: str
    event_id: str
    promotion_assessment_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class StrategyActivationEvent:
    event_id: str
    principal_id: str
    strategy_class: str
    generation: int
    action: str
    from_strategy_id: str | None
    from_version: str | None
    to_strategy_id: str
    to_version: str
    config_sha256: str
    evaluation_sha256: str | None
    approval_id: str
    approver_id: str
    created_at: str
    previous_hash: str
    event_hash: str
    promotion_assessment_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class StrategyPromotionRecord:
    assessment_id: str
    principal_id: str
    strategy_class: str
    baseline_id: str
    baseline_version: str
    candidate_id: str
    candidate_version: str
    policy_version: str
    task_family: str
    primary_metric: str
    assessment_sha256: str
    summary: dict[str, Any]
    evidence_manifest_refs: tuple[tuple[str, str], ...]
    cohort_sha256s: tuple[tuple[str, str], ...]
    created_at: str


def _text(value: object, field: str, maximum: int = 256) -> str:
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise StrategyStoreError(f"{field} must be a non-empty bounded string")
    if contains_surrogate(value) or value != value.strip():
        raise StrategyStoreError(f"{field} contains invalid or non-normalized text")
    return value


def _identifier(value: object, field: str) -> str:
    result = _text(value, field, 64)
    if not _ID.fullmatch(result):
        raise StrategyStoreError(f"{field} must use lowercase identifier syntax")
    return result


def _version(value: object) -> str:
    result = _text(value, "version", 64)
    if not _VERSION.fullmatch(result) or result == "unversioned":
        raise StrategyStoreError("version must be an explicit bounded version identifier")
    return result


def _timestamp(value: object, field: str) -> datetime:
    if type(value) is not str or not value or len(value) > 64:
        raise StrategyStoreError(f"{field} must be a timezone-aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise StrategyStoreError(f"{field} must be a timezone-aware ISO timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise StrategyStoreError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _config_value(value: object, *, depth: int = 0) -> object:
    if depth > 4:
        raise StrategyStoreError("strategy config nesting exceeds the supported depth")
    if value is None or type(value) in (bool, int, str):
        if type(value) is str and (
            len(value) > 512 or contains_surrogate(value)
        ):
            raise StrategyStoreError("strategy config string is invalid or too long")
        if type(value) is int and abs(value) > 10**12:
            raise StrategyStoreError("strategy config integer exceeds its bound")
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise StrategyStoreError("strategy config floats must be finite")
        return value
    if type(value) is list:
        if len(value) > 32:
            raise StrategyStoreError("strategy config lists exceed 32 items")
        return [_config_value(item, depth=depth + 1) for item in value]
    if type(value) is dict:
        if len(value) > 32:
            raise StrategyStoreError("strategy config objects exceed 32 keys")
        result: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key):
                raise StrategyStoreError("strategy config keys must be lowercase identifiers")
            if key in _RESERVED_CONFIG_KEYS:
                raise StrategyStoreError(f"strategy config cannot modify reserved field: {key}")
            result[key] = _config_value(item, depth=depth + 1)
        return result
    raise StrategyStoreError("strategy config accepts JSON data only")


def _encode_config(config: object) -> tuple[str, str]:
    if type(config) is not dict:
        raise StrategyStoreError("strategy config must be a JSON object")
    normalized = _config_value(config)
    encoded = json.dumps(
        normalized, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    )
    if len(encoded.encode("utf-8")) > _MAX_CONFIG_BYTES:
        raise StrategyStoreError("strategy config exceeds the 8192-byte limit")
    return encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _decode_config(encoded: str, expected_hash: str) -> dict[str, Any]:
    if hashlib.sha256(encoded.encode("utf-8")).hexdigest() != expected_hash:
        raise StrategyIntegrityError("stored strategy config hash does not match")
    try:
        value = json.loads(encoded)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise StrategyIntegrityError("stored strategy config is corrupt") from None
    if type(value) is not dict:
        raise StrategyIntegrityError("stored strategy config is not an object")
    return value


def _grant_payload(grant: StrategyActivationGrant) -> None:
    if type(grant) is not StrategyActivationGrant:
        raise StrategyAuthorizationError("a host-issued StrategyActivationGrant is required")
    _text(grant.grant_id, "grant_id", 128)
    _text(grant.principal_id, "principal_id", 128)
    _identifier(grant.strategy_class, "strategy_class")
    _identifier(grant.strategy_id, "strategy_id")
    _version(grant.version)
    if grant.evaluation_sha256 is not None and (
        type(grant.evaluation_sha256) is not str
        or not _SHA256.fullmatch(grant.evaluation_sha256)
    ):
        raise StrategyAuthorizationError("evaluation fingerprint is invalid")
    if type(grant.expected_generation) is not int or not 0 <= grant.expected_generation < 2**63 - 1:
        raise StrategyAuthorizationError("expected_generation is invalid")
    if type(grant.action) is not str or grant.action not in {"activate", "rollback"}:
        raise StrategyAuthorizationError("grant action must be activate or rollback")
    if type(grant.config_sha256) is not str or not _SHA256.fullmatch(grant.config_sha256):
        raise StrategyAuthorizationError("strategy config fingerprint is invalid")
    issued = _timestamp(grant.issued_at, "issued_at")
    expires = _timestamp(grant.expires_at, "expires_at")
    if expires <= issued or (expires - issued).total_seconds() > _MAX_APPROVAL_TTL:
        raise StrategyAuthorizationError("approval grant lifetime is invalid")
    _text(grant.approver_id, "approver_id", 128)
    _text(grant.signature, "signature", 2048)
    if grant.promotion_assessment_sha256 is not None and (
        type(grant.promotion_assessment_sha256) is not str
        or not _SHA256.fullmatch(grant.promotion_assessment_sha256)
    ):
        raise StrategyAuthorizationError("promotion assessment fingerprint is invalid")


def _promotion_json(value: object, *, field: str, maximum: int) -> str:
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        )
    except (TypeError, ValueError):
        raise StrategyStoreError(f"{field} is not canonical JSON data") from None
    if len(encoded.encode("utf-8")) > maximum:
        raise StrategyStoreError(f"{field} exceeds its size limit")
    return encoded


def _promotion_record_digest(summary_json: str, refs_json: str, hashes_json: str) -> str:
    try:
        summary = json.loads(summary_json)
        refs = json.loads(refs_json)
        hashes = json.loads(hashes_json)
        if type(summary) is not dict or type(refs) is not dict or type(hashes) is not dict:
            raise ValueError("promotion record payloads must be JSON objects")
        payload = {
            "schema": "capri.strategy-promotion-record.v1",
            "summary": summary,
            "evidence_manifest_refs": refs,
            "cohort_sha256s": hashes,
        }
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, json.JSONDecodeError):
        raise StrategyIntegrityError("stored promotion assessment is corrupt") from None
    return hashlib.sha256(encoded).hexdigest()


def _promotion_record_from_row(row: tuple[Any, ...]) -> StrategyPromotionRecord:
    summary_json, refs_json, hashes_json = row[10], row[11], row[12]
    if (
        len(summary_json.encode("utf-8")) > 32_768
        or len(refs_json.encode("utf-8")) > 4_096
        or len(hashes_json.encode("utf-8")) > 2_048
    ):
        raise StrategyIntegrityError("stored promotion assessment exceeds its size bounds")
    digest = _promotion_record_digest(summary_json, refs_json, hashes_json)
    if digest != row[9]:
        raise StrategyIntegrityError("promotion assessment fingerprint does not match its stored evidence")
    try:
        summary = json.loads(summary_json)
        refs = json.loads(refs_json)
        hashes = json.loads(hashes_json)
        if type(summary) is not dict or type(refs) is not dict or type(hashes) is not dict:
            raise ValueError("invalid promotion record")
        normalized_refs = tuple(sorted(
            (_text(key, "cohort_id", 128), _text(value, "evidence_manifest_ref", 512))
            for key, value in refs.items()
        ))
        normalized_hashes = tuple(sorted(
            (_text(key, "cohort_id", 128), value)
            for key, value in hashes.items()
            if type(value) is str and _SHA256.fullmatch(value)
        ))
        if len(normalized_hashes) != len(hashes):
            raise ValueError("invalid cohort fingerprint")
        if {key for key, _ in normalized_refs} != {key for key, _ in normalized_hashes}:
            raise ValueError("cohort evidence bindings are inconsistent")
    except (TypeError, ValueError, json.JSONDecodeError):
        raise StrategyIntegrityError("stored promotion assessment payload is invalid") from None
    return StrategyPromotionRecord(
        row[0], row[1], row[2], row[3], row[4], row[5], row[6],
        row[7], row[8], row[13], row[9], summary, normalized_refs,
        normalized_hashes, row[14],
    )


class SQLiteStrategyStore:
    """Append-only strategy registry sharing the task store's private SQLite DB.

    A trusted host must inject an approval verifier. Missing, false, or failing
    verifiers deny activation and rollback. The model never receives the verifier.
    """

    def __init__(
        self,
        task_store: SQLiteTaskStore,
        *,
        approval_verifier: Callable[[StrategyActivationGrant], bool] | None = None,
        evidence_verifier: Callable[[StrategyEvidenceContext], bool] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if type(task_store) is not SQLiteTaskStore:
            raise StrategyStoreError("SQLiteStrategyStore requires the exact trusted SQLiteTaskStore")
        if approval_verifier is not None and not callable(approval_verifier):
            raise StrategyStoreError("approval_verifier must be callable")
        if evidence_verifier is not None and not callable(evidence_verifier):
            raise StrategyStoreError("evidence_verifier must be callable")
        if clock is not None and not callable(clock):
            raise StrategyStoreError("clock must be callable")
        self._task_store = task_store
        self._approval_verifier = approval_verifier
        self._evidence_verifier = evidence_verifier
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = task_store._lock
        self._initialize()

    @property
    def task_store(self) -> SQLiteTaskStore:
        """The exact task store whose private database and lock this registry shares."""
        return self._task_store

    def _connect(self) -> sqlite3.Connection:
        return self._task_store._connect()

    def _now(self) -> datetime:
        try:
            value = self._clock()
        except Exception:
            raise StrategyAuthorizationError("trusted strategy clock is unavailable") from None
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise StrategyAuthorizationError("trusted strategy clock must return an aware datetime")
        return value.astimezone(timezone.utc)

    def _initialize(self) -> None:
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("""CREATE TABLE IF NOT EXISTS strategy_evaluations (
                    evaluation_id TEXT PRIMARY KEY,
                    principal_id TEXT NOT NULL,
                    strategy_class TEXT NOT NULL,
                    baseline_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    cohort_sha256 TEXT NOT NULL,
                    matched_pairs INTEGER NOT NULL CHECK(matched_pairs >= 20),
                    eligible INTEGER NOT NULL CHECK(eligible=1),
                    evidence_verified INTEGER NOT NULL CHECK(evidence_verified IN (0,1)),
                    summary_json TEXT NOT NULL,
                    evidence_manifest_ref TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(principal_id, strategy_class, cohort_sha256)
                )""")
                evaluation_columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(strategy_evaluations)")
                }
                if "evidence_verified" not in evaluation_columns:
                    connection.execute(
                        "ALTER TABLE strategy_evaluations ADD COLUMN "
                        "evidence_verified INTEGER NOT NULL DEFAULT 0 "
                        "CHECK(evidence_verified IN (0,1))"
                    )
                connection.execute("""CREATE TABLE IF NOT EXISTS strategy_versions (
                    principal_id TEXT NOT NULL,
                    strategy_class TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    config_sha256 TEXT NOT NULL,
                    is_baseline INTEGER NOT NULL CHECK(is_baseline IN (0,1)),
                    evaluation_id TEXT REFERENCES strategy_evaluations(evaluation_id),
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(principal_id, strategy_class, strategy_id, version),
                    CHECK(
                        (is_baseline=1 AND evaluation_id IS NULL)
                        OR (is_baseline=0 AND evaluation_id IS NOT NULL)
                    ),
                    UNIQUE(evaluation_id)
                )""")
                connection.execute("""CREATE TABLE IF NOT EXISTS strategy_promotion_assessments (
                    assessment_id TEXT PRIMARY KEY,
                    principal_id TEXT NOT NULL,
                    strategy_class TEXT NOT NULL,
                    baseline_id TEXT NOT NULL,
                    baseline_version TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    candidate_version TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    task_family TEXT NOT NULL,
                    primary_metric TEXT NOT NULL,
                    assessment_sha256 TEXT NOT NULL CHECK(length(assessment_sha256)=64),
                    summary_json TEXT NOT NULL CHECK(length(summary_json)<=32768),
                    evidence_manifest_refs_json TEXT NOT NULL CHECK(length(evidence_manifest_refs_json)<=4096),
                    cohort_sha256s_json TEXT NOT NULL CHECK(length(cohort_sha256s_json)<=2048),
                    eligible_for_canary INTEGER NOT NULL CHECK(eligible_for_canary=1),
                    created_at TEXT NOT NULL,
                    UNIQUE(principal_id,strategy_class,candidate_id,candidate_version,assessment_sha256),
                    FOREIGN KEY(principal_id,strategy_class,baseline_id,baseline_version)
                        REFERENCES strategy_versions(principal_id,strategy_class,strategy_id,version),
                    FOREIGN KEY(principal_id,strategy_class,candidate_id,candidate_version)
                        REFERENCES strategy_versions(principal_id,strategy_class,strategy_id,version)
                )""")
                connection.execute("""CREATE TABLE IF NOT EXISTS strategy_events (
                    event_id TEXT PRIMARY KEY,
                    principal_id TEXT NOT NULL,
                    strategy_class TEXT NOT NULL,
                    generation INTEGER NOT NULL CHECK(generation > 0),
                    action TEXT NOT NULL CHECK(action IN ('activate','rollback')),
                    from_strategy_id TEXT,
                    from_version TEXT,
                    to_strategy_id TEXT NOT NULL,
                    to_version TEXT NOT NULL,
                    to_config_sha256 TEXT NOT NULL,
                    evaluation_id TEXT REFERENCES strategy_evaluations(evaluation_id),
                    approval_id TEXT NOT NULL UNIQUE,
                    approver_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL,
                    promotion_assessment_sha256 TEXT,
                    UNIQUE(principal_id, strategy_class, generation),
                    CHECK(
                        (from_strategy_id IS NULL AND from_version IS NULL)
                        OR (from_strategy_id IS NOT NULL AND from_version IS NOT NULL)
                    ),
                    FOREIGN KEY(principal_id, strategy_class, to_strategy_id, to_version)
                        REFERENCES strategy_versions(principal_id, strategy_class, strategy_id, version),
                    FOREIGN KEY(principal_id, strategy_class, from_strategy_id, from_version)
                        REFERENCES strategy_versions(principal_id, strategy_class, strategy_id, version)
                )""")
                event_columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(strategy_events)")
                }
                if "promotion_assessment_sha256" not in event_columns:
                    connection.execute(
                        "ALTER TABLE strategy_events ADD COLUMN promotion_assessment_sha256 TEXT"
                    )
                connection.execute("""CREATE TABLE IF NOT EXISTS strategy_active (
                    principal_id TEXT NOT NULL,
                    strategy_class TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    generation INTEGER NOT NULL CHECK(generation > 0),
                    event_id TEXT NOT NULL REFERENCES strategy_events(event_id),
                    PRIMARY KEY(principal_id, strategy_class),
                    FOREIGN KEY(principal_id, strategy_class, strategy_id, version)
                        REFERENCES strategy_versions(principal_id, strategy_class, strategy_id, version)
                )""")
                for table in (
                    "strategy_evaluations", "strategy_versions",
                    "strategy_promotion_assessments", "strategy_events",
                ):
                    connection.execute(f"""CREATE TRIGGER IF NOT EXISTS {table}_immutable_update
                        BEFORE UPDATE ON {table}
                        BEGIN SELECT RAISE(ABORT, '{table} are immutable'); END""")
                    connection.execute(f"""CREATE TRIGGER IF NOT EXISTS {table}_immutable_delete
                        BEFORE DELETE ON {table}
                        BEGIN SELECT RAISE(ABORT, '{table} are immutable'); END""")
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS strategy_versions_owner_idx "
                    "ON strategy_versions(principal_id, strategy_class, strategy_id)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS strategy_events_owner_idx "
                    "ON strategy_events(principal_id, strategy_class, generation)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS strategy_promotion_assessments_owner_idx "
                    "ON strategy_promotion_assessments(principal_id, strategy_class, candidate_id, candidate_version)"
                )
            finally:
                connection.close()

    def register_baseline_for_principal(
        self, principal_id: str, strategy_class: str, strategy_id: str,
        version: str, config: dict[str, Any], *,
        created_at: datetime | None = None,
    ) -> StrategyVersionRecord:
        principal = _text(principal_id, "principal_id", 128)
        category = _identifier(strategy_class, "strategy_class")
        strategy = _identifier(strategy_id, "strategy_id")
        version = _version(version)
        config_json, config_hash = _encode_config(config)
        timestamp = created_at or datetime.now(timezone.utc)
        if not isinstance(timestamp, datetime) or timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise StrategyStoreError("created_at must be timezone-aware")
        timestamp = timestamp.astimezone(timezone.utc)
        created = timestamp.isoformat()
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """SELECT config_json, config_sha256, is_baseline, evaluation_id, created_at
                    FROM strategy_versions WHERE principal_id=? AND strategy_class=?
                    AND strategy_id=? AND version=?""",
                    (principal, category, strategy, version),
                ).fetchone()
                if row is None:
                    connection.execute(
                        """INSERT INTO strategy_versions
                        (principal_id,strategy_class,strategy_id,version,config_json,
                         config_sha256,is_baseline,evaluation_id,created_at)
                        VALUES (?,?,?,?,?,?,1,NULL,?)""",
                        (principal, category, strategy, version, config_json, config_hash, created),
                    )
                elif row[:4] != (config_json, config_hash, 1, None):
                    raise StrategyConflictError("baseline version already exists with different content")
                if row is not None:
                    created = row[4]
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()
        return StrategyVersionRecord(
            principal, category, strategy, version, json.loads(config_json),
            config_hash, True, None, created,
        )

    def register_candidate_for_principal(
        self, principal_id: str, strategy_class: str, strategy_id: str,
        version: str, config: dict[str, Any], evaluation: StrategyEvaluation, *,
        observations: Iterable[StrategyObservation],
        evidence_manifest_ref: str,
        created_at: datetime | None = None,
    ) -> StrategyVersionRecord:
        principal = _text(principal_id, "principal_id", 128)
        category = _identifier(strategy_class, "strategy_class")
        strategy = _identifier(strategy_id, "strategy_id")
        version = _version(version)
        if type(evaluation) is not StrategyEvaluation:
            raise StrategyStoreError("a StrategyEvaluation result is required")
        try:
            baseline_id = _identifier(evaluation.baseline_id, "baseline_id")
            candidate_id = _identifier(evaluation.candidate_id, "candidate_id")
            baseline_version = _version(evaluation.baseline_version)
            candidate_version = _version(evaluation.candidate_version)
            recomputed = evaluate_strategies(
                baseline_id, candidate_id, observations, min_pairs=20
            )
        except Exception:
            raise StrategyStoreError("candidate evaluation could not be independently recomputed") from None
        if (
            candidate_id != strategy
            or candidate_version != version
            or evaluation.eligible_for_manual_review is not True
            or evaluation.blocked_reasons
            or not evaluation.improved_dimensions
            or type(evaluation.matched_pairs) is not int
            or evaluation.matched_pairs < 20
            or type(evaluation.cohort_sha256) is not str
            or not _SHA256.fullmatch(evaluation.cohort_sha256)
            or recomputed.to_dict() != evaluation.to_dict()
        ):
            raise StrategyStoreError("candidate evaluation does not meet the independently recomputed registry admission gate")
        evidence_ref = _text(evidence_manifest_ref, "evidence_manifest_ref", 512)
        if self._evidence_verifier is None:
            raise StrategyAuthorizationError(
                "candidate admission requires a trusted host evidence verifier"
            )
        evidence_context = StrategyEvidenceContext(
            principal_id=principal,
            strategy_class=category,
            baseline_id=baseline_id,
            baseline_version=baseline_version,
            candidate_id=candidate_id,
            candidate_version=candidate_version,
            cohort_sha256=evaluation.cohort_sha256,
            cohort_schema=evaluation.cohort_schema,
            evidence_manifest_ref=evidence_ref,
            matched_pairs=evaluation.matched_pairs,
        )
        try:
            evidence_verified = self._evidence_verifier(evidence_context)
        except Exception:
            raise StrategyAuthorizationError("candidate evidence verification failed") from None
        if evidence_verified is not True:
            raise StrategyAuthorizationError("candidate evidence provenance could not be verified")
        config_json, config_hash = _encode_config(config)
        timestamp = created_at or datetime.now(timezone.utc)
        if not isinstance(timestamp, datetime) or timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise StrategyStoreError("created_at must be timezone-aware")
        timestamp = timestamp.astimezone(timezone.utc)
        created = timestamp.isoformat()
        summary_json = json.dumps(
            evaluation.to_dict(), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        )
        if len(summary_json.encode("utf-8")) > 16_384:
            raise StrategyStoreError("evaluation summary exceeds its size limit")
        evaluation_id = uuid4().hex

        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                baseline = connection.execute(
                    """SELECT 1 FROM strategy_versions WHERE principal_id=?
                    AND strategy_class=? AND strategy_id=? AND version=? AND is_baseline=1""",
                    (principal, category, baseline_id, baseline_version),
                ).fetchone()
                if baseline is None:
                    raise StrategyNotFoundError("the evaluated baseline is not registered for this principal")
                existing_evaluation = connection.execute(
                    """SELECT evaluation_id,baseline_id,candidate_id,summary_json,evidence_manifest_ref,evidence_verified
                    FROM strategy_evaluations WHERE principal_id=? AND strategy_class=? AND cohort_sha256=?""",
                    (principal, category, evaluation.cohort_sha256),
                ).fetchone()
                if existing_evaluation is not None:
                    if existing_evaluation[5] != 1:
                        raise StrategyAuthorizationError(
                            "existing cohort evidence is unverified; register a new verified cohort"
                        )
                    evaluation_id = existing_evaluation[0]
                    if existing_evaluation[1:5] != (
                        evaluation.baseline_id, evaluation.candidate_id,
                        summary_json, evidence_ref,
                    ):
                        raise StrategyConflictError("cohort fingerprint already belongs to different evaluation data")
                else:
                    connection.execute(
                        """INSERT INTO strategy_evaluations
                        (evaluation_id,principal_id,strategy_class,baseline_id,candidate_id,
                         cohort_sha256,matched_pairs,eligible,evidence_verified,summary_json,evidence_manifest_ref,created_at)
                        VALUES (?,?,?,?,?,?,?,1,1,?,?,?)""",
                        (evaluation_id, principal, category, baseline_id,
                         candidate_id, evaluation.cohort_sha256,
                         evaluation.matched_pairs, summary_json, evidence_ref, created),
                    )
                existing_version = connection.execute(
                    """SELECT config_json,config_sha256,is_baseline,evaluation_id
                    FROM strategy_versions WHERE principal_id=? AND strategy_class=?
                    AND strategy_id=? AND version=?""",
                    (principal, category, strategy, version),
                ).fetchone()
                if existing_version is None:
                    connection.execute(
                        """INSERT INTO strategy_versions
                        (principal_id,strategy_class,strategy_id,version,config_json,
                         config_sha256,is_baseline,evaluation_id,created_at)
                        VALUES (?,?,?,?,?,?,0,?,?)""",
                        (principal, category, strategy, version, config_json,
                         config_hash, evaluation_id, created),
                    )
                elif existing_version != (config_json, config_hash, 0, evaluation_id):
                    raise StrategyConflictError("candidate version already exists with different content")
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()
        return StrategyVersionRecord(
            principal, category, strategy, version, json.loads(config_json),
            config_hash, False, evaluation.cohort_sha256, created,
        )

    def register_promotion_assessment_for_principal(
        self,
        principal_id: str,
        strategy_class: str,
        task_family: str,
        baseline_id: str,
        candidate_id: str,
        primary_metric: str,
        cohorts: Iterable[PromotionCohort],
        evidence_manifest_refs: dict[str, str],
        *,
        created_at: datetime | None = None,
    ) -> StrategyPromotionRecord:
        """Recompute, authenticate, and persist an eligible multi-cohort assessment.

        Raw observations remain in the host evidence source. This registry stores
        only the canonical assessment summary and the exact manifest locators.
        Every cohort is independently re-authenticated by the host verifier.
        """
        principal = _text(principal_id, "principal_id", 128)
        category = _identifier(strategy_class, "strategy_class")
        family = _identifier(task_family, "task_family")
        baseline = _identifier(baseline_id, "baseline_id")
        candidate = _identifier(candidate_id, "candidate_id")
        metric = _identifier(primary_metric, "primary_metric")
        if self._evidence_verifier is None:
            raise StrategyAuthorizationError(
                "promotion assessment registration requires a trusted host evidence verifier"
            )
        if isinstance(cohorts, (str, bytes)):
            raise StrategyStoreError("promotion cohorts must be an iterable of PromotionCohort records")
        try:
            iterator = iter(cohorts)
        except TypeError:
            raise StrategyStoreError("promotion cohorts must be iterable") from None
        cohort_list: list[PromotionCohort] = []
        for cohort in iterator:
            if len(cohort_list) >= 4:
                raise StrategyStoreError("promotion assessment exceeds the maximum of four cohorts")
            cohort_list.append(cohort)
        cohort_tuple = tuple(cohort_list)
        if len(cohort_tuple) < 2 or any(type(item) is not PromotionCohort for item in cohort_tuple):
            raise StrategyStoreError("promotion assessment requires at least two PromotionCohort records")
        cohort_ids = tuple(_text(item.cohort_id, "cohort_id", 128) for item in cohort_tuple)
        if len(set(cohort_ids)) != len(cohort_ids):
            raise StrategyStoreError("promotion cohort IDs must be unique")
        if type(evidence_manifest_refs) is not dict:
            raise StrategyStoreError("evidence_manifest_refs must be a bounded dictionary")
        if len(evidence_manifest_refs) != len(cohort_tuple):
            raise StrategyStoreError("every promotion cohort must have exactly one evidence manifest")
        refs: dict[str, str] = {}
        for key, value in evidence_manifest_refs.items():
            cohort_key = _text(key, "cohort_id", 128)
            refs[cohort_key] = _text(value, "evidence_manifest_ref", 512)
        if set(refs) != set(cohort_ids):
            raise StrategyStoreError("evidence manifest keys must exactly match the promotion cohort IDs")

        try:
            assessment = assess_strategy_canary(
                strategy_class=category,
                task_family=family,
                baseline_id=baseline,
                candidate_id=candidate,
                primary_metric=metric,
                cohorts=cohort_tuple,
            )
        except Exception:
            raise StrategyStoreError("promotion assessment could not be independently recomputed") from None
        if (
            type(assessment) is not StrategyPromotionAssessment
            or assessment.policy_version != STRATEGY_PROMOTION_POLICY_VERSION
            or assessment.eligible_for_canary is not True
            or assessment.blocked_reasons
            or assessment.baseline_version is None
            or assessment.candidate_version is None
        ):
            reasons = ",".join(assessment.blocked_reasons) if type(assessment) is StrategyPromotionAssessment else "invalid_assessment"
            raise StrategyAuthorizationError(
                f"promotion assessment is not eligible under the current policy: {reasons}"
            )

        cohort_evaluations: dict[str, StrategyEvaluation] = {}
        for cohort in cohort_tuple:
            try:
                evaluation = evaluate_strategies(
                    baseline, candidate, cohort.observations, min_pairs=20
                )
            except Exception:
                raise StrategyStoreError("promotion cohort could not be independently evaluated") from None
            if (
                evaluation.baseline_version != assessment.baseline_version
                or evaluation.candidate_version != assessment.candidate_version
                or evaluation.eligible_for_manual_review is not True
                or evaluation.blocked_reasons
                or evaluation.matched_pairs < 100
            ):
                raise StrategyAuthorizationError("promotion cohort failed its independent evaluation gate")
            context = StrategyEvidenceContext(
                principal_id=principal,
                strategy_class=category,
                baseline_id=baseline,
                baseline_version=assessment.baseline_version,
                candidate_id=candidate,
                candidate_version=assessment.candidate_version,
                cohort_sha256=evaluation.cohort_sha256,
                cohort_schema=evaluation.cohort_schema,
                evidence_manifest_ref=refs[cohort.cohort_id],
                matched_pairs=evaluation.matched_pairs,
                cohort_id=cohort.cohort_id,
                task_family=family,
            )
            try:
                verified = self._evidence_verifier(context)
            except Exception:
                raise StrategyAuthorizationError("promotion cohort evidence verification failed") from None
            if verified is not True:
                raise StrategyAuthorizationError("promotion cohort evidence provenance could not be verified")
            cohort_evaluations[cohort.cohort_id] = evaluation

        summary_json = _promotion_json(asdict(assessment), field="promotion assessment summary", maximum=32_768)
        refs_json = _promotion_json(dict(sorted(refs.items())), field="promotion evidence manifest references", maximum=4_096)
        cohort_hashes = {
            cohort_id: evaluation.cohort_sha256
            for cohort_id, evaluation in sorted(cohort_evaluations.items())
        }
        hashes_json = _promotion_json(cohort_hashes, field="promotion cohort fingerprints", maximum=2_048)
        assessment_hash = _promotion_record_digest(summary_json, refs_json, hashes_json)
        timestamp = created_at or self._now()
        if not isinstance(timestamp, datetime) or timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise StrategyStoreError("created_at must be timezone-aware")
        created = timestamp.astimezone(timezone.utc).isoformat()
        assessment_id = uuid4().hex

        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                baseline_row = connection.execute(
                    """SELECT is_baseline FROM strategy_versions
                    WHERE principal_id=? AND strategy_class=? AND strategy_id=? AND version=?""",
                    (principal, category, baseline, assessment.baseline_version),
                ).fetchone()
                if baseline_row is None or baseline_row[0] != 1:
                    raise StrategyNotFoundError("promotion baseline version is not registered for this principal")
                candidate_row = connection.execute(
                    """SELECT is_baseline,evaluation_id FROM strategy_versions
                    WHERE principal_id=? AND strategy_class=? AND strategy_id=? AND version=?""",
                    (principal, category, candidate, assessment.candidate_version),
                ).fetchone()
                if candidate_row is None or candidate_row[0] != 0 or candidate_row[1] is None:
                    raise StrategyNotFoundError("promotion candidate version is not registered for this principal")
                registered_evaluation = connection.execute(
                    """SELECT baseline_id,candidate_id,cohort_sha256,evidence_manifest_ref,evidence_verified,summary_json
                    FROM strategy_evaluations WHERE evaluation_id=?""",
                    (candidate_row[1],),
                ).fetchone()
                if (
                    registered_evaluation is None
                    or registered_evaluation[0] != baseline
                    or registered_evaluation[1] != candidate
                    or registered_evaluation[4] != 1
                ):
                    raise StrategyAuthorizationError("candidate's registered evaluation is not evidence-verified")
                try:
                    registered_summary = json.loads(registered_evaluation[5])
                except (TypeError, ValueError, json.JSONDecodeError):
                    raise StrategyIntegrityError("candidate evaluation summary is corrupt") from None
                if (
                    type(registered_summary) is not dict
                    or registered_summary.get("baseline_version") != assessment.baseline_version
                    or registered_summary.get("candidate_version") != assessment.candidate_version
                ):
                    raise StrategyAuthorizationError("promotion assessment baseline or candidate version differs from the registered evaluation")
                matching_cohorts = [
                    cohort_id for cohort_id, evaluation in cohort_evaluations.items()
                    if evaluation.cohort_sha256 == registered_evaluation[2]
                ]
                if len(matching_cohorts) != 1:
                    raise StrategyAuthorizationError(
                        "promotion assessment must include the exact cohort already bound to the candidate version"
                    )
                if refs[matching_cohorts[0]] != registered_evaluation[3]:
                    raise StrategyAuthorizationError(
                        "promotion assessment manifest does not match the candidate's registered evidence manifest"
                    )

                existing = connection.execute(
                    """SELECT assessment_id,principal_id,strategy_class,baseline_id,baseline_version,
                    candidate_id,candidate_version,policy_version,task_family,assessment_sha256,
                    summary_json,evidence_manifest_refs_json,cohort_sha256s_json,primary_metric,created_at
                    FROM strategy_promotion_assessments
                    WHERE principal_id=? AND strategy_class=? AND candidate_id=?
                    AND candidate_version=? AND assessment_sha256=?""",
                    (principal, category, candidate, assessment.candidate_version, assessment_hash),
                ).fetchone()
                if existing is None:
                    connection.execute(
                        """INSERT INTO strategy_promotion_assessments
                        (assessment_id,principal_id,strategy_class,baseline_id,baseline_version,
                         candidate_id,candidate_version,policy_version,task_family,primary_metric,
                         assessment_sha256,summary_json,evidence_manifest_refs_json,cohort_sha256s_json,
                         eligible_for_canary,created_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)""",
                        (assessment_id, principal, category, baseline, assessment.baseline_version,
                         candidate, assessment.candidate_version, assessment.policy_version,
                         family, metric, assessment_hash, summary_json, refs_json, hashes_json, created),
                    )
                else:
                    if existing[1:9] != (
                        principal, category, baseline, assessment.baseline_version,
                        candidate, assessment.candidate_version, assessment.policy_version, family,
                    ) or existing[10:14] != (summary_json, refs_json, hashes_json, metric):
                        raise StrategyConflictError("promotion assessment fingerprint already belongs to different evidence")
                    assessment_id = existing[0]
                    created = existing[14]
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()
        return self.get_promotion_assessment_for_principal(
            principal, category, candidate, assessment.candidate_version, assessment_hash,
        )

    def get_promotion_assessment_for_principal(
        self,
        principal_id: str,
        strategy_class: str,
        candidate_id: str,
        candidate_version: str,
        assessment_sha256: str,
    ) -> StrategyPromotionRecord:
        principal = _text(principal_id, "principal_id", 128)
        category = _identifier(strategy_class, "strategy_class")
        candidate = _identifier(candidate_id, "candidate_id")
        version = _version(candidate_version)
        if type(assessment_sha256) is not str or not _SHA256.fullmatch(assessment_sha256):
            raise StrategyStoreError("promotion assessment fingerprint is invalid")
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute(
                    """SELECT assessment_id,principal_id,strategy_class,baseline_id,baseline_version,
                    candidate_id,candidate_version,policy_version,task_family,assessment_sha256,
                    summary_json,evidence_manifest_refs_json,cohort_sha256s_json,primary_metric,created_at
                    FROM strategy_promotion_assessments
                    WHERE principal_id=? AND strategy_class=? AND candidate_id=?
                    AND candidate_version=? AND assessment_sha256=?""",
                    (principal, category, candidate, version, assessment_sha256),
                ).fetchone()
                if row is None:
                    raise StrategyNotFoundError("promotion assessment is not registered for this candidate")
                record = _promotion_record_from_row(row)
                cohort_results = record.summary.get("cohorts")
                cohort_ids = {
                    item.get("cohort_id") for item in cohort_results
                    if type(item) is dict and type(item.get("cohort_id")) is str
                } if type(cohort_results) is list else set()
                if (
                    record.summary.get("eligible_for_canary") is not True
                    or record.summary.get("policy_version") != record.policy_version
                    or record.summary.get("baseline_id") != record.baseline_id
                    or record.summary.get("candidate_id") != record.candidate_id
                    or record.summary.get("baseline_version") != record.baseline_version
                    or record.summary.get("candidate_version") != record.candidate_version
                    or record.summary.get("task_family") != record.task_family
                    or record.summary.get("primary_metric") != record.primary_metric
                    or cohort_ids != {key for key, _ in record.evidence_manifest_refs}
                    or cohort_ids != {key for key, _ in record.cohort_sha256s}
                ):
                    raise StrategyIntegrityError("promotion assessment summary does not match its registry binding")
                return record
            finally:
                connection.close()

    def _verify_chain(
        self, connection: sqlite3.Connection, principal_id: str, strategy_class: str,
    ) -> tuple[Any, ...] | None:
        rows = connection.execute(
            """SELECT event_id,principal_id,strategy_class,generation,action,
            from_strategy_id,from_version,to_strategy_id,to_version,to_config_sha256,
            evaluation_id,approval_id,approver_id,created_at,previous_hash,event_hash,
            promotion_assessment_sha256
            FROM strategy_events WHERE principal_id=? AND strategy_class=?
            ORDER BY generation""",
            (principal_id, strategy_class),
        ).fetchall()
        previous_hash = ""
        expected_generation = 1
        for row in rows:
            payload = {
                "event_id": row[0], "principal_id": row[1], "strategy_class": row[2],
                "generation": row[3], "action": row[4], "from_strategy_id": row[5],
                "from_version": row[6], "to_strategy_id": row[7], "to_version": row[8],
                "to_config_sha256": row[9], "evaluation_id": row[10],
                "approval_id": row[11], "approver_id": row[12],
                "created_at": row[13], "previous_hash": row[14],
            }
            if row[16] is not None:
                payload["promotion_assessment_sha256"] = row[16]
            if row[3] != expected_generation or row[14] != previous_hash:
                raise StrategyIntegrityError("strategy event sequence or previous hash is invalid")
            digest = hashlib.sha256(json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            if digest != row[15]:
                raise StrategyIntegrityError("strategy event hash does not match")
            previous_hash = digest
            expected_generation += 1

        active = connection.execute(
            """SELECT strategy_id,version,generation,event_id FROM strategy_active
            WHERE principal_id=? AND strategy_class=?""",
            (principal_id, strategy_class),
        ).fetchone()
        last = rows[-1] if rows else None
        if last is None:
            if active is not None:
                raise StrategyIntegrityError("active strategy exists without an activation event")
        elif active != (last[7], last[8], last[3], last[0]):
            raise StrategyIntegrityError("active strategy projection does not match the event history")
        return last

    def _transition(
        self, principal_id: str, grant: StrategyActivationGrant, *,
        required_action: str, now: datetime | None = None,
    ) -> ActiveStrategyRecord:
        principal = _text(principal_id, "principal_id", 128)
        _grant_payload(grant)
        if grant.principal_id != principal or grant.action != required_action:
            raise StrategyAuthorizationError("approval grant is not bound to this principal and action")
        current_time = now.astimezone(timezone.utc) if now is not None else self._now()
        if not isinstance(current_time, datetime) or current_time.tzinfo is None or current_time.utcoffset() is None:
            raise StrategyAuthorizationError("current time must be timezone-aware")
        current_time = current_time.astimezone(timezone.utc)
        issued = _timestamp(grant.issued_at, "issued_at")
        expires = _timestamp(grant.expires_at, "expires_at")
        if issued > current_time or expires <= current_time:
            raise StrategyAuthorizationError("approval grant is not currently valid")
        if self._approval_verifier is None:
            raise StrategyAuthorizationError("strategy activation is disabled without a host approval verifier")
        try:
            verified = self._approval_verifier(grant)
        except Exception:
            raise StrategyAuthorizationError("host approval verification failed") from None
        if verified is not True:
            raise StrategyAuthorizationError("host approval verification rejected the grant")

        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                current_time = self._now()
                if issued > current_time or expires <= current_time:
                    raise StrategyAuthorizationError("approval grant expired before the transition")
                last_event = self._verify_chain(connection, principal, grant.strategy_class)
                active = connection.execute(
                    """SELECT strategy_id,version,generation FROM strategy_active
                    WHERE principal_id=? AND strategy_class=?""",
                    (principal, grant.strategy_class),
                ).fetchone()
                generation = active[2] if active is not None else 0
                if generation != grant.expected_generation:
                    raise StrategyConflictError("active strategy generation changed; refresh before retrying")
                if active is not None and active[:2] == (grant.strategy_id, grant.version):
                    raise StrategyConflictError("strategy is already active")

                target = connection.execute(
                    """SELECT v.config_json,v.config_sha256,v.is_baseline,v.evaluation_id,
                    e.cohort_sha256,e.eligible,e.evidence_verified,e.baseline_id,e.candidate_id
                    FROM strategy_versions v LEFT JOIN strategy_evaluations e
                    ON e.evaluation_id=v.evaluation_id
                    WHERE v.principal_id=? AND v.strategy_class=?
                    AND v.strategy_id=? AND v.version=?""",
                    (principal, grant.strategy_class, grant.strategy_id, grant.version),
                ).fetchone()
                if target is None:
                    raise StrategyNotFoundError("target strategy version is not registered for this principal")
                (
                    config_json, config_hash, is_baseline, evaluation_id,
                    cohort_hash, eligible, evidence_verified,
                    evaluation_baseline_id, evaluation_candidate_id,
                ) = target
                expected_hash = None if is_baseline else cohort_hash
                if grant.config_sha256 != config_hash:
                    raise StrategyAuthorizationError("approval grant config fingerprint does not match target version")
                if is_baseline:
                    if grant.evaluation_sha256 is not None:
                        raise StrategyAuthorizationError("baseline activation must not claim a candidate evaluation")
                elif (
                    eligible != 1 or evidence_verified != 1
                    or cohort_hash != grant.evaluation_sha256 or evaluation_id is None
                ):
                    raise StrategyAuthorizationError("candidate is not bound to an eligible, evidence-verified evaluation fingerprint")

                if grant.promotion_assessment_sha256 is not None:
                    if is_baseline:
                        raise StrategyAuthorizationError("baseline activation cannot claim a promotion assessment")
                    assessment_row = connection.execute(
                        """SELECT assessment_id,principal_id,strategy_class,baseline_id,baseline_version,
                        candidate_id,candidate_version,policy_version,task_family,assessment_sha256,
                        summary_json,evidence_manifest_refs_json,cohort_sha256s_json,primary_metric,created_at
                        FROM strategy_promotion_assessments
                        WHERE principal_id=? AND strategy_class=? AND candidate_id=?
                        AND candidate_version=? AND assessment_sha256=?""",
                        (principal, grant.strategy_class, grant.strategy_id, grant.version,
                         grant.promotion_assessment_sha256),
                    ).fetchone()
                    if assessment_row is None:
                        raise StrategyAuthorizationError("promotion assessment is not registered for this candidate version")
                    promotion_record = _promotion_record_from_row(assessment_row)
                    cohort_results = promotion_record.summary.get("cohorts")
                    cohort_ids = {
                        item.get("cohort_id") for item in cohort_results
                        if type(item) is dict and type(item.get("cohort_id")) is str
                    } if type(cohort_results) is list else set()
                    if (
                        promotion_record.policy_version != STRATEGY_PROMOTION_POLICY_VERSION
                        or promotion_record.summary.get("eligible_for_canary") is not True
                        or promotion_record.summary.get("policy_version") != promotion_record.policy_version
                        or promotion_record.baseline_id != evaluation_baseline_id
                        or promotion_record.candidate_id != evaluation_candidate_id
                        or promotion_record.candidate_version != grant.version
                        or cohort_ids != {key for key, _ in promotion_record.evidence_manifest_refs}
                        or cohort_ids != {key for key, _ in promotion_record.cohort_sha256s}
                        or cohort_hash not in {value for _, value in promotion_record.cohort_sha256s}
                    ):
                        raise StrategyAuthorizationError("promotion assessment does not match the candidate evidence or current policy")
                if required_action == "rollback":
                    previous_activation = connection.execute(
                        """SELECT 1 FROM strategy_events WHERE principal_id=? AND strategy_class=?
                        AND to_strategy_id=? AND to_version=? LIMIT 1""",
                        (principal, grant.strategy_class, grant.strategy_id, grant.version),
                    ).fetchone()
                    if previous_activation is None:
                        raise StrategyConflictError("rollback target was never active in this strategy history")
                elif grant.evaluation_sha256 != expected_hash:
                    raise StrategyAuthorizationError("approval grant evaluation fingerprint does not match target")

                if connection.execute(
                    "SELECT 1 FROM strategy_events WHERE approval_id=?", (grant.grant_id,)
                ).fetchone() is not None:
                    raise StrategyConflictError("approval grant has already been consumed")

                write_time = self._now()
                if issued > write_time or expires <= write_time:
                    raise StrategyAuthorizationError("approval grant expired before event publication")
                from_id, from_version = active[:2] if active is not None else (None, None)
                next_generation = generation + 1
                event_id = uuid4().hex
                created = write_time.isoformat()
                previous_hash = last_event[15] if last_event is not None else ""
                payload = {
                    "event_id": event_id, "principal_id": principal,
                    "strategy_class": grant.strategy_class,
                    "generation": next_generation, "action": required_action,
                    "from_strategy_id": from_id, "from_version": from_version,
                    "to_strategy_id": grant.strategy_id, "to_version": grant.version,
                    "to_config_sha256": config_hash,
                    "evaluation_id": evaluation_id, "approval_id": grant.grant_id,
                    "approver_id": grant.approver_id, "created_at": created,
                    "previous_hash": previous_hash,
                }
                event_hash = hashlib.sha256(json.dumps(
                    payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                ).encode("utf-8")).hexdigest()
                connection.execute(
                    """INSERT INTO strategy_events
                    (event_id,principal_id,strategy_class,generation,action,
                     from_strategy_id,from_version,to_strategy_id,to_version,to_config_sha256,
                     evaluation_id,approval_id,approver_id,created_at,previous_hash,event_hash)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (event_id, principal, grant.strategy_class, next_generation,
                     required_action, from_id, from_version, grant.strategy_id,
                     grant.version, config_hash, evaluation_id, grant.grant_id,
                     grant.approver_id, created, previous_hash, event_hash),
                )
                connection.execute(
                    """INSERT INTO strategy_active
                    (principal_id,strategy_class,strategy_id,version,generation,event_id)
                    VALUES (?,?,?,?,?,?)
                    ON CONFLICT(principal_id,strategy_class) DO UPDATE SET
                    strategy_id=excluded.strategy_id,version=excluded.version,
                    generation=excluded.generation,event_id=excluded.event_id""",
                    (principal, grant.strategy_class, grant.strategy_id, grant.version,
                     next_generation, event_id),
                )
                commit_check_time = self._now()
                if issued > commit_check_time or expires <= commit_check_time:
                    raise StrategyAuthorizationError("approval grant expired before commit")
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()
        return ActiveStrategyRecord(
            principal, grant.strategy_class, grant.strategy_id, grant.version,
            next_generation, _decode_config(config_json, config_hash), config_hash,
            created, event_id,
        )

    def activate_for_principal(
        self, principal_id: str, grant: StrategyActivationGrant, *,
        now: datetime | None = None,
    ) -> ActiveStrategyRecord:
        return self._transition(principal_id, grant, required_action="activate", now=now)

    def rollback_for_principal(
        self, principal_id: str, grant: StrategyActivationGrant, *,
        now: datetime | None = None,
    ) -> ActiveStrategyRecord:
        return self._transition(principal_id, grant, required_action="rollback", now=now)

    def get_active_for_principal(
        self, principal_id: str, strategy_class: str,
    ) -> ActiveStrategyRecord | None:
        principal = _text(principal_id, "principal_id", 128)
        category = _identifier(strategy_class, "strategy_class")
        with self._lock:
            connection = self._connect()
            try:
                self._verify_chain(connection, principal, category)
                row = connection.execute(
                    """SELECT a.strategy_id,a.version,a.generation,a.event_id,
                    e.created_at,v.config_json,v.config_sha256,v.is_baseline,ev.evidence_verified
                    FROM strategy_active a
                    JOIN strategy_events e ON e.event_id=a.event_id
                    JOIN strategy_versions v ON v.principal_id=a.principal_id
                      AND v.strategy_class=a.strategy_class
                      AND v.strategy_id=a.strategy_id AND v.version=a.version
                    LEFT JOIN strategy_evaluations ev ON ev.evaluation_id=v.evaluation_id
                    WHERE a.principal_id=? AND a.strategy_class=?""",
                    (principal, category),
                ).fetchone()
                if row is None:
                    return None
                if row[7] != 1 and row[8] != 1:
                    raise StrategyAuthorizationError(
                        "active candidate evidence is unverified; restore a verified baseline before serving it"
                    )
                return ActiveStrategyRecord(
                    principal, category, row[0], row[1], row[2],
                    _decode_config(row[5], row[6]), row[6], row[4], row[3],
                )
            finally:
                connection.close()

    def events_for_principal(
        self, principal_id: str, strategy_class: str,
    ) -> tuple[StrategyActivationEvent, ...]:
        principal = _text(principal_id, "principal_id", 128)
        category = _identifier(strategy_class, "strategy_class")
        with self._lock:
            connection = self._connect()
            try:
                self._verify_chain(connection, principal, category)
                rows = connection.execute(
                    """SELECT event_id,principal_id,strategy_class,generation,action,
                    from_strategy_id,from_version,to_strategy_id,to_version,to_config_sha256,
                    evaluation_id,approval_id,approver_id,created_at,previous_hash,event_hash
                    FROM strategy_events WHERE principal_id=? AND strategy_class=?
                    ORDER BY generation""",
                    (principal, category),
                ).fetchall()
                evaluation_hashes: dict[str, str] = {}
                for row in rows:
                    if row[10] is not None and row[10] not in evaluation_hashes:
                        evaluation_hashes[row[10]] = connection.execute(
                            "SELECT cohort_sha256 FROM strategy_evaluations WHERE evaluation_id=?",
                            (row[10],),
                        ).fetchone()[0]
                return tuple(
                    StrategyActivationEvent(
                        row[0], row[1], row[2], row[3], row[4], row[5], row[6],
                        row[7], row[8], row[9],
                        evaluation_hashes.get(row[10]) if row[10] else None,
                        row[11], row[12], row[13], row[14], row[15],
                    )
                    for row in rows
                )
            finally:
                connection.close()
