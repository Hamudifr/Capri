"""Durable SQLite-backed Nexus worker registry and reservation lifecycle."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from typing import Any, Callable, Iterator

from .worker_registry import (
    InMemoryWorkerRegistry,
    WorkerConflictError,
    WorkerDescriptor,
    WorkerHealth,
    WorkerNotFoundError,
    WorkerRegistryError,
    WorkerReservation,
    WorkerSnapshot,
    _identifier,
)


_SCHEMA_VERSION = 1
_ZERO_HASH = "0" * 64
_TABLES = {
    "worker_registry_meta",
    "worker_registry_state",
    "worker_registry_reservations",
    "worker_registry_events",
}
_EVENT_TYPES = {
    "worker_registered",
    "worker_descriptor_updated",
    "worker_heartbeat_state_changed",
    "worker_failure_recorded",
    "worker_quarantined",
    "worker_retired",
    "worker_quarantine_cleared",
    "worker_health_updated",
    "reservation_created",
    "reservation_committed",
    "reservation_released",
    "reservation_expired",
    "reservation_revoked",
}


def _execute_sql_script(connection: sqlite3.Connection, script: str) -> None:
    """Execute a schema script without sqlite3.executescript's implicit COMMIT."""
    statement = ""
    for line in script.splitlines():
        statement += line + "\n"
        if sqlite3.complete_statement(statement):
            if statement.strip():
                connection.execute(statement)
            statement = ""
    if statement.strip():
        raise WorkerRegistryError("worker registry schema script contains an incomplete statement")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    )


def _descriptor_payload(descriptor: WorkerDescriptor) -> dict[str, Any]:
    return {
        "worker_id": descriptor.worker_id,
        "protocol_versions": list(descriptor.protocol_versions),
        "capabilities": list(descriptor.capabilities),
        "max_concurrency": descriptor.max_concurrency,
        "priority": descriptor.priority,
        "enabled": descriptor.enabled,
        "revision": descriptor.revision,
    }


def _parse_descriptor(payload: str) -> WorkerDescriptor:
    data = json.loads(payload)
    if type(data) is not dict:
        raise WorkerRegistryError("worker descriptor payload is invalid")
    data["protocol_versions"] = tuple(data["protocol_versions"])
    data["capabilities"] = tuple(data["capabilities"])
    descriptor = WorkerDescriptor(**data)
    if _canonical_json(_descriptor_payload(descriptor)) != payload:
        raise WorkerRegistryError("worker descriptor payload is not canonical")
    return descriptor


def _event_payload(
    *,
    sequence: int,
    event_id: str,
    event_type: str,
    worker_id: str,
    actor_id: str,
    principal_id: str | None,
    task_id: str | None,
    token_sha256: str | None,
    timestamp_wall_ns: int,
    payload: dict[str, Any],
    previous_event_sha256: str,
) -> dict[str, Any]:
    return {
        "sequence": sequence,
        "event_id": event_id,
        "event_type": event_type,
        "worker_id": worker_id,
        "actor_id": actor_id,
        "principal_id": principal_id,
        "task_id": task_id,
        "token_sha256": token_sha256,
        "timestamp_wall_ns": timestamp_wall_ns,
        "payload": payload,
        "previous_event_sha256": previous_event_sha256,
    }


