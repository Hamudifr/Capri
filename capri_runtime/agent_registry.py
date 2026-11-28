"""Durable host-owned identity and agent-binding registry.

This module is the identity spine of the Capri Agent Network. The forum stores
agent *profiles* (name, capabilities); the network layer adds verification
tokens and responsibilities; the host facade binds invocations to agents. This
registry connects all three by adding the missing lifecycle and binding layer:

- **Lifecycle state**: every agent moves through registered → active →
  suspended → deactivated. The host controls every transition. An agent that
  is not ``active`` cannot propose, vote, challenge, review, or be bound to
  an invocation — its identity exists but its participation is frozen.
- **Principal-agent bindings**: durable records that a host principal controls
  a specific agent, with a formal role. One principal can control many agents;
  one agent is controlled by one principal (re-binding is a host-gated
  operation). This is what makes agents *independently identifiable* — each
  agent has a proven owner and a role, not just a name.
- **Roles**: formal role assignments (proposer, reviewer, moderator, scribe)
  distinct from capabilities (what the agent *can* do) and responsibilities
  (what the host expects it to *own*). Roles are the host's declaration of
  what role an agent plays in the network.
- **Host authority**: every lifecycle transition and binding change requires
  a host credential. Agents cannot activate, suspend, deactivate, or
  re-bind themselves. The host owns the registry.

The registry sits in the same SQLite database as the forum and the network
layer, sharing the forum's connection security model. It is deliberately
data-only with host-gated authentication: it never invokes tools or grants
permissions beyond its own lifecycle and binding state.
"""
from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from .agent_forum import (
    SQLiteAgentForum,
    _stamp,
    _text,
)
from .agent_network import AuthorizationError


class AgentRegistryError(Exception):
    """Base class for expected agent-registry failures."""


class AgentRegistryValidationError(AgentRegistryError):
    """A record or persisted value is invalid."""


class AgentRegistryConflictError(AgentRegistryError):
    """A lifecycle transition or binding change is invalid."""


class AgentRegistryNotFoundError(AgentRegistryError):
    """The agent or binding does not exist."""


# ---------------------------------------------------------------------------
# Lifecycle and role definitions
# ---------------------------------------------------------------------------

LIFECYCLE_STATES = frozenset({"registered", "active", "suspended", "deactivated"})

# State transitions the host may perform
_VALID_TRANSITIONS: dict[str, frozenset[str]] = {
    "registered": frozenset({"active", "deactivated"}),
    "active": frozenset({"suspended", "deactivated"}),
    "suspended": frozenset({"active", "deactivated"}),
    "deactivated": frozenset(),  # terminal
}

# Valid roles an agent can be assigned by the host
AGENT_ROLES = frozenset({"proposer", "reviewer", "moderator", "scribe", "observer"})


# ---------------------------------------------------------------------------
# Host authority protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class HostRegistryAuthority(Protocol):
    """Host-injected policy that authenticates and authorizes registry writes.

    The host provides two callbacks: one to authenticate a host credential
    (returning a principal ID or None), and one to check whether that
    principal may perform a registry action (e.g. ``set_state``,
    ``bind_principal``). This keeps the registry host-owned: no agent or
    model can call registry methods without a valid host credential that
    passes both checks.
    """

    def authenticate(self, credential: Any) -> str | None:
        """Return the principal ID for a valid host credential, or None."""

    def authorize(self, principal_id: str, action: str) -> bool:
        """Return True if the principal may perform the registry action."""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class LifecycleRecord:
    """The current lifecycle state of an agent."""

    agent_id: str
    state: str
    state_at: str
    assigned_by: str
    version: int


@dataclass(frozen=True, slots=True)
class PrincipalBinding:
    """A durable principal→agent binding with a formal role."""

    binding_id: int
    agent_id: str
    principal_id: str
    role: str
    bound_at: str
    bound_by: str


