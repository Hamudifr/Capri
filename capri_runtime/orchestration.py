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
        user_text: str,
        history: tuple[Message, ...],
        tools: tuple[ToolDefinition, ...],
    ) -> AssistantTurn:
        """Return assistant text or structured tool calls for the next turn."""
        ...


def _valid_text(value: str) -> bool:
    return isinstance(value, str) and not any(
        0xD800 <= ord(character) <= 0xDFFF for character in value
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
        max_tool_message_bytes: int = 65_536,
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
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ToolOrchestrationError(f"{name} must be a positive integer")
        if max_tool_rounds > 16 or max_history_messages > 512:
            raise ToolOrchestrationError("configured orchestration limit exceeds the hard maximum")
        if max_output_chars > 1_000_000 or max_tool_message_bytes > 1_048_576:
            raise ToolOrchestrationError("configured message limit exceeds the hard maximum")
        self.adapter = adapter
        self.bridge = bridge
        self.max_tool_rounds = max_tool_rounds
        self.max_history_messages = max_history_messages
        self.max_output_chars = max_output_chars
        self.max_tool_message_bytes = max_tool_message_bytes

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
        if not isinstance(history, tuple) or len(history) > self.max_history_messages:
            raise ToolOrchestrationError("history must be a bounded tuple of messages")
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
                    session_id, user_text, tuple(working), definitions
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
                working.append(Message(role="assistant", content=response.content))
                return OrchestrationResult(
                    response.content,
                    tuple(working),
                    tuple(outcomes),
                    tool_rounds,
                )

            if turn_index >= self.max_tool_rounds:
                raise ToolOrchestrationError("maximum tool-call rounds reached")
            for call in response.tool_calls:
                if not isinstance(call, ToolCallRequest):
                    raise ToolOrchestrationError("adapter returned an invalid tool call")
                if not isinstance(call.call_id, str) or call.call_id in seen_call_ids:
                    raise ToolOrchestrationError("tool call IDs must be unique across the turn")
                seen_call_ids.add(call.call_id)

            try:
                batch_outcomes = self.bridge.execute_batch(
                    list(response.tool_calls), context
                )
            except ToolBridgeValidationError:
                raise ToolOrchestrationError("model proposed an invalid tool-call batch") from None

            call_payload = {
                "content": response.content,
                "tool_calls": [
                    {"id": call.call_id, "name": call.name, "arguments": call.arguments}
                    for call in response.tool_calls
                ],
            }
            encoded_calls = json.dumps(
                call_payload, ensure_ascii=False, allow_nan=False,
                sort_keys=True, separators=(",", ":"),
            )
            encoded_results = [
                json.dumps(
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
                for item in batch_outcomes
            ]
            added_messages = 1 + len(encoded_results)
            if len(working) + added_messages > self.max_history_messages:
                raise ToolOrchestrationError("conversation history limit reached")
            if (
                len(encoded_calls.encode("utf-8")) > self.max_tool_message_bytes
                or any(len(item.encode("utf-8")) > self.max_tool_message_bytes for item in encoded_results)
            ):
                raise ToolOrchestrationError("tool transcript message exceeds the configured byte limit")

            working.append(Message(role="assistant", content=encoded_calls))
            working.extend(
                Message(role="tool", content=item) for item in encoded_results
            )
            outcomes.extend(batch_outcomes)
            tool_rounds += 1

        raise ToolOrchestrationError("orchestration ended without a final response")
