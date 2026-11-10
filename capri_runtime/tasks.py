"""Durable, bounded task orchestration with leases and at-least-once recovery.

This module is an orchestration primitive, not a model, sandbox, scheduler daemon,
or permission system. Hosts inject trusted handlers; model-originated side effects
must still pass through the permissioned ToolExecutor boundary.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping
from uuid import uuid4

from .sqlite_backup import backup_sqlite_database


class TaskError(Exception):
    """Base class for expected task-engine failures."""


class TaskValidationError(TaskError):
    """A task definition or persisted task value is invalid."""


class TaskNotFoundError(TaskError):
    """The requested task does not exist."""


class TaskConflictError(TaskError):
    """A task lease or state changed before the requested transition."""


class TaskIdempotencyConflict(TaskError):
    """An idempotency key was reused for a different task definition."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise TaskValidationError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        raise TaskValidationError("persisted timestamp is invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TaskValidationError("persisted timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _assert_json_value(value: Any, depth: int = 0) -> None:
    if depth > 16:
        raise TaskValidationError("JSON nesting exceeds 16 levels")
    if value is None or isinstance(value, (bool, int, float)):
        return
    if isinstance(value, str):
        if any(0xD800 <= ord(ch) <= 0xDFFF for ch in value):
            raise TaskValidationError("JSON strings must contain Unicode scalar values")
        return
    if type(value) is list:
        for child in value:
            _assert_json_value(child, depth + 1)
        return
    if type(value) is dict:
        for key, child in value.items():
            if not isinstance(key, str):
                raise TaskValidationError("JSON object keys must be strings")
            _assert_json_value(key, depth + 1)
            _assert_json_value(child, depth + 1)
        return
    raise TaskValidationError("value contains a non-JSON type")


def _json(value: Any, *, label: str, limit: int = 65_536) -> tuple[str, Any]:
    _assert_json_value(value)
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True,
            separators=(",", ":"),
        )
        raw = encoded.encode("utf-8", errors="strict")
        decoded = json.loads(encoded)
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        raise TaskValidationError(f"{label} must be valid JSON with Unicode scalar values") from None
    if len(raw) > limit:
        raise TaskValidationError(f"{label} exceeds the configured byte limit")
    if not isinstance(decoded, (dict, list)) and decoded is not None:
        raise TaskValidationError(f"{label} must be a JSON object or array")
    return encoded, decoded


def _text(value: Any, label: str, limit: int) -> str:
    if (not isinstance(value, str) or not value or len(value) > limit
            or any(0xD800 <= ord(ch) <= 0xDFFF for ch in value)):
        raise TaskValidationError(f"{label} is invalid")
    return value


def _validate_plan(plan: Any) -> tuple[str, list[dict[str, Any]]]:
    encoded, decoded = _json(plan, label="plan")
    if not isinstance(decoded, list) or not 1 <= len(decoded) <= 32:
        raise TaskValidationError("plan must contain between 1 and 32 steps")
    normalized = []
    for index, step in enumerate(decoded):
        if not isinstance(step, dict) or set(step) - {"tool", "input", "max_attempts"}:
            raise TaskValidationError(f"step {index} has unsupported fields")
        tool = _text(step.get("tool"), f"step {index} tool", 64)
        if not tool.replace("_", "").replace("-", "").replace(".", "").isalnum():
            raise TaskValidationError(f"step {index} tool name is invalid")
        args = step.get("input", {})
        if not isinstance(args, dict):
            raise TaskValidationError(f"step {index} input must be an object")
        attempts = step.get("max_attempts", 3)
        if isinstance(attempts, bool) or not isinstance(attempts, int) or not 1 <= attempts <= 10:
            raise TaskValidationError(f"step {index} max_attempts must be between 1 and 10")
        _json(args, label=f"step {index} input")
        normalized.append({"tool": tool, "input": args, "max_attempts": attempts})
    return _json(normalized, label="normalized plan")[0], normalized


@dataclass(frozen=True, slots=True)
class TaskRecord:
    task_id: str
    idempotency_key: str | None
    state: str
    created_at: str
    updated_at: str
    current_step: int
    attempts: int
    available_at: str
    cancel_requested: bool
    result: tuple[Any, ...]
    error_code: str | None


@dataclass(frozen=True, slots=True)
class TaskClaim:
    task_id: str
    executor_id: str
    step_index: int
    attempt: int
    idempotency_key: str
    tool: str
    input: dict[str, Any]
    lease_until: str
    principal_id: str | None = None