def validate_worker_registry_snapshot(connection: sqlite3.Connection) -> None:
    """Validate registry schema, projections, reservation invariants and audit chain."""
    connection.row_factory = sqlite3.Row
    present = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'worker_registry_%'"
        )
    }
    if not present:
        return
    if present != _TABLES:
        raise WorkerRegistryError("worker registry schema is incomplete")

    expected_columns = {
        "worker_registry_meta": (
            "singleton", "schema_version", "config_json", "last_sequence", "head_sha256",
        ),
        "worker_registry_state": (
            "worker_id", "descriptor_json", "health_state", "last_heartbeat_wall_ns",
            "consecutive_failures", "in_flight", "health_revision",
            "created_at_wall_ns", "updated_at_wall_ns",
        ),
        "worker_registry_reservations": (
            "token", "worker_id", "principal_id", "task_id", "capability",
            "protocol_version", "descriptor_revision", "expires_at_wall_ns",
            "committed", "revision", "created_at_wall_ns",
        ),
        "worker_registry_events": (
            "sequence", "event_id", "event_type", "worker_id", "actor_id",
            "principal_id", "task_id", "token_sha256", "timestamp_wall_ns",
            "payload_json", "previous_event_sha256", "event_sha256",
        ),
    }
    for table, columns in expected_columns.items():
        actual = tuple(
            row["name"] for row in connection.execute(f"PRAGMA table_info({table})")
        )
        if actual != columns:
            raise WorkerRegistryError(f"worker registry table {table} has an unexpected schema")

    triggers = {
        row["name"]: row["sql"] or ""
        for row in connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='trigger' "
            "AND name LIKE 'worker_registry_events_immutable_%'"
        )
    }
    for suffix in ("update", "delete"):
        name = f"worker_registry_events_immutable_{suffix}"
        if name not in triggers or "RAISE(ABORT" not in triggers[name].upper():
            raise WorkerRegistryError("worker registry audit append-only trigger is missing")

    meta_rows = connection.execute("SELECT * FROM worker_registry_meta").fetchall()
    if len(meta_rows) != 1:
        raise WorkerRegistryError("worker registry metadata row is missing or duplicated")
    meta = meta_rows[0]
    if meta["singleton"] != 1 or meta["schema_version"] != _SCHEMA_VERSION:
        raise WorkerRegistryError("worker registry schema version is unsupported")
    config = json.loads(meta["config_json"])
    if type(config) is not dict or _canonical_json(config) != meta["config_json"]:
        raise WorkerRegistryError("worker registry configuration is invalid")
    required_config = {
        "heartbeat_ttl_ms", "failure_threshold", "reservation_ttl_ms",
        "max_workers", "max_reservations",
    }
    if set(config) != required_config or any(type(value) is not int or value <= 0 for value in config.values()):
        raise WorkerRegistryError("worker registry configuration is invalid")

    previous_hash = _ZERO_HASH
    expected_sequence = 0
    events_by_token: dict[str, list[str]] = {}
    registered_workers: set[str] = set()
    for row in connection.execute("SELECT * FROM worker_registry_events ORDER BY sequence"):
        expected_sequence += 1
        if row["sequence"] != expected_sequence:
            raise WorkerRegistryError("worker registry audit sequence is discontinuous")
        if row["event_type"] not in _EVENT_TYPES:
            raise WorkerRegistryError("worker registry audit event type is invalid")
        _identifier(row["worker_id"], "audit worker_id")
        if type(row["actor_id"]) is not str or not row["actor_id"] or len(row["actor_id"]) > 256:
            raise WorkerRegistryError("worker registry audit actor is invalid")
        if type(row["timestamp_wall_ns"]) is not int or row["timestamp_wall_ns"] < 0:
            raise WorkerRegistryError("worker registry audit timestamp is invalid")
        if row["previous_event_sha256"] != previous_hash:
            raise WorkerRegistryError("worker registry audit chain predecessor is invalid")
        payload = json.loads(row["payload_json"])
        expected_payload = _event_payload(
            sequence=row["sequence"],
            event_id=row["event_id"],
            event_type=row["event_type"],
            worker_id=row["worker_id"],
            actor_id=row["actor_id"],
            principal_id=row["principal_id"],
            task_id=row["task_id"],
            token_sha256=row["token_sha256"],
            timestamp_wall_ns=row["timestamp_wall_ns"],
            payload=payload.get("payload") if type(payload) is dict else {},
            previous_event_sha256=row["previous_event_sha256"],
        )
        if type(payload) is not dict or payload != expected_payload:
            raise WorkerRegistryError("worker registry audit payload does not match its columns")
        if _canonical_json(payload) != row["payload_json"]:
            raise WorkerRegistryError("worker registry audit payload is not canonical")
        digest = hashlib.sha256(row["payload_json"].encode("utf-8")).hexdigest()
        if row["event_sha256"] != digest:
            raise WorkerRegistryError("worker registry audit hash is invalid")
        if row["event_type"] == "worker_registered":
            registered_workers.add(row["worker_id"])
        token_hash = row["token_sha256"]
        if token_hash is not None:
            if type(token_hash) is not str or len(token_hash) != 64:
                raise WorkerRegistryError("worker registry audit token digest is invalid")
            events_by_token.setdefault(token_hash, []).append(row["event_type"])
        previous_hash = digest

    if meta["last_sequence"] != expected_sequence or meta["head_sha256"] != previous_hash:
        raise WorkerRegistryError("worker registry audit head does not match the event chain")

    state_by_worker: dict[str, WorkerDescriptor] = {}
    for row in connection.execute("SELECT * FROM worker_registry_state"):
        descriptor = _parse_descriptor(row["descriptor_json"])
        if descriptor.worker_id != row["worker_id"]:
            raise WorkerRegistryError("worker registry descriptor identity mismatch")
        if row["health_state"] not in {
            "starting", "healthy", "degraded", "unavailable", "quarantined", "retired",
        }:
            raise WorkerRegistryError("worker registry health state is invalid")
        for field in ("consecutive_failures", "in_flight", "health_revision", "created_at_wall_ns", "updated_at_wall_ns"):
            if type(row[field]) is not int or row[field] < 0:
                raise WorkerRegistryError(f"worker registry {field} is invalid")
        if row["health_revision"] < 1:
            raise WorkerRegistryError("worker registry health revision must be positive")
        last_heartbeat = row["last_heartbeat_wall_ns"]
        if last_heartbeat is not None and (type(last_heartbeat) is not int or last_heartbeat < 0):
            raise WorkerRegistryError("worker registry heartbeat timestamp is invalid")
        if row["worker_id"] not in registered_workers:
            raise WorkerRegistryError("worker registry state has no registration audit event")
        state_by_worker[row["worker_id"]] = descriptor

    active_tasks: set[tuple[str, str]] = set()
    for row in connection.execute("SELECT * FROM worker_registry_reservations"):
        if row["worker_id"] not in state_by_worker:
            raise WorkerRegistryError("worker reservation references an unknown worker")
        if type(row["token"]) is not str or len(row["token"]) < 32:
            raise WorkerRegistryError("worker reservation identifier is invalid")
        reservation = WorkerReservation(
            token=row["token"],
            worker_id=row["worker_id"],
            expires_at_ns=0,
            descriptor_revision=row["descriptor_revision"],
            committed=bool(row["committed"]),
            principal_id=row["principal_id"],
            task_id=row["task_id"],
            capability=row["capability"],
            protocol_version=row["protocol_version"],
            revision=row["revision"],
        )
        if row["committed"] not in (0, 1):
            raise WorkerRegistryError("worker reservation committed flag is invalid")
        if row["expires_at_wall_ns"] < 0 or row["created_at_wall_ns"] < 0:
            raise WorkerRegistryError("worker reservation timestamp is invalid")
        descriptor = state_by_worker[row["worker_id"]]
        if reservation.descriptor_revision > descriptor.revision:
            raise WorkerRegistryError("worker reservation descriptor revision is from the future")
        if not reservation.committed and reservation.descriptor_revision != descriptor.revision:
            raise WorkerRegistryError("pending worker reservation has a stale descriptor revision")
        task_key = (reservation.principal_id, reservation.task_id)
        if task_key in active_tasks:
            raise WorkerRegistryError("multiple active reservations exist for one principal/task")
        active_tasks.add(task_key)
        token_hash = hashlib.sha256(reservation.token.encode("utf-8")).hexdigest()
        token_events = events_by_token.get(token_hash, [])
        if "reservation_created" not in token_events:
            raise WorkerRegistryError("active reservation has no creation audit event")
        if reservation.committed != ("reservation_committed" in token_events):
            raise WorkerRegistryError("active reservation state disagrees with audit events")
        if any(event in token_events for event in (
            "reservation_released", "reservation_expired", "reservation_revoked",
        )):
            raise WorkerRegistryError("active reservation has a terminal audit event")


