"""Host-facing tool invocation facade.

Untrusted request paths provide opaque credentials and structured tool requests.
The facade resolves authority internally and never accepts ExecutionContext input.
"""
from __future__ import annotations

import threading
from typing import Any

from .tool_bridge import ToolCallOutcome, ToolCallRequest, ToolDefinition, ToolExecutionBridge
from .tools import HostAuthorityError, HostAuthorityResolver


class HostToolGateway:
    """Resolve trusted authority and execute proposed calls.

    The authority derives the trusted execution context from authenticated host
    session state; it is never exposed to model/client code.
    """

    def __init__(
        self,
        authority: HostAuthorityResolver,
        bridge: ToolExecutionBridge,
    ) -> None:
        if not isinstance(authority, HostAuthorityResolver):
            raise HostAuthorityError("a trusted HostAuthorityResolver is required")
        if not isinstance(bridge, ToolExecutionBridge):
            raise HostAuthorityError("a trusted ToolExecutionBridge is required")
        self._authority = authority
        self._bridge = bridge

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
        """Authenticate and execute proposed calls.

        The model receives only the original bounded ToolCallOutcome records.
        """
        context = self._authority.resolve(credential)
        return self._bridge.execute_batch(
            requests,
            context,
            cancellation_event=cancellation_event,
        )
