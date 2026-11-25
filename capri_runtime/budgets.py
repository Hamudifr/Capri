"""Principal-scoped, fail-closed execution budgets with conservative reservations.

Budgets count provider calls/input bytes, tool calls, and task steps/input bytes.
They do not claim to measure provider tokens, money, or wall-clock handler time.
"""
from __future__ import annotations

import json
import os
import sqlite3
import stat
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from capri_core.validation import contains_surrogate

from .sqlite_backup import backup_sqlite_database


class BudgetError(Exception):
    """Base class for budget policy and persistence errors."""


class BudgetValidationError(BudgetError):
    """A budget policy, identity, or reservation is invalid."""


class BudgetExceededError(BudgetError):
    """A principal exhausted a hard budget dimension for the current window."""

    def __init__(self, dimension: str, reset_at: datetime, *, permanent: bool = False) -> None:
        self.dimension = dimension
        self.reset_at = reset_at
        self.permanent = permanent
        super().__init__(f"execution budget exhausted: {dimension}")


_DIMENSIONS = {
    "provider_calls": "max_provider_calls",
    "provider_input_bytes": "max_provider_input_bytes",
    "tool_calls": "max_tool_calls",
    "task_steps": "max_task_steps",
    "task_input_bytes": "max_task_input_bytes",
}


