"""Host-owned, authenticated source events for strategy evidence.

The journal records only digests and bounded execution metadata. It never stores
prompts, model output, credentials, or raw tool results. Hosts must inject
authentication, classification, strategy-resolution, and result-verification
callbacks; none may trust model-authored claims.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from uuid import uuid4

from capri_core.strategy import StrategyObservation
from .strategy_store import StrategyStoreError, StrategyAuthorizationError
from .tasks import SQLiteTaskStore, TaskClaim

_ALLOWED_FAMILIES = frozenset({
    "coding", "formatting", "general_qa", "research",
    "retrieval", "summarization", "writing",
})
_ALLOWED_OUTCOMES = frozenset({"verified_success", "verified_failure", "unverified"})
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}$")
_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_EVENT_REF = re.compile(r"^host-execution-event:([0-9a-f]{32})$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_RESULT_BYTES = 65_536


@dataclass(frozen=True, slots=True)
class TaskClassification:
    """Trusted host-derived family and matched-cohort scenario."""

    task_family: str
    scenario: str


@dataclass(frozen=True, slots=True)
class StrategyBinding:
    """Strategy identity resolved by the host for this exact task claim."""

    strategy_class: str
    strategy_id: str
    strategy_version: str


@dataclass(frozen=True, slots=True)
class VerifiedExecutionResult:
    """Metrics returned only by the injected host result verifier."""

    result_sha256: str
    outcome: str
    safety_violation: bool
    tool_calls: int
    context_tokens: int
    estimated_cost_units: int
    latency_ms: int


def _canonical(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    )


def _text(value: object, label: str, limit: int = 128) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > limit:
        raise StrategyAuthorizationError(f"{label} is invalid")
    if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise StrategyAuthorizationError(f"{label} is invalid")
    return value


def _claim_digest(claim: TaskClaim) -> str:
    if type(claim) is not TaskClaim or type(claim.input) is not dict:
        raise StrategyAuthorizationError("a validated host task claim is required")
    try:
        input_json = _canonical(claim.input)
        payload = {
            "task_id": claim.task_id,
            "principal_id": claim.principal_id,
            "executor_id": claim.executor_id,
            "step_index": claim.step_index,
            "attempt": claim.attempt,
            "idempotency_key": claim.idempotency_key,
            "tool": claim.tool,
            "input_sha256": hashlib.sha256(input_json.encode("utf-8")).hexdigest(),
        }
        return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
    except Exception:
        raise StrategyAuthorizationError("task claim cannot be fingerprinted") from None


class SQLiteExecutionEvidenceJournal:
    """Append-only HMAC-authenticated journal of host-verified task executions.

    Call record_execution after the handler returns but before finish_step consumes
    the lease. The task claim is revalidated against SQLite at write time. The
    host result verifier must independently derive the outcome and metrics from
    the actual execution/result; caller-supplied metrics are never accepted.
    """

    def __init__(
        self,
        task_store: SQLiteTaskStore,
        mac_provider: Any,
        authenticate_collector: Callable[[Any], str | None],
        classify_task: Callable[[str, str], TaskClassification],
        resolve_strategy: Callable[[str, TaskClaim], StrategyBinding],
        verify_result: Callable[[str, TaskClaim, object, str], VerifiedExecutionResult],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if type(task_store) is not SQLiteTaskStore:
            raise StrategyStoreError("an exact SQLiteTaskStore is required")
        if not (
            callable(getattr(mac_provider, "sign", None))
            and callable(getattr(mac_provider, "verify", None))
            and type(getattr(mac_provider, "active_key_id", None)) is str
        ):
            raise StrategyStoreError("a trusted execution-evidence MAC provider is required")
        if not all(callable(item) for item in (
            authenticate_collector, classify_task, resolve_strategy, verify_result,
        )):
            raise StrategyStoreError("all host execution-evidence callbacks are required")
        if clock is not None and not callable(clock):
            raise StrategyStoreError("clock must be callable")
        self._tasks = task_store
        self._mac = mac_provider
        self._authenticate = authenticate_collector
        self._classify = classify_task
        self._resolve_strategy = resolve_strategy
        self._verify_result = verify_result
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._initialize()

    def _initialize(self) -> None:
        with self._tasks._lock:
            connection = self._tasks._connect()
            try:
                connection.execute("""CREATE TABLE IF NOT EXISTS execution_evidence_events (
                    event_id TEXT PRIMARY KEY,
                    principal_id TEXT NOT NULL,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id),
                    step_index INTEGER NOT NULL,
                    attempt INTEGER NOT NULL,
                    claim_sha256 TEXT NOT NULL,
                    strategy_class TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    strategy_version TEXT NOT NULL,
                    task_family TEXT NOT NULL,
                    scenario TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    safety_violation INTEGER NOT NULL,
                    tool_calls INTEGER NOT NULL,
                    context_tokens INTEGER NOT NULL,
                    estimated_cost_units INTEGER NOT NULL,
                    latency_ms INTEGER NOT NULL,
                    result_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    key_id TEXT NOT NULL,
                    event_sha256 TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE(task_id,step_index,attempt,strategy_id)
                )""")
                connection.execute("""CREATE TRIGGER IF NOT EXISTS execution_evidence_immutable_update
                    BEFORE UPDATE ON execution_evidence_events
                    BEGIN SELECT RAISE(ABORT, 'execution evidence events are append-only'); END""")
                connection.execute("""CREATE TRIGGER IF NOT EXISTS execution_evidence_immutable_delete
                    BEFORE DELETE ON execution_evidence_events
                    BEGIN SELECT RAISE(ABORT, 'execution evidence events are append-only'); END""")
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS execution_evidence_owner_idx "
                    "ON execution_evidence_events(principal_id,strategy_class,task_id)"
                )
            finally:
                connection.close()

    def _now(self) -> str:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise StrategyAuthorizationError("trusted evidence clock must return an aware datetime")
        return value.astimezone(timezone.utc).isoformat()

    def _authenticate_claim(self, credential: Any, claim: TaskClaim) -> str:
        try:
            principal = self._authenticate(credential)
        except Exception:
            raise StrategyAuthorizationError("execution collector authentication failed") from None
        principal = _text(principal, "authenticated principal")
        if type(claim) is not TaskClaim or claim.principal_id != principal:
            raise StrategyAuthorizationError("authenticated principal does not own this task claim")
        try:
            self._tasks.validate_claim(claim)
            self._tasks.get_for_principal(claim.task_id, principal)
        except Exception:
            raise StrategyAuthorizationError("task claim is not valid for the authenticated principal") from None
        return principal

    @staticmethod
    def _validate_classification(value: object) -> TaskClassification:
        if type(value) is not TaskClassification:
            raise StrategyAuthorizationError("trusted task classifier returned an invalid record")
        family = _text(value.task_family, "task_family", 64)
        scenario = _text(value.scenario, "scenario", 128)
        if family not in _ALLOWED_FAMILIES:
            raise StrategyAuthorizationError("trusted task classifier returned an unsupported family")
        return value

    @staticmethod
    def _validate_binding(value: object) -> StrategyBinding:
        if type(value) is not StrategyBinding:
            raise StrategyAuthorizationError("trusted strategy resolver returned an invalid record")
        for field in ("strategy_class", "strategy_id"):
            if not _IDENTIFIER.fullmatch(_text(getattr(value, field), field, 64)):
                raise StrategyAuthorizationError(f"{field} is invalid")
        version = _text(value.strategy_version, "strategy_version", 64)
        if not _VERSION.fullmatch(version) or version == "unversioned":
            raise StrategyAuthorizationError("strategy_version is invalid")
        return value

    @staticmethod
    def _validate_result(value: object, expected_digest: str) -> VerifiedExecutionResult:
        if type(value) is not VerifiedExecutionResult:
            raise StrategyAuthorizationError("host result verifier did not return a verified result")
        if type(value.result_sha256) is not str or value.result_sha256 != expected_digest:
            raise StrategyAuthorizationError("host result verifier returned a mismatched result digest")
        if type(value.outcome) is not str or value.outcome not in _ALLOWED_OUTCOMES:
            raise StrategyAuthorizationError("verified outcome is invalid")
        if type(value.safety_violation) is not bool:
            raise StrategyAuthorizationError("verified safety flag is invalid")
        for field in ("tool_calls", "context_tokens", "estimated_cost_units", "latency_ms"):
            number = getattr(value, field)
            if type(number) is not int or not 0 <= number <= 10**12:
                raise StrategyAuthorizationError(f"verified {field} is invalid")
        return value

    def record_execution(self, credential: Any, claim: TaskClaim, result: object) -> str:
        """Persist a signed event only after host authentication and result verification."""
        principal = self._authenticate_claim(credential, claim)
        classification = self._validate_classification(self._classify(principal, claim.task_id))
        binding = self._validate_binding(self._resolve_strategy(principal, claim))
        try:
            encoded_result = _canonical(result).encode("utf-8")
        except Exception:
            raise StrategyAuthorizationError("execution result is not canonical JSON") from None
        if len(encoded_result) > _MAX_RESULT_BYTES:
            raise StrategyAuthorizationError("execution result exceeds the evidence hashing limit")
        result_digest = hashlib.sha256(encoded_result).hexdigest()
        try:
            verified = self._verify_result(principal, claim, result, result_digest)
        except Exception:
            raise StrategyAuthorizationError("host execution result verification failed") from None
        verified = self._validate_result(verified, result_digest)
        claim_digest = _claim_digest(claim)
        event_id = uuid4().hex
        created_at = self._now()
        key_id = self._mac.active_key_id
        if type(key_id) is not str or not _KEY_ID.fullmatch(key_id):
            raise StrategyAuthorizationError("execution evidence MAC key identifier is invalid")
        payload = {
            "event_schema": "capri.execution-evidence.v1",
            "event_id": event_id,
            "principal_id": principal,
            "task_id": claim.task_id,
            "step_index": claim.step_index,
            "attempt": claim.attempt,
            "claim_sha256": claim_digest,
            "strategy_class": binding.strategy_class,
            "strategy_id": binding.strategy_id,
            "strategy_version": binding.strategy_version,
            "task_family": classification.task_family,
            "scenario": classification.scenario,
            "outcome": verified.outcome,
            "safety_violation": verified.safety_violation,
            "tool_calls": verified.tool_calls,
            "context_tokens": verified.context_tokens,
            "estimated_cost_units": verified.estimated_cost_units,
            "latency_ms": verified.latency_ms,
            "result_sha256": result_digest,
            "created_at": created_at,
            "key_id": key_id,
        }
        payload_json = _canonical(payload)
        payload_bytes = payload_json.encode("utf-8")
        event_sha = hashlib.sha256(payload_bytes).hexdigest()
        try:
            signature = self._mac.sign(key_id, bytes.fromhex(event_sha))
        except Exception:
            raise StrategyAuthorizationError("execution evidence signing failed") from None
        if type(signature) is not bytes or len(signature) != 32:
            raise StrategyAuthorizationError("execution evidence signer returned an invalid signature")
        with self._tasks._lock:
            connection = self._tasks._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                # Revalidate the lease inside the same SQLite write transaction
                # as the append. The earlier callback-time validation is not
                # sufficient: another process may reclaim or finish the task
                # while classification/result verification is running.
                live_claim = connection.execute(
                    """SELECT tasks.state,tasks.lease_owner,tasks.lease_until,
                    tasks.current_step,tasks.attempts,tasks.plan_json,
                    task_owners.principal_id
                    FROM tasks LEFT JOIN task_owners
                    ON task_owners.task_id=tasks.task_id
                    WHERE tasks.task_id=?""",
                    (claim.task_id,),
                ).fetchone()
                if live_claim is None:
                    raise StrategyAuthorizationError("task claim is no longer valid")
                self._tasks._assert_claim_matches(claim, live_claim, created_at)
                existing = connection.execute(
                    """SELECT event_id,claim_sha256,result_sha256,principal_id,
                    strategy_class,strategy_version,task_family,scenario,outcome,
                    safety_violation,tool_calls,context_tokens,estimated_cost_units,latency_ms
                    FROM execution_evidence_events
                    WHERE task_id=? AND step_index=? AND attempt=? AND strategy_id=?""",
                    (claim.task_id, claim.step_index, claim.attempt, binding.strategy_id),
                ).fetchone()
                if existing:
                    expected_existing = (
                        claim_digest, result_digest, principal,
                        binding.strategy_class, binding.strategy_version,
                        classification.task_family, classification.scenario,
                        verified.outcome, int(verified.safety_violation),
                        verified.tool_calls, verified.context_tokens,
                        verified.estimated_cost_units, verified.latency_ms,
                    )
                    if existing[1:] != expected_existing:
                        raise StrategyAuthorizationError("conflicting execution evidence already exists")
                    connection.execute("COMMIT")
                    return f"host-execution-event:{existing[0]}"
                connection.execute(
                    """INSERT INTO execution_evidence_events(
                    event_id,principal_id,task_id,step_index,attempt,claim_sha256,
                    strategy_class,strategy_id,strategy_version,task_family,scenario,
                    outcome,safety_violation,tool_calls,context_tokens,estimated_cost_units,
                    latency_ms,result_sha256,created_at,key_id,event_sha256,signature,payload_json
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        event_id, principal, claim.task_id, claim.step_index, claim.attempt,
                        claim_digest, binding.strategy_class, binding.strategy_id,
                        binding.strategy_version, classification.task_family,
                        classification.scenario, verified.outcome, int(verified.safety_violation),
                        verified.tool_calls, verified.context_tokens,
                        verified.estimated_cost_units, verified.latency_ms, result_digest,
                        created_at, key_id, event_sha, signature.hex(), payload_json,
                    ),
                )
                connection.execute("COMMIT")
            except Exception:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                connection.close()
        return f"host-execution-event:{event_id}"

    def classify_task_family(self, principal_id: str, task_id: str) -> str | None:
        """Adapter for SQLiteStrategyEvidenceManifestStore's trusted classifier hook."""
        try:
            value = self._validate_classification(self._classify(principal_id, task_id))
            self._tasks.get_for_principal(task_id, principal_id)
            return value.task_family
        except Exception:
            return None

    def _read_verified_event(self, event_id: str) -> dict[str, Any] | None:
        with self._tasks._lock:
            connection = self._tasks._connect()
            try:
                row = connection.execute(
                    """SELECT payload_json,event_sha256,key_id,signature,principal_id,task_id,
                    step_index,attempt,claim_sha256,strategy_class,strategy_id,strategy_version,
                    task_family,scenario,outcome,safety_violation,tool_calls,context_tokens,
                    estimated_cost_units,latency_ms,result_sha256,created_at
                    FROM execution_evidence_events WHERE event_id=?""",
                    (event_id,),
                ).fetchone()
            finally:
                connection.close()
        if row is None:
            return None
        (
            payload_json, event_sha, key_id, signature_hex, principal_id, task_id,
            step_index, attempt, claim_sha, strategy_class, strategy_id, strategy_version,
            task_family, scenario, outcome, safety_violation, tool_calls, context_tokens,
            estimated_cost_units, latency_ms, result_sha, created_at,
        ) = row
        try:
            encoded = payload_json.encode("utf-8", errors="strict")
            if len(encoded) > 16_384 or hashlib.sha256(encoded).hexdigest() != event_sha:
                return None
            payload = json.loads(payload_json)
            if type(payload) is not dict or _canonical(payload) != payload_json:
                return None
            if payload.get("event_id") != event_id or payload.get("key_id") != key_id:
                return None
            expected_row = (
                payload.get("principal_id"), payload.get("task_id"),
                payload.get("step_index"), payload.get("attempt"),
                payload.get("claim_sha256"), payload.get("strategy_class"),
                payload.get("strategy_id"), payload.get("strategy_version"),
                payload.get("task_family"), payload.get("scenario"),
                payload.get("outcome"), int(payload.get("safety_violation") is True),
                payload.get("tool_calls"), payload.get("context_tokens"),
                payload.get("estimated_cost_units"), payload.get("latency_ms"),
                payload.get("result_sha256"), payload.get("created_at"),
            )
            actual_row = (
                principal_id, task_id, step_index, attempt, claim_sha,
                strategy_class, strategy_id, strategy_version, task_family,
                scenario, outcome, safety_violation, tool_calls, context_tokens,
                estimated_cost_units, latency_ms, result_sha, created_at,
            )
            if expected_row != actual_row:
                return None
            if type(signature_hex) is not str or not re.fullmatch(r"[0-9a-f]{64}", signature_hex):
                return None
            verified = self._mac.verify(key_id, bytes.fromhex(event_sha), bytes.fromhex(signature_hex))
            if verified is not True:
                return None
            return payload
        except Exception:
            return None

    def validate_source_events(
        self,
        principal_id: str,
        strategy_class: str,
        observations: tuple[StrategyObservation, ...],
        families: Mapping[str, str],
    ) -> bool:
        """Callback for the manifest store; every observation must match a signed event."""
        try:
            if type(principal_id) is not str or type(strategy_class) is not str:
                return False
            for observation in observations:
                match = _EVENT_REF.fullmatch(observation.evidence_ref)
                if match is None:
                    return False
                payload = self._read_verified_event(match.group(1))
                if payload is None:
                    return False
                if (
                    payload.get("principal_id") != principal_id
                    or payload.get("strategy_class") != strategy_class
                    or payload.get("task_id") != observation.task_id
                    or payload.get("scenario") != observation.scenario
                    or payload.get("strategy_id") != observation.strategy_id
                    or payload.get("strategy_version") != observation.strategy_version
                    or payload.get("outcome") != observation.outcome
                    or payload.get("safety_violation") is not observation.safety_violation
                    or payload.get("tool_calls") != observation.tool_calls
                    or payload.get("context_tokens") != observation.context_tokens
                    or payload.get("estimated_cost_units") != observation.estimated_cost_units
                    or payload.get("latency_ms") != observation.latency_ms
                    or families.get(observation.task_id) != payload.get("task_family")
                ):
                    return False
            return True
        except Exception:
            return False

    def integrity_check(self) -> str:
        """Validate append-only schema, canonical payloads and all stored MACs."""
        try:
            with self._tasks._lock:
                connection = self._tasks._connect()
                try:
                    validate_execution_evidence_snapshot(connection)
                    rows = connection.execute(
                        "SELECT event_id FROM execution_evidence_events ORDER BY created_at,event_id"
                    ).fetchall()
                    triggers = {
                        row[0]: (row[1] or "").upper()
                        for row in connection.execute(
                            "SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='execution_evidence_events'"
                        ).fetchall()
                    }
                finally:
                    connection.close()
            if (
                "BEFORE UPDATE ON EXECUTION_EVIDENCE_EVENTS" not in triggers.get("execution_evidence_immutable_update", "")
                or "RAISE(ABORT" not in triggers.get("execution_evidence_immutable_update", "")
                or "BEFORE DELETE ON EXECUTION_EVIDENCE_EVENTS" not in triggers.get("execution_evidence_immutable_delete", "")
                or "RAISE(ABORT" not in triggers.get("execution_evidence_immutable_delete", "")
            ):
                return "append-only protections missing"
            for (event_id,) in rows:
                if self._read_verified_event(event_id) is None:
                    return "execution evidence integrity failed"
            return "ok"
        except Exception:
            return "execution evidence integrity failed"


