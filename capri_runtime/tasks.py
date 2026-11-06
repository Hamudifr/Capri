"""Durable, bounded task orchestration with leases and at-least-once recovery.

This module is an orchestration primitive, not a model, sandbox, scheduler daemon,
or permission system. Hosts inject trusted handlers; model-originated side effects
must still pass through the permissioned ToolExecutor boundary.
"""
from __future__ import annotations

import json
import os
import sqlite3
import stat
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping
from uuid import uuid4


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


def _json(value: Any, *, label: str, limit: int = 65_536) -> tuple[str, Any]:
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
                connection.execute("CREATE INDEX IF NOT EXISTS task_ready_idx ON tasks(state, available_at, created_at)")
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
                        if existing[11] != plan_json:
                            raise TaskIdempotencyConflict("idempotency key already identifies a different plan")
                        connection.execute("COMMIT")
                        return self._record(existing[:11])
                connection.execute(
                    """INSERT INTO tasks(task_id,idempotency_key,state,plan_json,current_step,attempts,
                    created_at,updated_at,available_at) VALUES(?,?,'queued',?,0,0,?,?,?)""",
                    (task_id, idempotency_key, plan_json, stamp, stamp, stamp),
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
                    """SELECT task_id,state,plan_json,current_step,attempts,cancel_requested
                    FROM tasks WHERE
                    (state IN ('queued','retry_wait') AND available_at<=?) OR
                    (state='running' AND lease_until<=?)
                    ORDER BY created_at LIMIT 32""",
                    (stamp, stamp),
                ).fetchall()
                for task_id, state, plan_json, index, attempts, cancel in rows:
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
                                     f"{task_id}:{index}", step["tool"], step["input"], lease_until)
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

    def finish_step(self, claim: TaskClaim, result: Any,
                    now: datetime | None = None) -> TaskRecord:
        result_json, decoded = _json(result, label="step result")
        stamp = _iso(now or _now())
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT state,lease_owner,lease_until,current_step,cancel_requested,results_json,plan_json FROM tasks WHERE task_id=?",
                    (claim.task_id,),
                ).fetchone()
                if not row:
                    raise TaskNotFoundError("task does not exist")
                state, owner, until, index, cancel, results_json, plan_json = row
                if state != "running" or owner != claim.executor_id or index != claim.step_index:
                    raise TaskConflictError("task lease is no longer owned by this executor")
                if _parse_time(until) <= _parse_time(stamp):
                    raise TaskConflictError("task lease expired before completion was recorded")
                results = json.loads(results_json)
                results.append(decoded)
                next_index = index + 1
                plan = json.loads(plan_json)
                if cancel:
                    next_state = "cancelled"
                elif next_index >= len(plan):
                    next_state = "succeeded"
                else:
                    next_state = "queued"
                connection.execute(
                    """UPDATE tasks SET state=?,current_step=?,attempts=0,results_json=?,updated_at=?,
                    available_at=?,lease_owner=NULL,lease_until=NULL WHERE task_id=?""",
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
                    "SELECT state,lease_owner,lease_until,current_step,plan_json FROM tasks WHERE task_id=?",
                    (claim.task_id,),
                ).fetchone()
                if not row:
                    raise TaskNotFoundError("task does not exist")
                state, owner, until, index, plan_json = row
                if state != "running" or owner != claim.executor_id or index != claim.step_index:
                    raise TaskConflictError("task lease is no longer owned by this executor")
                if _parse_time(until) <= _parse_time(stamp):
                    raise TaskConflictError("task lease expired before failure was recorded")
                plan = json.loads(plan_json)
                retry = retryable and claim.attempt < plan[index]["max_attempts"]
                next_state = "retry_wait" if retry else "failed"
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

    def integrity_check(self) -> str:
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute("PRAGMA integrity_check").fetchone()
                return str(row[0]) if row else "no result"
            finally:
                connection.close()


class TaskEngine:
    """Run one claimed task step per call; hosts own scheduling and worker lifecycle.

    Handlers receive (input_dict, stable_idempotency_key). They must be trusted
    host code and must make side effects idempotent with that key. Model-proposed
    calls must still be routed through ToolExecutor and host authorization.
    """

    def __init__(self, store: SQLiteTaskStore,
                 handlers: Mapping[str, Callable[[dict[str, Any], str], Any]],
                 executor_id: str, lease_seconds: int = 60) -> None:
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
        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int) or not 5 <= lease_seconds <= 3600:
            raise TaskValidationError("lease_seconds must be between 5 and 3600")
        self.store = store
        self.handlers = copied
        self.executor_id = executor_id
        self.lease_seconds = lease_seconds

    def run_once(self, now: datetime | None = None) -> TaskRecord | None:
        claim = self.store.claim_next(self.executor_id, self.lease_seconds, now)
        if claim is None:
            return None
        handler = self.handlers.get(claim.tool)
        if handler is None:
            return self.store.fail_step(claim, "unknown_handler", retry_delay_seconds=0, now=now, retryable=False)
        try:
            result = handler(dict(claim.input), claim.idempotency_key)
            _json(result, label="handler result")
        except Exception:
            return self.store.fail_step(claim, "handler_failed", now=now)
        return self.store.finish_step(claim, result, now=now)
