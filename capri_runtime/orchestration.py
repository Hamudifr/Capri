"""Provider-neutral bounded model/tool orchestration.

The host supplies the adapter, trusted identity context, and session persistence.
Every proposed tool call passes through ToolExecutionBridge.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from .runtime import Message
from .tool_bridge import (
    ToolBridgeValidationError,
    ToolCallOutcome,
    ToolCallRequest,
    ToolDefinition,
    ToolExecutionBridge,
)
from .tools import ExecutionContext


class ToolOrchestrationError(Exception):
    """A model turn could not safely complete within configured limits."""


@dataclass(frozen=True, slots=True)
class AssistantTurn:
    """Structured adapter output; all fields are treated as untrusted."""

    content: str = ""
    tool_calls: tuple[ToolCallRequest, ...] = ()


@dataclass(frozen=True, slots=True)
class OrchestrationResult:
    """Completed assistant turn and provider-neutral transcript."""

    final_text: str
    messages: tuple[Message, ...]
    tool_outcomes: tuple[ToolCallOutcome, ...]
    tool_rounds: int


class ToolModelAdapter(Protocol):
    """Host-supplied adapter that translates provider responses to AssistantTurn."""

    def complete_with_tools(
        self,
        session_id: str,
        history: tuple[Message, ...],
        tools: tuple[ToolDefinition, ...],
    ) -> AssistantTurn:
        """Return assistant text or structured tool calls for the next turn."""
        ...


def _valid_text(value: str) -> bool:
    return isinstance(value, str) and not any(
        0xD800 <= ord(character) <= 0xDFFF for character in value
    )


def _history_size(messages: list[Message]) -> int:
    """Count UTF-8 transcript bytes plus small per-message framing overhead."""
    return sum(
        len(message.role.encode("utf-8"))
        + len(message.content.encode("utf-8"))
        + 16
        for message in messages
    )


class ToolOrchestrator:
    """Run a bounded model/tool loop without creating or escalating authority."""

    def __init__(
        self,
        adapter: ToolModelAdapter,
        bridge: ToolExecutionBridge,
        *,
        max_tool_rounds: int = 4,
        max_history_messages: int = 64,
        max_output_chars: int = 64_000,
        max_tool_message_bytes: int = 131_072,
        max_history_bytes: int = 2_097_152,
    ) -> None:
        if not callable(getattr(adapter, "complete_with_tools", None)):
            raise ToolOrchestrationError("adapter must implement complete_with_tools()")
        if not isinstance(bridge, ToolExecutionBridge):
            raise ToolOrchestrationError("bridge must be a ToolExecutionBridge")
        for name, value in (
            ("max_tool_rounds", max_tool_rounds),
            ("max_history_messages", max_history_messages),
            ("max_output_chars", max_output_chars),
            ("max_tool_message_bytes", max_tool_message_bytes),
            ("max_history_bytes", max_history_bytes),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ToolOrchestrationError(f"{name} must be a positive integer")
        if max_tool_rounds > 16 or max_history_messages > 512:
            raise ToolOrchestrationError("configured orchestration limit exceeds the hard maximum")
        if max_output_chars > 1_000_000 or max_tool_message_bytes > 1_048_576:
            raise ToolOrchestrationError("configured message limit exceeds the hard maximum")
        if max_history_bytes > 16_777_216:
            raise ToolOrchestrationError("configured history byte limit exceeds the hard maximum")
        if max_tool_message_bytes < bridge.executor.max_result_bytes + 2_048:
            raise ToolOrchestrationError(
                "tool message limit must exceed the executor result limit by at least 2048 bytes"
            )
        self.adapter = adapter
        self.bridge = bridge
        self.max_tool_rounds = max_tool_rounds
        self.max_history_messages = max_history_messages
        self.max_output_chars = max_output_chars
        self.max_tool_message_bytes = max_tool_message_bytes
        self.max_history_bytes = max_history_bytes

    def run(
        self,
        session_id: str,
        user_text: str,
        history: tuple[Message, ...],
        context: ExecutionContext,
    ) -> OrchestrationResult:
        """Complete one turn, executing at most max_tool_rounds tool batches.

        The returned transcript includes intermediate assistant-call and tool-result
        messages. The host decides how to persist it and must serialize concurrent
        turns for the same session before invoking this method.
        """
        if not _valid_text(session_id) or not session_id.strip() or len(session_id) > 256:
            raise ToolOrchestrationError("session_id must be bounded valid text")
        if not _valid_text(user_text) or not user_text.strip() or len(user_text) > 16_000:
            raise ToolOrchestrationError("user_text must be bounded non-empty valid text")
        if not isinstance(context, ExecutionContext):
            raise ToolOrchestrationError("a trusted host ExecutionContext is required")
        if not isinstance(history, tuple) or len(history) + 1 > self.max_history_messages:
            raise ToolOrchestrationError("history plus the current user message exceeds the configured limit")
        for message in history:
            if (
                not isinstance(message, Message)
                or not _valid_text(message.role)
                or not _valid_text(message.content)
                or not message.role
                or len(message.role) > 32
                or len(message.content) > self.max_output_chars
            ):
                raise ToolOrchestrationError("history contains an invalid message")
        working = list(history)
        working.append(Message(role="user", content=user_text))
        if _history_size(working) > self.max_history_bytes:
            raise ToolOrchestrationError("conversation history exceeds the configured byte limit")
        outcomes: list[ToolCallOutcome] = []
        seen_call_ids: set[str] = set()
        tool_rounds = 0
        try:
            definitions = self.bridge.available_tools(context)
        except Exception:
            raise ToolOrchestrationError("tool definitions could not be prepared") from None

        for turn_index in range(self.max_tool_rounds + 1):
            try:
                response = self.adapter.complete_with_tools(
                    session_id, tuple(working), definitions
                )
            except Exception:
                raise ToolOrchestrationError("model adapter failed") from None
            if not isinstance(response, AssistantTurn):
                raise ToolOrchestrationError("adapter must return an AssistantTurn")
            if not _valid_text(response.content) or len(response.content) > self.max_output_chars:
                raise ToolOrchestrationError("adapter content is invalid or oversized")
            if not isinstance(response.tool_calls, tuple):
                raise ToolOrchestrationError("adapter tool_calls must be a tuple")

            if not response.tool_calls:
                if not response.content.strip():
                    raise ToolOrchestrationError("adapter must return final text or tool calls")
                if len(working) + 1 > self.max_history_messages:
                    raise ToolOrchestrationError("conversation history limit reached")
                final_message = Message(role="assistant", content=response.content)
                if _history_size(working + [final_message]) > self.max_history_bytes:
                    raise ToolOrchestrationError("final transcript exceeds the configured byte limit")
                working.append(final_message)
                return OrchestrationResult(
                    response.content,
                    tuple(working),
                    tuple(outcomes),
                    tool_rounds,
                )

            if turn_index >= self.max_tool_rounds:
                raise ToolOrchestrationError("maximum tool-call rounds reached")
            if len(response.tool_calls) > self.bridge.max_calls:
                raise ToolOrchestrationError("adapter exceeded the maximum tool-call batch size")
            if len(working) + 1 + len(response.tool_calls) > self.max_history_messages:
                raise ToolOrchestrationError("conversation history limit reached")

            duplicate_prior_id = False
            duplicate_batch_id = False
            batch_call_ids: set[str] = set()
            for call in response.tool_calls:
                if not isinstance(call, ToolCallRequest):
                    raise ToolOrchestrationError("adapter returned an invalid tool call")
                if not isinstance(call.call_id, str):
                    raise ToolOrchestrationError("adapter returned an invalid tool call ID")
                if call.call_id in batch_call_ids:
                    duplicate_batch_id = True
                if call.call_id in seen_call_ids:
                    duplicate_prior_id = True
                batch_call_ids.add(call.call_id)
            if duplicate_batch_id:
                raise ToolOrchestrationError("tool call IDs must be unique within each batch")
            seen_call_ids.update(batch_call_ids)

            call_payload = {
                "content": response.content,
                "tool_calls": [
                    {"id": call.call_id, "name": call.name, "arguments": call.arguments}
                    for call in response.tool_calls
                ],
            }
            try:
                encoded_calls = json.dumps(
                    call_payload, ensure_ascii=False, allow_nan=False,
                    sort_keys=True, separators=(",", ":"),
                )
                call_bytes = encoded_calls.encode("utf-8", errors="strict")
            except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
                raise ToolOrchestrationError("model proposed a non-JSON tool-call batch") from None
            if len(call_bytes) > self.max_tool_message_bytes:
                raise ToolOrchestrationError("tool-call message exceeds the configured byte limit")

            # Reserve the maximum permitted result envelope for every call before
            # any handler runs. This prevents successful side effects from being
            # followed by an unreturnable transcript due solely to history growth.
            projected_bytes = (
                _history_size(working)
                + len(call_bytes)
                + 16
                + len(response.tool_calls) * (self.max_tool_message_bytes + 16)
            )
            if projected_bytes > self.max_history_bytes:
                raise ToolOrchestrationError(
                    "tool-call batch could exceed the remaining transcript byte budget"
                )

            if duplicate_prior_id:
                batch_outcomes = [
                    ToolCallOutcome(
                        call.call_id, call.name, "invalid_request",
                        error_code="duplicate_call_id",
                    )
                    for call in response.tool_calls
                ]
            else:
                try:
                    batch_outcomes = self.bridge.execute_batch(
                        list(response.tool_calls), context
                    )
                except ToolBridgeValidationError:
                    raise ToolOrchestrationError("model proposed an invalid tool-call batch") from None

            encoded_results = []
            for item in batch_outcomes:
                try:
                    encoded = json.dumps(
                        {
                            "call_id": item.call_id,
                            "name": item.name,
                            "status": item.status,
                            "result": item.result,
                            "error_code": item.error_code,
                            "argument_digest": item.argument_digest,
                        },
                        ensure_ascii=False, allow_nan=False,
                        sort_keys=True, separators=(",", ":"),
                    )
                    if len(encoded.encode("utf-8", errors="strict")) > self.max_tool_message_bytes:
                        raise ValueError("tool result message too large")
                    encoded_results.append(encoded)
                except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
                    raise ToolOrchestrationError(
                        "tool outcome could not be represented safely; inspect the audit record"
                    ) from None

            working.append(Message(role="assistant", content=encoded_calls))
            working.extend(
                Message(role="tool", content=item) for item in encoded_results
            )
            if _history_size(working) > self.max_history_bytes:
                # Defensive invariant; the pre-execution reservation should make
                # this unreachable for executor-bounded results.
                raise ToolOrchestrationError("conversation history byte limit reached")
            outcomes.extend(batch_outcomes)
            tool_rounds += 1

        raise ToolOrchestrationError("orchestration ended without a final response")
