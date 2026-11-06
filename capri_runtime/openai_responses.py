"""OpenAI Responses API adapter for Capri's provider-neutral tool loop.

The host injects an SDK-compatible client. This module never reads credentials,
executes tools, or creates authority; every function call is returned to the
existing ToolOrchestrator and ToolExecutionBridge.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .orchestration import AssistantTurn
from .runtime import Message
from .tool_bridge import ToolCallRequest, ToolDefinition


class OpenAIResponsesAdapterError(Exception):
    """The provider response or transcript could not be mapped safely."""


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _no_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("non-finite JSON number")


def _load_object(value: str) -> dict[str, Any]:
    parsed = json.loads(
        value,
        object_pairs_hook=_no_duplicate_pairs,
        parse_constant=_reject_constant,
    )
    if not isinstance(parsed, dict):
        raise ValueError("expected a JSON object")
    return parsed


def _plain_json(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return _plain_json(dump(mode="json", exclude_none=True))
    raise ValueError("provider item is not JSON serializable")


class OpenAIResponsesAdapter:
    """Translate Capri messages and tool definitions to the Responses API.

    Pass an initialized OpenAI SDK client (or a compatible test double). The
    adapter uses stateless full-history requests with server-side response
    storage disabled, and preserves reasoning items needed for tool-call
    continuation. The host remains responsible for SDK installation, API key
    custody, network policy, and spend limits.
    """

    def __init__(
        self,
        client: Any,
        *,
        model: str,
        instructions: str | None = None,
        max_output_tokens: int = 4096,
    ) -> None:
        responses = getattr(client, "responses", None)
        if not callable(getattr(responses, "create", None)):
            raise OpenAIResponsesAdapterError("client must expose responses.create()")
        if not isinstance(model, str) or not model.strip() or len(model) > 128:
            raise OpenAIResponsesAdapterError("model must be bounded non-empty text")
        if instructions is not None and (
            not isinstance(instructions, str) or len(instructions) > 16_000
        ):
            raise OpenAIResponsesAdapterError("instructions must be bounded text")
        if (
            isinstance(max_output_tokens, bool)
            or not isinstance(max_output_tokens, int)
            or not 1 <= max_output_tokens <= 65_536
        ):
            raise OpenAIResponsesAdapterError("max_output_tokens must be between 1 and 65536")
        self.client = client
        self.model = model
        self.instructions = instructions
        self.max_output_tokens = max_output_tokens

    @staticmethod
    def _tools(definitions: tuple[ToolDefinition, ...]) -> list[dict[str, Any]]:
        if not isinstance(definitions, tuple):
            raise OpenAIResponsesAdapterError("tool definitions must be a tuple")
        tools: list[dict[str, Any]] = []
        seen: set[str] = set()
        for definition in definitions:
            if not isinstance(definition, ToolDefinition):
                raise OpenAIResponsesAdapterError("invalid tool definition")
            if definition.name in seen:
                raise OpenAIResponsesAdapterError("duplicate tool definition")
            seen.add(definition.name)
            try:
                parameters = definition.parameters()
            except Exception:
                raise OpenAIResponsesAdapterError("tool schema is invalid") from None
            if not isinstance(parameters, dict):
                raise OpenAIResponsesAdapterError("tool schema must be an object")
            description = (
                "Registered Capri tool. The host checks permissions, arguments, "
                "and any required approval before execution."
            )
            if definition.requires_approval:
                description += " This action requires host-side approval."
            tools.append({
                "type": "function",
                "name": definition.name,
                "description": description,
                "parameters": parameters,
                # Capri's own schema validator remains authoritative. Strict
                # mode is not forced because legacy schemas may have optional fields.
                "strict": False,
            })
        return tools

    @staticmethod
    def _history(history: tuple[Message, ...]) -> list[dict[str, Any]]:
        if not isinstance(history, tuple):
            raise OpenAIResponsesAdapterError("history must be a tuple")
        result: list[dict[str, Any]] = []
        for message in history:
            if not isinstance(message, Message) or not isinstance(message.content, str):
                raise OpenAIResponsesAdapterError("history contains an invalid message")
            if message.role == "user":
                result.append({"role": "user", "content": message.content})
                continue
            if message.role == "assistant":
                try:
                    envelope = _load_object(message.content)
                except (ValueError, TypeError, json.JSONDecodeError):
                    result.append({"role": "assistant", "content": message.content})
                    continue
                if not isinstance(envelope.get("tool_calls"), list):
                    result.append({"role": "assistant", "content": message.content})
                    continue
                assistant_text = envelope.get("content", "")
                if not isinstance(assistant_text, str):
                    raise OpenAIResponsesAdapterError("assistant tool-call text is invalid")
                if assistant_text:
                    result.append({"role": "assistant", "content": assistant_text})
                provider_data = envelope.get("provider_data", [])
                if not isinstance(provider_data, list):
                    raise OpenAIResponsesAdapterError("provider continuation data is invalid")
                for item in provider_data:
                    if not isinstance(item, dict) or item.get("type") != "reasoning":
                        raise OpenAIResponsesAdapterError("unsupported provider continuation item")
                    result.append(item)
                for call in envelope["tool_calls"]:
                    if not isinstance(call, dict):
                        raise OpenAIResponsesAdapterError("stored tool call is invalid")
                    call_id = call.get("id")
                    name = call.get("name")
                    arguments = call.get("arguments")
                    if (
                        not isinstance(call_id, str) or not call_id or len(call_id) > 64
                        or not isinstance(name, str) or not name
                        or not isinstance(arguments, dict)
                    ):
                        raise OpenAIResponsesAdapterError("stored tool call fields are invalid")
                    try:
                        arguments_json = json.dumps(
                            arguments, ensure_ascii=False, allow_nan=False,
                            sort_keys=True, separators=(",", ":"),
                        )
                    except (TypeError, ValueError, RecursionError):
                        raise OpenAIResponsesAdapterError("stored tool arguments are invalid") from None
                    result.append({
                        "type": "function_call",
                        "call_id": call_id,
                        "name": name,
                        "arguments": arguments_json,
                    })
                continue
            if message.role == "tool":
                try:
                    outcome = _load_object(message.content)
                except (ValueError, TypeError, json.JSONDecodeError):
                    raise OpenAIResponsesAdapterError("stored tool result is invalid") from None
                call_id = outcome.get("call_id")
                if not isinstance(call_id, str) or not call_id:
                    raise OpenAIResponsesAdapterError("stored tool result has no call ID")
                output = json.dumps(
                    outcome, ensure_ascii=False, allow_nan=False,
                    sort_keys=True, separators=(",", ":"),
                )
                result.append({
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": output,
                })
                continue
            raise OpenAIResponsesAdapterError("history contains an unsupported message role")
        return result

    def complete_with_tools(
        self,
        session_id: str,
        history: tuple[Message, ...],
        tools: tuple[ToolDefinition, ...],
    ) -> AssistantTurn:
        if not isinstance(session_id, str) or not session_id.strip() or len(session_id) > 256:
            raise OpenAIResponsesAdapterError("session ID is invalid")
        payload: dict[str, Any] = {
            "model": self.model,
            "input": self._history(history),
            "tools": self._tools(tools),
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "max_output_tokens": self.max_output_tokens,
            "store": False,
        }
        if self.instructions is not None:
            payload["instructions"] = self.instructions
        try:
            response = self.client.responses.create(**payload)
        except Exception:
            raise OpenAIResponsesAdapterError("OpenAI Responses API request failed") from None

        status = _field(response, "status")
        if status != "completed" or _field(response, "error") is not None:
            raise OpenAIResponsesAdapterError("OpenAI response did not complete successfully")
        output_items = _field(response, "output")
        if not isinstance(output_items, (list, tuple)):
            raise OpenAIResponsesAdapterError("OpenAI response output is invalid")

        output_text = _field(response, "output_text")
        if not isinstance(output_text, str):
            output_text = ""
        tool_calls: list[ToolCallRequest] = []
        provider_data: list[dict[str, Any]] = []
        collected_text: list[str] = [output_text] if output_text else []

        for item in output_items:
            item_type = _field(item, "type")
            if item_type == "reasoning":
                try:
                    plain = _plain_json(item)
                except (TypeError, ValueError, RecursionError):
                    raise OpenAIResponsesAdapterError("reasoning continuation item is invalid") from None
                if not isinstance(plain, dict):
                    raise OpenAIResponsesAdapterError("reasoning continuation item is invalid")
                provider_data.append(plain)
                continue
            if item_type == "function_call":
                call_id = _field(item, "call_id")
                name = _field(item, "name")
                arguments = _field(item, "arguments")
                if (
                    not isinstance(call_id, str) or not call_id or len(call_id) > 64
                    or not isinstance(name, str) or not name or len(name) > 128
                    or not isinstance(arguments, str) or len(arguments) > 65_536
                ):
                    raise OpenAIResponsesAdapterError("function call fields are invalid")
                try:
                    parsed_arguments = _load_object(arguments)
                except (ValueError, TypeError, json.JSONDecodeError):
                    raise OpenAIResponsesAdapterError("function call arguments are invalid JSON") from None
                tool_calls.append(ToolCallRequest(call_id, name, parsed_arguments))
                continue
            if item_type == "message":
                content_items = _field(item, "content", [])
                if not isinstance(content_items, (list, tuple)):
                    raise OpenAIResponsesAdapterError("message content is invalid")
                for content_item in content_items:
                    content_type = _field(content_item, "type")
                    if content_type in ("output_text", "refusal"):
                        text = _field(content_item, "text")
                        if isinstance(text, str) and text:
                            collected_text.append(text)
                continue
            raise OpenAIResponsesAdapterError("unsupported OpenAI response output item")

        content = output_text or "\n".join(collected_text)
        if not content and not tool_calls:
            raise OpenAIResponsesAdapterError("OpenAI response contained no text or function calls")
        return AssistantTurn(
            content=content,
            tool_calls=tuple(tool_calls),
            provider_data=tuple(provider_data) if tool_calls else (),
        )
