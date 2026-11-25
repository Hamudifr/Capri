"""Host-only HMAC authority for exact, short-lived strategy transitions.

The authority authenticates the approver and checks host policy before signing.
It is not exposed through model tools. SQLiteStrategyStore remains responsible
for one-use consumption, principal scoping, generation CAS, and audit history.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from uuid import uuid4

from .strategy_store import (
    StrategyActivationGrant,
    StrategyAuthorizationError,
    StrategyStoreError,
    _grant_payload,
)
from .tools import ApprovalMacProvider

_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_TTL_SECONDS = 900


@dataclass(frozen=True, slots=True)
class StrategyApprovalIdentity:
    """Identity returned only by the trusted host credential authenticator."""

    principal_id: str
    approver_id: str


@dataclass(frozen=True, slots=True)
class StrategyApprovalRequest:
    """Exact state transition submitted to host authorization policy."""

    principal_id: str
    strategy_class: str
    strategy_id: str
    version: str
    evaluation_sha256: str | None
    config_sha256: str
    expected_generation: int
    action: str
    promotion_assessment_sha256: str | None = None


def _text(value: object, label: str, limit: int = 128) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > limit:
        raise StrategyAuthorizationError(f"{label} is invalid")
    if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise StrategyAuthorizationError(f"{label} is invalid")
    return value


def _payload(grant: StrategyActivationGrant, key_id: str) -> bytes:
    data = {
        "domain": "capri.strategy-activation-grant.v1",
        "key_id": key_id,
        "grant_id": grant.grant_id,
        "principal_id": grant.principal_id,
        "strategy_class": grant.strategy_class,
        "strategy_id": grant.strategy_id,
        "version": grant.version,
        "evaluation_sha256": grant.evaluation_sha256,
        "config_sha256": grant.config_sha256,
        "expected_generation": grant.expected_generation,
        "action": grant.action,
        "issued_at": grant.issued_at,
        "expires_at": grant.expires_at,
        "approver_id": grant.approver_id,
    }
    if grant.promotion_assessment_sha256 is not None:
        data["promotion_assessment_sha256"] = grant.promotion_assessment_sha256
    return json.dumps(
        data, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


class HostStrategyApprovalAuthority:
    """Trusted host signer and verifier for one-use strategy activation grants.

    The model must never receive this object, its MAC provider, or a credential
    accepted by its authenticator. The provider should be backed by a host-held
    secret or non-exportable key service.
    """

    def __init__(
        self,
        mac_provider: ApprovalMacProvider,
        authenticate_approver: Callable[[Any], StrategyApprovalIdentity | None],
        authorize_approver: Callable[[StrategyApprovalIdentity, StrategyApprovalRequest], bool],
        *,
        clock: Callable[[], datetime] | None = None,
        max_ttl_seconds: int = 300,
    ) -> None:
        if not (
            callable(getattr(mac_provider, "sign", None))
            and callable(getattr(mac_provider, "verify", None))
            and isinstance(getattr(mac_provider, "active_key_id", None), str)
        ):
            raise StrategyStoreError("a trusted approval MAC provider is required")
        if not callable(authenticate_approver) or not callable(authorize_approver):
            raise StrategyStoreError("host authentication and authorization callbacks are required")
        if type(max_ttl_seconds) is not int or not 1 <= max_ttl_seconds <= _MAX_TTL_SECONDS:
            raise StrategyStoreError("max_ttl_seconds must be between 1 and 900")
        if clock is not None and not callable(clock):
            raise StrategyStoreError("clock must be callable")
        self._mac = mac_provider
        self._authenticate = authenticate_approver
        self._authorize = authorize_approver
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._max_ttl = max_ttl_seconds

    @staticmethod
    def _validate_request(request: StrategyApprovalRequest) -> None:
        if type(request) is not StrategyApprovalRequest:
            raise StrategyAuthorizationError("a typed strategy approval request is required")
        _text(request.principal_id, "principal_id")
        if not _IDENTIFIER.fullmatch(_text(request.strategy_class, "strategy_class", 64)):
            raise StrategyAuthorizationError("strategy_class is invalid")
        if not _IDENTIFIER.fullmatch(_text(request.strategy_id, "strategy_id", 64)):
            raise StrategyAuthorizationError("strategy_id is invalid")
        if not _VERSION.fullmatch(_text(request.version, "version", 64)) or request.version == "unversioned":
            raise StrategyAuthorizationError("version is invalid")
        if request.evaluation_sha256 is not None and (
            type(request.evaluation_sha256) is not str
            or not _SHA256.fullmatch(request.evaluation_sha256)
        ):
            raise StrategyAuthorizationError("evaluation fingerprint is invalid")
        if type(request.config_sha256) is not str or not _SHA256.fullmatch(request.config_sha256):
            raise StrategyAuthorizationError("config fingerprint is invalid")
        if type(request.expected_generation) is not int or not 0 <= request.expected_generation < 2**63 - 1:
            raise StrategyAuthorizationError("expected_generation is invalid")
        if type(request.action) is not str or request.action not in {"activate", "rollback"}:
            raise StrategyAuthorizationError("action must be activate or rollback")
        if request.promotion_assessment_sha256 is not None and (
            type(request.promotion_assessment_sha256) is not str
            or not _SHA256.fullmatch(request.promotion_assessment_sha256)
        ):
            raise StrategyAuthorizationError("promotion assessment fingerprint is invalid")

    def issue_grant(
        self,
        credential: Any,
        request: StrategyApprovalRequest,
        *,
        ttl_seconds: int = 300,
    ) -> StrategyActivationGrant:
        """Authenticate, authorize, then sign a single exact transition."""
        self._validate_request(request)
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= self._max_ttl:
            raise StrategyAuthorizationError("grant TTL exceeds host policy")
        try:
            identity = self._authenticate(credential)
        except Exception:
            raise StrategyAuthorizationError("approver authentication failed") from None
        if type(identity) is not StrategyApprovalIdentity:
            raise StrategyAuthorizationError("approver authentication failed")
        _text(identity.principal_id, "authenticated principal")
        _text(identity.approver_id, "approver identity", 128)
        if identity.principal_id != request.principal_id:
            raise StrategyAuthorizationError("authenticated principal does not own this strategy")
        try:
            authorized = self._authorize(identity, request)
        except Exception:
            raise StrategyAuthorizationError("strategy transition authorization failed") from None
        if authorized is not True:
            raise StrategyAuthorizationError("strategy transition is not authorized")
        try:
            now = self._clock()
        except Exception:
            raise StrategyAuthorizationError("host clock is unavailable") from None
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise StrategyAuthorizationError("host clock must be timezone-aware")
        now = now.astimezone(timezone.utc)
        try:
            key_id = self._mac.active_key_id
        except Exception:
            raise StrategyAuthorizationError("active MAC key identifier is unavailable") from None
        if not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id):
            raise StrategyAuthorizationError("active MAC key identifier is invalid")
        unsigned = StrategyActivationGrant(
            grant_id=uuid4().hex,
            principal_id=request.principal_id,
            strategy_class=request.strategy_class,
            strategy_id=request.strategy_id,
            version=request.version,
            evaluation_sha256=request.evaluation_sha256,
            config_sha256=request.config_sha256,
            expected_generation=request.expected_generation,
            action=request.action,
            issued_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=ttl_seconds)).isoformat(),
            approver_id=identity.approver_id,
            signature="pending",
            promotion_assessment_sha256=request.promotion_assessment_sha256,
        )
        # Share the registry's exact grant validation so the host cannot sign a
        # request that the store will later reject as malformed.
        _grant_payload(unsigned)
        try:
            tag = self._mac.sign(key_id, _payload(unsigned, key_id))
        except Exception:
            raise StrategyAuthorizationError("host signing provider is unavailable") from None
        if type(tag) is not bytes or len(tag) != 32:
            raise StrategyAuthorizationError("host signing provider returned an invalid MAC")
        signature = f"{key_id}:{tag.hex()}"
        return StrategyActivationGrant(
            grant_id=unsigned.grant_id,
            principal_id=unsigned.principal_id,
            strategy_class=unsigned.strategy_class,
            strategy_id=unsigned.strategy_id,
            version=unsigned.version,
            evaluation_sha256=unsigned.evaluation_sha256,
            config_sha256=unsigned.config_sha256,
            expected_generation=unsigned.expected_generation,
            action=unsigned.action,
            issued_at=unsigned.issued_at,
            expires_at=unsigned.expires_at,
            approver_id=unsigned.approver_id,
            signature=signature,
            promotion_assessment_sha256=unsigned.promotion_assessment_sha256,
        )

    def verify(self, grant: StrategyActivationGrant) -> bool:
        """Verify the MAC and key ID; store enforces expiry and one-use semantics."""
        if type(grant) is not StrategyActivationGrant:
            return False
        try:
            _grant_payload(grant)
            if type(grant.signature) is not str or len(grant.signature) > 2048:
                return False
            issued = datetime.fromisoformat(grant.issued_at.replace("Z", "+00:00"))
            expires = datetime.fromisoformat(grant.expires_at.replace("Z", "+00:00"))
            if (
                issued.tzinfo is None or issued.utcoffset() is None
                or expires.tzinfo is None or expires.utcoffset() is None
                or expires <= issued
                or (expires - issued).total_seconds() > self._max_ttl
            ):
                return False
            key_id, separator, encoded_tag = grant.signature.partition(":")
            if not separator or not _KEY_ID.fullmatch(key_id) or not re.fullmatch(r"[0-9a-f]{64}", encoded_tag):
                return False
            tag = bytes.fromhex(encoded_tag)
            result = self._mac.verify(key_id, _payload(grant, key_id), tag)
            return result is True
        except Exception:
            return False
