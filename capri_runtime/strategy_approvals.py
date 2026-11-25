"""Host-only bridge from durable approval challenges to strategy activation grants.

The bridge reuses HostApprovalService's authenticated approver workflow and HMAC
signer. It does not expose approval credentials or signing keys to model input.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from uuid import uuid4

from .approval import HostApprovalService
from .strategy_store import (
    StrategyActivationGrant,
    StrategyAuthorizationError,
    _grant_payload,
    _identifier,
    _text,
    _timestamp,
    _version,
)
from .tools import ApprovalGrant

_OPERATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_GRANT_LIFETIME_SECONDS = 900


@dataclass(frozen=True, slots=True)
class StrategyApprovalRequest:
    """Host-owned, immutable request metadata needed to finish one approval."""

    challenge_id: str
    operation_id: str
    principal_id: str
    strategy_class: str
    strategy_id: str
    version: str
    evaluation_sha256: str | None
    config_sha256: str
    expected_generation: int
    action: str
    issued_at: str


def _validated_fields(
    principal_id: object,
    strategy_class: object,
    strategy_id: object,
    version: object,
    evaluation_sha256: object,
    config_sha256: object,
    expected_generation: object,
    action: object,
) -> tuple[str, str, str, str, str | None, str, int, str]:
    principal = _text(principal_id, "principal_id", 128)
    category = _identifier(strategy_class, "strategy_class")
    strategy = _identifier(strategy_id, "strategy_id")
    strategy_version = _version(version)
    if evaluation_sha256 is not None and (
        type(evaluation_sha256) is not str or not _SHA256.fullmatch(evaluation_sha256)
    ):
        raise StrategyAuthorizationError("evaluation fingerprint is invalid")
    if type(config_sha256) is not str or not _SHA256.fullmatch(config_sha256):
        raise StrategyAuthorizationError("strategy config fingerprint is invalid")
    if type(expected_generation) is not int or not 0 <= expected_generation < 2**63 - 1:
        raise StrategyAuthorizationError("expected_generation is invalid")
    if type(action) is not str or action not in {"activate", "rollback"}:
        raise StrategyAuthorizationError("strategy approval action must be activate or rollback")
    return (
        principal, category, strategy, strategy_version, evaluation_sha256,
        config_sha256, expected_generation, action,
    )


def _argument_digest(
    principal_id: str,
    strategy_class: str,
    strategy_id: str,
    version: str,
    evaluation_sha256: str | None,
    config_sha256: str,
    expected_generation: int,
    action: str,
) -> str:
    payload = {
        "schema": "capri.strategy-activation-approval.v1",
        "principal_id": principal_id,
        "strategy_class": strategy_class,
        "strategy_id": strategy_id,
        "version": version,
        "evaluation_sha256": evaluation_sha256,
        "config_sha256": config_sha256,
        "expected_generation": expected_generation,
        "action": action,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class StrategyApprovalBridge:
    """Bind strategy state transitions to a durable, authenticated host approval.

    Construct this in trusted host code and pass the verify method as the
    SQLiteStrategyStore approval_verifier. Never expose this object to the model.
    """

    def __init__(self, approval_service: HostApprovalService) -> None:
        if type(approval_service) is not HostApprovalService:
            raise StrategyAuthorizationError("a trusted HostApprovalService is required")
        if (
            approval_service.challenge_ttl_seconds + approval_service.grant_ttl_seconds
            > _MAX_GRANT_LIFETIME_SECONDS
        ):
            raise StrategyAuthorizationError(
                "strategy challenge and grant lifetimes must total no more than 15 minutes"
            )
        self._service = approval_service

    def request(
        self,
        *,
        principal_id: str,
        strategy_class: str,
        strategy_id: str,
        version: str,
        evaluation_sha256: str | None,
        config_sha256: str,
        expected_generation: int,
        action: str = "activate",
        operation_id: str | None = None,
    ) -> StrategyApprovalRequest:
        """Create a host approval challenge for one exact strategy transition.

        Preserve and reuse the returned request object for lost-response retries.
        A caller-supplied stable operation_id is accepted for idempotent challenge
        creation; the original fields must be reused.
        """
        fields = _validated_fields(
            principal_id, strategy_class, strategy_id, version,
            evaluation_sha256, config_sha256, expected_generation, action,
        )
        (
            principal, category, strategy, strategy_version, evaluation_hash,
            config_hash, generation, normalized_action,
        ) = fields
        op_id = operation_id or f"strategy-{uuid4().hex}"
        if type(op_id) is not str or not _OPERATION_ID.fullmatch(op_id):
            raise StrategyAuthorizationError("strategy approval operation ID is invalid")
        digest = _argument_digest(
            principal, category, strategy, strategy_version, evaluation_hash,
            config_hash, generation, normalized_action,
        )
        challenge = self._service.create_action_challenge(
            principal, f"strategy.{normalized_action}", digest, op_id,
        )
        if (
            challenge.operation_id != op_id
            or challenge.principal_id != principal
            or challenge.tool_name != f"strategy.{normalized_action}"
            or challenge.argument_digest != digest
            or challenge.status not in {"pending", "approved"}
        ):
            raise StrategyAuthorizationError("stored approval challenge does not match the strategy request")
        # The immutable challenge creation time is the grant's issued_at. This
        # binds it through the durable challenge record and bounds total lifetime.
        _timestamp(challenge.created_at, "challenge created_at")
        return StrategyApprovalRequest(
            challenge.challenge_id, op_id, principal, category, strategy,
            strategy_version, evaluation_hash, config_hash, generation,
            normalized_action, challenge.created_at,
        )

    @staticmethod
    def _request_digest(request: StrategyApprovalRequest) -> str:
        if type(request) is not StrategyApprovalRequest:
            raise StrategyAuthorizationError("a host-owned StrategyApprovalRequest is required")
        _timestamp(request.issued_at, "request issued_at")
        fields = _validated_fields(
            request.principal_id, request.strategy_class, request.strategy_id,
            request.version, request.evaluation_sha256, request.config_sha256,
            request.expected_generation, request.action,
        )
        return _argument_digest(*fields)

    def approve(self, credential: object, request: StrategyApprovalRequest) -> StrategyActivationGrant:
        """Authenticate and approve the stored challenge, then return a store-ready grant."""
        digest = self._request_digest(request)
        if (
            type(request.challenge_id) is not str
            or not request.challenge_id
            or len(request.challenge_id) > 64
            or type(request.operation_id) is not str
            or not _OPERATION_ID.fullmatch(request.operation_id)
        ):
            raise StrategyAuthorizationError("strategy approval request identifiers are invalid")
        stored = self._service.get_challenge_by_operation_id(request.operation_id)
        if (
            stored is None
            or stored.challenge_id != request.challenge_id
            or stored.created_at != request.issued_at
            or stored.argument_digest != digest
            or stored.principal_id != request.principal_id
            or stored.tool_name != f"strategy.{request.action}"
        ):
            raise StrategyAuthorizationError("strategy approval request does not match its durable challenge")
        approved = self._service.approve(credential, request.challenge_id)
        if approved.status != "approved" or approved.grant is None or approved.approver_id is None:
            raise StrategyAuthorizationError("strategy approval was not granted")
        approval = approved.grant
        grant = StrategyActivationGrant(
            grant_id=approval.grant_id,
            principal_id=request.principal_id,
            strategy_class=request.strategy_class,
            strategy_id=request.strategy_id,
            version=request.version,
            evaluation_sha256=request.evaluation_sha256,
            config_sha256=request.config_sha256,
            expected_generation=request.expected_generation,
            action=request.action,
            issued_at=request.issued_at,
            expires_at=approval.expires_at,
            approver_id=approved.approver_id,
            signature=approval.signature or "",
            key_id=approval.key_id,
            operation_id=approval.operation_id,
        )
        _grant_payload(grant)
        if not self.verify(grant):
            raise StrategyAuthorizationError("approved strategy grant failed durable signature verification")
        return grant

    def verify(self, grant: StrategyActivationGrant) -> bool:
        """Verify HMAC, exact challenge record, approver, and all strategy bindings."""
        try:
            _grant_payload(grant)
            if grant.key_id is None or grant.operation_id is None:
                return False
            digest = _argument_digest(
                grant.principal_id, grant.strategy_class, grant.strategy_id,
                grant.version, grant.evaluation_sha256, grant.config_sha256,
                grant.expected_generation, grant.action,
            )
            approval = ApprovalGrant(
                grant.grant_id, grant.principal_id, f"strategy.{grant.action}",
                digest, grant.expires_at, grant.signature, grant.key_id,
                grant.operation_id,
            )
            if self._service.verify_grant(approval) is not True:
                return False
            challenge = self._service.get_challenge_by_operation_id(grant.operation_id)
            return bool(
                challenge is not None
                and challenge.status == "approved"
                and challenge.grant == approval
                and challenge.created_at == grant.issued_at
                and challenge.approver_id == grant.approver_id
                and challenge.principal_id == grant.principal_id
                and challenge.tool_name == f"strategy.{grant.action}"
                and challenge.argument_digest == digest
            )
        except Exception:
            return False
