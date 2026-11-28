"""Durable inter-agent communication, consensus, and skill improvement.

This module is the agreement substrate for a fleet of Capri agents that work
together over long horizons. It is deliberately data-only: proposing an idea,
voting on it, logging work, or recording a skill improvement never grants
permission or invokes a tool. A trusted host validates any decision against
its current allowlist before the resulting plan is executed.

Design goals, in the same spirit as ``goals.py``:

- **Communication**: agents register an identity, propose ideas, and record
  what they actually did (work logs) so other agents can build on it.
- **Consensus**: other agents can agree, disagree, or abstain on a proposal.
  A proposal reaches a decided state when the vote count crosses a quorum,
  so a group converges on which ideas to pursue without a central authority.
- **Continuous work**: work logs and skill ledger entries are append-only and
  durable, so an agent can keep working across restarts and improve the skills
  it uses the longer it runs.
- **Profound ideas**: a proposal may be marked ``profound`` to flag ideas with
  exceptional rationale; the ledger keeps the reasoning so it can be re-read.

All records are principal-scoped and immutable where it matters; votes, work
logs, and skill entries are append-only via triggers. Backups are validated.
"""
from __future__ import annotations

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


class ForumError(Exception):
    """Base class for expected forum-store failures."""


class ForumValidationError(ForumError):
    """A record or persisted value is invalid."""


class ForumConflictError(ForumError):
    """A record changed or its requested lifecycle transition is invalid."""


class ForumNotFoundError(ForumError):
    """The record does not exist or is not owned by the given agent."""


_PROPOSAL_STATES = {"open", "agreed", "rejected", "superseded"}
_DECISIONS = {"agree", "disagree", "abstain"}


def _text(value: Any, label: str, limit: int) -> str:
    if type(value) is not str or not value.strip() or len(value) > limit or contains_surrogate(value):
        raise ForumValidationError(f"{label} is invalid")
    return value


def _json_object(value: Any, label: str, limit: int = 32_768) -> tuple[str, dict[str, Any]]:
    if type(value) is not dict:
        raise ForumValidationError(f"{label} must be a plain JSON object")
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True,
            separators=(",", ":"),
        )
        raw = encoded.encode("utf-8", errors="strict")
        decoded = json.loads(encoded)
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        raise ForumValidationError(f"{label} must be valid JSON") from None
    if len(raw) > limit:
        raise ForumValidationError(f"{label} exceeds the configured byte limit")
    return encoded, decoded


def _json_value(value: Any, depth: int = 0) -> None:
    if depth > 12:
        raise ForumValidationError("forum JSON nesting exceeds 12 levels")
    if value is None or type(value) in (bool, int, float):
        if type(value) is float and (value != value or value in (float("inf"), float("-inf"))):
            raise ForumValidationError("forum JSON numbers must be finite")
        return
    if type(value) is str:
        if contains_surrogate(value):
            raise ForumValidationError("forum JSON strings must contain Unicode scalar values")
        return
    if type(value) is list:
        for item in value:
            _json_value(item, depth + 1)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ForumValidationError("forum JSON object keys must be strings")
            _json_value(key, depth + 1)
            _json_value(item, depth + 1)
        return
    raise ForumValidationError("forum record contains a non-JSON value")


def _capabilities(value: Any) -> tuple[str, ...]:
    if type(value) not in (list, tuple):
        raise ForumValidationError("capabilities must be a list of strings")
    result = []
    for item in value:
        result.append(_text(item, "capability", 64))
    if len(set(result)) != len(result):
        raise ForumValidationError("capabilities must not contain duplicates")
    if len(result) > 64:
        raise ForumValidationError("capabilities are limited to 64 entries")
    return tuple(result)


def _confidence(value: Any) -> float:
    if type(value) is not float or not (0.0 <= value <= 1.0):
        raise ForumValidationError("confidence must be a float between 0.0 and 1.0")
    return value


