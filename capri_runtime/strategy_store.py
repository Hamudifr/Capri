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
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable
from uuid import uuid4

from capri_core.validation import contains_surrogate
from capri_core.strategy import StrategyEvaluation, StrategyObservation, evaluate_strategies
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
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if type(task_store) is not SQLiteTaskStore:
            raise StrategyStoreError("SQLiteStrategyStore requires the exact trusted SQLiteTaskStore")
        if approval_verifier is not None and not callable(approval_verifier):
            raise StrategyStoreError("approval_verifier must be callable")
        if clock is not None and not callable(clock):
            raise StrategyStoreError("clock must be callable")
        self._task_store = task_store
        self._approval_verifier = approval_verifier
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
                    summary_json TEXT NOT NULL,
                    evidence_manifest_ref TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(principal_id, strategy_class, cohort_sha256)
                )""")
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
                for table in ("strategy_evaluations", "strategy_versions", "strategy_events"):
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
                    """SELECT evaluation_id,baseline_id,candidate_id,summary_json,evidence_manifest_ref
                    FROM strategy_evaluations WHERE principal_id=? AND strategy_class=? AND cohort_sha256=?""",
                    (principal, category, evaluation.cohort_sha256),
                ).fetchone()
                if existing_evaluation is not None:
                    evaluation_id = existing_evaluation[0]
                    if existing_evaluation[1:] != (
                        evaluation.baseline_id, evaluation.candidate_id,
                        summary_json, evidence_ref,
                    ):
                        raise StrategyConflictError("cohort fingerprint already belongs to different evaluation data")
                else:
                    connection.execute(
                        """INSERT INTO strategy_evaluations
                        (evaluation_id,principal_id,strategy_class,baseline_id,candidate_id,
                         cohort_sha256,matched_pairs,eligible,summary_json,evidence_manifest_ref,created_at)
                        VALUES (?,?,?,?,?,?,?,1,?,?,?)""",
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

    def _verify_chain(
        self, connection: sqlite3.Connection, principal_id: str, strategy_class: str,
    ) -> tuple[Any, ...] | None:
        rows = connection.execute(
            """SELECT event_id,principal_id,strategy_class,generation,action,
            from_strategy_id,from_version,to_strategy_id,to_version,to_config_sha256,
            evaluation_id,approval_id,approver_id,created_at,previous_hash,event_hash
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
                    e.cohort_sha256,e.eligible
                    FROM strategy_versions v LEFT JOIN strategy_evaluations e
                    ON e.evaluation_id=v.evaluation_id
                    WHERE v.principal_id=? AND v.strategy_class=?
                    AND v.strategy_id=? AND v.version=?""",
                    (principal, grant.strategy_class, grant.strategy_id, grant.version),
                ).fetchone()
                if target is None:
                    raise StrategyNotFoundError("target strategy version is not registered for this principal")
                config_json, config_hash, is_baseline, evaluation_id, cohort_hash, eligible = target
                expected_hash = None if is_baseline else cohort_hash
                if grant.config_sha256 != config_hash:
                    raise StrategyAuthorizationError("approval grant config fingerprint does not match target version")
                if is_baseline:
                    if grant.evaluation_sha256 is not None:
                        raise StrategyAuthorizationError("baseline activation must not claim a candidate evaluation")
                elif (
                    eligible != 1 or cohort_hash != grant.evaluation_sha256
                    or evaluation_id is None
                ):
                    raise StrategyAuthorizationError("candidate is not bound to an eligible evaluation fingerprint")

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

                from_id, from_version = active[:2] if active is not None else (None, None)
                next_generation = generation + 1
                event_id = uuid4().hex
                created = current_time.isoformat()
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
                    e.created_at,v.config_json,v.config_sha256
                    FROM strategy_active a
                    JOIN strategy_events e ON e.event_id=a.event_id
                    JOIN strategy_versions v ON v.principal_id=a.principal_id
                      AND v.strategy_class=a.strategy_class
                      AND v.strategy_id=a.strategy_id AND v.version=a.version
                    WHERE a.principal_id=? AND a.strategy_class=?""",
                    (principal, category),
                ).fetchone()
                if row is None:
                    return None
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