@dataclass(frozen=True, slots=True)
class BudgetPolicy:
    window_seconds: int = 86_400
    max_provider_calls: int = 40
    max_provider_input_bytes: int = 2_097_152
    max_tool_calls: int = 80
    max_task_steps: int = 100
    max_task_input_bytes: int = 2_097_152

    def __post_init__(self) -> None:
        for name in (
            "window_seconds", "max_provider_calls", "max_provider_input_bytes",
            "max_tool_calls", "max_task_steps", "max_task_input_bytes",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise BudgetValidationError(f"{name} must be a positive integer")
        if self.window_seconds > 2_592_000:
            raise BudgetValidationError("budget window cannot exceed 30 days")
        if self.max_provider_calls > 100_000 or self.max_tool_calls > 1_000_000:
            raise BudgetValidationError("call-count budget exceeds the supported hard maximum")
        if self.max_task_steps > 1_000_000:
            raise BudgetValidationError("task-step budget exceeds the supported hard maximum")
        if self.max_provider_input_bytes > 1_073_741_824 or self.max_task_input_bytes > 1_073_741_824:
            raise BudgetValidationError("byte budget exceeds the supported hard maximum")


@dataclass(frozen=True, slots=True)
class BudgetReservation:
    reservation_id: str
    principal_id: str
    window_start: str
    reset_at: datetime
    amounts: dict[str, int]
    created_at: str


@dataclass(frozen=True, slots=True)
class BudgetUsage:
    principal_id: str
    window_start: str
    reset_at: datetime
    policy: BudgetPolicy
    used: dict[str, int]


def _identity(value: Any) -> str:
    if (type(value) is not str or not value.strip() or len(value) > 256
            or contains_surrogate(value)):
        raise BudgetValidationError("principal_id must be bounded non-empty text")
    return value


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if not isinstance(current, datetime) or current.tzinfo is None or current.utcoffset() is None:
        raise BudgetValidationError("budget timestamps must be timezone-aware")
    return current.astimezone(timezone.utc)


class SQLiteBudgetStore:
    """Private SQLite budget ledger. Reservations are charged before execution.

    Failed or interrupted calls are not refunded. This is intentionally
    conservative: it prevents retries and crashes from creating free capacity.
    """

    def __init__(self, path: str, default_policy: BudgetPolicy | None = None) -> None:
        if type(default_policy) is not BudgetPolicy and default_policy is not None:
            raise BudgetValidationError("default_policy must be a BudgetPolicy")
        self.default_policy = default_policy or BudgetPolicy()
        if (type(path) is not str or not path.strip() or len(path) > 4096
                or contains_surrogate(path)):
            raise BudgetValidationError("database path is invalid")
        absolute = os.path.abspath(path)
        parent = os.path.dirname(absolute)
        if not os.path.isdir(parent) or os.path.realpath(parent) != parent:
            raise BudgetValidationError("database parent must be an existing non-symlink directory")
        parent_stat = os.stat(parent, follow_symlinks=False)
        if not stat.S_ISDIR(parent_stat.st_mode):
            raise BudgetValidationError("database parent must be a directory")
        if os.name == "posix" and (
            parent_stat.st_uid != os.geteuid() or stat.S_IMODE(parent_stat.st_mode) & 0o077
        ):
            raise BudgetValidationError("database parent must be owned by the current user and private")
        if os.path.lexists(absolute):
            existing = os.lstat(absolute)
            if not stat.S_ISREG(existing.st_mode):
                raise BudgetValidationError("database path must be a regular non-symlink file")
            if os.name == "posix" and (existing.st_uid != os.geteuid() or existing.st_nlink != 1):
                raise BudgetValidationError("database ownership or link count is unsafe")
        try:
            descriptor = os.open(
                absolute, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600
            )
        except OSError:
            raise BudgetValidationError("database file could not be opened safely") from None
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise BudgetValidationError("database path must be a regular file")
            if os.name == "posix":
                if opened.st_uid != os.geteuid() or opened.st_nlink != 1:
                    raise BudgetValidationError("database ownership or link count is unsafe")
                os.fchmod(descriptor, 0o600)
        finally:
            os.close(descriptor)
        self.path = absolute
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        if os.path.realpath(os.path.dirname(self.path)) != os.path.dirname(self.path):
            raise BudgetValidationError("database parent changed")
        if os.name == "posix":
            info = os.lstat(self.path)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077):
                raise BudgetValidationError("database file identity or permissions changed")
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("""CREATE TABLE IF NOT EXISTS budget_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )""")
                connection.execute("""CREATE TABLE IF NOT EXISTS budget_policies (
                    principal_id TEXT PRIMARY KEY,
                    policy_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )""")
                connection.execute("""CREATE TABLE IF NOT EXISTS budget_usage (
                    principal_id TEXT NOT NULL,
                    window_start TEXT NOT NULL,
                    dimension TEXT NOT NULL,
                    used INTEGER NOT NULL,
                    PRIMARY KEY(principal_id,window_start,dimension)
                )""")
                connection.execute("""CREATE TABLE IF NOT EXISTS budget_reservations (
                    reservation_id TEXT PRIMARY KEY,
                    principal_id TEXT NOT NULL,
                    window_start TEXT NOT NULL,
                    amounts_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )""")
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS budget_usage_principal_window_idx "
                    "ON budget_usage(principal_id,window_start)"
                )
                existing_default = connection.execute(
                    "SELECT value FROM budget_meta WHERE key='default_policy'"
                ).fetchone()
                if existing_default:
                    self.default_policy = self._policy_from_json(existing_default[0])
                else:
                    connection.execute(
                        "INSERT INTO budget_meta(key,value) VALUES('default_policy',?)",
                        (json.dumps(asdict(self.default_policy), sort_keys=True, separators=(",", ":")),),
                    )
                connection.execute("""CREATE TRIGGER IF NOT EXISTS budget_reservation_immutable_update
                    BEFORE UPDATE ON budget_reservations
                    BEGIN SELECT RAISE(ABORT, 'budget reservations are append-only'); END""")
                connection.execute("""CREATE TRIGGER IF NOT EXISTS budget_reservation_immutable_delete
                    BEFORE DELETE ON budget_reservations
                    BEGIN SELECT RAISE(ABORT, 'budget reservations are append-only'); END""")
            finally:
                connection.close()

    @staticmethod
    def _policy_from_json(value: str) -> BudgetPolicy:
        try:
            data = json.loads(value)
            if type(data) is not dict or set(data) != {
                "window_seconds", "max_provider_calls", "max_provider_input_bytes",
                "max_tool_calls", "max_task_steps", "max_task_input_bytes",
            }:
                raise ValueError
            return BudgetPolicy(**data)
        except (TypeError, ValueError, BudgetValidationError):
            raise BudgetValidationError("persisted budget policy is invalid") from None

    def set_policy_for_principal(
        self, principal_id: str, policy: BudgetPolicy, *,
        now: datetime | None = None,
    ) -> BudgetPolicy:
        principal_id = _identity(principal_id)
        if type(policy) is not BudgetPolicy:
            raise BudgetValidationError("policy must be a BudgetPolicy")
        stamp = _utc(now).isoformat()
        encoded = json.dumps(asdict(policy), sort_keys=True, separators=(",", ":"))
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """INSERT INTO budget_policies(principal_id,policy_json,updated_at)
                    VALUES(?,?,?) ON CONFLICT(principal_id) DO UPDATE SET
                    policy_json=excluded.policy_json,updated_at=excluded.updated_at""",
                    (principal_id, encoded, stamp),
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
        return policy

    def get_policy_for_principal(self, principal_id: str) -> BudgetPolicy:
        principal_id = _identity(principal_id)
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute(
                    "SELECT policy_json FROM budget_policies WHERE principal_id=?",
                    (principal_id,),
                ).fetchone()
                return self._policy_from_json(row[0]) if row else self.default_policy
            finally:
                connection.close()

    def reserve_for_principal(
        self, principal_id: str, amounts: dict[str, int], *,
        now: datetime | None = None,
    ) -> BudgetReservation:
        principal_id = _identity(principal_id)
        if type(amounts) is not dict or not amounts or len(amounts) > len(_DIMENSIONS):
            raise BudgetValidationError("amounts must be a bounded non-empty dimension map")
        normalized: dict[str, int] = {}
        for dimension, amount in amounts.items():
            if dimension not in _DIMENSIONS:
                raise BudgetValidationError("budget dimension is unsupported")
            if type(amount) is not int or amount < 1 or amount > 1_073_741_824:
                raise BudgetValidationError("budget reservation amount is invalid")
            normalized[dimension] = amount
        current = _utc(now)
        stamp = current.isoformat()
        reservation_id = str(uuid4())
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                policy_row = connection.execute(
                    "SELECT policy_json FROM budget_policies WHERE principal_id=?",
                    (principal_id,),
                ).fetchone()
                policy = self._policy_from_json(policy_row[0]) if policy_row else self.default_policy
                window_epoch = int(current.timestamp()) // policy.window_seconds * policy.window_seconds
                window_start = datetime.fromtimestamp(window_epoch, timezone.utc).isoformat()
                reset_at = datetime.fromtimestamp(
                    window_epoch + policy.window_seconds, timezone.utc
                )
                for dimension, amount in normalized.items():
                    used_row = connection.execute(
                        """SELECT used FROM budget_usage
                        WHERE principal_id=? AND window_start=? AND dimension=?""",
                        (principal_id, window_start, dimension),
                    ).fetchone()
                    used = used_row[0] if used_row else 0
                    limit = getattr(policy, _DIMENSIONS[dimension])
                    if amount > limit:
                        connection.execute("ROLLBACK")
                        raise BudgetExceededError(dimension, reset_at, permanent=True)
                    if used + amount > limit:
                        connection.execute("ROLLBACK")
                        raise BudgetExceededError(dimension, reset_at)
                connection.execute(
                    """INSERT INTO budget_reservations(
                    reservation_id,principal_id,window_start,amounts_json,created_at
                    ) VALUES(?,?,?,?,?)""",
                    (reservation_id, principal_id, window_start,
                     json.dumps(normalized, sort_keys=True, separators=(",", ":")), stamp),
                )
                for dimension, amount in normalized.items():
                    connection.execute(
                        """INSERT INTO budget_usage(principal_id,window_start,dimension,used)
                        VALUES(?,?,?,?) ON CONFLICT(principal_id,window_start,dimension)
                        DO UPDATE SET used=used+excluded.used""",
                        (principal_id, window_start, dimension, amount),
                    )
                connection.execute("COMMIT")
            except BudgetExceededError:
                raise
            except Exception:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                connection.close()
        return BudgetReservation(
            reservation_id, principal_id, window_start, reset_at, normalized, stamp,
        )

    def usage_for_principal(
        self, principal_id: str, *, now: datetime | None = None,
    ) -> BudgetUsage:
        principal_id = _identity(principal_id)
        current = _utc(now)
        policy = self.get_policy_for_principal(principal_id)
        window_epoch = int(current.timestamp()) // policy.window_seconds * policy.window_seconds
        window_start = datetime.fromtimestamp(window_epoch, timezone.utc).isoformat()
        reset_at = datetime.fromtimestamp(window_epoch + policy.window_seconds, timezone.utc)
        with self._lock:
            connection = self._connect()
            try:
                rows = connection.execute(
                    """SELECT dimension,used FROM budget_usage
                    WHERE principal_id=? AND window_start=?""",
                    (principal_id, window_start),
                ).fetchall()
                used = {dimension: amount for dimension, amount in rows}
            finally:
                connection.close()
        complete_usage = {dimension: used.get(dimension, 0) for dimension in _DIMENSIONS}
        return BudgetUsage(principal_id, window_start, reset_at, policy, complete_usage)

    @staticmethod
    def _validate_backup_snapshot(connection: sqlite3.Connection) -> None:
        meta = connection.execute(
            "SELECT value FROM budget_meta WHERE key='default_policy'"
        ).fetchone()
        if not meta:
            raise BudgetValidationError("budget backup is missing its default policy")
        SQLiteBudgetStore._policy_from_json(meta[0])
        for principal_id, policy_json in connection.execute(
            "SELECT principal_id,policy_json FROM budget_policies"
        ).fetchall():
            _identity(principal_id)
            SQLiteBudgetStore._policy_from_json(policy_json)
        for principal_id, window_start, dimension, used in connection.execute(
            "SELECT principal_id,window_start,dimension,used FROM budget_usage"
        ).fetchall():
            _identity(principal_id)
            if dimension not in _DIMENSIONS or type(used) is not int or used < 0:
                raise BudgetValidationError("budget backup contains invalid usage")
            try:
                parsed = datetime.fromisoformat(window_start)
            except (TypeError, ValueError):
                raise BudgetValidationError("budget backup contains invalid window start") from None
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise BudgetValidationError("budget backup window start must be timezone-aware")
        expected_usage: dict[tuple[str, str, str], int] = {}
        for reservation_id, principal_id, window_start, amounts_json, created_at in connection.execute(
            "SELECT reservation_id,principal_id,window_start,amounts_json,created_at FROM budget_reservations"
        ).fetchall():
            _identity(principal_id)
            if type(reservation_id) is not str or not reservation_id:
                raise BudgetValidationError("budget backup contains invalid reservation id")
            try:
                amounts = json.loads(amounts_json)
                created = datetime.fromisoformat(created_at)
                window = datetime.fromisoformat(window_start)
            except (TypeError, ValueError):
                raise BudgetValidationError("budget backup contains invalid reservation data") from None
            if (type(amounts) is not dict or not amounts
                    or created.tzinfo is None or window.tzinfo is None):
                raise BudgetValidationError("budget backup contains invalid reservation data")
            for dimension, amount in amounts.items():
                if dimension not in _DIMENSIONS or type(amount) is not int or amount < 1:
                    raise BudgetValidationError("budget backup contains invalid reservation amount")
                key = (principal_id, window_start, dimension)
                expected_usage[key] = expected_usage.get(key, 0) + amount
        actual_usage = {
            (principal_id, window_start, dimension): used
            for principal_id, window_start, dimension, used in connection.execute(
                "SELECT principal_id,window_start,dimension,used FROM budget_usage"
            ).fetchall()
        }
        if expected_usage != actual_usage:
            raise BudgetValidationError("budget backup reservation totals do not match usage")

    def backup_to(self, destination_path: str) -> str:
        return backup_sqlite_database(
            self.path, destination_path, lock=self._lock, connect=self._connect,
            validate_snapshot=self._validate_backup_snapshot,
            error_type=BudgetValidationError, prefix=".capri-budget-backup-",
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