def _stamp(value: datetime | None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ForumValidationError("timestamps must be timezone-aware")
    return current.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class AgentProfile:
    agent_id: str
    display_name: str
    capabilities: tuple[str, ...]
    created_at: str
    version: int


@dataclass(frozen=True, slots=True)
class Proposal:
    proposal_id: str
    author_id: str
    title: str
    body: dict[str, Any]
    rationale: str
    profound: bool
    state: str
    version: int
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class Vote:
    vote_id: int
    proposal_id: str
    agent_id: str
    decision: str
    rationale: str
    created_at: str


@dataclass(frozen=True, slots=True)
class WorkEntry:
    entry_id: int
    agent_id: str
    summary: str
    detail: dict[str, Any]
    created_at: str


@dataclass(frozen=True, slots=True)
class SkillEntry:
    entry_id: int
    agent_id: str
    skill_name: str
    note: str
    confidence: float
    evidence_reference: str
    created_at: str


@runtime_checkable
class ConsensusPolicy(Protocol):
    """Host-injected policy that decides when a proposal has consensus.

    It receives the current vote tally and returns one of the decided
    states, or ``None`` to leave the proposal open. It returns data only.
    """

    def decide(
        self, agree: int, disagree: int, abstain: int, eligible: int
    ) -> str | None:
        """Return ``'agreed'``/``'rejected'`` or ``None`` to stay open."""


class MajorityConsensus:
    """Default policy: agree wins when a strict majority of eligible agents agree.

    ``eligible`` is the number of registered agents; ``None`` is returned
    until at least one vote is cast, so an unvoted proposal stays open.
    """

    def decide(
        self, agree: int, disagree: int, abstain: int, eligible: int
    ) -> str | None:
        if agree == 0 and disagree == 0:
            return None
        if eligible <= 0:
            return "agreed" if agree > 0 else "rejected"
        if agree * 2 > eligible:
            return "agreed"
        if disagree * 2 > eligible:
            return "rejected"
        return None


class SQLiteAgentForum:
    """Private SQLite store for agent identities, proposals, and durable logs."""

    def __init__(self, path: str, consensus: ConsensusPolicy | None = None) -> None:
        _text(path, "database path", 4096)
        absolute = os.path.abspath(path)
        parent = os.path.dirname(absolute)
        if not os.path.isdir(parent) or os.path.realpath(parent) != parent:
            raise ForumValidationError("database parent must be an existing non-symlink directory")
        parent_stat = os.stat(parent, follow_symlinks=False)
        if not stat.S_ISDIR(parent_stat.st_mode):
            raise ForumValidationError("database parent must be a directory")
        if os.name == "posix" and (
            parent_stat.st_uid != os.geteuid() or stat.S_IMODE(parent_stat.st_mode) & 0o077
        ):
            raise ForumValidationError("database parent must be owned by the current user and private")
        if os.path.lexists(absolute):
            existing = os.lstat(absolute)
            if not stat.S_ISREG(existing.st_mode):
                raise ForumValidationError("database path must be a regular non-symlink file")
            if os.name == "posix" and (existing.st_uid != os.geteuid() or existing.st_nlink != 1):
                raise ForumValidationError("database ownership or link count is unsafe")
        try:
            descriptor = os.open(absolute, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        except OSError:
            raise ForumValidationError("database file could not be opened safely") from None
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise ForumValidationError("database path must be a regular file")
            if os.name == "posix":
                if opened.st_uid != os.geteuid() or opened.st_nlink != 1:
                    raise ForumValidationError("database ownership or link count is unsafe")
                os.fchmod(descriptor, 0o600)
        finally:
            os.close(descriptor)
        self.path = absolute
        self.consensus = consensus or MajorityConsensus()
        if not isinstance(self.consensus, ConsensusPolicy):
            raise ForumValidationError("consensus must implement ConsensusPolicy")
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        parent = os.path.dirname(self.path)
        if os.path.realpath(parent) != parent:
            raise ForumValidationError("database parent changed")
        if os.name == "posix":
            info = os.lstat(self.path)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077):
                raise ForumValidationError("database file identity changed")
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("""CREATE TABLE IF NOT EXISTS agents (
                    agent_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    capabilities_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    version INTEGER NOT NULL
                )""")
                connection.execute("""CREATE TABLE IF NOT EXISTS proposals (
                    proposal_id TEXT PRIMARY KEY,
                    author_id TEXT NOT NULL REFERENCES agents(agent_id) ON DELETE RESTRICT,
                    title TEXT NOT NULL,
                    body_json TEXT NOT NULL DEFAULT '{}',
                    rationale TEXT NOT NULL DEFAULT '',
                    profound INTEGER NOT NULL DEFAULT 0,
                    state TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )""")
                eligibility_table_exists = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='proposal_eligible_voters'"
                ).fetchone() is not None
                connection.execute("""CREATE TABLE IF NOT EXISTS proposal_eligible_voters (
                    proposal_id TEXT NOT NULL REFERENCES proposals(proposal_id) ON DELETE RESTRICT,
                    agent_id TEXT NOT NULL REFERENCES agents(agent_id) ON DELETE RESTRICT,
                    PRIMARY KEY(proposal_id, agent_id)
                )""")
                if not eligibility_table_exists:
                    # Upgrade legacy forums once: freeze the currently registered
                    # roster for every existing proposal. New proposals snapshot
                    # their roster atomically in propose().
                    connection.execute(
                        """INSERT OR IGNORE INTO proposal_eligible_voters(proposal_id,agent_id)
                        SELECT proposals.proposal_id, agents.agent_id
                        FROM proposals CROSS JOIN agents"""
                    )
                connection.execute("""CREATE TRIGGER IF NOT EXISTS proposal_eligible_voters_immutable_update
                    BEFORE UPDATE ON proposal_eligible_voters
                    BEGIN SELECT RAISE(ABORT, 'proposal voter snapshots are immutable'); END""")
                connection.execute("""CREATE TRIGGER IF NOT EXISTS proposal_eligible_voters_immutable_delete
                    BEFORE DELETE ON proposal_eligible_voters
                    BEGIN SELECT RAISE(ABORT, 'proposal voter snapshots are immutable'); END""")
                connection.execute("""CREATE TABLE IF NOT EXISTS proposal_votes (
                    vote_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    proposal_id TEXT NOT NULL REFERENCES proposals(proposal_id) ON DELETE RESTRICT,
                    agent_id TEXT NOT NULL REFERENCES agents(agent_id) ON DELETE RESTRICT,
                    decision TEXT NOT NULL,
                    rationale TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(proposal_id, agent_id)
                )""")
                connection.execute("""CREATE TABLE IF NOT EXISTS proposal_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    proposal_id TEXT NOT NULL REFERENCES proposals(proposal_id) ON DELETE RESTRICT,
                    timestamp TEXT NOT NULL,
                    state TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    event_type TEXT NOT NULL
                )""")
                connection.execute("""CREATE TABLE IF NOT EXISTS work_log (
                    entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT NOT NULL REFERENCES agents(agent_id) ON DELETE RESTRICT,
                    summary TEXT NOT NULL,
                    detail_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )""")
                connection.execute("""CREATE TABLE IF NOT EXISTS skill_ledger (
                    entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT NOT NULL REFERENCES agents(agent_id) ON DELETE RESTRICT,
                    skill_name TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL,
                    evidence_reference TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )""")
                connection.execute("CREATE INDEX IF NOT EXISTS vote_proposal_idx ON proposal_votes(proposal_id)")
                connection.execute("CREATE INDEX IF NOT EXISTS vote_agent_idx ON proposal_votes(agent_id)")
                connection.execute("CREATE INDEX IF NOT EXISTS work_agent_idx ON work_log(agent_id, entry_id)")
                connection.execute("CREATE INDEX IF NOT EXISTS skill_agent_idx ON skill_ledger(agent_id, skill_name, entry_id)")
                for table, table_type in (
                    ("proposal_votes", "votes"), ("proposal_events", "events"),
                    ("work_log", "work logs"), ("skill_ledger", "skill entries"),
                ):
                    connection.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_immutable_update\
                        BEFORE UPDATE ON {table}\
                        BEGIN SELECT RAISE(ABORT, '{table_type} are append-only'); END")
                    connection.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_immutable_delete\
                        BEFORE DELETE ON {table}\
                        BEGIN SELECT RAISE(ABORT, '{table_type} are append-only'); END")
            finally:
                connection.close()

    # ------------------------------------------------------------------ agents

    def register_agent(
        self, agent_id: str, display_name: str, *,
        capabilities: list[str] | tuple[str, ...] = (), now: datetime | None = None,
    ) -> AgentProfile:
        agent_id = _text(agent_id, "agent_id", 128)
        display_name = _text(display_name, "display_name", 128)
        caps = _capabilities(capabilities)
        caps_json = json.dumps(caps, ensure_ascii=False, separators=(",", ":"))
        stamp = _stamp(now)
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT version FROM agents WHERE agent_id=?", (agent_id,),
                ).fetchone()
                if existing is not None:
                    connection.execute("COMMIT")
                    return self.get_agent(agent_id)
                connection.execute(
                    "INSERT INTO agents(agent_id,display_name,capabilities_json,created_at,version) VALUES(?,?,?,?,1)",
                    (agent_id, display_name, caps_json, stamp),
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
        return self.get_agent(agent_id)

    def get_agent(self, agent_id: str) -> AgentProfile:
        agent_id = _text(agent_id, "agent_id", 128)
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute(
                    "SELECT agent_id,display_name,capabilities_json,created_at,version FROM agents WHERE agent_id=?",
                    (agent_id,),
                ).fetchone()
            finally:
                connection.close()
        if row is None:
            raise ForumNotFoundError("agent does not exist")
        try:
            caps = json.loads(row[2])
            if type(caps) is not list:
                raise ValueError
        except (TypeError, ValueError):
            raise ForumValidationError("persisted agent capabilities are corrupt") from None
        return AgentProfile(row[0], row[1], tuple(caps), row[3], row[4])

    def list_agents(self) -> tuple[AgentProfile, ...]:
        with self._lock:
            connection = self._connect()
            try:
                rows = connection.execute(
                    "SELECT agent_id,display_name,capabilities_json,created_at,version FROM agents ORDER BY agent_id"
                ).fetchall()
            finally:
                connection.close()
        out = []
        for row in rows:
            caps = json.loads(row[2])
            out.append(AgentProfile(row[0], row[1], tuple(caps), row[3], row[4]))
        return tuple(out)

    def _agent_exists(self, connection: sqlite3.Connection, agent_id: str) -> bool:
        return connection.execute(
            "SELECT 1 FROM agents WHERE agent_id=?", (agent_id,),
        ).fetchone() is not None

    # ---------------------------------------------------------------- proposals

    def propose(
        self, author_id: str, title: str, body: dict[str, Any], *,
        rationale: str = "", profound: bool = False,
        eligible_voter_ids: list[str] | tuple[str, ...] | None = None,
        now: datetime | None = None,
    ) -> Proposal:
        author_id = _text(author_id, "author_id", 128)
        title = _text(title, "title", 200)
        body_json, body = _json_object(body, "body")
        rationale = _text(rationale, "rationale", 2_000) if rationale else ""
        if type(profound) is not bool:
            raise ForumValidationError("profound must be a boolean")
        if eligible_voter_ids is not None:
            if type(eligible_voter_ids) not in (list, tuple) or not eligible_voter_ids:
                raise ForumValidationError("eligible_voter_ids must be a non-empty list or tuple")
            eligible = tuple(
                _text(agent_id, "eligible voter agent_id", 128)
                for agent_id in eligible_voter_ids
            )
            if len(eligible) > 1024 or len(set(eligible)) != len(eligible):
                raise ForumValidationError("eligible voter roster is too large or contains duplicates")
            if author_id not in eligible:
                raise ForumValidationError("proposal author must be included in the eligible voter roster")
        else:
            eligible = None
        stamp = _stamp(now)
        proposal_id = str(uuid4())
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                if not self._agent_exists(connection, author_id):
                    raise ForumNotFoundError("author agent does not exist")
                if eligible is None:
                    voter_ids = tuple(
                        row[0] for row in connection.execute(
                            "SELECT agent_id FROM agents ORDER BY agent_id"
                        ).fetchall()
                    )
                else:
                    voter_ids = eligible
                    registered = {
                        row[0] for row in connection.execute(
                            "SELECT agent_id FROM agents"
                        ).fetchall()
                    }
                    if not set(voter_ids).issubset(registered):
                        raise ForumNotFoundError("eligible voter roster contains an unknown agent")
                connection.execute(
                    """INSERT INTO proposals(proposal_id,author_id,title,body_json,rationale,profound,state,version,created_at,updated_at)
                    VALUES(?,?,?,?,?,?, 'open', 1, ?, ?)""",
                    (proposal_id, author_id, title, body_json, rationale, 1 if profound else 0, stamp, stamp),
                )
                connection.execute(
                    "INSERT INTO proposal_events(proposal_id,timestamp,state,version,event_type) VALUES(?,?,'open',1,'created')",
                    (proposal_id, stamp),
                )
                connection.executemany(
                    "INSERT INTO proposal_eligible_voters(proposal_id,agent_id) VALUES(?,?)",
                    ((proposal_id, agent_id) for agent_id in voter_ids),
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
        return self.get_proposal(proposal_id)

    @staticmethod
    def _proposal_row(row: tuple[Any, ...]) -> Proposal:
        try:
            body = json.loads(row[3])
            if type(body) is not dict:
                raise ValueError
            if row[6] not in _PROPOSAL_STATES or type(row[7]) is not int or row[7] < 1:
                raise ValueError
            _json_value(body)
        except (TypeError, ValueError, ForumValidationError):
            raise ForumValidationError("persisted proposal is corrupt") from None
        return Proposal(
            row[0], row[1], row[2], body, row[4], bool(row[5]), row[6], row[7], row[8], row[9],
        )

    def get_proposal(self, proposal_id: str) -> Proposal:
        proposal_id = _text(proposal_id, "proposal_id", 64)
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute(
                    "SELECT proposal_id,author_id,title,body_json,rationale,profound,state,version,created_at,updated_at FROM proposals WHERE proposal_id=?",
                    (proposal_id,),
                ).fetchone()
            finally:
                connection.close()
        if row is None:
            raise ForumNotFoundError("proposal does not exist")
        return self._proposal_row(row)

    def list_proposals(self, state: str | None = None) -> tuple[Proposal, ...]:
        with self._lock:
            connection = self._connect()
            try:
                if state is None:
                    rows = connection.execute(
                        "SELECT proposal_id,author_id,title,body_json,rationale,profound,state,version,created_at,updated_at FROM proposals ORDER BY created_at, proposal_id"
                    ).fetchall()
                else:
                    state = _text(state, "state", 32)
                    if state not in _PROPOSAL_STATES:
                        raise ForumValidationError("proposal state is unsupported")
                    rows = connection.execute(
                        """SELECT proposal_id,author_id,title,body_json,rationale,profound,state,version,created_at,updated_at
                        FROM proposals WHERE state=? ORDER BY created_at, proposal_id""",
                        (state,),
                    ).fetchall()
            finally:
                connection.close()
        return tuple(self._proposal_row(row) for row in rows)

    # ------------------------------------------------------------------- votes

    def vote(
        self, proposal_id: str, agent_id: str, decision: str, *,
        rationale: str = "", now: datetime | None = None,
    ) -> tuple[Proposal, Vote]:
        proposal_id = _text(proposal_id, "proposal_id", 64)
        agent_id = _text(agent_id, "agent_id", 128)
        decision = _text(decision, "decision", 32)
        if decision not in _DECISIONS:
            raise ForumValidationError("decision must be agree, disagree, or abstain")
        rationale = _text(rationale, "rationale", 2_000) if rationale else ""
        stamp = _stamp(now)
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                proposal = connection.execute(
                    "SELECT state,version FROM proposals WHERE proposal_id=?", (proposal_id,),
                ).fetchone()
                if proposal is None:
                    raise ForumNotFoundError("proposal does not exist")
                existing = connection.execute(
                    "SELECT vote_id,decision,rationale FROM proposal_votes WHERE proposal_id=? AND agent_id=?",
                    (proposal_id, agent_id),
                ).fetchone()
                if existing is not None:
                    if existing[1] != decision or existing[2] != rationale:
                        raise ForumConflictError("agent has already cast a different vote")
                    # An exact retry remains idempotent even after this vote
                    # finalized the proposal. A conflicting retry never does.
                    connection.execute("COMMIT")
                    return self.get_proposal(proposal_id), self.get_vote(existing[0])
                if proposal[0] != "open":
                    raise ForumConflictError("proposal is not open and cannot accept votes")
                eligible = connection.execute(
                    "SELECT 1 FROM proposal_eligible_voters WHERE proposal_id=? AND agent_id=?",
                    (proposal_id, agent_id),
                ).fetchone()
                if eligible is None:
                    raise ForumNotFoundError("voting agent is not eligible for this proposal")
                cursor = connection.execute(
                    """INSERT INTO proposal_votes(proposal_id,agent_id,decision,rationale,created_at)
                    VALUES(?,?,?,?,?)""",
                    (proposal_id, agent_id, decision, rationale, stamp),
                )
                vote_id = int(cursor.lastrowid)
                connection.execute("COMMIT")
            except Exception:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                connection.close()
        proposal = self.resolve_consensus(proposal_id)
        return proposal, self.get_vote(vote_id)

    def get_vote(self, vote_id: int) -> Vote:
        if type(vote_id) is not int or vote_id < 1:
            raise ForumValidationError("vote_id must be a positive integer")
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute(
                    "SELECT vote_id,proposal_id,agent_id,decision,rationale,created_at FROM proposal_votes WHERE vote_id=?",
                    (vote_id,),
                ).fetchone()
            finally:
                connection.close()
        if row is None:
            raise ForumNotFoundError("vote does not exist")
        return Vote(row[0], row[1], row[2], row[3], row[4], row[5])

    def votes_for(self, proposal_id: str) -> tuple[Vote, ...]:
        proposal_id = _text(proposal_id, "proposal_id", 64)
        with self._lock:
            connection = self._connect()
            try:
                rows = connection.execute(
                    "SELECT vote_id,proposal_id,agent_id,decision,rationale,created_at FROM proposal_votes WHERE proposal_id=? ORDER BY vote_id",
                    (proposal_id,),
                ).fetchall()
            finally:
                connection.close()
        return tuple(Vote(r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows)

    def _tally(self, connection: sqlite3.Connection, proposal_id: str) -> tuple[int, int, int]:
        agree = connection.execute(
            "SELECT COUNT(*) FROM proposal_votes WHERE proposal_id=? AND decision='agree'", (proposal_id,),
        ).fetchone()[0]
        disagree = connection.execute(
            "SELECT COUNT(*) FROM proposal_votes WHERE proposal_id=? AND decision='disagree'", (proposal_id,),
        ).fetchone()[0]
        abstain = connection.execute(
            "SELECT COUNT(*) FROM proposal_votes WHERE proposal_id=? AND decision='abstain'", (proposal_id,),
        ).fetchone()[0]
        return agree, disagree, abstain

    def resolve_consensus(self, proposal_id: str) -> Proposal:
        """Resolve against the voter roster frozen when the proposal was created.

        Tally, eligible-voter count, and state transition share one IMMEDIATE
        transaction. Concurrent registration cannot change an in-flight
        proposal's quorum, and separate forum instances see the same snapshot.
        """
        proposal_id = _text(proposal_id, "proposal_id", 64)
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT state,version FROM proposals WHERE proposal_id=?",
                    (proposal_id,),
                ).fetchone()
                if row is None:
                    raise ForumNotFoundError("proposal does not exist")
                if row[0] != "open":
                    connection.execute("COMMIT")
                else:
                    agree, disagree, abstain = self._tally(connection, proposal_id)
                    eligible = connection.execute(
                        "SELECT COUNT(*) FROM proposal_eligible_voters WHERE proposal_id=?",
                        (proposal_id,),
                    ).fetchone()[0]
                    decided = self.consensus.decide(
                        agree, disagree, abstain, eligible
                    )
                    if decided not in {"agreed", "rejected"}:
                        connection.execute("COMMIT")
                    else:
                        stamp = _stamp(None)
                        cursor = connection.execute(
                            """UPDATE proposals
                            SET state=?, version=version+1, updated_at=?
                            WHERE proposal_id=? AND state='open' AND version=?""",
                            (decided, stamp, proposal_id, row[1]),
                        )
                        if cursor.rowcount != 1:
                            raise ForumConflictError(
                                "proposal version changed during consensus"
                            )
                        connection.execute(
                            """INSERT INTO proposal_events(
                                proposal_id,timestamp,state,version,event_type
                            ) VALUES(?,?,?,?,'consensus')""",
                            (proposal_id, stamp, decided, row[1] + 1),
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
        return self.get_proposal(proposal_id)

    def supersede(
        self, proposal_id: str, *, expected_version: int, now: datetime | None = None,
    ) -> Proposal:
        proposal_id = _text(proposal_id, "proposal_id", 64)
        if type(expected_version) is not int or expected_version < 1:
            raise ForumValidationError("expected_version must be a positive integer")
        stamp = _stamp(now)
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT state,version FROM proposals WHERE proposal_id=?", (proposal_id,),
                ).fetchone()
                if row is None:
                    raise ForumNotFoundError("proposal does not exist")
                if row[0] != "open" or row[1] != expected_version:
                    connection.execute("ROLLBACK")
                    raise ForumConflictError("proposal is not open at the expected version")
                connection.execute(
                    "UPDATE proposals SET state='superseded', version=version+1, updated_at=? WHERE proposal_id=? AND version=?",
                    (stamp, proposal_id, expected_version),
                )
                connection.execute(
                    "INSERT INTO proposal_events(proposal_id,timestamp,state,version,event_type) VALUES(?,?,'superseded',?,'superseded')",
                    (proposal_id, stamp, expected_version + 1),
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
        return self.get_proposal(proposal_id)

    # --------------------------------------------------------------- work + skill

    def record_work(
        self, agent_id: str, summary: str, *,
        detail: dict[str, Any] | None = None, now: datetime | None = None,
    ) -> WorkEntry:
        agent_id = _text(agent_id, "agent_id", 128)
        summary = _text(summary, "summary", 2_000)
        detail = {} if detail is None else detail
        detail_json, detail = _json_object(detail, "work detail")
        stamp = _stamp(now)
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                if not self._agent_exists(connection, agent_id):
                    raise ForumNotFoundError("agent does not exist")
                cursor = connection.execute(
                    "INSERT INTO work_log(agent_id,summary,detail_json,created_at) VALUES(?,?,?,?)",
                    (agent_id, summary, detail_json, stamp),
                )
                entry_id = int(cursor.lastrowid)
                connection.execute("COMMIT")
            except Exception:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                connection.close()
        return WorkEntry(entry_id, agent_id, summary, detail, stamp)

    def work_log(self, agent_id: str) -> tuple[WorkEntry, ...]:
        agent_id = _text(agent_id, "agent_id", 128)
        with self._lock:
            connection = self._connect()
            try:
                rows = connection.execute(
                    "SELECT entry_id,agent_id,summary,detail_json,created_at FROM work_log WHERE agent_id=? ORDER BY entry_id",
                    (agent_id,),
                ).fetchall()
            finally:
                connection.close()
        out = []
        for row in rows:
            detail = json.loads(row[3])
            out.append(WorkEntry(row[0], row[1], row[2], detail, row[4]))
        return tuple(out)

    def record_skill(
        self, agent_id: str, skill_name: str, *,
        note: str = "", confidence: float, evidence_reference: str = "",
        now: datetime | None = None,
    ) -> SkillEntry:
        agent_id = _text(agent_id, "agent_id", 128)
        skill_name = _text(skill_name, "skill_name", 128)
        note = _text(note, "note", 2_000) if note else ""
        confidence = _confidence(confidence)
        evidence_reference = _text(evidence_reference, "evidence_reference", 512) if evidence_reference else ""
        stamp = _stamp(now)
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                if not self._agent_exists(connection, agent_id):
                    raise ForumNotFoundError("agent does not exist")
                cursor = connection.execute(
                    "INSERT INTO skill_ledger(agent_id,skill_name,note,confidence,evidence_reference,created_at) VALUES(?,?,?,?,?,?)",
                    (agent_id, skill_name, note, confidence, evidence_reference, stamp),
                )
                entry_id = int(cursor.lastrowid)
                connection.execute("COMMIT")
            except Exception:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                connection.close()
        return SkillEntry(entry_id, agent_id, skill_name, note, confidence, evidence_reference, stamp)

    def skill_history(self, agent_id: str, skill_name: str) -> tuple[SkillEntry, ...]:
        agent_id = _text(agent_id, "agent_id", 128)
        skill_name = _text(skill_name, "skill_name", 128)
        with self._lock:
            connection = self._connect()
            try:
                rows = connection.execute(
                    "SELECT entry_id,agent_id,skill_name,note,confidence,evidence_reference,created_at FROM skill_ledger WHERE agent_id=? AND skill_name=? ORDER BY entry_id",
                    (agent_id, skill_name),
                ).fetchall()
            finally:
                connection.close()
        return tuple(
            SkillEntry(r[0], r[1], r[2], r[3], r[4], r[5], r[6]) for r in rows
        )

    def latest_skill_confidence(self, agent_id: str, skill_name: str) -> float | None:
        history = self.skill_history(agent_id, skill_name)
        return history[-1].confidence if history else None

    # ----------------------------------------------------------- integrity/backup

    @staticmethod
    def _validate_backup_snapshot(connection: sqlite3.Connection) -> None:
        agents = connection.execute("SELECT agent_id,display_name,capabilities_json,created_at,version FROM agents").fetchall()
        for agent_id, display_name, caps_json, created_at, version in agents:
            _text(agent_id, "agent_id", 128)
            _text(display_name, "display_name", 128)
            _text(created_at, "created_at", 64)
            if type(version) is not int or version < 1:
                raise ForumValidationError("agent backup contains an invalid version")
            try:
                caps = json.loads(caps_json)
                if type(caps) is not list:
                    raise ValueError
                _capabilities(caps)
            except (TypeError, ValueError, ForumValidationError):
                raise ForumValidationError("agent backup capabilities are corrupt") from None
        proposals = connection.execute(
            "SELECT proposal_id,author_id,title,body_json,rationale,profound,state,version,created_at,updated_at FROM proposals"
        ).fetchall()
        agent_ids = {row[0] for row in agents}
        for proposal_id, author_id, title, body_json, rationale, profound, state, version, created_at, updated_at in proposals:
            if author_id not in agent_ids:
                raise ForumValidationError("proposal backup references an unknown author")
            if state not in _PROPOSAL_STATES:
                raise ForumValidationError("proposal backup contains an invalid state")
            try:
                body = json.loads(body_json)
                _json_value(body)
            except (TypeError, ValueError, ForumValidationError):
                raise ForumValidationError("proposal backup body is corrupt") from None
        proposal_ids = {row[0] for row in proposals}
        eligible_rows = connection.execute(
            "SELECT proposal_id,agent_id FROM proposal_eligible_voters"
        ).fetchall()
        eligible_by_proposal: dict[str, set[str]] = {}
        for proposal_id, agent_id in eligible_rows:
            if proposal_id not in proposal_ids or agent_id not in agent_ids:
                raise ForumValidationError(
                    "proposal voter snapshot references an unknown proposal or agent"
                )
            eligible_by_proposal.setdefault(proposal_id, set()).add(agent_id)
        for proposal_id, author_id, *_ in proposals:
            if author_id not in eligible_by_proposal.get(proposal_id, set()):
                raise ForumValidationError(
                    "proposal voter snapshot omits its author or is empty"
                )
        votes = connection.execute(
            "SELECT proposal_id,agent_id FROM proposal_votes"
        ).fetchall()
        for proposal_id, agent_id in votes:
            if proposal_id not in proposal_ids or agent_id not in eligible_by_proposal.get(proposal_id, set()):
                raise ForumValidationError(
                    "vote backup references an unknown or ineligible proposal voter"
                )
        work = connection.execute("SELECT agent_id,detail_json FROM work_log").fetchall()
        for agent_id, detail_json in work:
            if agent_id not in agent_ids:
                raise ForumValidationError("work log backup references an unknown agent")
            try:
                _json_value(json.loads(detail_json))
            except (TypeError, ValueError, ForumValidationError):
                raise ForumValidationError("work log backup detail is corrupt") from None
        skills = connection.execute("SELECT agent_id,confidence FROM skill_ledger").fetchall()
        for agent_id, confidence in skills:
            if agent_id not in agent_ids:
                raise ForumValidationError("skill ledger backup references an unknown agent")
            if not (0.0 <= confidence <= 1.0):
                raise ForumValidationError("skill ledger backup confidence is out of range")

    def backup_to(self, destination_path: str) -> str:
        return backup_sqlite_database(
            self.path,
            destination_path,
            lock=self._lock,
            connect=self._connect,
            validate_snapshot=self._validate_backup_snapshot,
            error_type=ForumValidationError,
            prefix=".capri-forum-backup-",
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