class SQLiteWorkerRegistry:
    """Cross-process durable registry backed by the exact SQLiteTaskStore database.

    Reservation identifiers are opaque IDs, not credentials. The host runtime
    still authenticates the supervisor, principal/task owner and worker identity.
    """

    def __init__(
        self,
        task_store: Any,
        *,
        heartbeat_ttl_ms: int = 30_000,
        failure_threshold: int = 3,
        reservation_ttl_ms: int = 30_000,
        max_workers: int = 1024,
        max_reservations: int = 4096,
        clock_ns: Callable[[], int] = time.monotonic_ns,
        clock_wall_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        if not callable(getattr(task_store, "_connect", None)) or not hasattr(task_store, "_lock"):
            raise WorkerRegistryError("SQLiteWorkerRegistry requires a SQLiteTaskStore")
        self.task_store = task_store
        self._tasks = task_store
        self._heartbeat_ttl_ms = heartbeat_ttl_ms
        self._failure_threshold = failure_threshold
        self._reservation_ttl_ms = reservation_ttl_ms
        self._max_workers = max_workers
        self._max_reservations = max_reservations
        self._clock_ns = clock_ns
        self._clock_wall_ns = clock_wall_ns
        self._config = {
            "heartbeat_ttl_ms": heartbeat_ttl_ms,
            "failure_threshold": failure_threshold,
            "reservation_ttl_ms": reservation_ttl_ms,
            "max_workers": max_workers,
            "max_reservations": max_reservations,
        }
        # Reuse the in-memory implementation's validated configuration bounds.
        InMemoryWorkerRegistry(
            heartbeat_ttl_ms=heartbeat_ttl_ms,
            failure_threshold=failure_threshold,
            reservation_ttl_ms=reservation_ttl_ms,
            max_workers=max_workers,
            max_reservations=max_reservations,
            clock_ns=clock_ns,
        )
        self._initialize()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._tasks._lock:
            connection = self._tasks._connect()
            connection.row_factory = sqlite3.Row
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    def _initialize(self) -> None:
        with self._transaction() as connection:
            present = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'worker_registry_%'"
                )
            }
            if present and present != _TABLES:
                raise WorkerRegistryError("worker registry schema is partially initialized")
            if not present:
                _execute_sql_script(connection,
                    """
                    CREATE TABLE worker_registry_meta (
                        singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                        schema_version INTEGER NOT NULL,
                        config_json TEXT NOT NULL,
                        last_sequence INTEGER NOT NULL,
                        head_sha256 TEXT NOT NULL
                    );
                    CREATE TABLE worker_registry_state (
                        worker_id TEXT PRIMARY KEY,
                        descriptor_json TEXT NOT NULL,
                        health_state TEXT NOT NULL,
                        last_heartbeat_wall_ns INTEGER,
                        consecutive_failures INTEGER NOT NULL,
                        in_flight INTEGER NOT NULL,
                        health_revision INTEGER NOT NULL,
                        created_at_wall_ns INTEGER NOT NULL,
                        updated_at_wall_ns INTEGER NOT NULL
                    );
                    CREATE TABLE worker_registry_reservations (
                        token TEXT PRIMARY KEY,
                        worker_id TEXT NOT NULL REFERENCES worker_registry_state(worker_id) ON DELETE RESTRICT,
                        principal_id TEXT NOT NULL,
                        task_id TEXT NOT NULL,
                        capability TEXT NOT NULL,
                        protocol_version INTEGER NOT NULL,
                        descriptor_revision INTEGER NOT NULL,
                        expires_at_wall_ns INTEGER NOT NULL,
                        committed INTEGER NOT NULL CHECK(committed IN (0, 1)),
                        revision INTEGER NOT NULL,
                        created_at_wall_ns INTEGER NOT NULL
                    );
                    CREATE UNIQUE INDEX worker_registry_one_active_task_reservation
                        ON worker_registry_reservations(principal_id, task_id);
                    CREATE INDEX worker_registry_reservations_worker_idx
                        ON worker_registry_reservations(worker_id);
                    CREATE TABLE worker_registry_events (
                        sequence INTEGER PRIMARY KEY,
                        event_id TEXT NOT NULL UNIQUE,
                        event_type TEXT NOT NULL,
                        worker_id TEXT NOT NULL,
                        actor_id TEXT NOT NULL,
                        principal_id TEXT,
                        task_id TEXT,
                        token_sha256 TEXT,
                        timestamp_wall_ns INTEGER NOT NULL,
                        payload_json TEXT NOT NULL,
                        previous_event_sha256 TEXT NOT NULL,
                        event_sha256 TEXT NOT NULL,
                        FOREIGN KEY(worker_id) REFERENCES worker_registry_state(worker_id) ON DELETE RESTRICT
                    );
                    CREATE INDEX worker_registry_events_worker_idx
                        ON worker_registry_events(worker_id, sequence);
                    CREATE TRIGGER worker_registry_events_immutable_update
                    BEFORE UPDATE ON worker_registry_events
                    BEGIN
                        SELECT RAISE(ABORT, 'worker registry audit events are append-only');
                    END;
                    CREATE TRIGGER worker_registry_events_immutable_delete
                    BEFORE DELETE ON worker_registry_events
                    BEGIN
                        SELECT RAISE(ABORT, 'worker registry audit events are append-only');
                    END;
                    """
                )
                connection.execute(
                    "INSERT INTO worker_registry_meta "
                    "(singleton, schema_version, config_json, last_sequence, head_sha256) "
                    "VALUES (1, ?, ?, 0, ?)",
                    (_SCHEMA_VERSION, _canonical_json(self._config), _ZERO_HASH),
                )
            else:
                meta = connection.execute(
                    "SELECT * FROM worker_registry_meta WHERE singleton=1"
                ).fetchone()
                if meta is None or meta["schema_version"] != _SCHEMA_VERSION:
                    raise WorkerRegistryError("worker registry schema version is unsupported")
                if meta["config_json"] != _canonical_json(self._config):
                    raise WorkerRegistryError("worker registry configuration differs from the persisted configuration")
            validate_worker_registry_snapshot(connection)

    def _wall_now(self) -> int:
        value = self._clock_wall_ns()
        if type(value) is not int or value < 0:
            raise WorkerRegistryError("wall clock must return a non-negative integer")
        return value

    def _load_memory(
        self, connection: sqlite3.Connection, wall_now: int, mono_now: int,
    ) -> InMemoryWorkerRegistry:
        memory = InMemoryWorkerRegistry(
            heartbeat_ttl_ms=self._heartbeat_ttl_ms,
            failure_threshold=self._failure_threshold,
            reservation_ttl_ms=self._reservation_ttl_ms,
            max_workers=self._max_workers,
            max_reservations=self._max_reservations,
            clock_ns=lambda: mono_now,
        )
        for row in connection.execute("SELECT * FROM worker_registry_state"):
            descriptor = _parse_descriptor(row["descriptor_json"])
            last_wall = row["last_heartbeat_wall_ns"]
            last_mono = None
            if last_wall is not None:
                age = wall_now - last_wall
                if age >= 0:
                    last_mono = max(0, mono_now - age)
            health = WorkerHealth(
                state=row["health_state"],
                last_heartbeat_ns=last_mono,
                consecutive_failures=row["consecutive_failures"],
                in_flight=row["in_flight"],
                revision=row["health_revision"],
            )
            memory._workers[descriptor.worker_id] = WorkerSnapshot(descriptor, health)

        for row in connection.execute("SELECT * FROM worker_registry_reservations"):
            expiry_wall = row["expires_at_wall_ns"]
            created_wall = row["created_at_wall_ns"]
            if wall_now < created_wall or wall_now > expiry_wall:
                expiry_mono = mono_now
            else:
                expiry_mono = mono_now + (expiry_wall - wall_now)
            reservation = WorkerReservation(
                token=row["token"],
                worker_id=row["worker_id"],
                expires_at_ns=expiry_mono,
                descriptor_revision=row["descriptor_revision"],
                committed=bool(row["committed"]),
                principal_id=row["principal_id"],
                task_id=row["task_id"],
                capability=row["capability"],
                protocol_version=row["protocol_version"],
                revision=row["revision"],
            )
            memory._reservations[reservation.token] = reservation
        return memory

    def _persist_memory(
        self,
        connection: sqlite3.Connection,
        memory: InMemoryWorkerRegistry,
        wall_now: int,
        mono_now: int,
    ) -> None:
        for worker_id, snapshot in memory._workers.items():
            health = snapshot.health
            last_wall = None
            if health.last_heartbeat_ns is not None:
                age = mono_now - health.last_heartbeat_ns
                if age >= 0 and wall_now >= age:
                    last_wall = wall_now - age
            descriptor_json = _canonical_json(_descriptor_payload(snapshot.descriptor))
            connection.execute(
                """
                INSERT INTO worker_registry_state (
                    worker_id, descriptor_json, health_state, last_heartbeat_wall_ns,
                    consecutive_failures, in_flight, health_revision,
                    created_at_wall_ns, updated_at_wall_ns
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(worker_id) DO UPDATE SET
                    descriptor_json=excluded.descriptor_json,
                    health_state=excluded.health_state,
                    last_heartbeat_wall_ns=excluded.last_heartbeat_wall_ns,
                    consecutive_failures=excluded.consecutive_failures,
                    in_flight=excluded.in_flight,
                    health_revision=excluded.health_revision,
                    updated_at_wall_ns=excluded.updated_at_wall_ns
                """,
                (
                    worker_id, descriptor_json, health.state, last_wall,
                    health.consecutive_failures, health.in_flight, health.revision,
                    wall_now, wall_now,
                ),
            )

        existing_rows = connection.execute(
            "SELECT token, created_at_wall_ns, expires_at_wall_ns FROM worker_registry_reservations"
        ).fetchall()
        existing = {row["token"]: row for row in existing_rows}
        current_tokens = set(memory._reservations)
        for reservation in memory._reservations.values():
            old = existing.get(reservation.token)
            created_wall = old["created_at_wall_ns"] if old is not None else wall_now
            if old is not None and reservation.committed:
                expiry_wall = old["expires_at_wall_ns"]
            else:
                expiry_wall = wall_now + max(0, reservation.expires_at_ns - mono_now)
            connection.execute(
                """
                INSERT INTO worker_registry_reservations (
                    token, worker_id, principal_id, task_id, capability,
                    protocol_version, descriptor_revision, expires_at_wall_ns,
                    committed, revision, created_at_wall_ns
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(token) DO UPDATE SET
                    worker_id=excluded.worker_id,
                    principal_id=excluded.principal_id,
                    task_id=excluded.task_id,
                    capability=excluded.capability,
                    protocol_version=excluded.protocol_version,
                    descriptor_revision=excluded.descriptor_revision,
                    expires_at_wall_ns=excluded.expires_at_wall_ns,
                    committed=excluded.committed,
                    revision=excluded.revision
                """,
                (
                    reservation.token, reservation.worker_id, reservation.principal_id,
                    reservation.task_id, reservation.capability, reservation.protocol_version,
                    reservation.descriptor_revision, expiry_wall, int(reservation.committed),
                    reservation.revision, created_wall,
                ),
            )
        for token in set(existing) - current_tokens:
            connection.execute(
                "DELETE FROM worker_registry_reservations WHERE token=?", (token,),
            )

    def _append_event(
        self,
        connection: sqlite3.Connection,
        *,
        event_type: str,
        worker_id: str,
        actor_id: str,
        principal_id: str | None = None,
        task_id: str | None = None,
        token: str | None = None,
        timestamp_wall_ns: int,
        payload: dict[str, Any],
    ) -> None:
        if event_type not in _EVENT_TYPES:
            raise WorkerRegistryError("unsupported worker registry audit event")
        meta = connection.execute(
            "SELECT last_sequence, head_sha256 FROM worker_registry_meta WHERE singleton=1"
        ).fetchone()
        sequence = meta["last_sequence"] + 1
        event_id = uuid.uuid4().hex
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest() if token else None
        full_payload = _event_payload(
            sequence=sequence,
            event_id=event_id,
            event_type=event_type,
            worker_id=worker_id,
            actor_id=actor_id,
            principal_id=principal_id,
            task_id=task_id,
            token_sha256=token_hash,
            timestamp_wall_ns=timestamp_wall_ns,
            payload=payload,
            previous_event_sha256=meta["head_sha256"],
        )
        payload_json = _canonical_json(full_payload)
        digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        connection.execute(
            """
            INSERT INTO worker_registry_events (
                sequence, event_id, event_type, worker_id, actor_id,
                principal_id, task_id, token_sha256, timestamp_wall_ns,
                payload_json, previous_event_sha256, event_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sequence, event_id, event_type, worker_id, actor_id,
                principal_id, task_id, token_hash, timestamp_wall_ns,
                payload_json, meta["head_sha256"], digest,
            ),
        )
        connection.execute(
            "UPDATE worker_registry_meta SET last_sequence=?, head_sha256=? WHERE singleton=1",
            (sequence, digest),
        )

    def _append_diff_events(
        self,
        connection: sqlite3.Connection,
        before_workers: dict[str, WorkerSnapshot],
        after_workers: dict[str, WorkerSnapshot],
        before_reservations: dict[str, WorkerReservation],
        after_reservations: dict[str, WorkerReservation],
        *,
        operation: str,
        actor_id: str,
        wall_now: int,
        mono_now: int,
        event_context: dict[str, Any] | None = None,
    ) -> None:
        context = event_context or {}
        for worker_id, current in after_workers.items():
            previous = before_workers.get(worker_id)
            if previous is None:
                self._append_event(
                    connection, event_type="worker_registered", worker_id=worker_id,
                    actor_id=actor_id or worker_id, timestamp_wall_ns=wall_now,
                    payload={"descriptor": _descriptor_payload(current.descriptor),
                             "health_state": current.health.state},
                )
                continue
            if previous.descriptor != current.descriptor:
                self._append_event(
                    connection, event_type="worker_descriptor_updated", worker_id=worker_id,
                    actor_id=actor_id or worker_id, timestamp_wall_ns=wall_now,
                    payload={
                        "previous_revision": previous.descriptor.revision,
                        "new_revision": current.descriptor.revision,
                    },
                )
            old_health = previous.health
            new_health = current.health
            if (
                old_health.state != new_health.state
                or old_health.consecutive_failures != new_health.consecutive_failures
                or old_health.in_flight != new_health.in_flight
            ):
                event_type = {
                    "record_failure": "worker_failure_recorded",
                    "quarantine": "worker_quarantined",
                    "retire": "worker_retired",
                    "clear_quarantine": "worker_quarantine_cleared",
                    "heartbeat": "worker_heartbeat_state_changed",
                }.get(operation, "worker_health_updated")
                self._append_event(
                    connection, event_type=event_type, worker_id=worker_id,
                    actor_id=actor_id or "host", timestamp_wall_ns=wall_now,
                    payload={
                        "previous_state": old_health.state,
                        "new_state": new_health.state,
                        "previous_in_flight": old_health.in_flight,
                        "new_in_flight": new_health.in_flight,
                        "consecutive_failures": new_health.consecutive_failures,
                        "health_revision": new_health.revision,
                    },
                )

        for token, current in after_reservations.items():
            previous = before_reservations.get(token)
            if previous is None:
                self._append_event(
                    connection, event_type="reservation_created",
                    worker_id=current.worker_id, actor_id="host",
                    principal_id=current.principal_id, task_id=current.task_id,
                    token=token, timestamp_wall_ns=wall_now,
                    payload={
                        "capability": current.capability,
                        "protocol_version": current.protocol_version,
                        "descriptor_revision": current.descriptor_revision,
                        "committed": current.committed,
                    },
                )
            elif not previous.committed and current.committed:
                self._append_event(
                    connection, event_type="reservation_committed",
                    worker_id=current.worker_id, actor_id="host",
                    principal_id=current.principal_id, task_id=current.task_id,
                    token=token, timestamp_wall_ns=wall_now,
                    payload={"revision": current.revision},
                )

        for token, previous in before_reservations.items():
            if token in after_reservations:
                continue
            if operation == "release_reservation":
                event_type = "reservation_released"
                reason = "host_release"
            elif not previous.committed and previous.expires_at_ns <= mono_now:
                event_type = "reservation_expired"
                reason = "pending_ttl_elapsed"
            else:
                event_type = "reservation_revoked"
                reason = operation
            self._append_event(
                connection, event_type=event_type,
                worker_id=previous.worker_id, actor_id="host",
                principal_id=previous.principal_id, task_id=previous.task_id,
                token=token, timestamp_wall_ns=wall_now,
                payload={
                    "reason": reason,
                    "was_committed": previous.committed,
                    "observed_unreserved_in_flight": context.get("observed_unreserved_in_flight"),
                },
            )

    def _run(
        self,
        operation: str,
        callback: Callable[[InMemoryWorkerRegistry, int], Any],
        *,
        now_ns: int | None = None,
        actor_id: str = "host",
        event_context: dict[str, Any] | None = None,
    ) -> Any:
        mono_now = now_ns if now_ns is not None else self._clock_ns()
        if type(mono_now) is not int or mono_now < 0:
            raise WorkerRegistryError("monotonic clock must return a non-negative integer")
        wall_now = self._wall_now()
        with self._transaction() as connection:
            memory = self._load_memory(connection, wall_now, mono_now)
            before_workers = dict(memory._workers)
            before_reservations = dict(memory._reservations)
            memory._purge_expired_reservations(mono_now)
            result = callback(memory, mono_now)
            self._persist_memory(connection, memory, wall_now, mono_now)
            self._append_diff_events(
                connection, before_workers, dict(memory._workers),
                before_reservations, dict(memory._reservations),
                operation=operation, actor_id=actor_id, wall_now=wall_now,
                mono_now=mono_now, event_context=event_context,
            )
            return result

    @staticmethod
    def _current_reservation(
        memory: InMemoryWorkerRegistry, reservation: WorkerReservation,
    ) -> WorkerReservation | None:
        if not isinstance(reservation, WorkerReservation):
            raise WorkerRegistryError("reservation object is invalid")
        current = memory._reservations.get(reservation.token)
        if current is None:
            return None
        identity = (
            "token", "worker_id", "descriptor_revision", "principal_id",
            "task_id", "capability", "protocol_version",
        )
        if any(getattr(current, field) != getattr(reservation, field) for field in identity):
            raise WorkerConflictError("reservation context does not match the active registry record")
        return current

    def register(
        self, descriptor: WorkerDescriptor, *, authenticated_worker_id: str,
        now_ns: int | None = None,
    ) -> WorkerSnapshot:
        return self._run(
            "register",
            lambda memory, timestamp: memory.register(
                descriptor, authenticated_worker_id=authenticated_worker_id, now_ns=timestamp,
            ),
            now_ns=now_ns, actor_id=authenticated_worker_id,
        )

    def get(self, worker_id: str) -> WorkerSnapshot:
        return self._run("get", lambda memory, timestamp: memory.get(worker_id))

    def get_reservation(self, token: str, *, now_ns: int | None = None) -> WorkerReservation | None:
        return self._run(
            "get_reservation",
            lambda memory, timestamp: memory.get_reservation(token, now_ns=timestamp),
            now_ns=now_ns,
        )

    def get_reservation_for_task(
        self, principal_id: str, task_id: str, *, now_ns: int | None = None,
    ) -> WorkerReservation | None:
        return self._run(
            "get_reservation_for_task",
            lambda memory, timestamp: memory.get_reservation_for_task(
                principal_id, task_id, now_ns=timestamp,
            ),
            now_ns=now_ns,
        )

    def update_descriptor(
        self, descriptor: WorkerDescriptor, *, authenticated_worker_id: str,
        expected_revision: int,
    ) -> WorkerSnapshot:
        return self._run(
            "update_descriptor",
            lambda memory, timestamp: memory.update_descriptor(
                descriptor, authenticated_worker_id=authenticated_worker_id,
                expected_revision=expected_revision,
            ),
            actor_id=authenticated_worker_id,
        )

    def heartbeat(
        self, worker_id: str, *, authenticated_worker_id: str,
        in_flight: int, now_ns: int | None = None,
    ) -> WorkerSnapshot:
        return self._run(
            "heartbeat",
            lambda memory, timestamp: memory.heartbeat(
                worker_id, authenticated_worker_id=authenticated_worker_id,
                in_flight=in_flight, now_ns=timestamp,
            ),
            now_ns=now_ns, actor_id=authenticated_worker_id,
        )

    def record_failure(
        self, worker_id: str, *, authenticated_worker_id: str,
    ) -> WorkerSnapshot:
        return self._run(
            "record_failure",
            lambda memory, timestamp: memory.record_failure(
                worker_id, authenticated_worker_id=authenticated_worker_id,
            ),
            actor_id=authenticated_worker_id,
        )

    def quarantine(self, worker_id: str, *, expected_health_revision: int) -> WorkerSnapshot:
        return self._run(
            "quarantine",
            lambda memory, timestamp: memory.quarantine(
                worker_id, expected_health_revision=expected_health_revision,
            ),
        )

    def retire(self, worker_id: str, *, expected_health_revision: int) -> WorkerSnapshot:
        return self._run(
            "retire",
            lambda memory, timestamp: memory.retire(
                worker_id, expected_health_revision=expected_health_revision,
            ),
        )

    def clear_quarantine(self, worker_id: str, *, expected_health_revision: int) -> WorkerSnapshot:
        return self._run(
            "clear_quarantine",
            lambda memory, timestamp: memory.clear_quarantine(
                worker_id, expected_health_revision=expected_health_revision,
            ),
        )

    def reserve_eligible(
        self,
        capability: str,
        *,
        protocol_version: int,
        authorized_worker_ids: set[str] | frozenset[str],
        principal_id: str,
        task_id: str,
        now_ns: int | None = None,
    ) -> WorkerReservation | None:
        return self._run(
            "reserve_eligible",
            lambda memory, timestamp: memory.reserve_eligible(
                capability, protocol_version=protocol_version,
                authorized_worker_ids=authorized_worker_ids,
                principal_id=principal_id, task_id=task_id, now_ns=timestamp,
            ),
            now_ns=now_ns,
        )

    def commit_reservation(
        self, reservation: WorkerReservation, *, authenticated_worker_id: str,
        now_ns: int | None = None,
    ) -> WorkerReservation | None:
        def commit(memory: InMemoryWorkerRegistry, timestamp: int):
            current = self._current_reservation(memory, reservation)
            if current is None or current.committed:
                return current
            return memory.commit_reservation(
                current, authenticated_worker_id=authenticated_worker_id, now_ns=timestamp,
            )
        return self._run(
            "commit_reservation", commit, now_ns=now_ns, actor_id=authenticated_worker_id,
        )

    def release_reservation(
        self,
        reservation: WorkerReservation,
        *,
        authenticated_worker_id: str,
        observed_unreserved_in_flight: int | None = None,
        now_ns: int | None = None,
    ) -> bool:
        def release(memory: InMemoryWorkerRegistry, timestamp: int):
            current = self._current_reservation(memory, reservation)
            if current is None:
                return False
            return memory.release_reservation(
                current,
                authenticated_worker_id=authenticated_worker_id,
                observed_unreserved_in_flight=observed_unreserved_in_flight,
                now_ns=timestamp,
            )
        return self._run(
            "release_reservation", release, now_ns=now_ns,
            actor_id=authenticated_worker_id,
            event_context={"observed_unreserved_in_flight": observed_unreserved_in_flight},
        )

    def expire_reservations(self, *, now_ns: int | None = None) -> tuple[WorkerReservation, ...]:
        return self._run(
            "expire_reservations",
            lambda memory, timestamp: memory.expire_reservations(now_ns=timestamp),
            now_ns=now_ns,
        )

    def eligible(
        self,
        capability: str,
        *,
        protocol_version: int,
        authorized_worker_ids: set[str] | frozenset[str],
        now_ns: int | None = None,
        limit: int = 20,
    ) -> tuple[WorkerSnapshot, ...]:
        return self._run(
            "eligible",
            lambda memory, timestamp: memory.eligible(
                capability, protocol_version=protocol_version,
                authorized_worker_ids=authorized_worker_ids,
                now_ns=timestamp, limit=limit,
            ),
            now_ns=now_ns,
        )

    def events_for_worker(self, worker_id: str) -> tuple[dict[str, Any], ...]:
        _identifier(worker_id, "worker_id")
        with self._tasks._lock:
            connection = self._tasks._connect()
            connection.row_factory = sqlite3.Row
            try:
                rows = connection.execute(
                    "SELECT payload_json FROM worker_registry_events "
                    "WHERE worker_id=? ORDER BY sequence",
                    (worker_id,),
                ).fetchall()
                return tuple(json.loads(row["payload_json"]) for row in rows)
            finally:
                connection.close()

    def integrity_check(self) -> str:
        with self._tasks._lock:
            connection = self._tasks._connect()
            connection.row_factory = sqlite3.Row
            try:
                result = connection.execute("PRAGMA integrity_check").fetchone()[0]
                if result != "ok":
                    return "worker registry SQLite integrity check failed"
                if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    return "worker registry foreign key check failed"
                validate_worker_registry_snapshot(connection)
                return "ok"
            except Exception:
                return "worker registry validation failed"
            finally:
                connection.close()
