"""Durable, principal-scoped goal contracts and a data-only planner protocol.

Planning proposes data. It never grants permission or invokes tools. A trusted host
must validate a proposal against its current handler allowlist before task creation.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from capri_core.validation import contains_surrogate
from .sqlite_backup import backup_sqlite_database
from .domain_events import DomainEvent, goal_event, project_domain_events


class GoalError(Exception):
    """Base class for expected goal-store failures."""


class GoalValidationError(GoalError):
    """A goal contract or persisted goal value is invalid."""


class GoalNotFoundError(GoalError):
    """The goal does not exist or is not owned by the authenticated principal."""


class GoalConflictError(GoalError):
    """The goal changed or its requested lifecycle transition is invalid."""


class GoalIdempotencyConflict(GoalError):
    """An idempotency key was reused for a different goal contract."""


_GOAL_STATES = {
    "accepted", "planning", "planned", "running", "paused", "cancelling",
    "awaiting_verification", "succeeded", "failed", "cancelled", "reconciliation_required",
}
_TRANSITIONS = {
    "accepted": {"planning", "cancelled"},
    "planning": {"planned", "paused", "failed", "cancelled"},
    "planned": {"running", "paused", "cancelled"},
    "running": {"paused", "awaiting_verification", "failed", "cancelled", "cancelling", "reconciliation_required"},
    "paused": {"planning", "planned", "running", "cancelled"},
    "cancelling": {"cancelled", "reconciliation_required", "failed", "awaiting_verification"},
    "awaiting_verification": {"succeeded", "failed", "cancelled", "reconciliation_required"},
    "reconciliation_required": {"running", "failed", "cancelled"},
    "succeeded": set(), "failed": set(), "cancelled": set(),
}


def _text(value: Any, label: str, limit: int) -> str:
    if type(value) is not str or not value.strip() or len(value) > limit or contains_surrogate(value):
        raise GoalValidationError(f"{label} is invalid")
    return value


def _json_object(value: Any, label: str, limit: int = 16_384) -> tuple[str, dict[str, Any]]:
    if type(value) is not dict:
        raise GoalValidationError(f"{label} must be a plain JSON object")
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True,
            separators=(",", ":"),
        )
        raw = encoded.encode("utf-8", errors="strict")
        decoded = json.loads(encoded)
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        raise GoalValidationError(f"{label} must be valid JSON") from None
    if len(raw) > limit:
        raise GoalValidationError(f"{label} exceeds the configured byte limit")
    return encoded, decoded


def _json_value(value: Any, depth: int = 0) -> None:
    if depth > 12:
        raise GoalValidationError("goal JSON nesting exceeds 12 levels")
    if value is None or type(value) in (bool, int, float):
        if type(value) is float and (value != value or value in (float("inf"), float("-inf"))):
            raise GoalValidationError("goal JSON numbers must be finite")
        return
    if type(value) is str:
        if contains_surrogate(value):
            raise GoalValidationError("goal JSON strings must contain Unicode scalar values")
        return
    if type(value) is list:
        for item in value:
            _json_value(item, depth + 1)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise GoalValidationError("goal JSON object keys must be strings")
            _json_value(key, depth + 1)
            _json_value(item, depth + 1)
        return
    raise GoalValidationError("goal contains a non-JSON value")


def _criteria(value: Any) -> tuple[str, ...]:
    if type(value) not in (list, tuple) or not 1 <= len(value) <= 32:
        raise GoalValidationError("acceptance_criteria must contain 1 to 32 items")
    result = []
    for item in value:
        result.append(_text(item, "acceptance criterion", 500))
    if len(set(result)) != len(result):
        raise GoalValidationError("acceptance_criteria must not contain duplicates")
    return tuple(result)


def _deadline(value: Any) -> str | None:
    if value is None:
        return None
    if type(value) is not str or len(value) > 64:
        raise GoalValidationError("deadline must be an ISO-8601 timestamp or null")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise GoalValidationError("deadline must be an ISO-8601 timestamp or null") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GoalValidationError("deadline must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class GoalRecord:
    goal_id: str
    principal_id: str
    outcome: str
    constraints: dict[str, Any]
    deadline: str | None
    acceptance_criteria: tuple[str, ...]
    state: str
    version: int
    created_at: str
    updated_at: str
    plan: tuple[dict[str, Any], ...] = ()
    task_id: str | None = None
    evidence: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class GoalPlanProposal:
    """Untrusted, data-only planner output. It is not an execution capability."""

    steps: tuple[dict[str, Any], ...]
    rationale: str = ""


@runtime_checkable
class GoalPlanner(Protocol):
    """A host-injected planner. Implementations must return data, never execute tools."""

    def propose(self, goal: GoalRecord) -> GoalPlanProposal:
        """Return a bounded candidate plan for host validation."""


def validate_goal_plan(
    proposal: Any, allowed_tools: frozenset[str]
) -> tuple[dict[str, Any], ...]:
    if type(proposal) is not GoalPlanProposal:
        raise GoalValidationError("planner must return a GoalPlanProposal")
    if type(allowed_tools) is not frozenset or len(allowed_tools) > 128:
        raise GoalValidationError("allowed_tools must be a bounded frozenset")
    for name in allowed_tools:
        _text(name, "allowed tool name", 64)
    if type(proposal.steps) is not tuple or not 1 <= len(proposal.steps) <= 32:
        raise GoalValidationError("planner steps must contain 1 to 32 items")
    _text(proposal.rationale, "planner rationale", 2_000) if proposal.rationale else None
    normalized = []
    for index, step in enumerate(proposal.steps):
        if type(step) is not dict or set(step) - {"tool", "input", "max_attempts"}:
            raise GoalValidationError(f"planner step {index} has unsupported fields")
        tool = _text(step.get("tool"), f"planner step {index} tool", 64)
        if tool not in allowed_tools:
            raise GoalValidationError(f"planner step {index} references an unavailable tool")
        args = step.get("input", {})
        _json_value(args)
        if type(args) is not dict:
            raise GoalValidationError(f"planner step {index} input must be an object")
        _json_object(args, f"planner step {index} input")
        attempts = step.get("max_attempts", 3)
        if type(attempts) is not int or not 1 <= attempts <= 10:
            raise GoalValidationError(f"planner step {index} max_attempts is invalid")
        normalized.append({"tool": tool, "input": json.loads(json.dumps(args)), "max_attempts": attempts})
    try:
        encoded_plan = json.dumps(
            normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        raise GoalValidationError("planner output is not valid bounded JSON") from None
    if len(encoded_plan) > 65_536:
        raise GoalValidationError("planner output exceeds the 65,536-byte plan limit")
    return tuple(normalized)


def _stamp(value: datetime | None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise GoalValidationError("timestamps must be timezone-aware")
    return current.astimezone(timezone.utc).isoformat()


class SQLiteGoalStore:
    """Private SQLite goal records with immutable principal ownership and CAS transitions."""

    def __init__(self, path: str) -> None:
        _text(path, "database path", 4096)
        absolute = os.path.abspath(path)
        parent = os.path.dirname(absolute)
        if not os.path.isdir(parent) or os.path.realpath(parent) != parent:
            raise GoalValidationError("database parent must be an existing non-symlink directory")
        parent_stat = os.stat(parent, follow_symlinks=False)
        if not stat.S_ISDIR(parent_stat.st_mode):
            raise GoalValidationError("database parent must be a directory")
        if os.name == "posix" and (
            parent_stat.st_uid != os.geteuid() or stat.S_IMODE(parent_stat.st_mode) & 0o077
        ):
            raise GoalValidationError("database parent must be owned by the current user and private")
        if os.path.lexists(absolute):
            existing = os.lstat(absolute)
            if not stat.S_ISREG(existing.st_mode):
                raise GoalValidationError("database path must be a regular non-symlink file")
            if os.name == "posix" and (existing.st_uid != os.geteuid() or existing.st_nlink != 1):
                raise GoalValidationError("database ownership or link count is unsafe")
        try:
            descriptor = os.open(absolute, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        except OSError:
            raise GoalValidationError("database file could not be opened safely") from None
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise GoalValidationError("database path must be a regular file")
            if os.name == "posix":
                if opened.st_uid != os.geteuid() or opened.st_nlink != 1:
                    raise GoalValidationError("database ownership or link count is unsafe")
                os.fchmod(descriptor, 0o600)
        finally:
            os.close(descriptor)
        self.path = absolute
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        parent = os.path.dirname(self.path)
        if os.path.realpath(parent) != parent:
            raise GoalValidationError("database parent changed")
        if os.name == "posix":
            info = os.lstat(self.path)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077):
                raise GoalValidationError("database file identity changed")
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("""CREATE TABLE IF NOT EXISTS goals (
                    goal_id TEXT PRIMARY KEY,
                    idempotency_key TEXT UNIQUE,
                    outcome TEXT NOT NULL,
                    constraints_json TEXT NOT NULL,
                    deadline TEXT,
                    criteria_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    plan_json TEXT NOT NULL DEFAULT '[]'
                )""")
                connection.execute("""CREATE TABLE IF NOT EXISTS goal_owners (
                    goal_id TEXT PRIMARY KEY REFERENCES goals(goal_id) ON DELETE RESTRICT,
                    principal_id TEXT NOT NULL
                )""")
                connection.execute("""CREATE TABLE IF NOT EXISTS goal_task_links (
                    goal_id TEXT PRIMARY KEY REFERENCES goals(goal_id) ON DELETE RESTRICT,
                    task_id TEXT NOT NULL UNIQUE,
                    principal_id TEXT NOT NULL,
                    linked_at TEXT NOT NULL
                )""")
                connection.execute("""CREATE TABLE IF NOT EXISTS goal_evidence (
                    evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    goal_id TEXT NOT NULL REFERENCES goals(goal_id) ON DELETE RESTRICT,
                    principal_id TEXT NOT NULL,
                    evidence_type TEXT NOT NULL,
                    reference TEXT NOT NULL,
                    step_index INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(goal_id,evidence_type,reference,step_index)
                )""")
                connection.execute("""CREATE TABLE IF NOT EXISTS goal_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    goal_id TEXT NOT NULL REFERENCES goals(goal_id),
                    timestamp TEXT NOT NULL,
                    state TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    event_type TEXT NOT NULL
                )""")
                connection.execute("""CREATE TRIGGER IF NOT EXISTS goal_task_link_immutable_update
                    BEFORE UPDATE ON goal_task_links
                    BEGIN SELECT RAISE(ABORT, 'goal task links are immutable'); END""")
                connection.execute("""CREATE TRIGGER IF NOT EXISTS goal_task_link_immutable_delete
                    BEFORE DELETE ON goal_task_links
                    BEGIN SELECT RAISE(ABORT, 'goal task links are immutable'); END""")
                connection.execute("""CREATE TRIGGER IF NOT EXISTS goal_task_link_immutable_insert
                    BEFORE INSERT ON goal_task_links
                    WHEN EXISTS (SELECT 1 FROM goal_task_links WHERE goal_id=NEW.goal_id OR task_id=NEW.task_id)
                    BEGIN SELECT RAISE(ABORT, 'goal task links are immutable'); END""")
                connection.execute("""CREATE TRIGGER IF NOT EXISTS goal_evidence_immutable_update
                    BEFORE UPDATE ON goal_evidence
                    BEGIN SELECT RAISE(ABORT, 'goal evidence is append-only'); END""")
                connection.execute("""CREATE TRIGGER IF NOT EXISTS goal_evidence_immutable_delete
                    BEFORE DELETE ON goal_evidence
                    BEGIN SELECT RAISE(ABORT, 'goal evidence is append-only'); END""")
                connection.execute("""CREATE TRIGGER IF NOT EXISTS goal_event_immutable_update
                    BEFORE UPDATE ON goal_events
                    BEGIN SELECT RAISE(ABORT, 'goal events are append-only'); END""")
                connection.execute("""CREATE TRIGGER IF NOT EXISTS goal_event_immutable_delete
                    BEFORE DELETE ON goal_events
                    BEGIN SELECT RAISE(ABORT, 'goal events are append-only'); END""")
                connection.execute("""CREATE TRIGGER IF NOT EXISTS goal_owner_immutable_update
                    BEFORE UPDATE ON goal_owners
                    BEGIN SELECT RAISE(ABORT, 'goal ownership is immutable'); END""")
                connection.execute("""CREATE TRIGGER IF NOT EXISTS goal_owner_immutable_delete
                    BEFORE DELETE ON goal_owners
                    BEGIN SELECT RAISE(ABORT, 'goal ownership is immutable'); END""")
                connection.execute("""CREATE TRIGGER IF NOT EXISTS goal_owner_immutable_insert
                    BEFORE INSERT ON goal_owners
                    WHEN EXISTS (SELECT 1 FROM goal_owners WHERE goal_id=NEW.goal_id)
                    BEGIN SELECT RAISE(ABORT, 'goal ownership is immutable'); END""")
                connection.execute("CREATE INDEX IF NOT EXISTS goal_owner_principal_idx ON goal_owners(principal_id, goal_id)")
            finally:
                connection.close()

    @staticmethod
    def _record(
        row: tuple[Any, ...], principal_id: str, task_id: str | None = None,
        evidence: tuple[dict[str, Any], ...] = (),
    ) -> GoalRecord:
        try:
            constraints = json.loads(row[2])
            criteria = json.loads(row[4])
            plan = json.loads(row[9])
            if type(constraints) is not dict or type(criteria) is not list or type(plan) is not list:
                raise ValueError
            if row[5] not in _GOAL_STATES or type(row[6]) is not int or row[6] < 1:
                raise ValueError
            _json_value(constraints)
            checked_criteria = _criteria(criteria)
            for step in plan:
                if type(step) is not dict:
                    raise ValueError
                _json_value(step)
        except (TypeError, ValueError, GoalValidationError):
            raise GoalValidationError("persisted goal record is corrupt") from None
        return GoalRecord(
            row[0], principal_id, row[1], constraints, row[3], checked_criteria,
            row[5], row[6], row[7], row[8], tuple(plan), task_id, evidence,
        )

    def create_for_principal(
        self, principal_id: str, outcome: str, *,
        constraints: dict[str, Any] | None = None,
        deadline: str | None = None,
        acceptance_criteria: list[str] | tuple[str, ...],
        idempotency_key: str | None = None,
        now: datetime | None = None,
    ) -> GoalRecord:
        principal_id = _text(principal_id, "principal_id", 128)
        outcome = _text(outcome, "outcome", 4_000)
        constraints = {} if constraints is None else constraints
        _json_value(constraints)
        constraints_json, constraints = _json_object(constraints, "constraints")
        criteria = _criteria(acceptance_criteria)
        criteria_json = json.dumps(criteria, ensure_ascii=False, separators=(",", ":"))
        deadline = _deadline(deadline)
        scoped_key = None
        if idempotency_key is not None:
            key = _text(idempotency_key, "idempotency_key", 128)
            scoped_key = "principal:" + hashlib.sha256(
                (principal_id + "\0" + key).encode("utf-8")
            ).hexdigest()
        stamp = _stamp(now)
        goal_id = str(uuid4())
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                if scoped_key is not None:
                    existing = connection.execute(
                        "SELECT goal_id,outcome,constraints_json,deadline,criteria_json FROM goals WHERE idempotency_key=?",
                        (scoped_key,),
                    ).fetchone()
                    if existing:
                        if existing[1:] != (outcome, constraints_json, deadline, criteria_json):
                            raise GoalIdempotencyConflict("idempotency key identifies a different goal contract")
                        owner = connection.execute(
                            "SELECT principal_id FROM goal_owners WHERE goal_id=?", (existing[0],)
                        ).fetchone()
                        if not owner or owner[0] != principal_id:
                            raise GoalIdempotencyConflict("idempotency key is bound to another owner")
                        connection.execute("COMMIT")
                        return self.get_for_principal(existing[0], principal_id)
                connection.execute(
                    """INSERT INTO goals(goal_id,idempotency_key,outcome,constraints_json,deadline,
                    criteria_json,state,version,created_at,updated_at) VALUES(?,?,?,?,?,?,'accepted',1,?,?)""",
                    (goal_id, scoped_key, outcome, constraints_json, deadline, criteria_json, stamp, stamp),
                )
                connection.execute(
                    "INSERT INTO goal_owners(goal_id,principal_id) VALUES(?,?)",
                    (goal_id, principal_id),
                )
                connection.execute(
                    "INSERT INTO goal_events(goal_id,timestamp,state,version,event_type) VALUES(?,?,'accepted',1,'created')",
                    (goal_id, stamp),
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
        return self.get_for_principal(goal_id, principal_id)

    def _owned_row(self, goal_id: str, principal_id: str) -> tuple[Any, ...]:
        _text(goal_id, "goal_id", 64)
        principal_id = _text(principal_id, "principal_id", 128)
        connection = self._connect()
        try:
            row = connection.execute(
                """SELECT g.goal_id,g.outcome,g.constraints_json,g.deadline,g.criteria_json,
                g.state,g.version,g.created_at,g.updated_at,g.plan_json,o.principal_id,l.task_id
                FROM goals g JOIN goal_owners o ON o.goal_id=g.goal_id
                LEFT JOIN goal_task_links l ON l.goal_id=g.goal_id
                WHERE g.goal_id=? AND o.principal_id=?""",
                (goal_id, principal_id),
            ).fetchone()
            if row is None:
                raise GoalNotFoundError("goal does not exist")
            return row
        finally:
            connection.close()

    def get_for_principal(self, goal_id: str, principal_id: str) -> GoalRecord:
        with self._lock:
            row = self._owned_row(goal_id, principal_id)
            evidence = self._evidence_rows(goal_id, principal_id)
            return self._record(row[:10], row[10], row[11], evidence)

    def save_plan_for_principal(
        self, goal_id: str, principal_id: str, proposal: GoalPlanProposal,
        allowed_tools: frozenset[str], *, expected_version: int,
        now: datetime | None = None,
    ) -> GoalRecord:
        steps = validate_goal_plan(proposal, allowed_tools)
        if type(expected_version) is not int or expected_version < 1:
            raise GoalValidationError("expected_version must be a positive integer")
        plan_json = json.dumps(steps, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        stamp = _stamp(now)
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """SELECT g.state,g.version FROM goals g JOIN goal_owners o ON o.goal_id=g.goal_id
                    WHERE g.goal_id=? AND o.principal_id=?""",
                    (goal_id, principal_id),
                ).fetchone()
                if row is None:
                    raise GoalNotFoundError("goal does not exist")
                if row[1] != expected_version:
                    raise GoalConflictError("goal version changed")
                if row[0] not in {"accepted", "planning", "paused"}:
                    raise GoalConflictError("goal cannot accept a plan in its current state")
                connection.execute(
                    """UPDATE goals SET plan_json=?,state='planned',version=version+1,updated_at=?
                    WHERE goal_id=? AND version=?""",
                    (plan_json, stamp, goal_id, expected_version),
                )
                connection.execute(
                    "INSERT INTO goal_events(goal_id,timestamp,state,version,event_type) VALUES(?,?,'planned',?,'plan_saved')",
                    (goal_id, stamp, expected_version + 1),
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
        return self.get_for_principal(goal_id, principal_id)

    def transition_for_principal(
        self, goal_id: str, principal_id: str, new_state: str, *,
        expected_version: int, now: datetime | None = None,
    ) -> GoalRecord:
        new_state = _text(new_state, "new_state", 32)
        if new_state not in _GOAL_STATES:
            raise GoalValidationError("goal state is unsupported")
        if type(expected_version) is not int or expected_version < 1:
            raise GoalValidationError("expected_version must be a positive integer")
        stamp = _stamp(now)
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """SELECT g.state,g.version FROM goals g JOIN goal_owners o ON o.goal_id=g.goal_id
                    WHERE g.goal_id=? AND o.principal_id=?""",
                    (goal_id, principal_id),
                ).fetchone()
                if row is None:
                    raise GoalNotFoundError("goal does not exist")
                current, version = row
                if version != expected_version:
                    raise GoalConflictError("goal version changed")
                if new_state not in _TRANSITIONS[current]:
                    raise GoalConflictError("goal lifecycle transition is not allowed")
                connection.execute(
                    "UPDATE goals SET state=?,version=version+1,updated_at=? WHERE goal_id=? AND version=?",
                    (new_state, stamp, goal_id, expected_version),
                )
                connection.execute(
                    "INSERT INTO goal_events(goal_id,timestamp,state,version,event_type) VALUES(?,?,?,?, 'transition')",
                    (goal_id, stamp, new_state, expected_version + 1),
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
        return self.get_for_principal(goal_id, principal_id)


    def _evidence_rows(
        self, goal_id: str, principal_id: str
    ) -> tuple[dict[str, Any], ...]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """SELECT evidence_type,reference,step_index,created_at
                FROM goal_evidence WHERE goal_id=? AND principal_id=?
                ORDER BY evidence_id""",
                (goal_id, principal_id),
            ).fetchall()
            return tuple({
                "evidence_type": row[0], "reference": row[1],
                "step_index": row[2], "created_at": row[3],
            } for row in rows)
        finally:
            connection.close()

    def link_task_for_principal(
        self, goal_id: str, principal_id: str, task_id: str, *,
        expected_version: int, now: datetime | None = None,
    ) -> GoalRecord:
        _text(goal_id, "goal_id", 64)
        principal_id = _text(principal_id, "principal_id", 128)
        task_id = _text(task_id, "task_id", 64)
        if type(expected_version) is not int or expected_version < 1:
            raise GoalValidationError("expected_version must be a positive integer")
        stamp = _stamp(now)
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """SELECT g.state,g.version,l.task_id FROM goals g
                    JOIN goal_owners o ON o.goal_id=g.goal_id
                    LEFT JOIN goal_task_links l ON l.goal_id=g.goal_id
                    WHERE g.goal_id=? AND o.principal_id=?""",
                    (goal_id, principal_id),
                ).fetchone()
                if row is None:
                    raise GoalNotFoundError("goal does not exist")
                if row[2] is not None:
                    if row[2] != task_id:
                        raise GoalConflictError("goal is already linked to another task")
                    connection.execute("COMMIT")
                    return self.get_for_principal(goal_id, principal_id)
                if row[1] != expected_version:
                    raise GoalConflictError("goal version changed")
                if row[0] != "planned":
                    raise GoalConflictError("only a planned goal can be linked to a task")
                connection.execute(
                    "INSERT INTO goal_task_links(goal_id,task_id,principal_id,linked_at) VALUES(?,?,?,?)",
                    (goal_id, task_id, principal_id, stamp),
                )
                connection.execute(
                    "UPDATE goals SET state='running',version=version+1,updated_at=? WHERE goal_id=? AND version=?",
                    (stamp, goal_id, expected_version),
                )
                connection.execute(
                    "INSERT INTO goal_events(goal_id,timestamp,state,version,event_type) VALUES(?,?,'running',?,'task_linked')",
                    (goal_id, stamp, expected_version + 1),
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
        return self.get_for_principal(goal_id, principal_id)

    def record_evidence_for_principal(
        self, goal_id: str, principal_id: str, evidence_type: str,
        reference: str, step_index: int, *, now: datetime | None = None,
    ) -> GoalRecord:
        _text(goal_id, "goal_id", 64)
        principal_id = _text(principal_id, "principal_id", 128)
        _text(evidence_type, "evidence_type", 64)
        _text(reference, "evidence reference", 512)
        if type(step_index) is not int or not -1 <= step_index < 32:
            raise GoalValidationError("evidence step_index must be between -1 and 31")
        stamp = _stamp(now)
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """SELECT g.state FROM goals g JOIN goal_owners o ON o.goal_id=g.goal_id
                    JOIN goal_task_links l ON l.goal_id=g.goal_id
                    WHERE g.goal_id=? AND o.principal_id=? AND l.principal_id=?""",
                    (goal_id, principal_id, principal_id),
                ).fetchone()
                if row is None:
                    raise GoalNotFoundError("goal does not exist")
                if row[0] not in {"running", "awaiting_verification", "succeeded", "cancelling", "reconciliation_required"}:
                    raise GoalConflictError("goal is not accepting task evidence")
                inserted = connection.execute(
                    """INSERT OR IGNORE INTO goal_evidence(
                    goal_id,principal_id,evidence_type,reference,step_index,created_at
                    ) VALUES(?,?,?,?,?,?)""",
                    (goal_id, principal_id, evidence_type, reference, step_index, stamp),
                ).rowcount
                if inserted:
                    connection.execute(
                        "INSERT INTO goal_events(goal_id,timestamp,state,version,event_type) SELECT goal_id,updated_at,state,version,'evidence_recorded' FROM goals WHERE goal_id=?",
                        (goal_id,),
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
        return self.get_for_principal(goal_id, principal_id)

    def evidence_for_principal(
        self, goal_id: str, principal_id: str
    ) -> tuple[dict[str, Any], ...]:
        with self._lock:
            self._owned_row(goal_id, principal_id)
            return self._evidence_rows(goal_id, principal_id)

    def events_for_principal(
        self, goal_id: str, principal_id: str
    ) -> tuple[dict[str, Any], ...]:
        with self._lock:
            self._owned_row(goal_id, principal_id)
            connection = self._connect()
            try:
                rows = connection.execute(
                    """SELECT timestamp,state,version,event_type FROM goal_events
                    WHERE goal_id=? ORDER BY event_id""",
                    (goal_id,),
                ).fetchall()
                return tuple({
                    "timestamp": row[0], "state": row[1],
                    "version": row[2], "event_type": row[3],
                } for row in rows)
            finally:
                connection.close()

    def domain_events_for_principal(
        self, goal_id: str, principal_id: str
    ) -> tuple[DomainEvent, ...]:
        """Return an owner-checked CloudEvents projection of this goal's local history."""
        with self._lock:
            self._owned_row(goal_id, principal_id)
            connection = self._connect()
            try:
                rows = connection.execute(
                    """SELECT event_id,timestamp,state,version,event_type FROM goal_events
                    WHERE goal_id=? ORDER BY event_id""",
                    (goal_id,),
                ).fetchall()
                evidence = connection.execute(
                    """SELECT evidence_id,evidence_type,reference,step_index,created_at
                    FROM goal_evidence WHERE goal_id=? AND principal_id=? ORDER BY evidence_id""",
                    (goal_id, principal_id),
                ).fetchall()
                events = [
                    goal_event(
                        event_id=row[0], goal_id=goal_id, timestamp=row[1],
                        state=row[2], version=row[3], event_type=row[4],
                        principal_id=principal_id,
                    ) for row in rows
                ]
                events.extend(DomainEvent(
                    id=f"evidence-{row[0]}",
                    source=f"urn:capri:goal:{goal_id}",
                    type="com.capri.goal.evidence_recorded",
                    subject=goal_id,
                    time=row[4],
                    data=(
                        ("actor_id", principal_id),
                        ("evidence_type", row[1]),
                        ("evidence_reference", row[2]),
                        ("step_index", row[3]),
                        ("derived_from", row[2]),
                    ),
                ) for row in evidence)
                return project_domain_events(events)
            finally:
                connection.close()

    @staticmethod
    def _validate_backup_snapshot(connection: sqlite3.Connection) -> None:
        goal_count = connection.execute("SELECT COUNT(*) FROM goals").fetchone()[0]
        owner_count = connection.execute("SELECT COUNT(*) FROM goal_owners").fetchone()[0]
        if goal_count != owner_count:
            raise GoalValidationError("goal backup contains missing or orphaned owners")
        rows = connection.execute(
            """SELECT g.goal_id,g.outcome,g.constraints_json,g.deadline,g.criteria_json,
            g.state,g.version,g.created_at,g.updated_at,g.plan_json,o.principal_id
            FROM goals g JOIN goal_owners o ON o.goal_id=g.goal_id"""
        ).fetchall()
        for row in rows:
            SQLiteGoalStore._record(row[:10], row[10])
        owners = {
            goal_id: principal_id
            for goal_id, principal_id in connection.execute(
                "SELECT goal_id,principal_id FROM goal_owners"
            ).fetchall()
        }
        links = connection.execute(
            "SELECT goal_id,task_id,principal_id,linked_at FROM goal_task_links"
        ).fetchall()
        for goal_id, task_id, principal_id, linked_at in links:
            _text(goal_id, "goal task link goal_id", 64)
            _text(task_id, "goal task link task_id", 64)
            _text(principal_id, "goal task link principal_id", 128)
            _text(linked_at, "goal task link timestamp", 64)
            _deadline(linked_at)
            if goal_id not in owners or owners[goal_id] != principal_id:
                raise GoalValidationError("goal backup contains a mismatched task link owner")
        evidence_rows = connection.execute(
            "SELECT goal_id,principal_id,evidence_type,reference,step_index,created_at FROM goal_evidence"
        ).fetchall()
        for goal_id, principal_id, evidence_type, reference, step_index, created_at in evidence_rows:
            if goal_id not in owners or owners[goal_id] != principal_id:
                raise GoalValidationError("goal backup contains mismatched evidence ownership")
            _text(evidence_type, "evidence type", 64)
            _text(reference, "evidence reference", 512)
            _text(created_at, "evidence timestamp", 64)
            if type(step_index) is not int or not -1 <= step_index < 32:
                raise GoalValidationError("goal backup contains invalid evidence step index")
        event_rows = connection.execute(
            "SELECT state,version,event_type FROM goal_events"
        ).fetchall()
        for state, version, event_type in event_rows:
            if state not in _GOAL_STATES or type(version) is not int or version < 1:
                raise GoalValidationError("goal backup contains an invalid event")
            if event_type not in {"created", "plan_saved", "transition", "task_linked", "evidence_recorded"}:
                raise GoalValidationError("goal backup contains an invalid event type")

    def backup_to(self, destination_path: str) -> str:
        """Create a private, consistent goal-state snapshot without overwriting."""
        return backup_sqlite_database(
            self.path,
            destination_path,
            lock=self._lock,
            connect=self._connect,
            validate_snapshot=self._validate_backup_snapshot,
            error_type=GoalValidationError,
            prefix=".capri-goal-backup-",
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
