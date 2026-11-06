"""Host-authenticated, durable approval challenges.

The model can request a challenge but cannot decide it, mint grants, or access the signer.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from uuid import uuid4

from .security_store import SQLiteSecurityStore
from .tool_bridge import ToolCallOutcome
from .tools import (
    ApprovalGrant,
    ExecutionContext,
    HmacApprovalAuthority,
    HostAuthorityError,
    ToolValidationError,
)

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_OPERATION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


@dataclass(frozen=True, slots=True)
class ApprovalChallenge:
    challenge_id: str
    operation_id: str
    principal_id: str
    tool_name: str
    argument_digest: str
    created_at: str
    expires_at: str
    status: str
    approver_id: str | None = None
    grant: ApprovalGrant | None = None


def _utc(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ToolValidationError(f"{label} must be timezone-aware")
    return value.astimezone(timezone.utc)


class SQLiteApprovalChallengeStore:
    """Challenge state sharing SQLiteSecurityStore's already-hardened database.

    The wrapped store owns path validation, private permissions, SQLite settings,
    and connection creation. No second database or weaker filesystem path is used.
    """

    def __init__(self, security_store: SQLiteSecurityStore) -> None:
        if not isinstance(security_store, SQLiteSecurityStore):
            raise ToolValidationError("a trusted SQLiteSecurityStore is required")
        self._store = security_store
        with self._store._lock:
            connection = self._store._connect()
            try:
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS approval_challenges (
                        challenge_id TEXT PRIMARY KEY,
                        operation_id TEXT NOT NULL UNIQUE,
                        principal_id TEXT NOT NULL,
                        tool_name TEXT NOT NULL,
                        argument_digest TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected','expired')),
                        approver_id TEXT,
                        grant_json TEXT,
                        CHECK(
                            (status='approved' AND approver_id IS NOT NULL AND grant_json IS NOT NULL)
                            OR (status!='approved' AND grant_json IS NULL)
                        )
                    )"""
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS approval_challenges_status_expiry "
                    "ON approval_challenges(status, expires_at)"
                )
            finally:
                connection.close()

    @staticmethod
    def _from_row(row: tuple[Any, ...]) -> ApprovalChallenge:
        grant = None
        if row[9] is not None:
            try:
                grant = ApprovalGrant(**json.loads(row[9]))
            except (TypeError, ValueError, json.JSONDecodeError):
                raise ToolValidationError("stored approval grant is invalid") from None
        return ApprovalChallenge(*row[:8], row[8], grant)

    @staticmethod
    def _validate(operation_id: str, principal_id: str, tool_name: str, digest: str) -> None:
        if not isinstance(operation_id, str) or not _OPERATION.fullmatch(operation_id):
            raise ToolValidationError("operation_id must be a bounded identifier")
        if (not isinstance(principal_id, str) or not principal_id.strip()
                or len(principal_id) > 256 or any(0xD800 <= ord(c) <= 0xDFFF for c in principal_id)):
            raise ToolValidationError("challenge principal is invalid")
        if not isinstance(tool_name, str) or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", tool_name):
            raise ToolValidationError("challenge tool name is invalid")
        if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
            raise ToolValidationError("challenge digest must be SHA-256 hex")

    def create(
        self, operation_id: str, principal_id: str, tool_name: str, digest: str,
        created_at: datetime, expires_at: datetime,
    ) -> ApprovalChallenge:
        self._validate(operation_id, principal_id, tool_name, digest)
        created, expiry = _utc(created_at, "created_at"), _utc(expires_at, "expires_at")
        if expiry <= created:
            raise ToolValidationError("challenge expiry must be after creation")
        challenge_id = str(uuid4())
        with self._store._lock:
            connection = self._store._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """SELECT challenge_id,operation_id,principal_id,tool_name,argument_digest,
                    created_at,expires_at,status,approver_id,grant_json
                    FROM approval_challenges WHERE operation_id=?""", (operation_id,),
                ).fetchone()
                if row is not None:
                    record = self._from_row(row)
                    if (record.principal_id, record.tool_name, record.argument_digest) != (
                        principal_id, tool_name, digest
                    ):
                        raise ToolValidationError("operation_id was reused for a different operation")
                    connection.execute("COMMIT")
                    return record
                connection.execute(
                    """INSERT INTO approval_challenges
                    (challenge_id,operation_id,principal_id,tool_name,argument_digest,
                     created_at,expires_at,status)
                    VALUES (?,?,?,?,?,?,?,'pending')""",
                    (challenge_id, operation_id, principal_id, tool_name, digest,
                     created.isoformat(), expiry.isoformat()),
                )
                connection.execute(
                    """INSERT INTO audit_events
                    (event_id,timestamp,principal_id,tool_name,argument_digest,status,error_code)
                    VALUES (?,?,?,?,?,'approval_requested',NULL)""",
                    (str(uuid4()), created.isoformat(), principal_id, tool_name, digest),
                )
                connection.execute("COMMIT")
                return ApprovalChallenge(
                    challenge_id, operation_id, principal_id, tool_name, digest,
                    created.isoformat(), expiry.isoformat(), "pending",
                )
            except Exception:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                connection.close()

    def get(self, challenge_id: str, now: datetime) -> ApprovalChallenge | None:
        current = _utc(now, "challenge clock")
        if not isinstance(challenge_id, str) or not 0 < len(challenge_id) <= 64:
            return None
        with self._store._lock:
            connection = self._store._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """SELECT challenge_id,operation_id,principal_id,tool_name,argument_digest,
                    created_at,expires_at,status,approver_id,grant_json
                    FROM approval_challenges WHERE challenge_id=?""", (challenge_id,),
                ).fetchone()
                if row is None:
                    connection.execute("COMMIT")
                    return None
                if row[7] == "pending" and datetime.fromisoformat(row[6]) <= current:
                    connection.execute(
                        "UPDATE approval_challenges SET status='expired' WHERE challenge_id=? AND status='pending'",
                        (challenge_id,),
                    )
                    connection.execute(
                        """INSERT INTO audit_events
                        (event_id,timestamp,principal_id,tool_name,argument_digest,status,error_code)
                        VALUES (?,?,?,?,?,'approval_expired',NULL)""",
                        (str(uuid4()), current.isoformat(), row[2], row[3], row[4]),
                    )
                    row = (*row[:7], "expired", row[8], row[9])
                connection.execute("COMMIT")
                return self._from_row(row)
            except Exception:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                connection.close()

    def decide(
        self, challenge_id: str, approver_id: str, decision: str, now: datetime,
        grant_factory: Callable[[ApprovalChallenge], ApprovalGrant] | None = None,
    ) -> ApprovalChallenge:
        current = _utc(now, "decision clock")
        if not isinstance(challenge_id, str) or not 0 < len(challenge_id) <= 64:
            raise ToolValidationError("challenge_id is invalid")
        if decision not in {"approve", "reject"}:
            raise ToolValidationError("decision must be approve or reject")
        if decision == "approve" and not callable(grant_factory):
            raise ToolValidationError("approval requires a trusted grant factory")
        if (not isinstance(approver_id, str) or not approver_id.strip()
                or len(approver_id) > 256 or any(0xD800 <= ord(c) <= 0xDFFF for c in approver_id)):
            raise ToolValidationError("approver identity is invalid")
        with self._store._lock:
            connection = self._store._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """SELECT challenge_id,operation_id,principal_id,tool_name,argument_digest,
                    created_at,expires_at,status,approver_id,grant_json
                    FROM approval_challenges WHERE challenge_id=?""", (challenge_id,),
                ).fetchone()
                if row is None:
                    raise ToolValidationError("approval challenge was not found")
                record = self._from_row(row)
                if record.status == "approved":
                    if decision != "approve":
                        raise ToolValidationError("approval challenge is already approved")
                    if record.grant is None or _utc(
                        datetime.fromisoformat(record.grant.expires_at.replace("Z", "+00:00")),
                        "stored grant expiry",
                    ) <= current:
                        raise ToolValidationError("approved grant has expired")
                    connection.execute("COMMIT")
                    return record
                if record.status != "pending":
                    raise ToolValidationError("approval challenge is no longer pending")
                if _utc(datetime.fromisoformat(record.expires_at), "challenge expiry") <= current:
                    connection.execute(
                        "UPDATE approval_challenges SET status='expired' WHERE challenge_id=? AND status='pending'",
                        (challenge_id,),
                    )
                    connection.execute(
                        """INSERT INTO audit_events
                        (event_id,timestamp,principal_id,tool_name,argument_digest,status,error_code)
                        VALUES (?,?,?,?,?,'approval_expired',NULL)""",
                        (str(uuid4()), current.isoformat(), record.principal_id,
                         record.tool_name, record.argument_digest),
                    )
                    connection.execute("COMMIT")
                    raise ToolValidationError("approval challenge has expired")
                grant = None
                status = "rejected"
                if decision == "approve":
                    grant = grant_factory(record)
                    if (not isinstance(grant, ApprovalGrant)
                            or grant.principal_id != record.principal_id
                            or grant.tool_name != record.tool_name
                            or grant.argument_digest != record.argument_digest
                            or not isinstance(grant.signature, str)
                            or not re.fullmatch(r"[0-9a-f]{64}", grant.signature)):
                        raise ToolValidationError("grant factory returned a mismatched or unsigned grant")
                    if _utc(datetime.fromisoformat(grant.expires_at.replace("Z", "+00:00")), "grant expiry") <= current:
                        raise ToolValidationError("grant factory returned an expired grant")
                    status = "approved"
                grant_json = json.dumps({
                    "grant_id": grant.grant_id, "principal_id": grant.principal_id,
                    "tool_name": grant.tool_name, "argument_digest": grant.argument_digest,
                    "expires_at": grant.expires_at, "signature": grant.signature,
                }, sort_keys=True, separators=(",", ":")) if grant else None
                connection.execute(
                    """UPDATE approval_challenges SET status=?,approver_id=?,grant_json=?
                    WHERE challenge_id=? AND status='pending'""",
                    (status, approver_id, grant_json, challenge_id),
                )
                connection.execute(
                    """INSERT INTO audit_events
                    (event_id,timestamp,principal_id,tool_name,argument_digest,status,error_code)
                    VALUES (?,?,?,?,?,?,NULL)""",
                    (str(uuid4()), current.isoformat(), record.principal_id,
                     record.tool_name, record.argument_digest, "approval_" + status),
                )
                connection.execute("COMMIT")
                return ApprovalChallenge(
                    record.challenge_id, record.operation_id, record.principal_id,
                    record.tool_name, record.argument_digest, record.created_at,
                    record.expires_at, status, approver_id, grant,
                )
            except Exception:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                connection.close()