def validate_execution_evidence_snapshot(connection: Any) -> None:
    """Validate journal structure and signed-payload bindings in a task-store backup.

    The host journal's integrity_check additionally verifies each HMAC with the
    live key provider. Backup validation deliberately does not require key
    material to be copied into the database or backup artifact.
    """
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='execution_evidence_events'"
    ).fetchone()
    if table is None:
        return
    columns_info = connection.execute("PRAGMA table_info(execution_evidence_events)").fetchall()
    columns = {row[1] for row in columns_info}
    required = {
        "event_id", "principal_id", "task_id", "step_index", "attempt",
        "claim_sha256", "strategy_class", "strategy_id", "strategy_version",
        "task_family", "scenario", "outcome", "safety_violation", "tool_calls",
        "context_tokens", "estimated_cost_units", "latency_ms", "result_sha256",
        "created_at", "key_id", "event_sha256", "signature", "payload_json",
    }
    if not required.issubset(columns):
        raise StrategyStoreError("execution evidence journal schema is incomplete")
    if [row[1] for row in columns_info if row[5]] != ["event_id"]:
        raise StrategyStoreError("execution evidence journal primary key is invalid")
    triggers = {
        row[0]: (row[1] or "").upper()
        for row in connection.execute(
            "SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='execution_evidence_events'"
        ).fetchall()
    }
    for name, operation in (
        ("execution_evidence_immutable_update", "UPDATE"),
        ("execution_evidence_immutable_delete", "DELETE"),
    ):
        sql = triggers.get(name, "")
        if f"BEFORE {operation} ON EXECUTION_EVIDENCE_EVENTS" not in sql or "RAISE(ABORT" not in sql:
            raise StrategyStoreError("execution evidence append-only protections are missing")
    unique_constraint = False
    for index in connection.execute("PRAGMA index_list(execution_evidence_events)").fetchall():
        if index[2] != 1 or index[4] != 0:
            continue
        name = str(index[1]).replace('"', '""')
        indexed = [
            row[2] for row in connection.execute(f'PRAGMA index_info("{name}")').fetchall()
        ]
        if indexed == ["task_id", "step_index", "attempt", "strategy_id"]:
            unique_constraint = True
            break
    if not unique_constraint:
        raise StrategyStoreError("execution evidence idempotency constraint is missing")

    rows = connection.execute(
        """SELECT event_id,principal_id,task_id,step_index,attempt,claim_sha256,
        strategy_class,strategy_id,strategy_version,task_family,scenario,outcome,
        safety_violation,tool_calls,context_tokens,estimated_cost_units,latency_ms,
        result_sha256,created_at,key_id,event_sha256,signature,payload_json
        FROM execution_evidence_events"""
    ).fetchall()
    expected_keys = {
        "event_schema", "event_id", "principal_id", "task_id", "step_index",
        "attempt", "claim_sha256", "strategy_class", "strategy_id",
        "strategy_version", "task_family", "scenario", "outcome",
        "safety_violation", "tool_calls", "context_tokens",
        "estimated_cost_units", "latency_ms", "result_sha256", "created_at", "key_id",
    }
    for row in rows:
        (
            event_id, principal, task_id, step_index, attempt, claim_sha,
            strategy_class, strategy_id, strategy_version, task_family, scenario,
            outcome, safety, tool_calls, context_tokens, cost_units, latency,
            result_sha, created_at, key_id, event_sha, signature, payload_json,
        ) = row
        try:
            encoded = payload_json.encode("utf-8", errors="strict")
            if len(encoded) > 16_384 or hashlib.sha256(encoded).hexdigest() != event_sha:
                raise StrategyStoreError("execution evidence payload digest is invalid")
            payload = json.loads(payload_json)
            if type(payload) is not dict or set(payload) != expected_keys or _canonical(payload) != payload_json:
                raise StrategyStoreError("execution evidence payload is not canonical")
            if (
                payload["event_schema"] != "capri.execution-evidence.v1"
                or payload["event_id"] != event_id
                or payload["principal_id"] != principal
                or payload["task_id"] != task_id
                or payload["step_index"] != step_index
                or payload["attempt"] != attempt
                or payload["claim_sha256"] != claim_sha
                or payload["strategy_class"] != strategy_class
                or payload["strategy_id"] != strategy_id
                or payload["strategy_version"] != strategy_version
                or payload["task_family"] != task_family
                or payload["scenario"] != scenario
                or payload["outcome"] != outcome
                or payload["safety_violation"] is not (safety == 1)
                or payload["tool_calls"] != tool_calls
                or payload["context_tokens"] != context_tokens
                or payload["estimated_cost_units"] != cost_units
                or payload["latency_ms"] != latency
                or payload["result_sha256"] != result_sha
                or payload["created_at"] != created_at
                or payload["key_id"] != key_id
            ):
                raise StrategyStoreError("execution evidence payload does not match its immutable row")
            _text(event_id, "event_id", 32)
            _text(principal, "principal_id", 128)
            _text(task_id, "task_id", 64)
            if not re.fullmatch(r"[0-9a-f]{32}", event_id):
                raise StrategyStoreError("execution evidence event identifier is invalid")
            if type(step_index) is not int or step_index < 0 or type(attempt) is not int or attempt < 1:
                raise StrategyStoreError("execution evidence task progress is invalid")
            for digest in (claim_sha, result_sha, event_sha):
                if type(digest) is not str or not _SHA256.fullmatch(digest):
                    raise StrategyStoreError("execution evidence digest is invalid")
            if (
                not _IDENTIFIER.fullmatch(strategy_class)
                or not _IDENTIFIER.fullmatch(strategy_id)
                or not _VERSION.fullmatch(strategy_version)
                or strategy_version == "unversioned"
                or task_family not in _ALLOWED_FAMILIES
                or outcome not in _ALLOWED_OUTCOMES
                or type(safety) is not int or safety not in (0, 1)
                or type(tool_calls) is not int or not 0 <= tool_calls <= 10**12
                or type(context_tokens) is not int or not 0 <= context_tokens <= 10**12
                or type(cost_units) is not int or not 0 <= cost_units <= 10**12
                or type(latency) is not int or not 0 <= latency <= 10**12
                or type(signature) is not str or not re.fullmatch(r"[0-9a-f]{64}", signature)
                or type(key_id) is not str or not _KEY_ID.fullmatch(key_id)
            ):
                raise StrategyStoreError("execution evidence row metadata is invalid")
            _text(scenario, "scenario", 128)
            _text(strategy_version, "strategy_version", 64)
            _text(created_at, "created_at", 64)
            parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise StrategyStoreError("execution evidence timestamp must include a timezone")
        except StrategyStoreError:
            raise
        except Exception:
            raise StrategyStoreError("execution evidence backup contains malformed records") from None