class SQLiteTaskStore:
    """Private SQLite task state with atomic claims and cross-process leases.

    The parent directory must already exist and be private. Task inputs/results
    are persisted as bounded JSON; callers must not put secrets or sensitive
    personal data in them. Execution is at-least-once after lease expiry.
    """

    def __init__(self, path: str) -> None:
        _text(path, "database path", 4096)
        absolute = os.path.abspath(path)
        parent = os.path.dirname(absolute)
        if not os.path.isdir(parent) or os.path.realpath(parent) != parent:
            raise TaskValidationError("database parent must be an existing non-symlink directory")
        parent_stat = os.stat(parent, follow_symlinks=False)
        if not stat.S_ISDIR(parent_stat.st_mode):
            raise TaskValidationError("database parent must be a directory")
        if os.name == "posix" and (
            parent_stat.st_uid != os.geteuid() or stat.S_IMODE(parent_stat.st_mode) & 0o077
        ):
            raise TaskValidationError("database parent must be owned by the current user and private")
        if os.path.lexists(absolute):
            existing = os.lstat(absolute)
            if not stat.S_ISREG(existing.st_mode):
                raise TaskValidationError("database path must be a regular non-symlink file")
            if os.name == "posix" and (existing.st_uid != os.geteuid() or existing.st_nlink != 1):
                raise TaskValidationError("database file ownership or link count is unsafe")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(absolute, flags, 0o600)
        except OSError:
            raise TaskValidationError("database file could not be opened safely") from None
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise TaskValidationError("database path must be a regular file")
            if os.name == "posix":
                if opened.st_uid != os.geteuid() or opened.st_nlink != 1:
                    raise TaskValidationError("database ownership or link count is unsafe")
                os.fchmod(descriptor, 0o600)
        finally:
            os.close(descriptor)
        self.path = absolute
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        parent = os.path.dirname(self.path)
        if os.path.realpath(parent) != parent:
            raise TaskValidationError("database parent path changed")
        parent_stat = os.stat(parent, follow_symlinks=False)
        if not stat.S_ISDIR(parent_stat.st_mode):
            raise TaskValidationError("database parent changed")
        if os.name == "posix" and (
            parent_stat.st_uid != os.geteuid() or stat.S_IMODE(parent_stat.st_mode) & 0o077
        ):
            raise TaskValidationError("database parent privacy changed")
        current = os.lstat(self.path)
        if not stat.S_ISREG(current.st_mode):
            raise TaskValidationError("database path changed")
        if os.name == "posix" and (
            current.st_uid != os.geteuid() or stat.S_IMODE(current.st_mode) != 0o600
            or current.st_nlink != 1
        ):
            raise TaskValidationError("database ownership, permissions, or link count changed")
        connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _initialize(self) -> None:
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("""CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    idempotency_key TEXT UNIQUE,
                    state TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    current_step INTEGER NOT NULL,
                    attempts INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    available_at TEXT NOT NULL,
                    lease_owner TEXT,
                    lease_until TEXT,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    results_json TEXT NOT NULL DEFAULT '[]',
                    error_code TEXT
                )""")
                connection.execute("""CREATE TABLE IF NOT EXISTS task_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id),
                    timestamp TEXT NOT NULL,
                    state TEXT NOT NULL,
                    step_index INTEGER NOT NULL,
                    attempt INTEGER NOT NULL,
                    error_code TEXT
                )""")
                connection.execute("""CREATE TABLE IF NOT EXISTS task_owners (
                    task_id TEXT PRIMARY KEY REFERENCES tasks(task_id) ON DELETE RESTRICT,
                    principal_id TEXT NOT NULL
                )""")
                connection.execute("""CREATE TRIGGER IF NOT EXISTS task_owner_immutable_update
                    BEFORE UPDATE ON task_owners
                    BEGIN SELECT RAISE(ABORT, 'task ownership is immutable'); END""")
                connection.execute("""CREATE TRIGGER IF NOT EXISTS task_owner_immutable_delete
                    BEFORE DELETE ON task_owners
                    BEGIN SELECT RAISE(ABORT, 'task ownership is immutable'); END""")
                connection.execute("CREATE INDEX IF NOT EXISTS task_ready_idx ON tasks(state, available_at, created_at)")
                connection.execute("CREATE INDEX IF NOT EXISTS task_owner_principal_idx ON task_owners(principal_id, task_id)")
            finally:
                connection.close()

    @staticmethod
    def _record(row: tuple[Any, ...]) -> TaskRecord:
        (task_id, key, state, created, updated, index, attempts, available,
         cancel, results, error) = row
        try:
            parsed = json.loads(results)
        except (TypeError, ValueError):
            raise TaskValidationError("persisted task results are corrupt") from None
        if not isinstance(parsed, list):
            raise TaskValidationError("persisted task results are corrupt")
        return TaskRecord(task_id, key, state, created, updated, index, attempts,
                          available, bool(cancel), tuple(parsed), error)

    def create(self, plan: Any, idempotency_key: str | None = None,
               now: datetime | None = None) -> TaskRecord:
        """Create a legacy unowned task for trusted single-principal hosts."""
        return self._create(plan, idempotency_key, now, principal_id=None)

    def create_for_principal(
        self, principal_id: str, plan: Any, idempotency_key: str | None = None,
        now: datetime | None = None,
    ) -> TaskRecord:
        """Atomically create a task bound to an authenticated principal.

        The caller must obtain principal_id from trusted host authentication.
        Principal-scoped idempotency keys are stored as one-way namespaced
        digests so different principals can safely reuse the same client key.
        """
        principal_id = _text(principal_id, "principal_id", 128)
        scoped_key = None
        if idempotency_key is not None:
            key = _text(idempotency_key, "idempotency_key", 128)
            digest = hashlib.sha256(
                (principal_id + "\0" + key).encode("utf-8")
            ).hexdigest()
            scoped_key = "principal:" + digest
        return self._create(plan, scoped_key, now, principal_id=principal_id)

    def _create(
        self, plan: Any, idempotency_key: str | None, now: datetime | None,
        *, principal_id: str | None,
    ) -> TaskRecord:
        plan_json, _ = _validate_plan(plan)
        if idempotency_key is not None:
            idempotency_key = _text(idempotency_key, "idempotency_key", 128)
        stamp = _iso(now or _now())
        task_id = str(uuid4())
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                if idempotency_key is not None:
                    existing = connection.execute(
                        "SELECT task_id, idempotency_key, state, created_at, updated_at, current_step, attempts, available_at, cancel_requested, results_json, error_code, plan_json FROM tasks WHERE idempotency_key=?",
                        (idempotency_key,),
                    ).fetchone()
                    if existing:
                        owner = connection.execute(
                            "SELECT principal_id FROM task_owners WHERE task_id=?",
                            (existing[0],),
                        ).fetchone()
                        existing_owner = owner[0] if owner else None
                        if existing_owner != principal_id:
                            raise TaskIdempotencyConflict(
                                "idempotency key is already bound to a different task owner"
                            )
                        if existing[11] != plan_json:
                            raise TaskIdempotencyConflict("idempotency key already identifies a different plan")
                        connection.execute("COMMIT")
                        return self._record(existing[:11])
                connection.execute(
                    """INSERT INTO tasks(task_id,idempotency_key,state,plan_json,current_step,attempts,
                    created_at,updated_at,available_at) VALUES(?,?,'queued',?,0,0,?,?,?)""",
                    (task_id, idempotency_key, plan_json, stamp, stamp, stamp),
                )
                if principal_id is not None:
                    connection.execute(
                        "INSERT INTO task_owners(task_id,principal_id) VALUES(?,?)",
                        (task_id, principal_id),
                    )
                connection.execute(
                    "INSERT INTO task_events(task_id,timestamp,state,step_index,attempt) VALUES(?,?,'queued',0,0)",
                    (task_id, stamp),
                )
                row = connection.execute(
                    "SELECT task_id,idempotency_key,state,created_at,updated_at,current_step,attempts,available_at,cancel_requested,results_json,error_code FROM tasks WHERE task_id=?",
                    (task_id,),
                ).fetchone()
                connection.execute("COMMIT")
                return self._record(row)
            except Exception:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                connection.close()

    def _assert_principal_owner(self, task_id: str, principal_id: str) -> None:
        _text(task_id, "task_id", 64)
        _text(principal_id, "principal_id", 128)
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute(
                    "SELECT principal_id FROM task_owners WHERE task_id=?",
                    (task_id,),
                ).fetchone()
                if not row or row[0] != principal_id:
                    raise TaskNotFoundError("task does not exist")
            finally:
                connection.close()

    def get_for_principal(self, task_id: str, principal_id: str) -> TaskRecord:
        self._assert_principal_owner(task_id, principal_id)
        return self.get(task_id)

    def request_cancel_for_principal(
        self, task_id: str, principal_id: str, now: datetime | None = None
    ) -> TaskRecord:
        self._assert_principal_owner(task_id, principal_id)
        return self.request_cancel(task_id, now=now)

    def events_for_principal(
        self, task_id: str, principal_id: str
    ) -> tuple[dict[str, Any], ...]:
        self._assert_principal_owner(task_id, principal_id)
        return self.events(task_id)

    def get(self, task_id: str) -> TaskRecord:
        _text(task_id, "task_id", 64)
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute(
                    "SELECT task_id,idempotency_key,state,created_at,updated_at,current_step,attempts,available_at,cancel_requested,results_json,error_code FROM tasks WHERE task_id=?",
                    (task_id,),
                ).fetchone()
                if not row:
                    raise TaskNotFoundError("task does not exist")
                return self._record(row)
            finally:
                connection.close()

    def request_cancel(self, task_id: str, now: datetime | None = None) -> TaskRecord:
        stamp = _iso(now or _now())
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT state FROM tasks WHERE task_id=?", (task_id,)
                ).fetchone()
                if not row:
                    raise TaskNotFoundError("task does not exist")
                state = row[0]
                if state in {"succeeded", "failed", "cancelled"}:
                    connection.execute("COMMIT")
                    return self.get(task_id)
                if state in {"queued", "retry_wait"}:
                    connection.execute(
                        "UPDATE tasks SET state='cancelled',cancel_requested=1,updated_at=?,lease_owner=NULL,lease_until=NULL WHERE task_id=?",
                        (stamp, task_id),
                    )
                    new_state = "cancelled"
                else:
                    connection.execute(
                        "UPDATE tasks SET cancel_requested=1,updated_at=? WHERE task_id=?",
                        (stamp, task_id),
                    )
                    new_state = "running"
                connection.execute(
                    "INSERT INTO task_events(task_id,timestamp,state,step_index,attempt) SELECT task_id,?, ?,current_step,attempts FROM tasks WHERE task_id=?",
                    (stamp, new_state, task_id),
                )
                connection.execute("COMMIT")
                return self.get(task_id)
            except Exception:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                connection.close()

    def claim_next(self, executor_id: str, lease_seconds: int = 60,
                   now: datetime | None = None) -> TaskClaim | None:
        _text(executor_id, "executor_id", 128)
        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int) or not 5 <= lease_seconds <= 3600:
            raise TaskValidationError("lease_seconds must be between 5 and 3600")
        current = now or _now()
        stamp = _iso(current)
        lease_until = _iso(current + timedelta(seconds=lease_seconds))
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                rows = connection.execute(
                    """SELECT tasks.task_id,tasks.state,tasks.plan_json,tasks.current_step,
                    tasks.attempts,tasks.cancel_requested,task_owners.principal_id
                    FROM tasks LEFT JOIN task_owners ON task_owners.task_id=tasks.task_id
                    WHERE
                    (tasks.state IN ('queued','retry_wait') AND tasks.available_at<=?) OR
                    (tasks.state='running' AND tasks.lease_until<=?)
                    ORDER BY tasks.created_at LIMIT 32""",
                    (stamp, stamp),
                ).fetchall()
                for task_id, state, plan_json, index, attempts, cancel, principal_id in rows:
                    plan = json.loads(plan_json)
                    if cancel:
                        connection.execute(
                            "UPDATE tasks SET state='cancelled',updated_at=?,lease_owner=NULL,lease_until=NULL WHERE task_id=?",
                            (stamp, task_id),
                        )
                        connection.execute(
                            "INSERT INTO task_events(task_id,timestamp,state,step_index,attempt) VALUES(?,?,'cancelled',?,?)",
                            (task_id, stamp, index, attempts),
                        )
                        continue
                    if index >= len(plan):
                        connection.execute(
                            "UPDATE tasks SET state='succeeded',updated_at=?,lease_owner=NULL,lease_until=NULL WHERE task_id=?",
                            (stamp, task_id),
                        )
                        continue
                    if state == "running" and attempts >= plan[index]["max_attempts"]:
                        connection.execute(
                            "UPDATE tasks SET state='failed',error_code='lease_expired',updated_at=?,lease_owner=NULL,lease_until=NULL WHERE task_id=?",
                            (stamp, task_id),
                        )
                        connection.execute(
                            "INSERT INTO task_events(task_id,timestamp,state,step_index,attempt,error_code) VALUES(?,?,'failed',?,?,'lease_expired')",
                            (task_id, stamp, index, attempts),
                        )
                        continue
                    attempt = attempts + 1
                    connection.execute(
                        "UPDATE tasks SET state='running',attempts=?,lease_owner=?,lease_until=?,updated_at=? WHERE task_id=?",
                        (attempt, executor_id, lease_until, stamp, task_id),
                    )
                    connection.execute(
                        "INSERT INTO task_events(task_id,timestamp,state,step_index,attempt) VALUES(?,?,'running',?,?)",
                        (task_id, stamp, index, attempt),
                    )
                    step = plan[index]
                    connection.execute("COMMIT")
                    return TaskClaim(task_id, executor_id, index, attempt,
                                     f"{task_id}:{index}", step["tool"], step["input"],
                                     lease_until, principal_id)
                connection.execute("COMMIT")
                return None
            except Exception:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                connection.close()

    @staticmethod
    def _assert_claim_matches(
        claim: TaskClaim, row: tuple[Any, ...], stamp: str
    ) -> list[dict[str, Any]]:
        """Validate a claim against an authoritative row inside its write transaction."""
        if not isinstance(claim, TaskClaim):
            raise TaskValidationError("claim must be a TaskClaim")
        _text(claim.task_id, "task_id", 64)
        _text(claim.executor_id, "executor_id", 128)
        state, owner, until, index, attempt, plan_json, principal_id = row
        if type(claim.step_index) is not int or type(claim.attempt) is not int:
            raise TaskConflictError("task claim progress fields must be integers")
        if (
            state != "running"
            or owner != claim.executor_id
            or index != claim.step_index
            or attempt != claim.attempt
            or principal_id != claim.principal_id
        ):
            raise TaskConflictError("task claim does not match its authoritative lease")
        if _parse_time(until) <= _parse_time(stamp):
            raise TaskConflictError("task lease expired before the requested transition")
        try:
            plan = json.loads(plan_json)
        except (TypeError, ValueError, RecursionError):
            raise TaskValidationError("persisted task plan is corrupt") from None
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(plan):
            raise TaskConflictError("task claim step is outside the persisted plan")
        step = plan[index]
        if (
            claim.idempotency_key != f"{claim.task_id}:{index}"
            or claim.tool != step["tool"]
            or type(claim.input) is not dict
            or claim.input != step["input"]
        ):
            raise TaskConflictError("task claim payload differs from the persisted plan")
        return plan

    def renew_lease(self, claim: TaskClaim, lease_seconds: int = 60,
                    now: datetime | None = None) -> TaskClaim:
        """Extend a live claim before expiry; expired or superseded owners fail closed."""
        if not isinstance(claim, TaskClaim) or type(claim.input) is not dict:
            raise TaskValidationError("claim must contain a TaskClaim with object input")
        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int) or not 5 <= lease_seconds <= 3600:
            raise TaskValidationError("lease_seconds must be between 5 and 3600")
        _, input_snapshot = _json(claim.input, label="claim input")
        claim = TaskClaim(
            claim.task_id, claim.executor_id, claim.step_index, claim.attempt,
            claim.idempotency_key, claim.tool, input_snapshot, claim.lease_until,
            claim.principal_id,
        )
        current = now or _now()
        stamp = _iso(current)
        lease_until = _iso(current + timedelta(seconds=lease_seconds))
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """SELECT tasks.state,tasks.lease_owner,tasks.lease_until,
                    tasks.current_step,tasks.attempts,tasks.plan_json,
                    task_owners.principal_id
                    FROM tasks LEFT JOIN task_owners
                    ON task_owners.task_id=tasks.task_id WHERE tasks.task_id=?""",
                    (claim.task_id,),
                ).fetchone()
                if not row:
                    raise TaskNotFoundError("task does not exist")
                self._assert_claim_matches(claim, row, stamp)
                connection.execute(
                    "UPDATE tasks SET lease_until=?,updated_at=? WHERE task_id=?",
                    (lease_until, stamp, claim.task_id),
                )
                connection.execute("COMMIT")
                return TaskClaim(
                    claim.task_id, claim.executor_id, claim.step_index, claim.attempt,
                    claim.idempotency_key, claim.tool, input_snapshot, lease_until,
                    claim.principal_id,
                )
            except Exception:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                connection.close()

    def validate_claim(
        self, claim: TaskClaim, now: datetime | None = None
    ) -> None:
        """Verify every executable claim field against the authoritative SQLite row.

        TaskClaim is a transport object, not an authority source. A caller can
        construct or alter one, so worker dispatch must not trust its principal,
        tool, input, attempt, or lease metadata without checking the stored task.
        """
        if not isinstance(claim, TaskClaim):
            raise TaskValidationError("claim must be a TaskClaim")
        _text(claim.task_id, "task_id", 64)
        _text(claim.executor_id, "executor_id", 128)
        stamp = _iso(now or _now())
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute(
                    """SELECT tasks.state,tasks.lease_owner,tasks.lease_until,
                    tasks.current_step,tasks.attempts,tasks.plan_json,
                    task_owners.principal_id
                    FROM tasks LEFT JOIN task_owners
                    ON task_owners.task_id=tasks.task_id
                    WHERE tasks.task_id=?""",
                    (claim.task_id,),
                ).fetchone()
                if not row:
                    raise TaskNotFoundError("task does not exist")
                self._assert_claim_matches(claim, row, stamp)
            finally:
                connection.close()

    def finish_step(self, claim: TaskClaim, result: Any,
                    now: datetime | None = None) -> TaskRecord:
        if not isinstance(claim, TaskClaim):
            raise TaskValidationError("claim must be a TaskClaim")
        result_json, decoded = _json(result, label="step result")
        stamp = _iso(now or _now())
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """SELECT tasks.state,tasks.lease_owner,tasks.lease_until,
                    tasks.current_step,tasks.attempts,tasks.plan_json,
                    task_owners.principal_id,tasks.cancel_requested,tasks.results_json
                    FROM tasks LEFT JOIN task_owners
                    ON task_owners.task_id=tasks.task_id WHERE tasks.task_id=?""",
                    (claim.task_id,),
                ).fetchone()
                if not row:
                    raise TaskNotFoundError("task does not exist")
                plan = self._assert_claim_matches(claim, row[:7], stamp)
                cancel, results_json = row[7], row[8]
                index = claim.step_index
                results = json.loads(results_json)
                results.append(decoded)
                next_index = index + 1
                if cancel:
                    next_state = "cancelled"
                elif next_index >= len(plan):
                    next_state = "succeeded"
                else:
                    next_state = "queued"
                connection.execute(
                    """UPDATE tasks SET state=?,current_step=?,attempts=0,results_json=?,updated_at=?,
                    available_at=?,lease_owner=NULL,lease_until=NULL,error_code=NULL WHERE task_id=?""",
                    (next_state, next_index, json.dumps(results, ensure_ascii=False, allow_nan=False,
                     sort_keys=True, separators=(",", ":")), stamp, stamp, claim.task_id),
                )
                connection.execute(
                    "INSERT INTO task_events(task_id,timestamp,state,step_index,attempt) VALUES(?,?,?,?,?)",
                    (claim.task_id, stamp, next_state, index, claim.attempt),
                )
                connection.execute("COMMIT")
                return self.get(claim.task_id)
            except Exception:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                connection.close()

    def fail_step(self, claim: TaskClaim, error_code: str = "handler_failed",
                  retry_delay_seconds: int = 5, now: datetime | None = None,
                  retryable: bool = True) -> TaskRecord:
        if not isinstance(claim, TaskClaim):
            raise TaskValidationError("claim must be a TaskClaim")
        _text(error_code, "error_code", 64)
        if not error_code.replace("_", "").isalnum():
            raise TaskValidationError("error_code must be a simple identifier")
        if isinstance(retry_delay_seconds, bool) or not isinstance(retry_delay_seconds, int) or not 0 <= retry_delay_seconds <= 3600:
            raise TaskValidationError("retry_delay_seconds must be between 0 and 3600")
        current = now or _now()
        stamp = _iso(current)
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """SELECT tasks.state,tasks.lease_owner,tasks.lease_until,
                    tasks.current_step,tasks.attempts,tasks.plan_json,
                    task_owners.principal_id,tasks.cancel_requested
                    FROM tasks LEFT JOIN task_owners
                    ON task_owners.task_id=tasks.task_id WHERE tasks.task_id=?""",
                    (claim.task_id,),
                ).fetchone()
                if not row:
                    raise TaskNotFoundError("task does not exist")
                plan = self._assert_claim_matches(claim, row[:7], stamp)
                index = claim.step_index
                cancel = row[7]
                retry = retryable and not cancel and claim.attempt < plan[index]["max_attempts"]
                next_state = "cancelled" if cancel else ("retry_wait" if retry else "failed")
                delay = min(retry_delay_seconds * (2 ** max(0, claim.attempt - 1)), 3600)
                available = _iso(current + timedelta(seconds=delay)) if retry else stamp
                connection.execute(
                    """UPDATE tasks SET state=?,error_code=?,updated_at=?,available_at=?,
                    lease_owner=NULL,lease_until=NULL WHERE task_id=?""",
                    (next_state, error_code, stamp, available, claim.task_id),
                )
                connection.execute(
                    "INSERT INTO task_events(task_id,timestamp,state,step_index,attempt,error_code) VALUES(?,?,?,?,?,?)",
                    (claim.task_id, stamp, next_state, index, claim.attempt, error_code),
                )
                connection.execute("COMMIT")
                return self.get(claim.task_id)
            except Exception:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                connection.close()

    def events(self, task_id: str) -> tuple[dict[str, Any], ...]:
        self.get(task_id)
        with self._lock:
            connection = self._connect()
            try:
                rows = connection.execute(
                    "SELECT timestamp,state,step_index,attempt,error_code FROM task_events WHERE task_id=? ORDER BY event_id",
                    (task_id,),
                ).fetchall()
                return tuple(dict(zip(("timestamp","state","step_index","attempt","error_code"), row)) for row in rows)
            finally:
                connection.close()

    def _validate_backup_snapshot(self, connection: sqlite3.Connection) -> None:
        allowed_states = {"queued", "running", "retry_wait", "succeeded", "failed", "cancelled"}
        rows = connection.execute(
            """SELECT task_id,idempotency_key,state,created_at,updated_at,current_step,
            attempts,available_at,cancel_requested,results_json,error_code,plan_json
            FROM tasks"""
        ).fetchall()
        task_plan_lengths = {}
        for row in rows:
            self._record(row[:11])
            _text(row[0], "task_id", 64)
            if row[1] is not None:
                _text(row[1], "idempotency_key", 128)
            for timestamp in (row[3], row[4], row[7]):
                _text(timestamp, "task timestamp", 64)
                _parse_time(timestamp)
            if row[8] not in (0, 1):
                raise TaskValidationError("backup contains invalid cancellation state")
            if row[10] is not None:
                _text(row[10], "task error_code", 64)
            if row[2] not in allowed_states:
                raise TaskValidationError("backup contains an unsupported task state")
            try:
                plan = json.loads(row[11])
            except (TypeError, ValueError, RecursionError):
                raise TaskValidationError("backup contains a malformed task plan") from None
            _validate_plan(plan)
            task_plan_lengths[row[0]] = len(plan)
            if (
                isinstance(row[5], bool) or not isinstance(row[5], int)
                or not 0 <= row[5] <= len(plan)
                or isinstance(row[6], bool) or not isinstance(row[6], int)
                or row[6] < 0
            ):
                raise TaskValidationError("backup contains invalid task progress")
        owners = connection.execute(
            "SELECT task_id,principal_id FROM task_owners"
        ).fetchall()
        for task_id, principal_id in owners:
            _text(task_id, "task owner task_id", 64)
            _text(principal_id, "task owner principal_id", 128)
            if task_id not in task_plan_lengths:
                raise TaskValidationError("backup contains an owner for a missing task")
        events = connection.execute(
            "SELECT task_id,timestamp,state,step_index,attempt,error_code FROM task_events"
        ).fetchall()
        for task_id, timestamp, state, step_index, attempt, error_code in events:
            _text(task_id, "task_id", 64)
            _text(timestamp, "event timestamp", 64)
            _parse_time(timestamp)
            if state not in allowed_states:
                raise TaskValidationError("backup contains an unsupported task event state")
            if (
                isinstance(step_index, bool) or not isinstance(step_index, int)
                or not 0 <= step_index <= task_plan_lengths.get(task_id, -1)
                or isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 0
            ):
                raise TaskValidationError("backup contains invalid task event progress")
            if error_code is not None:
                _text(error_code, "event error_code", 64)

    def backup_to(self, destination_path: str) -> str:
        """Create a private, consistent task-state snapshot without overwriting."""
        return backup_sqlite_database(
            self.path,
            destination_path,
            lock=self._lock,
            connect=self._connect,
            validate_snapshot=self._validate_backup_snapshot,
            error_type=TaskValidationError,
            prefix=".capri-task-backup-",
        )

    def integrity_check(self) -> str:
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute("PRAGMA integrity_check").fetchone()
                foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
                if not row:
                    return "no result"
                if row[0] != "ok":
                    return str(row[0])
                if foreign_key_errors:
                    return "foreign key check failed"
                return "ok"
            finally:
                connection.close()


