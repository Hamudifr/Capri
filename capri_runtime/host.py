"""Host-facing tool invocation facade.

Untrusted request paths provide opaque credentials and structured tool requests.
The facade resolves authority internally and never accepts ExecutionContext input.
"""
from __future__ import annotations

import threading
from typing import Any, Callable

from .approval import ApprovalChallenge, HostApprovalService
from .tool_bridge import ToolCallOutcome, ToolCallRequest, ToolDefinition, ToolExecutionBridge
from .tools import ExecutionContext, HostAuthorityError, HostAuthorityResolver


class HostToolGateway:
    """Resolve trusted authority and optionally create approval challenges.

    The operation ID resolver and notification callback are trusted host code.
    The resolver must derive a stable operation ID from authenticated host session
    state plus the request identity; never accept a client-supplied operation ID.
    The approval service and signer must never be exposed to model/client code.
    """

    def __init__(
        self,
        authority: HostAuthorityResolver,
        bridge: ToolExecutionBridge,
        *,
        approval_service: HostApprovalService | None = None,
        operation_id_resolver: Callable[[Any, ExecutionContext, ToolCallRequest], str] | None = None,
        on_approval_challenge: Callable[[ApprovalChallenge], None] | None = None,
    ) -> None:
        if not isinstance(authority, HostAuthorityResolver):
            raise HostAuthorityError("a trusted HostAuthorityResolver is required")
        if not isinstance(bridge, ToolExecutionBridge):
            raise HostAuthorityError("a trusted ToolExecutionBridge is required")
        if approval_service is None:
            if operation_id_resolver is not None or on_approval_challenge is not None:
                raise HostAuthorityError("approval callbacks require a trusted approval service")
        else:
            if not isinstance(approval_service, HostApprovalService):
                raise HostAuthorityError("approval_service must be a trusted HostApprovalService")
            if not callable(operation_id_resolver) or not callable(on_approval_challenge):
                raise HostAuthorityError("approval integration requires host operation-ID and notification callbacks")
        self._authority = authority
        self._bridge = bridge
        self._approval_service = approval_service
        self._operation_id_resolver = operation_id_resolver
        self._on_approval_challenge = on_approval_challenge

    def available_tools(self, credential: Any) -> tuple[ToolDefinition, ...]:
        """Authenticate the caller and return only tools allowed by host policy."""
        context = self._authority.resolve(credential)
        return self._bridge.available_tools(context)

    def execute_batch(
        self,
        credential: Any,
        requests: list[ToolCallRequest] | tuple[ToolCallRequest, ...],
        *,
        cancellation_event: threading.Event | None = None,
    ) -> tuple[ToolCallOutcome, ...]:
        """Authenticate, execute proposed calls, and create host approval challenges.

        The model receives only the original bounded ToolCallOutcome records.
        Challenge objects are delivered exclusively to the host notification
        callback. If notification fails, the challenge remains durably stored;
        retrying the same operation ID recovers that same challenge.
        """
        context = self._authority.resolve(credential)
        outcomes = self._bridge.execute_batch(
            requests,
            context,
            cancellation_event=cancellation_event,
        )
        if self._approval_service is None:
            return outcomes
        request_by_id = {request.call_id: request for request in requests}
        for outcome in outcomes:
            if outcome.status != "approval_required":
                continue
            request = request_by_id.get(outcome.call_id)
            if request is None:
                raise HostAuthorityError("approval outcome could not be matched to its host request")
            try:
                operation_id = self._operation_id_resolver(credential, context, request)
            except Exception:
                raise HostAuthorityError("host operation identity resolution failed") from None
            challenge = self._approval_service.create_challenge(context, outcome, operation_id)
            try:
                self._on_approval_challenge(challenge)
            except Exception:
                raise HostAuthorityError(
                    "approval challenge was stored but host notification failed; retry the same operation"
                ) from None
        return outcomes
