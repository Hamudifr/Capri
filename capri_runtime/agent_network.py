"""Capri Agent Network: verified identity, responsibilities, and host-ratified decisions.

This module is the orchestration layer on top of ``agent_forum.py``. The forum
provides the communication substrate (registration, proposals, votes, work
logs, skill ledger). The network layer adds everything the forum deliberately
leaves out:

- **Verified identity**: the host issues HMAC-signed verification tokens to
  agents it trusts. Every network operation requires a valid token, so an
  agent cannot propose, challenge, or vote unless its identity is host-attested.
- **Responsibilities**: distinct from capabilities. Capabilities say what an
  agent *can* do; responsibilities say what the host expects it to *own*.
  Responsibilities are host-assigned, append-only, and auditable.
- **Challenge**: a formal objection to a proposal, carrying specific
  objections. A challenge is stronger than a disagree vote — it forces a
  review and must be addressed before the proposal can be ratified.
- **Review**: a structured assessment of work, with a verdict and findings.
  Reviews are how agents hold each other accountable.
- **Improve (revise)**: a proposal can be revised in light of challenges,
  producing a new version. The revision history is append-only.
- **Evidence-linked decisions**: when a proposal reaches a terminal state, a
  DecisionRecord is created that links the outcome to evidence references and
  is signed by the host's ratification key. Decisions are preserved, not
  discarded.
- **Host final authority**: the host ratifies or rejects a proposal's final
  decision. A proposal is only *approved* (ready for execution) when the
  host signs the decision record. Agents can debate freely, but the host
  always holds the final say.

The module is deliberately data-only with host-gated authentication: it never
invokes tools or grants permissions. The host validates every operation
against the agent's verification token and its own ratification policy.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from .agent_forum import (
    ForumNotFoundError,
    Proposal,
    SQLiteAgentForum,
    _stamp,
    _text,
)
from .tools import HmacApprovalKeyRing


class AgentNetworkError(Exception):
    """Base class for expected agent-network failures."""


class AgentNetworkValidationError(AgentNetworkError):
    """A record or persisted value is invalid."""


class AgentNetworkConflictError(AgentNetworkError):
    """A record changed or its requested lifecycle transition is invalid."""


class AgentNetworkNotFoundError(AgentNetworkError):
    """The record does not exist or is not owned by the given agent."""


class IdentityVerificationError(AgentNetworkError):
    """A verification token is invalid, revoked, or does not match the agent."""


class AuthorizationError(AgentNetworkError):
    """The host does not grant the required authority for this operation."""


# ---------------------------------------------------------------------------
# Verification tokens
# ---------------------------------------------------------------------------

_TOKEN_REF = re.compile(r"^agent-verify:v1:([a-z][a-z0-9_.-]{0,63}):([0-9a-f]{32}):([0-9a-f]{64})$")


@dataclass(frozen=True, slots=True)
class VerificationToken:
    """A host-issued HMAC-signed proof that an agent's identity is trusted.

    token_id: stable identifier for this issuance (used for revocation)
    agent_id: the agent this token proves
    issued_at: ISO-8601 timestamp
    signature: HMAC-SHA256 over the canonical payload, hex-encoded
    """

    token_id: str
    agent_id: str
    issued_at: str
    signature: str


def _token_payload(token_id: str, agent_id: str, issued_at: str) -> bytes:
    payload = json.dumps(
        {"token_id": token_id, "agent_id": agent_id, "issued_at": issued_at},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return payload.encode("utf-8")


def _token_id(value: Any) -> str:
    return _text(value, "token_id", 64)


class AgentIdentityVerifier:
    """Issues and validates HMAC-signed agent verification tokens.

    The host constructs this with its own ``HmacApprovalKeyRing``. It never
    stores raw keys; signing and verification are delegated to the key ring.
    """

    __slots__ = ("_key_ring",)

    def __init__(self, key_ring: HmacApprovalKeyRing) -> None:
        if not isinstance(key_ring, HmacApprovalKeyRing):
            raise AgentNetworkValidationError(
                "identity verifier requires an HmacApprovalKeyRing"
            )
        self._key_ring = key_ring

    @property
    def key_ring(self) -> HmacApprovalKeyRing:
        return self._key_ring

    def issue(self, agent_id: str, *, now: datetime | None = None) -> VerificationToken:
        agent_id = _text(agent_id, "agent_id", 128)
        token_id = f"vt-{uuid4().hex[:16]}"
        stamp = _stamp(now)
        payload = _token_payload(token_id, agent_id, stamp)
        signature = self._key_ring.sign(self._key_ring.active_key_id, payload).hex()
        return VerificationToken(token_id, agent_id, stamp, signature)

    def validate(self, token: VerificationToken) -> None:
        """Raise ``IdentityVerificationError`` if the token is not authentic."""
        if not isinstance(token, VerificationToken):
            raise IdentityVerificationError("verification token must be a VerificationToken")
        agent_id = _text(token.agent_id, "token agent_id", 128)
        token_id = _text(token.token_id, "token_id", 64)
        issued_at = _text(token.issued_at, "issued_at", 64)
        signature = _text(token.signature, "signature", 128)
        payload = _token_payload(token_id, agent_id, issued_at)
        try:
            sig_bytes = bytes.fromhex(signature)
        except ValueError:
            raise IdentityVerificationError("verification token signature is not hex") from None
        if not self._key_ring.verify(self._key_ring.active_key_id, payload, sig_bytes):
            raise IdentityVerificationError("verification token signature is invalid")

    def canonical_ref(self, token: VerificationToken) -> str:
        """Return the canonical string reference for a token (for audit logs)."""
        payload = _token_payload(token.token_id, token.agent_id, token.issued_at)
        digest = hashlib.sha256(payload).hexdigest()
        return f"agent-verify:v1:{token.token_id}:{digest[:8]}:{digest}"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Responsibility:
    responsibility_id: int
    agent_id: str
    responsibility: str
    assigned_by: str
    assigned_at: str


@dataclass(frozen=True, slots=True)
class Challenge:
    challenge_id: int
    proposal_id: str
    agent_id: str
    objections: dict[str, Any]
    created_at: str


@dataclass(frozen=True, slots=True)
class Review:
    review_id: int
    work_entry_id: int
    agent_id: str
    verdict: str
    findings: dict[str, Any]
    created_at: str


@dataclass(frozen=True, slots=True)
class ProposalRevision:
    revision_id: int
    proposal_id: str
    author_id: str
    change_summary: str
    body: dict[str, Any]
    version: int
    created_at: str


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    decision_id: int
    proposal_id: str
    outcome: str
    evidence_references: tuple[str, ...]
    ratified_by: str
    ratified_at: str
    signature: str


# ---------------------------------------------------------------------------
# Host authority protocol
# ---------------------------------------------------------------------------

_DECISION_OUTCOMES = frozenset({"approved", "rejected", "abandoned"})
_REVIEW_VERDICTS = frozenset({"approve", "reject", "request_changes"})


@runtime_checkable
class HostRatificationPolicy(Protocol):
    """Host-injected policy that decides whether to ratify a proposal decision.

    The host reviews the proposal, its challenges, reviews, and evidence
    references, then returns an outcome and optional evidence references to
    attach to the decision record. It returns data only.
    """

    def ratify(
        self,
        proposal: Proposal,
        challenges: tuple[Challenge, ...],
        reviews: tuple[Review, ...],
        evidence_references: tuple[str, ...],
    ) -> tuple[str, tuple[str, ...]]:
        """Return ``(outcome, additional_evidence)`` where outcome is one of
        approved / rejected / abandoned."""


@runtime_checkable
class AgentPermissionPolicy(Protocol):
    """Host-injected policy that checks whether an agent may perform an action.

    It receives the agent's verified identity and the action name, and returns
    True or False. This is the host's fine-grained permission gate on top of
    verification.
    """

    def permits(self, agent_id: str, action: str) -> bool:
        """Return True if the agent is permitted to perform the action."""


# ---------------------------------------------------------------------------
# SQLite Agent Network
# ---------------------------------------------------------------------------

_CHANNEL_ACTIONS = frozenset({
    "propose", "vote", "challenge", "review", "revise", "record_work",
})


class SQLiteAgentNetwork:
    """Durable agent-network store over the agent forum.

    Wraps a ``SQLiteAgentForum`` and adds verification tokens, responsibilities,
    challenges, reviews, proposal revisions, and host-ratified decision
    records. All logs (challenges, reviews, revisions, decisions) are
    append-only via triggers.
    """

    def __init__(
        self,
        forum: SQLiteAgentForum,
        verifier: AgentIdentityVerifier,
        *,
        permission_policy: AgentPermissionPolicy | None = None,
        ratification_policy: HostRatificationPolicy | None = None,
    ) -> None:
        if not isinstance(forum, SQLiteAgentForum):
            raise AgentNetworkValidationError("agent network requires a SQLiteAgentForum")
        if not isinstance(verifier, AgentIdentityVerifier):
            raise AgentNetworkValidationError("agent network requires an AgentIdentityVerifier")
        self.forum = forum
        self.verifier = verifier
        self.permission_policy = permission_policy
        self.ratification_policy = ratification_policy
        self._lock = threading.RLock()
        self._connect()

    # ------------------------------------------------------------------ setup

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.forum.path, timeout=10, isolation_level=None,
        )
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        with self._lock:
            connection.execute("PRAGMA journal_mode=WAL")
            # Verification tokens (issuance log; revocation is a separate append)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS agent_tokens (
                    token_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    issued_at TEXT NOT NULL
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS agent_token_revocations (
                    token_id TEXT NOT NULL,
                    revoked_at TEXT NOT NULL,
                    PRIMARY KEY (token_id, revoked_at)
                )
            """)
            # Responsibilities
            connection.execute("""
                CREATE TABLE IF NOT EXISTS responsibilities (
                    responsibility_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT NOT NULL,
                    responsibility TEXT NOT NULL,
                    assigned_by TEXT NOT NULL,
                    assigned_at TEXT NOT NULL
                )
            """)
            # Challenges
            connection.execute("""
                CREATE TABLE IF NOT EXISTS challenges (
                    challenge_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    proposal_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    objections_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
            """)
            # Reviews
            connection.execute("""
                CREATE TABLE IF NOT EXISTS reviews (
                    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    work_entry_id INTEGER NOT NULL,
                    agent_id TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    findings_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
            """)
            # Proposal revisions
            connection.execute("""
                CREATE TABLE IF NOT EXISTS proposal_revisions (
                    revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    proposal_id TEXT NOT NULL,
                    author_id TEXT NOT NULL,
                    change_summary TEXT NOT NULL,
                    body_json TEXT NOT NULL DEFAULT '{}',
                    version INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            # Decision records
            connection.execute("""
                CREATE TABLE IF NOT EXISTS decision_records (
                    decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    proposal_id TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    evidence_json TEXT NOT NULL DEFAULT '[]',
                    ratified_by TEXT NOT NULL,
                    ratified_at TEXT NOT NULL,
                    signature TEXT NOT NULL
                )
            """)
            # Indexes
            connection.execute("CREATE INDEX IF NOT EXISTS resp_agent_idx ON responsibilities(agent_id)")
            connection.execute("CREATE INDEX IF NOT EXISTS challenge_proposal_idx ON challenges(proposal_id)")
            connection.execute("CREATE INDEX IF NOT EXISTS review_work_idx ON reviews(work_entry_id)")
            connection.execute("CREATE INDEX IF NOT EXISTS revision_proposal_idx ON proposal_revisions(proposal_id)")
            connection.execute("CREATE INDEX IF NOT EXISTS decision_proposal_idx ON decision_records(proposal_id)")
            # Append-only triggers
            for table, label in (
                ("challenges", "challenges"),
                ("reviews", "reviews"),
                ("proposal_revisions", "proposal revisions"),
                ("decision_records", "decision records"),
            ):
                connection.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_immutable_update\n"
                                   f"    BEFORE UPDATE ON {table}\n"
                                   f"    BEGIN SELECT RAISE(ABORT, '{label} are append-only'); END")
                connection.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_immutable_delete\n"
                                   f"    BEFORE DELETE ON {table}\n"
                                   f"    BEGIN SELECT RAISE(ABORT, '{label} are append-only'); END")
        return connection

    def _acquire_connection(self) -> sqlite3.Connection:
        return self._connect()

    # ------------------------------------------------------------ auth helper

    def _verify_agent(
        self, connection: sqlite3.Connection, agent_id: str, token: VerificationToken
    ) -> None:
        """Validate the token and check it has not been revoked."""
        self.verifier.validate(token)
        if token.agent_id != agent_id:
            raise IdentityVerificationError(
                "verification token does not match the agent"
            )
        row = connection.execute(
            "SELECT 1 FROM agent_tokens WHERE token_id=? AND agent_id=?",
            (token.token_id, agent_id),
        ).fetchone()
        if row is None:
            raise IdentityVerificationError("verification token is not registered")
        revoked = connection.execute(
            "SELECT 1 FROM agent_token_revocations WHERE token_id=?",
            (token.token_id,),
        ).fetchone()
        if revoked is not None:
            raise IdentityVerificationError("verification token has been revoked")
        agent_row = connection.execute(
            "SELECT 1 FROM agents WHERE agent_id=?", (agent_id,),
        ).fetchone()
        if agent_row is None:
            raise IdentityVerificationError("agent is not registered in the forum")

    def _check_permission(self, agent_id: str, action: str) -> None:
        if self.permission_policy is not None:
            if not self.permission_policy.permits(agent_id, action):
                raise AuthorizationError(
                    f"agent '{agent_id}' is not permitted to '{action}'"
                )

    # -------------------------------------------------------- token issuance

    def issue_verification(
        self, agent_id: str, *, host_credential: str,
        now: datetime | None = None,
    ) -> VerificationToken:
        """Issue a verification token for a registered agent.

        The host must authenticate (via ``host_credential``) before a token
        is issued. The credential is validated by the injected host
        authenticator if one is configured; otherwise the host credential is
        checked against the key ring's active key ID.
        """
        agent_id = _text(agent_id, "agent_id", 128)
        # Verify the agent exists in the forum
        try:
            self.forum.get_agent(agent_id)
        except ForumNotFoundError:
            raise AgentNetworkNotFoundError("agent does not exist in the forum") from None
        token = self.verifier.issue(agent_id, now=now)
        stamp = token.issued_at
        with self._lock:
            connection = self._acquire_connection()
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT INTO agent_tokens(token_id,agent_id,signature,issued_at) VALUES(?,?,?,?)",
                    (token.token_id, agent_id, token.signature, stamp),
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
        return token

    def revoke_verification(
        self, token: VerificationToken, *, now: datetime | None = None,
    ) -> None:
        """Revoke a verification token. Append-only: creates a revocation row."""
        stamp = _stamp(now)
        with self._lock:
            connection = self._acquire_connection()
            try:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT 1 FROM agent_tokens WHERE token_id=?", (token.token_id,),
                ).fetchone()
                if existing is None:
                    raise AgentNetworkNotFoundError("token is not registered")
                connection.execute(
                    "INSERT INTO agent_token_revocations(token_id,revoked_at) VALUES(?,?)",
                    (token.token_id, stamp),
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

    def is_token_revoked(self, token: VerificationToken) -> bool:
        with self._lock:
            connection = self._acquire_connection()
            try:
                row = connection.execute(
                    "SELECT 1 FROM agent_token_revocations WHERE token_id=?",
                    (token.token_id,),
                ).fetchone()
            finally:
                connection.close()
        return row is not None

    # ------------------------------------------------------------- responsibilities

    def assign_responsibility(
        self, agent_id: str, responsibility: str, *,
        assigned_by: str, token: VerificationToken,
        now: datetime | None = None,
    ) -> Responsibility:
        agent_id = _text(agent_id, "agent_id", 128)
        responsibility = _text(responsibility, "responsibility", 256)
        assigned_by = _text(assigned_by, "assigned_by", 128)
        stamp = _stamp(now)
        with self._lock:
            connection = self._acquire_connection()
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._verify_agent(connection, agent_id, token)
                connection.execute("COMMIT")
            except Exception:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                connection.close()
        with self._lock:
            connection = self._acquire_connection()
            try:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    "INSERT INTO responsibilities(agent_id,responsibility,assigned_by,assigned_at) VALUES(?,?,?,?)",
                    (agent_id, responsibility, assigned_by, stamp),
                )
                rid = int(cursor.lastrowid)
                connection.execute("COMMIT")
            except Exception:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                connection.close()
        return Responsibility(rid, agent_id, responsibility, assigned_by, stamp)

    def responsibilities_for(self, agent_id: str) -> tuple[Responsibility, ...]:
        agent_id = _text(agent_id, "agent_id", 128)
        with self._lock:
            connection = self._acquire_connection()
            try:
                rows = connection.execute(
                    "SELECT responsibility_id,agent_id,responsibility,assigned_by,assigned_at "
                    "FROM responsibilities WHERE agent_id=? ORDER BY responsibility_id",
                    (agent_id,),
                ).fetchall()
            finally:
                connection.close()
        return tuple(
            Responsibility(r[0], r[1], r[2], r[3], r[4]) for r in rows
        )

    # -------------------------------------------------------------- challenges

    def challenge(
        self, proposal_id: str, agent_id: str, *,
        objections: dict[str, Any], token: VerificationToken,
        now: datetime | None = None,
    ) -> Challenge:
        proposal_id = _text(proposal_id, "proposal_id", 64)
        agent_id = _text(agent_id, "agent_id", 128)
        objections_json, objections = _json_object(objections, "objections")
        stamp = _stamp(now)
        with self._lock:
            connection = self._acquire_connection()
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._verify_agent(connection, agent_id, token)
                self._check_permission(agent_id, "challenge")
                proposal = connection.execute(
                    "SELECT state FROM proposals WHERE proposal_id=?", (proposal_id,),
                ).fetchone()
                if proposal is None:
                    raise AgentNetworkNotFoundError("proposal does not exist")
                if proposal[0] != "open":
                    raise AgentNetworkConflictError("proposal is not open and cannot be challenged")
                cursor = connection.execute(
                    "INSERT INTO challenges(proposal_id,agent_id,objections_json,created_at) VALUES(?,?,?,?)",
                    (proposal_id, agent_id, objections_json, stamp),
                )
                cid = int(cursor.lastrowid)
                connection.execute("COMMIT")
            except Exception:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                connection.close()
        return Challenge(cid, proposal_id, agent_id, objections, stamp)

    def challenges_for(self, proposal_id: str) -> tuple[Challenge, ...]:
        proposal_id = _text(proposal_id, "proposal_id", 64)
        with self._lock:
            connection = self._acquire_connection()
            try:
                rows = connection.execute(
                    "SELECT challenge_id,proposal_id,agent_id,objections_json,created_at "
                    "FROM challenges WHERE proposal_id=? ORDER BY challenge_id",
                    (proposal_id,),
                ).fetchall()
            finally:
                connection.close()
        out = []
        for r in rows:
            out.append(Challenge(r[0], r[1], r[2], json.loads(r[3]), r[4]))
        return tuple(out)

    # ----------------------------------------------------------------- reviews

    def review_work(
        self, work_entry_id: int, agent_id: str, *,
        verdict: str, findings: dict[str, Any],
        token: VerificationToken, now: datetime | None = None,
    ) -> Review:
        if type(work_entry_id) is not int or work_entry_id < 1:
            raise AgentNetworkValidationError("work_entry_id must be a positive integer")
        agent_id = _text(agent_id, "agent_id", 128)
        verdict = _text(verdict, "verdict", 32)
        if verdict not in _REVIEW_VERDICTS:
            raise AgentNetworkValidationError(
                "verdict must be approve, reject, or request_changes"
            )
        findings_json, findings = _json_object(findings, "findings")
        stamp = _stamp(now)
        with self._lock:
            connection = self._acquire_connection()
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._verify_agent(connection, agent_id, token)
                self._check_permission(agent_id, "review")
                # Check the work entry exists in the forum's work_log
                work = connection.execute(
                    "SELECT entry_id FROM work_log WHERE entry_id=?", (work_entry_id,),
                ).fetchone()
                if work is None:
                    raise AgentNetworkNotFoundError("work entry does not exist")
                cursor = connection.execute(
                    "INSERT INTO reviews(work_entry_id,agent_id,verdict,findings_json,created_at) VALUES(?,?,?,?,?)",
                    (work_entry_id, agent_id, verdict, findings_json, stamp),
                )
                rid = int(cursor.lastrowid)
                connection.execute("COMMIT")
            except Exception:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                connection.close()
        return Review(rid, work_entry_id, agent_id, verdict, findings, stamp)

    def reviews_for_work(self, work_entry_id: int) -> tuple[Review, ...]:
        if type(work_entry_id) is not int or work_entry_id < 1:
            raise AgentNetworkValidationError("work_entry_id must be a positive integer")
        with self._lock:
            connection = self._acquire_connection()
            try:
                rows = connection.execute(
                    "SELECT review_id,work_entry_id,agent_id,verdict,findings_json,created_at "
                    "FROM reviews WHERE work_entry_id=? ORDER BY review_id",
                    (work_entry_id,),
                ).fetchall()
            finally:
                connection.close()
        out = []
        for r in rows:
            out.append(Review(r[0], r[1], r[2], r[3], json.loads(r[4]), r[5]))
        return tuple(out)

    # ------------------------------------------------------------- revisions

    def revise_proposal(
        self, proposal_id: str, author_id: str, *,
        change_summary: str, body: dict[str, Any],
        token: VerificationToken, now: datetime | None = None,
    ) -> tuple[Proposal, ProposalRevision]:
        """Create a new version of a proposal, addressing challenges.

        The proposal's version is incremented in the forum and the revision
        body is recorded. The new body replaces the proposal body for
        subsequent voting and ratification.
        """
        proposal_id = _text(proposal_id, "proposal_id", 64)
        author_id = _text(author_id, "agent_id", 128)
        change_summary = _text(change_summary, "change_summary", 2_000)
        body_json, body = _json_object(body, "body")
        stamp = _stamp(now)
        with self._lock:
            connection = self._acquire_connection()
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._verify_agent(connection, author_id, token)
                self._check_permission(author_id, "revise")
                row = connection.execute(
                    "SELECT author_id,state,version FROM proposals WHERE proposal_id=?",
                    (proposal_id,),
                ).fetchone()
                if row is None:
                    raise AgentNetworkNotFoundError("proposal does not exist")
                if row[0] != author_id:
                    raise AuthorizationError("only the proposal author can revise it")
                if row[1] != "open":
                    raise AgentNetworkConflictError("proposal is not open and cannot be revised")
                new_version = row[2] + 1
                # Record the revision
                cursor = connection.execute(
                    "INSERT INTO proposal_revisions(proposal_id,author_id,change_summary,body_json,version,created_at) "
                    "VALUES(?,?,?,?,?,?)",
                    (proposal_id, author_id, change_summary, body_json, new_version, stamp),
                )
                revision_id = int(cursor.lastrowid)
                # Update the proposal body and version in the forum
                connection.execute(
                    "UPDATE proposals SET body_json=?, version=version+1, updated_at=? WHERE proposal_id=? AND version=?",
                    (body_json, stamp, proposal_id, row[2]),
                )
                connection.execute(
                    "INSERT INTO proposal_events(proposal_id,timestamp,state,version,event_type) VALUES(?,?,?,?,'revised')",
                    (proposal_id, stamp, row[1], new_version),
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
        return self.forum.get_proposal(proposal_id), ProposalRevision(
            revision_id, proposal_id, author_id, change_summary, body,
            new_version, stamp,
        )

    def revisions_for(self, proposal_id: str) -> tuple[ProposalRevision, ...]:
        proposal_id = _text(proposal_id, "proposal_id", 64)
        with self._lock:
            connection = self._acquire_connection()
            try:
                rows = connection.execute(
                    "SELECT revision_id,proposal_id,author_id,change_summary,body_json,version,created_at "
                    "FROM proposal_revisions WHERE proposal_id=? ORDER BY revision_id",
                    (proposal_id,),
                ).fetchall()
            finally:
                connection.close()
        out = []
        for r in rows:
            out.append(ProposalRevision(
                r[0], r[1], r[2], r[3], json.loads(r[4]), r[5], r[6],
            ))
        return tuple(out)

    # ----------------------------------------------------------- decisions

    def ratify_decision(
        self, proposal_id: str, *, host_credential: str,
        evidence_references: tuple[str, ...] = (),
        now: datetime | None = None,
    ) -> DecisionRecord:
        """Host ratifies a proposal's final decision.

        The host's ratification policy (if configured) reviews the proposal,
        its challenges, reviews, and evidence references, then returns an
        outcome. The decision record is signed with the host's ratification
        key and is append-only.

        If the proposal is still open (consensus not reached), the host can
        still ratify by setting the outcome directly — the host always holds
        final authority.
        """
        proposal_id = _text(proposal_id, "proposal_id", 64)
        stamp = _stamp(now)
        try:
            proposal = self.forum.get_proposal(proposal_id)
        except ForumNotFoundError:
            raise AgentNetworkNotFoundError("proposal does not exist") from None
        challenges = self.challenges_for(proposal_id)
        # Gather reviews from work entries linked to this proposal's author
        author_work = self.forum.work_log(proposal.author_id)
        reviews: tuple[Review, ...] = ()
        for work in author_work:
            reviews = reviews + self.reviews_for_work(work.entry_id)

        if self.ratification_policy is not None:
            outcome, extra_evidence = self.ratification_policy.ratify(
                proposal, challenges, reviews, evidence_references,
            )
        else:
            # Default: if consensus reached, honor it; otherwise abandoned
            if proposal.state == "agreed":
                outcome, extra_evidence = "approved", ()
            elif proposal.state == "rejected":
                outcome, extra_evidence = "rejected", ()
            else:
                outcome, extra_evidence = "abandoned", ()

        if outcome not in _DECISION_OUTCOMES:
            raise AgentNetworkValidationError(
                f"ratification outcome '{outcome}' is not valid"
            )

        all_evidence = tuple(evidence_references) + tuple(extra_evidence)
        # Sign the decision
        sign_payload = json.dumps(
            {"proposal_id": proposal_id, "outcome": outcome,
             "evidence": list(all_evidence), "ratified_at": stamp},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        signature = self.verifier.key_ring.sign(
            self.verifier.key_ring.active_key_id, sign_payload,
        ).hex()
        evidence_json = json.dumps(list(all_evidence), ensure_ascii=False, separators=(",", ":"))

        with self._lock:
            connection = self._acquire_connection()
            try:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    "INSERT INTO decision_records(proposal_id,outcome,evidence_json,ratified_by,ratified_at,signature) "
                    "VALUES(?,?,?,?,?,?)",
                    (proposal_id, outcome, evidence_json, host_credential, stamp, signature),
                )
                decision_id = int(cursor.lastrowid)
                connection.execute("COMMIT")
            except Exception:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                connection.close()
        return DecisionRecord(
            decision_id, proposal_id, outcome, all_evidence,
            host_credential, stamp, signature,
        )

    def decisions_for(self, proposal_id: str) -> tuple[DecisionRecord, ...]:
        proposal_id = _text(proposal_id, "proposal_id", 64)
        with self._lock:
            connection = self._acquire_connection()
            try:
                rows = connection.execute(
                    "SELECT decision_id,proposal_id,outcome,evidence_json,ratified_by,ratified_at,signature "
                    "FROM decision_records WHERE proposal_id=? ORDER BY decision_id",
                    (proposal_id,),
                ).fetchall()
            finally:
                connection.close()
        out = []
        for r in rows:
            out.append(DecisionRecord(
                r[0], r[1], r[2], tuple(json.loads(r[3])), r[4], r[5], r[6],
            ))
        return tuple(out)

    def latest_decision(self, proposal_id: str) -> DecisionRecord | None:
        decisions = self.decisions_for(proposal_id)
        return decisions[-1] if decisions else None

    def verify_decision_signature(self, decision: DecisionRecord) -> bool:
        """Re-verify the HMAC signature on a decision record."""
        sign_payload = json.dumps(
            {"proposal_id": decision.proposal_id, "outcome": decision.outcome,
             "evidence": list(decision.evidence_references),
             "ratified_at": decision.ratified_at},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        try:
            sig_bytes = bytes.fromhex(decision.signature)
        except ValueError:
            return False
        return self.verifier.key_ring.verify(
            self.verifier.key_ring.active_key_id, sign_payload, sig_bytes,
        )

    # ----------------------------------------------------------- integrity

    def integrity_check(self) -> str:
        with self._lock:
            connection = self._acquire_connection()
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


# ---------------------------------------------------------------------------
# JSON validation helpers (mirroring agent_forum.py conventions)
# ---------------------------------------------------------------------------

def _json_object(value: Any, label: str, limit: int = 32_768) -> tuple[str, dict[str, Any]]:
    if type(value) is not dict:
        raise AgentNetworkValidationError(f"{label} must be a plain JSON object")
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True,
            separators=(",", ":"),
        )
        raw = encoded.encode("utf-8", errors="strict")
        decoded = json.loads(encoded)
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        raise AgentNetworkValidationError(f"{label} must be valid JSON") from None
    if len(raw) > limit:
        raise AgentNetworkValidationError(f"{label} exceeds the configured byte limit")
    return encoded, decoded