class TaskEngine:
    """Run one claimed task step per call; hosts own scheduling and worker lifecycle.

    Legacy unowned tasks use handlers(input_dict, stable_idempotency_key).
    Principal-owned tasks require principal_handlers(
    input_dict, stable_idempotency_key, principal_id) and never fall back to the
    legacy map. Both handler classes must be trusted host code, enforce current
    resource authorization, and make side effects idempotent with the key.
    Model-proposed tool calls must still pass through ToolExecutor and host policy.
    """

    def __init__(
        self, store: SQLiteTaskStore,
        handlers: Mapping[str, Callable[[dict[str, Any], str], Any]],
        executor_id: str, lease_seconds: int = 60,
        *,
        principal_handlers: Mapping[str, Callable[[dict[str, Any], str, str], Any]] | None = None,
    ) -> None:
        if not isinstance(store, SQLiteTaskStore):
            raise TaskValidationError("store must be a SQLiteTaskStore")
        _text(executor_id, "executor_id", 128)
        if not isinstance(handlers, Mapping) or len(handlers) > 128:
            raise TaskValidationError("handlers must be a bounded mapping")
        copied = {}
        for name, handler in handlers.items():
            _text(name, "handler name", 64)
            if not callable(handler):
                raise TaskValidationError("every handler must be callable")
            copied[name] = handler
        if principal_handlers is None:
            principal_handlers = {}
        if not isinstance(principal_handlers, Mapping) or len(principal_handlers) > 128:
            raise TaskValidationError("principal_handlers must be a bounded mapping")
        principal_copied = {}
        for name, handler in principal_handlers.items():
            _text(name, "principal handler name", 64)
            if not callable(handler):
                raise TaskValidationError("every principal handler must be callable")
            principal_copied[name] = handler
        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int) or not 5 <= lease_seconds <= 3600:
            raise TaskValidationError("lease_seconds must be between 5 and 3600")
        self.store = store
        self.handlers = copied
        self.principal_handlers = principal_copied
        self.executor_id = executor_id
        self.lease_seconds = lease_seconds

    def execute_claim(self, claim: TaskClaim, now: datetime | None = None) -> TaskRecord:
        if not isinstance(claim, TaskClaim) or claim.executor_id != self.executor_id:
            raise TaskConflictError("claim does not belong to this task engine")
        # TaskClaim is frozen, but its nested input dictionary is not. Snapshot
        # the JSON payload before validation so a caller cannot mutate it between
        # the authoritative check and handler dispatch.
        if type(claim.input) is not dict:
            raise TaskConflictError("task claim input is not an object")
        _, input_snapshot = _json(claim.input, label="claim input")
        if not isinstance(input_snapshot, dict):
            raise TaskConflictError("task claim input is not an object")
        claim = TaskClaim(
            claim.task_id, claim.executor_id, claim.step_index, claim.attempt,
            claim.idempotency_key, claim.tool, input_snapshot, claim.lease_until,
            claim.principal_id,
        )
        self.store.validate_claim(claim, now=now)
        # Handlers are trusted host code, but must not mutate the validated claim
        # through nested references shared by a shallow dict copy.
        handler_input = _json(claim.input, label="handler input")[1]
        if claim.principal_id is None:
            handler = self.handlers.get(claim.tool)
            if handler is None:
                return self.store.fail_step(
                    claim, "unknown_handler", retry_delay_seconds=0, now=now, retryable=False
                )
            invoke = lambda: handler(handler_input, claim.idempotency_key)
        else:
            handler = self.principal_handlers.get(claim.tool)
            if handler is None:
                return self.store.fail_step(
                    claim, "principal_handler_required", retry_delay_seconds=0,
                    now=now, retryable=False,
                )
            invoke = lambda: handler(
                handler_input, claim.idempotency_key, claim.principal_id
            )
        try:
            result = invoke()
            _json(result, label="handler result")
        except Exception:
            return self.store.fail_step(claim, "handler_failed", now=now)
        return self.store.finish_step(claim, result, now=now)

    def run_once(self, now: datetime | None = None) -> TaskRecord | None:
        claim = self.store.claim_next(self.executor_id, self.lease_seconds, now)
        if claim is None:
            return None
        return self.execute_claim(claim, now=now)


