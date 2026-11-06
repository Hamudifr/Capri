"""Bounded bridge from model-proposed calls to the trusted tool executor.

This module accepts structured requests as untrusted data. It never constructs
ExecutionContext, grants permissions, approves actions, or invokes handlers directly.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .tools import (
    ApprovalRequiredError,
    AuditError,
    ExecutionContext,
    PermissionDeniedError,
    ToolExecutionError,
    ToolExecutor,
    ToolNotFoundError,
    ToolValidationError,
    _canonical_json,
    _NAME_RE,
    _assert_json_object_keys,
)

_CALL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")


class ToolBridgeValidationError(Exception):
    """The batch envelope is malformed or exceeds configured limits."""


@dataclass(frozen=True, slots=True)
class ToolCallRequest:
    """Untrusted model-proposed tool call; never carries authority."""

    call_id: str
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ToolCallOutcome:
    """Safe, bounded result for one proposed call."""

    call_id: str
    name: str
    status: str
    result: Any = None
    error_code: str | None = None
    argument_digest: str | None = None


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """Model-facing schema for a tool the trusted context is allowed to request."""

    name: str
    parameters_json: str
    requires_approval: bool

    def parameters(self) -> dict[str, Any]:
        return json.loads(self.parameters_json)


class ToolExecutionBridge:
    """Validate bounded batches and route every call through ToolExecutor."""

    def __init__(
        self,
        executor: ToolExecutor,
        *,
        max_calls: int = 8,
        max_batch_bytes: int = 65_536,
        max_call_id_chars: int = 64,
    ) -> None:
        if not isinstance(executor, ToolExecutor):
            raise ToolBridgeValidationError("executor must be a ToolExecutor")
        for name, value in (
            ("max_calls", max_calls),
            ("max_batch_bytes", max_batch_bytes),
            ("max_call_id_chars", max_call_id_chars),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ToolBridgeValidationError(f"{name} must be a positive integer")
        if max_calls > 64 or max_batch_bytes > 1_048_576 or max_call_id_chars > 64:
            raise ToolBridgeValidationError("configured bridge limit exceeds the hard maximum")
        self.executor = executor
        self.max_calls = max_calls
        self.max_batch_bytes = max_batch_bytes
        self.max_call_id_chars = max_call_id_chars

    def available_tools(self, context: ExecutionContext) -> tuple[ToolDefinition, ...]:
        """Return schemas only for tools permitted by the trusted host context."""
        if not isinstance(context, ExecutionContext):
            raise ToolBridgeValidationError("a trusted ExecutionContext is required")
        if not isinstance(context.permissions, frozenset):
            raise ToolBridgeValidationError("host permissions must be a frozenset")
        definitions = []
        for name in self.executor.registry.names():
            spec, _ = self.executor.registry.resolve(name)
            if spec.permission in context.permissions:
                schema, _ = _canonical_json(
                    spec.schema(), max_bytes=32_768, label="tool schema"
                )
                definitions.append(
                    ToolDefinition(name, schema, spec.requires_approval)
                )
        return tuple(definitions)

    def execute_batch(
        self,
        requests: list[ToolCallRequest] | tuple[ToolCallRequest, ...],
        context: ExecutionContext,
    ) -> tuple[ToolCallOutcome, ...]:
        """Execute a fully validated batch in order using host-supplied authority.

        Envelope validation completes before the first handler can run. Execution
        outcomes are per-call; an audit failure is marked uncertain and is never
        retried by this bridge.
        """
        if not isinstance(context, ExecutionContext):
            raise ToolBridgeValidationError("a trusted ExecutionContext is required")
        if not isinstance(requests, (list, tuple)):
            raise ToolBridgeValidationError("requests must be a list or tuple")
        if not requests or len(requests) > self.max_calls:
            raise ToolBridgeValidationError("batch call count is outside configured limits")

        prepared: list[tuple[str, str, dict[str, Any], str, int]] = []
        seen: set[str] = set()
        total_bytes = 2
        for request in requests:
            if not isinstance(request, ToolCallRequest):
                raise ToolBridgeValidationError("each request must be a ToolCallRequest")
            call_id, name, arguments = request.call_id, request.name, request.arguments
            if (
                not isinstance(call_id, str)
                or len(call_id) > self.max_call_id_chars
                or not _CALL_ID_RE.fullmatch(call_id)
                or call_id in seen
            ):
                raise ToolBridgeValidationError("call IDs must be unique bounded identifiers")
            if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
                raise ToolBridgeValidationError("tool names must be lowercase identifiers")
            if not isinstance(arguments, Mapping) or not isinstance(arguments, dict):
                raise ToolBridgeValidationError("tool arguments must be JSON objects")
            try:
                encoded, raw = _canonical_json(
                    arguments,
                    max_bytes=self.executor.max_argument_bytes,
                    label="arguments",
                )
                _assert_json_object_keys(arguments)
                normalized = json.loads(encoded)
            except ToolValidationError:
                raise ToolBridgeValidationError(
                    "tool arguments must be bounded valid JSON objects"
                ) from None
            digest = hashlib.sha256(raw).hexdigest()
            request_bytes = len(call_id.encode("utf-8")) + len(name.encode("utf-8")) + len(raw) + 16
            total_bytes += request_bytes
            if total_bytes > self.max_batch_bytes:
                raise ToolBridgeValidationError("batch exceeds the configured byte limit")
            seen.add(call_id)
            prepared.append((call_id, name, normalized, digest, request_bytes))

        outcomes = []
        for call_id, name, arguments, digest, _ in prepared:
            try:
                result = self.executor.execute(name, arguments, context)
            except ApprovalRequiredError:
                outcomes.append(ToolCallOutcome(
                    call_id, name, "approval_required",
                    error_code="approval_required", argument_digest=digest,
                ))
            except PermissionDeniedError:
                outcomes.append(ToolCallOutcome(
                    call_id, name, "permission_denied", error_code="permission_denied",
                ))
            except ToolNotFoundError:
                outcomes.append(ToolCallOutcome(
                    call_id, name, "tool_not_found", error_code="tool_not_found",
                ))
            except ToolValidationError:
                outcomes.append(ToolCallOutcome(
                    call_id, name, "invalid_arguments", error_code="invalid_arguments",
                ))
            except ToolExecutionError:
                outcomes.append(ToolCallOutcome(
                    call_id, name, "execution_failed", error_code="handler_failed",
                ))
            except AuditError:
                outcomes.append(ToolCallOutcome(
                    call_id, name, "outcome_uncertain", error_code="audit_outcome_uncertain",
                    argument_digest=digest,
                ))
            else:
                outcomes.append(ToolCallOutcome(
                    call_id, name, "succeeded", result=result,
                ))
        return tuple(outcomes)
