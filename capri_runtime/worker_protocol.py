"""Versioned, bounded JSON contract for isolated Capri workers.

This module validates messages only. It does not launch processes, grant permissions,
or treat worker output as trusted authorization.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 1_048_576
MAX_DEADLINE_MS = 120_000
MAX_JSON_DEPTH = 32
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CAPABILITY_PATTERN = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")


class WorkerProtocolError(ValueError):
    """Raised when a worker message violates the public protocol contract."""


def _pairs_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise WorkerProtocolError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise WorkerProtocolError(f"non-standard JSON constant: {value}")


def _depth(value: Any) -> int:
    """Validate JSON-shaped data iteratively, including cycles and nesting depth."""
    maximum = 0
    active: set[int] = set()
    stack: list[tuple[Any, int, bool]] = [(value, 0, False)]
    while stack:
        current, level, exiting = stack.pop()
        if level > MAX_JSON_DEPTH:
            raise WorkerProtocolError("JSON nesting exceeds the protocol limit")
        maximum = max(maximum, level)
        kind = type(current)
        if kind in (dict, list):
            identity = id(current)
            if exiting:
                active.remove(identity)
                continue
            if identity in active:
                raise WorkerProtocolError("cyclic values are not valid JSON data")
            active.add(identity)
            stack.append((current, level, True))
            if kind is dict:
                children = []
                for key, child in current.items():
                    if type(key) is not str:
                        raise WorkerProtocolError("JSON object keys must be strings")
                    children.append(child)
            else:
                children = current
            for child in reversed(children):
                stack.append((child, level + 1, False))
        elif current is not None and kind not in (str, int, float, bool):
            raise WorkerProtocolError("unsupported JSON value")
    return maximum


def _json_object(value: Any, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise WorkerProtocolError(f"{field} must be a JSON object")
    _depth(value)
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError):
        raise WorkerProtocolError(f"{field} is not valid JSON data") from None
    if len(encoded) > MAX_MESSAGE_BYTES:
        raise WorkerProtocolError(f"{field} exceeds the message size limit")
    return value


def _identifier(value: Any, field: str) -> str:
    if type(value) is not str or not _ID_PATTERN.fullmatch(value):
        raise WorkerProtocolError(f"{field} must be a valid protocol identifier")
    return value


def _capability(value: Any) -> str:
    if type(value) is not str or not _CAPABILITY_PATTERN.fullmatch(value):
        raise WorkerProtocolError("capability must be a lowercase capability identifier")
    return value


def _encode(envelope: dict[str, Any]) -> str:
    _depth(envelope)
    try:
        raw = json.dumps(
            envelope, ensure_ascii=False, allow_nan=False, sort_keys=True,
            separators=(",", ":"),
        )
        size = len(raw.encode("utf-8"))
    except (TypeError, ValueError, UnicodeEncodeError):
        raise WorkerProtocolError("message contains unsupported JSON data") from None
    if size > MAX_MESSAGE_BYTES:
        raise WorkerProtocolError("message exceeds the protocol size limit")
    return raw


def _decode(raw: str | bytes) -> dict[str, Any]:
    if type(raw) not in (str, bytes):
        raise WorkerProtocolError("message must be UTF-8 text or bytes")
    try:
        encoded = raw.encode("utf-8") if type(raw) is str else raw
        if len(encoded) > MAX_MESSAGE_BYTES:
            raise WorkerProtocolError("message exceeds the protocol size limit")
        decoded = encoded.decode("utf-8")
        value = json.loads(
            decoded, object_pairs_hook=_pairs_without_duplicates,
            parse_constant=_reject_constant,
        )
    except WorkerProtocolError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise WorkerProtocolError("message is not valid UTF-8 JSON") from None
    if type(value) is not dict:
        raise WorkerProtocolError("message envelope must be a JSON object")
    _depth(value)
    return value


@dataclass(frozen=True, slots=True)
class WorkerRequest:
    request_id: str
    capability: str
    input: dict[str, Any]
    deadline_ms: int

    def to_json(self) -> str:
        _identifier(self.request_id, "request_id")
        _capability(self.capability)
        _json_object(self.input, "input")
        if type(self.deadline_ms) is not int or not 1 <= self.deadline_ms <= MAX_DEADLINE_MS:
            raise WorkerProtocolError("deadline_ms is outside the permitted range")
        return _encode({
            "protocol_version": PROTOCOL_VERSION,
            "message_type": "request",
            "request_id": self.request_id,
            "capability": self.capability,
            "deadline_ms": self.deadline_ms,
            "input": self.input,
        })

    @classmethod
    def from_json(cls, raw: str | bytes) -> "WorkerRequest":
        data = _decode(raw)
        expected = {
            "protocol_version", "message_type", "request_id",
            "capability", "deadline_ms", "input",
        }
        if set(data) != expected:
            raise WorkerProtocolError("request envelope has missing or unknown fields")
        if type(data["protocol_version"]) is not int or data["protocol_version"] != PROTOCOL_VERSION:
            raise WorkerProtocolError("unsupported worker protocol version")
        if data["message_type"] != "request":
            raise WorkerProtocolError("expected a worker request")
        request_id = _identifier(data["request_id"], "request_id")
        capability = _capability(data["capability"])
        deadline = data["deadline_ms"]
        if type(deadline) is not int or not 1 <= deadline <= MAX_DEADLINE_MS:
            raise WorkerProtocolError("deadline_ms is outside the permitted range")
        payload = _json_object(data["input"], "input")
        return cls(request_id, capability, payload, deadline)


@dataclass(frozen=True, slots=True)
class WorkerResponse:
    request_id: str
    worker_id: str
    status: str
    duration_ms: int
    output: dict[str, Any] | None = None
    error: str | None = None

    def to_json(self) -> str:
        _identifier(self.request_id, "request_id")
        _identifier(self.worker_id, "worker_id")
        if type(self.status) is not str or self.status not in {"succeeded", "failed"}:
            raise WorkerProtocolError("status must be succeeded or failed")
        if type(self.duration_ms) is not int or self.duration_ms < 0:
            raise WorkerProtocolError("duration_ms must be a non-negative integer")
        if self.status == "succeeded":
            if self.output is None or self.error is not None:
                raise WorkerProtocolError("successful responses require output and forbid error")
            _json_object(self.output, "output")
        else:
            if self.output is not None or type(self.error) is not str or not self.error.strip():
                raise WorkerProtocolError("failed responses require an error and forbid output")
            if len(self.error) > 2_000:
                raise WorkerProtocolError("error exceeds the protocol limit")
        return _encode({
            "protocol_version": PROTOCOL_VERSION,
            "message_type": "response",
            "request_id": self.request_id,
            "worker_id": self.worker_id,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "output": self.output,
            "error": self.error,
        })

    @classmethod
    def from_json(cls, raw: str | bytes) -> "WorkerResponse":
        data = _decode(raw)
        expected = {
            "protocol_version", "message_type", "request_id", "worker_id",
            "status", "duration_ms", "output", "error",
        }
        if set(data) != expected:
            raise WorkerProtocolError("response envelope has missing or unknown fields")
        if type(data["protocol_version"]) is not int or data["protocol_version"] != PROTOCOL_VERSION:
            raise WorkerProtocolError("unsupported worker protocol version")
        if data["message_type"] != "response":
            raise WorkerProtocolError("expected a worker response")
        response = cls(
            _identifier(data["request_id"], "request_id"),
            _identifier(data["worker_id"], "worker_id"),
            data["status"],
            data["duration_ms"],
            data["output"],
            data["error"],
        )
        response.to_json()
        return response

    def validate_for(
        self,
        request: WorkerRequest,
        *,
        expected_worker_id: str,
        elapsed_ns: int | None = None,
    ) -> None:
        """Validate correlation and a deadline measured by the trusted host.

        elapsed_ns must be measured by the host with monotonic_ns() from dispatch
        until response acceptance. Worker-reported duration_ms is telemetry only
        and is never sufficient to establish deadline compliance.
        """
        if type(request) is not WorkerRequest:
            raise WorkerProtocolError("request must be a validated WorkerRequest")
        if type(self) is not WorkerResponse:
            raise WorkerProtocolError("response must be a validated WorkerResponse")
        # Validate in-memory instances too; callers must not bypass the wire contract.
        request.to_json()
        self.to_json()
        _identifier(expected_worker_id, "expected_worker_id")
        if type(elapsed_ns) is not int or elapsed_ns < 0:
            raise WorkerProtocolError("elapsed_ns must be a non-negative host-measured integer")
        if self.request_id != request.request_id:
            raise WorkerProtocolError("response request_id does not match the request")
        if self.worker_id != expected_worker_id:
            raise WorkerProtocolError("response worker_id does not match the selected worker")
        if self.duration_ms > request.deadline_ms:
            raise WorkerProtocolError("worker-reported duration exceeds the request deadline")
        if elapsed_ns > request.deadline_ms * 1_000_000:
            raise WorkerProtocolError("host-measured response time exceeds the request deadline")


__all__ = [
    "MAX_DEADLINE_MS", "MAX_JSON_DEPTH", "MAX_MESSAGE_BYTES",
    "PROTOCOL_VERSION", "WorkerProtocolError", "WorkerRequest", "WorkerResponse",
]