class TaskWorker:
    """Explicit host-managed polling worker with a concurrent lease heartbeat.

    Constructing a worker starts no threads. The host calls run_once() or
    run_forever(stop_event) and owns process lifecycle and shutdown.
    """

    def __init__(self, engine: TaskEngine, poll_interval_seconds: float = 1.0,
                 heartbeat_interval_seconds: float = 10.0) -> None:
        if not isinstance(engine, TaskEngine):
            raise TaskValidationError("engine must be a TaskEngine")
        if (isinstance(poll_interval_seconds, bool)
                or not isinstance(poll_interval_seconds, (int, float))
                or not 0.05 <= poll_interval_seconds <= 60):
            raise TaskValidationError("poll interval must be between 0.05 and 60 seconds")
        if (isinstance(heartbeat_interval_seconds, bool)
                or not isinstance(heartbeat_interval_seconds, (int, float))
                or not 0.05 <= heartbeat_interval_seconds < engine.lease_seconds):
            raise TaskValidationError("heartbeat interval must be positive and shorter than the lease")
        self.engine = engine
        self.poll_interval_seconds = float(poll_interval_seconds)
        self.heartbeat_interval_seconds = float(heartbeat_interval_seconds)

    def run_once(self) -> TaskRecord | None:
        engine = self.engine
        claim = engine.store.claim_next(engine.executor_id, engine.lease_seconds)
        if claim is None:
            return None
        heartbeat_stop = threading.Event()

        def heartbeat() -> None:
            while not heartbeat_stop.wait(self.heartbeat_interval_seconds):
                try:
                    engine.store.renew_lease(claim, engine.lease_seconds)
                except Exception:
                    # Completion will fail closed if the lease was lost or expired.
                    return

        thread = threading.Thread(target=heartbeat, name="capri-task-lease-heartbeat", daemon=True)
        thread.start()
        try:
            return engine.execute_claim(claim)
        finally:
            heartbeat_stop.set()
            thread.join(timeout=max(1.0, self.heartbeat_interval_seconds * 2))

    def run_forever(self, stop_event: threading.Event) -> None:
        if not callable(getattr(stop_event, "is_set", None)) or not callable(
            getattr(stop_event, "wait", None)
        ):
            raise TaskValidationError("stop_event must provide is_set() and wait()")
        while not stop_event.is_set():
            result = self.run_once()
            if result is None:
                stop_event.wait(self.poll_interval_seconds)