# ---------------------------------------------------------------------------
# SQLite Agent Registry
# ---------------------------------------------------------------------------

class SQLiteAgentRegistry:
    """Durable host-owned agent lifecycle and principal-binding registry.

    Shares the forum's SQLite database and connection security model. All
    lifecycle and binding changes are host-gated via the injected
    ``HostRegistryAuthority``.
    """

    def __init__(
        self,
        forum: SQLiteAgentForum,
        authority: HostRegistryAuthority,
    ) -> None:
        if not isinstance(forum, SQLiteAgentForum):
            raise AgentRegistryValidationError("registry requires a SQLiteAgentForum")
        if not isinstance(authority, HostRegistryAuthority):
            raise AgentRegistryValidationError("registry requires a HostRegistryAuthority")
        self.forum = forum
        self.authority = authority
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.forum.path, timeout=10, isolation_level=None,
        )
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("PRAGMA journal_mode=WAL")
                # Agent lifecycle: one row per agent, updated on state change
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS agent_lifecycle (
                        agent_id TEXT PRIMARY KEY,
                        state TEXT NOT NULL,
                        state_at TEXT NOT NULL,
                        assigned_by TEXT NOT NULL,
                        version INTEGER NOT NULL
                    )
                """)
                # Principal-agent bindings: durable owner + role records.
                # No UNIQUE on (agent_id, principal_id): unbinding marks the
                # old row inactive, and a new binding row can be inserted for
                # the same pair with a different role. Active bindings are
                # determined by the absence of an unbinding record.
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS agent_principal_bindings (
                        binding_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        agent_id TEXT NOT NULL,
                        principal_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        bound_at TEXT NOT NULL,
                        bound_by TEXT NOT NULL
                    )
                """)
                # Unbinding records: mark bindings as inactive without DELETE
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS agent_binding_unbindings (
                        agent_id TEXT NOT NULL,
                        principal_id TEXT NOT NULL,
                        unbound_at TEXT NOT NULL,
                        unbound_by TEXT NOT NULL,
                        PRIMARY KEY (agent_id, principal_id)
                    )
                """)
                # Indexes
                connection.execute("CREATE INDEX IF NOT EXISTS binding_agent_idx ON agent_principal_bindings(agent_id)")
                connection.execute("CREATE INDEX IF NOT EXISTS binding_principal_idx ON agent_principal_bindings(principal_id)")
                # Append-only triggers on bindings (cannot UPDATE/DELETE directly;
                # re-binding is a new row via unbind + bind)
                connection.execute("CREATE TRIGGER IF NOT EXISTS bindings_immutable_update\n"
                                   "    BEFORE UPDATE ON agent_principal_bindings\n"
                                   "    BEGIN SELECT RAISE(ABORT, 'principal bindings are append-only'); END")
                connection.execute("CREATE TRIGGER IF NOT EXISTS bindings_immutable_delete\n"
                                   "    BEFORE DELETE ON agent_principal_bindings\n"
                                   "    BEGIN SELECT RAISE(ABORT, 'principal bindings are append-only'); END")
            finally:
                connection.close()

    # ------------------------------------------------------------- host auth

    def _authenticate_host(self, credential: Any, action: str) -> str:
        principal = self.authority.authenticate(credential)
        if not isinstance(principal, str) or not principal:
            raise AgentRegistryValidationError("host credential is not valid")
        if not self.authority.authorize(principal, action):
            raise AuthorizationError(
                f"principal '{principal}' is not authorized for registry action '{action}'"
            )
        return principal

    # --------------------------------------------------------- lifecycle

    def set_state(
        self, agent_id: str, new_state: str, *,
        credential: Any, now: datetime | None = None,
    ) -> LifecycleRecord:
        """Host-gated lifecycle transition for an agent.

        The agent must be registered in the forum. The transition must be
        valid (see ``_VALID_TRANSITIONS``). Deactivated is terminal.
        """
        agent_id = _text(agent_id, "agent_id", 128)
        new_state = _text(new_state, "new_state", 32)
        if new_state not in LIFECYCLE_STATES:
            raise AgentRegistryValidationError(f"state '{new_state}' is not valid")
        principal = self._authenticate_host(credential, "set_state")
        stamp = _stamp(now)

        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                # Verify agent exists in forum
                agent_row = connection.execute(
                    "SELECT 1 FROM agents WHERE agent_id=?", (agent_id,),
                ).fetchone()
                if agent_row is None:
                    raise AgentRegistryNotFoundError("agent does not exist in the forum")
                # Get current state
                current = connection.execute(
                    "SELECT state, version FROM agent_lifecycle WHERE agent_id=?",
                    (agent_id,),
                ).fetchone()
                if current is None:
                    # First registration: must go to "registered" or "active"
                    if new_state not in ("registered", "active"):
                        raise AgentRegistryConflictError(
                            "cannot set initial state to '%s'; must be registered or active"
                            % new_state
                        )
                    connection.execute(
                        "INSERT INTO agent_lifecycle(agent_id,state,state_at,assigned_by,version) VALUES(?,?,?,?,1)",
                        (agent_id, new_state, stamp, principal),
                    )
                    connection.execute("COMMIT")
                    return LifecycleRecord(agent_id, new_state, stamp, principal, 1)
                # Validate transition
                current_state = current[0]
                if current_state == new_state:
                    connection.execute("COMMIT")
                    return self.get_lifecycle(agent_id)
                allowed = _VALID_TRANSITIONS.get(current_state, frozenset())
                if new_state not in allowed:
                    raise AgentRegistryConflictError(
                        f"cannot transition from '{current_state}' to '{new_state}'"
                    )
                new_version = current[1] + 1
                connection.execute(
                    "UPDATE agent_lifecycle SET state=?, state_at=?, assigned_by=?, version=version+1 WHERE agent_id=?",
                    (new_state, stamp, principal, agent_id),
                )
                connection.execute("COMMIT")
                return LifecycleRecord(agent_id, new_state, stamp, principal, new_version)
            except Exception:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                connection.close()

    def get_lifecycle(self, agent_id: str) -> LifecycleRecord:
        agent_id = _text(agent_id, "agent_id", 128)
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute(
                    "SELECT agent_id,state,state_at,assigned_by,version FROM agent_lifecycle WHERE agent_id=?",
                    (agent_id,),
                ).fetchone()
            finally:
                connection.close()
        if row is None:
            raise AgentRegistryNotFoundError("agent has no lifecycle record")
        return LifecycleRecord(row[0], row[1], row[2], row[3], row[4])

    def is_active(self, agent_id: str) -> bool:
        """Return True if the agent is in the active state."""
        try:
            return self.get_lifecycle(agent_id).state == "active"
        except AgentRegistryNotFoundError:
            return False

    def can_participate(self, agent_id: str) -> bool:
        """Return True if the agent may participate in the forum/network.

        Only ``active`` agents can propose, vote, challenge, review, or be
        bound to an invocation.
        """
        return self.is_active(agent_id)

    def list_by_state(self, state: str | None = None) -> tuple[LifecycleRecord, ...]:
        with self._lock:
            connection = self._connect()
            try:
                if state is None:
                    rows = connection.execute(
                        "SELECT agent_id,state,state_at,assigned_by,version FROM agent_lifecycle ORDER BY agent_id"
                    ).fetchall()
                else:
                    state = _text(state, "state", 32)
                    if state not in LIFECYCLE_STATES:
                        raise AgentRegistryValidationError("state is not valid")
                    rows = connection.execute(
                        "SELECT agent_id,state,state_at,assigned_by,version FROM agent_lifecycle WHERE state=? ORDER BY agent_id",
                        (state,),
                    ).fetchall()
            finally:
                connection.close()
        return tuple(
            LifecycleRecord(r[0], r[1], r[2], r[3], r[4]) for r in rows
        )

    def list_active(self) -> tuple[LifecycleRecord, ...]:
        return self.list_by_state("active")

    # ----------------------------------------------------------- bindings

    def bind_principal(
        self, agent_id: str, principal_id: str, role: str, *,
        credential: Any, now: datetime | None = None,
    ) -> PrincipalBinding:
        """Host-gated: bind a principal to an agent with a role.

        The agent must be registered in the forum. A principal can be bound
        to multiple agents. An agent can have multiple principals (e.g. a
        supervisor and a backup), but each (agent, principal) pair is
        unique. Re-binding the same pair with a different role requires an
        explicit unbind first (bindings are append-only).
        """
        agent_id = _text(agent_id, "agent_id", 128)
        principal_id = _text(principal_id, "principal_id", 256)
        role = _text(role, "role", 32)
        if role not in AGENT_ROLES:
            raise AgentRegistryValidationError(
                f"role '{role}' is not valid; must be one of: {', '.join(sorted(AGENT_ROLES))}"
            )
        principal = self._authenticate_host(credential, "bind_principal")
        stamp = _stamp(now)

        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                # Verify agent exists
                agent_row = connection.execute(
                    "SELECT 1 FROM agents WHERE agent_id=?", (agent_id,),
                ).fetchone()
                if agent_row is None:
                    raise AgentRegistryNotFoundError("agent does not exist in the forum")
                # Check for an active (not unbound) binding
                existing = connection.execute(
                    "SELECT 1 FROM agent_principal_bindings b "
                    "LEFT JOIN agent_binding_unbindings u "
                    "ON b.agent_id=u.agent_id AND b.principal_id=u.principal_id "
                    "WHERE b.agent_id=? AND b.principal_id=? AND u.agent_id IS NULL",
                    (agent_id, principal_id),
                ).fetchone()
                if existing is not None:
                    raise AgentRegistryConflictError(
                        "principal is already actively bound to this agent; "
                        "unbind first to change the role"
                    )
                cursor = connection.execute(
                    "INSERT INTO agent_principal_bindings(agent_id,principal_id,role,bound_at,bound_by) VALUES(?,?,?,?,?)",
                    (agent_id, principal_id, role, stamp, principal),
                )
                binding_id = int(cursor.lastrowid)
                connection.execute("COMMIT")
                return PrincipalBinding(binding_id, agent_id, principal_id, role, stamp, principal)
            except Exception:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                connection.close()

    def unbind_principal(
        self, agent_id: str, principal_id: str, *,
        credential: Any, now: datetime | None = None,
    ) -> None:
        """Host-gated: remove a principal-agent binding.

        Since bindings are append-only (triggers block DELETE), unbinding is
        implemented by marking the binding inactive via a separate registry
        flag stored in a dedicated table. This preserves the audit trail while
        allowing re-binding.
        """
        agent_id = _text(agent_id, "agent_id", 128)
        principal_id = _text(principal_id, "principal_id", 256)
        principal = self._authenticate_host(credential, "unbind_principal")
        stamp = _stamp(now)

        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                # Check binding exists
                existing = connection.execute(
                    "SELECT 1 FROM agent_principal_bindings WHERE agent_id=? AND principal_id=?",
                    (agent_id, principal_id),
                ).fetchone()
                if existing is None:
                    raise AgentRegistryNotFoundError("principal is not bound to this agent")
                # Check if already unbound
                already = connection.execute(
                    "SELECT 1 FROM agent_binding_unbindings WHERE agent_id=? AND principal_id=?",
                    (agent_id, principal_id),
                ).fetchone()
                if already is not None:
                    connection.execute("COMMIT")
                    return
                # Create unbinding record (table created in _initialize)
                connection.execute(
                    "INSERT OR IGNORE INTO agent_binding_unbindings(agent_id,principal_id,unbound_at,unbound_by) VALUES(?,?,?,?)",
                    (agent_id, principal_id, stamp, principal),
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

    def bindings_for_agent(self, agent_id: str) -> tuple[PrincipalBinding, ...]:
        """Return active (not unbound) principal bindings for an agent."""
        agent_id = _text(agent_id, "agent_id", 128)
        with self._lock:
            connection = self._connect()
            try:
                rows = connection.execute(
                    "SELECT b.binding_id,b.agent_id,b.principal_id,b.role,b.bound_at,b.bound_by "
                    "FROM agent_principal_bindings b "
                    "LEFT JOIN agent_binding_unbindings u "
                    "ON b.agent_id=u.agent_id AND b.principal_id=u.principal_id "
                    "WHERE b.agent_id=? AND u.agent_id IS NULL "
                    "ORDER BY b.binding_id",
                    (agent_id,),
                ).fetchall()
            finally:
                connection.close()
        return tuple(
            PrincipalBinding(r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows
        )

    def agents_for_principal(self, principal_id: str) -> tuple[PrincipalBinding, ...]:
        """Return active bindings for a principal across all agents."""
        principal_id = _text(principal_id, "principal_id", 256)
        with self._lock:
            connection = self._connect()
            try:
                rows = connection.execute(
                    "SELECT b.binding_id,b.agent_id,b.principal_id,b.role,b.bound_at,b.bound_by "
                    "FROM agent_principal_bindings b "
                    "LEFT JOIN agent_binding_unbindings u "
                    "ON b.agent_id=u.agent_id AND b.principal_id=u.principal_id "
                    "WHERE b.principal_id=? AND u.principal_id IS NULL "
                    "ORDER BY b.agent_id",
                    (principal_id,),
                ).fetchall()
            finally:
                connection.close()
        return tuple(
            PrincipalBinding(r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows
        )

    def role_for(self, agent_id: str, principal_id: str) -> str | None:
        """Return the role of a principal for an agent, or None if not bound."""
        bindings = self.bindings_for_agent(agent_id)
        for binding in bindings:
            if binding.principal_id == principal_id:
                return binding.role
        return None

    # ----------------------------------------------------------- integrity

    def integrity_check(self) -> str:
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute("PRAGMA integrity_check").fetchone()
                fk_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
                if not row or row[0] != "ok":
                    return str(row[0]) if row else "no result"
                if fk_errors:
                    return "foreign key check failed"
                return "ok"
            finally:
                connection.close()

    def _validate_backup_snapshot(self) -> None:
        """Validate registry state after a forum backup (called by backup_to)."""
        with self._lock:
            connection = self._connect()
            try:
                agents = {
                    row[0] for row in connection.execute("SELECT agent_id FROM agents").fetchall()
                }
                lifecycle_rows = connection.execute(
                    "SELECT agent_id,state,state_at,assigned_by,version FROM agent_lifecycle"
                ).fetchall()
                for agent_id, state, state_at, assigned_by, version in lifecycle_rows:
                    if agent_id not in agents:
                        raise AgentRegistryValidationError(
                            "lifecycle record references an unknown agent"
                        )
                    if state not in LIFECYCLE_STATES:
                        raise AgentRegistryValidationError("lifecycle state is invalid")
                    _text(state_at, "state_at", 64)
                    _text(assigned_by, "assigned_by", 256)
                    if type(version) is not int or version < 1:
                        raise AgentRegistryValidationError("lifecycle version is invalid")
                binding_rows = connection.execute(
                    "SELECT agent_id,principal_id,role FROM agent_principal_bindings"
                ).fetchall()
                for agent_id, principal_id, role in binding_rows:
                    if agent_id not in agents:
                        raise AgentRegistryValidationError(
                            "binding references an unknown agent"
                        )
                    _text(principal_id, "principal_id", 256)
                    if role not in AGENT_ROLES:
                        raise AgentRegistryValidationError("binding role is invalid")
            finally:
                connection.close()