class HostApprovalService:
    """Host-only approval API. Never expose this object or signer to model input."""

    def __init__(
        self,
        store: SQLiteApprovalChallengeStore,
        signer: HmacApprovalAuthority,
        authenticate_approver: Callable[[Any], str | None],
        authorize_approver: Callable[[str, ApprovalChallenge], bool],
        *,
        clock: Callable[[], datetime] | None = None,
        challenge_ttl_seconds: int = 300,
        grant_ttl_seconds: int = 300,
        allow_self_approval: bool = False,
    ) -> None:
        if not isinstance(store, SQLiteApprovalChallengeStore) or not isinstance(signer, HmacApprovalAuthority):
            raise ToolValidationError("trusted challenge store and HMAC signer are required")
        if not callable(authenticate_approver) or not callable(authorize_approver):
            raise ToolValidationError("host authentication and approval policy callbacks are required")
        for label, value in (("challenge_ttl_seconds", challenge_ttl_seconds), ("grant_ttl_seconds", grant_ttl_seconds)):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 3600:
                raise ToolValidationError(f"{label} must be between 1 and 3600")
        if not isinstance(allow_self_approval, bool):
            raise ToolValidationError("allow_self_approval must be boolean")
        self._store, self._signer = store, signer
        self._authenticate, self._authorize = authenticate_approver, authorize_approver
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._challenge_ttl, self._grant_ttl = challenge_ttl_seconds, grant_ttl_seconds
        self._allow_self_approval = allow_self_approval

    def create_challenge(
        self, context: ExecutionContext, outcome: ToolCallOutcome, operation_id: str,
    ) -> ApprovalChallenge:
        """Trusted host call after a bridge approval_required outcome."""
        if not isinstance(context, ExecutionContext) or not isinstance(outcome, ToolCallOutcome):
            raise ToolValidationError("trusted execution context and tool outcome are required")
        if outcome.status != "approval_required" or not isinstance(outcome.argument_digest, str):
            raise ToolValidationError("only approval_required outcomes can create challenges")
        now = _utc(self._clock(), "host clock")
        return self._store.create(
            operation_id, context.principal_id, outcome.name, outcome.argument_digest,
            now, now + timedelta(seconds=self._challenge_ttl),
        )

    def _decide(self, credential: Any, challenge_id: str, decision: str) -> ApprovalChallenge:
        now = _utc(self._clock(), "host clock")
        challenge = self._store.get(challenge_id, now)
        if challenge is None:
            raise HostAuthorityError("approval challenge was not found")
        try:
            approver_id = self._authenticate(credential)
        except Exception:
            raise HostAuthorityError("approval authentication failed") from None
        if (not isinstance(approver_id, str) or not approver_id.strip()
                or len(approver_id) > 256 or any(0xD800 <= ord(c) <= 0xDFFF for c in approver_id)):
            raise HostAuthorityError("approval authentication failed")
        if not self._allow_self_approval and approver_id == challenge.principal_id:
            raise HostAuthorityError("self-approval is not permitted")
        try:
            allowed = self._authorize(approver_id, challenge)
        except Exception:
            allowed = False
        if allowed is not True:
            raise HostAuthorityError("approver is not authorized for this challenge")
        factory = None
        if decision == "approve":
            factory = lambda item: self._signer.issue(
                item.principal_id, item.tool_name, item.argument_digest,
                ttl_seconds=self._grant_ttl,
            )
        # Re-read time after authentication/policy callbacks; the store checks it
        # inside its serialized decision transaction, not at challenge display time.
        decision_time = _utc(self._clock(), "host clock")
        return self._store.decide(challenge_id, approver_id, decision, decision_time, factory)

    def approve(self, credential: Any, challenge_id: str) -> ApprovalChallenge:
        return self._decide(credential, challenge_id, "approve")

    def reject(self, credential: Any, challenge_id: str) -> ApprovalChallenge:
        return self._decide(credential, challenge_id, "reject")
