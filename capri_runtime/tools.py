"""Permissioned host-injected tool execution.

No provider SDK, dynamic imports, shell execution, network access, or filesystem
access is provided here. Trusted host code supplies handlers and caller context.
"""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import math
import re
import time
from dataclasses import dataclass
from enum import Enum
from threading import RLock
from typing import Any, Callable, Mapping


_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_PERMISSION = re.compile(r"^[a-z][a-z0-9_.:-]{0,95}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_SCHEMA_DEPTH = 16
_MAX_VALUE_DEPTH = 16
_SUPPORTED_SCHEMA_KEYS = {
    "type", "properties", "required", "additionalProperties", "items", "enum",
    "minLength", "maxLength", "minimum", "maximum", "minItems", "maxItems",
}


class ToolError(Exception):
    """Base class for expected tool-registry failures."""


class ToolRegistrationError(ToolError):
    """A tool definition is invalid or duplicates an existing tool."""


class ToolNotFoundError(ToolError):
    """The requested tool is not registered."""


class ToolArgumentError(ToolError):
    """Tool arguments or a tool result violate the data contract."""


class ToolPermissionDenied(ToolError):
    """The trusted caller context lacks an exact required permission."""


class ToolApprovalRequired(ToolError):
    """A host approval is required for this exact tool call."""

    def __init__(self, tool_name: str, argument_digest: str) -> None:
        super().__init__("tool call requires action-specific approval")
        self.tool_name = tool_name
        self.argument_digest = argument_digest


class ToolApprovalInvalid(ToolError):
    """An approval grant is expired, mismatched, or already consumed."""


class ToolExecutionError(ToolError):
    """A handler failed or returned an invalid result."""

    def __init__(
        self,
        message: str,
        *,
        execution_attempted: bool,
        execution_completed: bool,
    ) -> None:
        super().__init__(message)
        self.execution_attempted = execution_attempted
        self.execution_completed = execution_completed


class ToolAuditError(ToolError):
    """The audit sink failed; the execution state may be uncertain."""

    def __init__(
        self,
        *,
        execution_attempted: bool,
        execution_completed: bool,
    ) -> None:
        super().__init__("tool audit sink failed")
        self.execution_attempted = execution_attempted
        self.execution_completed = execution_completed


class ToolEffect(str, Enum):
    READ = "read"
    WRITE = "write"
    EXTERNAL = "external"
    DESTRUCTIVE = "destructive"


@dataclass(frozen=True, slots=True)
class ApprovalGrant:
    """Host-issued, single-use approval for one principal and one exact call.

    Only trusted host code should construct grants after explicit approval.
    Never accept this object or its fields from model-generated arguments.
    """

    grant_id: str
    principal_id: str
    tool_name: str
    argument_digest: str
    expires_at: float

    def __post_init__(self) -> None:
        for name in ("grant_id", "principal_id", "tool_name"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if not _TOOL_NAME.fullmatch(self.tool_name):
            raise ValueError("tool_name is invalid")
        if not isinstance(self.argument_digest, str) or not _SHA256.fullmatch(
            self.argument_digest
        ):
            raise ValueError("argument_digest must be a lowercase SHA-256 hex digest")
        if (
            isinstance(self.expires_at, bool)
            or not isinstance(self.expires_at, (int, float))
            or not math.isfinite(self.expires_at)
            or self.expires_at <= 0
        ):
            raise ValueError("expires_at must be a positive finite timestamp")


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    """Trusted host context; never populate permissions or grants from model output."""

    principal_id: str
    permissions: frozenset[str]
    request_id: str
    approval_grants: tuple[ApprovalGrant, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.principal_id, str) or not self.principal_id.strip():
            raise ValueError("principal_id must be a non-empty string")
        if not isinstance(self.request_id, str) or not self.request_id.strip():
            raise ValueError("request_id must be a non-empty string")
        if not isinstance(self.permissions, frozenset):
            raise ValueError("permissions must be a frozenset")
        for permission in self.permissions:
            if not isinstance(permission, str) or not _PERMISSION.fullmatch(permission):
                raise ValueError("permissions must contain exact valid permission names")
        if not isinstance(self.approval_grants, tuple) or any(
            not isinstance(grant, ApprovalGrant) for grant in self.approval_grants
        ):
            raise ValueError("approval_grants must be a tuple of ApprovalGrant values")


@dataclass(frozen=True, slots=True)
class ToolCallContext:
    """Minimal identity and permissions passed to a trusted host handler."""

    principal_id: str
    request_id: str
    permissions: frozenset[str]


ToolHandler = Callable[[Mapping[str, Any], ToolCallContext], Any]
AuditSink = Callable[["ToolAuditEvent"], None]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: Mapping[str, Any]
    required_permissions: frozenset[str]
    effect: ToolEffect
    handler: ToolHandler
    approval_required: bool = False


@dataclass(frozen=True, slots=True)
class ToolAuditEvent:
    timestamp: float
    request_id: str
    principal_id: str
    tool_name: str
    effect: str
    status: str
    argument_digest: str
    duration_ms: int | None = None


@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
    tool_name: str
    output: Any
    argument_digest: str


@dataclass(frozen=True, slots=True)
class _RegisteredTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    required_permissions: frozenset[str]
    effect: ToolEffect
    handler: ToolHandler
    approval_required: bool


def _contains_surrogate(value: str) -> bool:
    return any(0xD800 <= ord(character) <= 0xDFFF for character in value)


def _assert_json_value(
    value: Any,
    *,
    depth: int = 0,
    seen: set[int] | None = None,
) -> None:
    if depth > _MAX_VALUE_DEPTH:
        raise ToolArgumentError("JSON value exceeds maximum nesting depth")
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, str):
        if _contains_surrogate(value):
            raise ToolArgumentError("JSON strings must contain valid Unicode scalar values")
        return
    if isinstance(value, int) and not isinstance(value, bool):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ToolArgumentError("JSON numbers must be finite")
        return
    if not isinstance(value, (dict, list)):
        raise ToolArgumentError("value is not composed of supported JSON types")

    active = seen if seen is not None else set()
    identity = id(value)
    if identity in active:
        raise ToolArgumentError("cyclic JSON values are not supported")
    active.add(identity)
    try:
        if isinstance(value, dict):
            for key, child in value.items():
                if not isinstance(key, str):
                    raise ToolArgumentError("JSON object keys must be strings")
                _assert_json_value(child, depth=depth + 1, seen=active)
        else:
            for child in value:
                _assert_json_value(child, depth=depth + 1, seen=active)
    finally:
        active.remove(identity)


def _canonical_json(value: Any) -> bytes:
    _assert_json_value(value)
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        raise ToolArgumentError("value cannot be encoded as bounded JSON") from None


def _validate_schema_definition(schema: Any, *, depth: int = 0) -> None:
    if depth > _MAX_SCHEMA_DEPTH or not isinstance(schema, dict):
        raise ToolRegistrationError("input schema must be a bounded JSON object")
    if set(schema) - _SUPPORTED_SCHEMA_KEYS:
        raise ToolRegistrationError("input schema contains unsupported keywords")

    value_type = schema.get("type")
    allowed_types = {"object", "array", "string", "integer", "number", "boolean"}
    if not isinstance(value_type, str) or value_type not in allowed_types:
        raise ToolRegistrationError("input schema has an unsupported or missing type")

    if "enum" in schema:
        enum_values = schema["enum"]
        if not isinstance(enum_values, list) or not enum_values:
            raise ToolRegistrationError("enum must be a non-empty list")
        try:
            for value in enum_values:
                _assert_json_value(value)
        except ToolArgumentError:
            raise ToolRegistrationError("enum values must be JSON-compatible") from None

    for key in ("minLength", "maxLength", "minItems", "maxItems"):
        if key in schema:
            value = schema[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ToolRegistrationError(f"{key} must be a non-negative integer")

    for key in ("minimum", "maximum"):
        if key in schema:
            value = schema[key]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ToolRegistrationError(f"{key} must be a finite number")

    if "minLength" in schema and "maxLength" in schema:
        if schema["minLength"] > schema["maxLength"]:
            raise ToolRegistrationError("minLength cannot exceed maxLength")
    if "minItems" in schema and "maxItems" in schema:
        if schema["minItems"] > schema["maxItems"]:
            raise ToolRegistrationError("minItems cannot exceed maxItems")
    if "minimum" in schema and "maximum" in schema:
        if schema["minimum"] > schema["maximum"]:
            raise ToolRegistrationError("minimum cannot exceed maximum")

    if value_type == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(properties, dict) or any(
            not isinstance(key, str) for key in properties
        ):
            raise ToolRegistrationError("object properties must be a mapping")
        if not isinstance(required, list) or any(
            not isinstance(key, str) for key in required
        ):
            raise ToolRegistrationError("required must be a list of property names")
        if len(set(required)) != len(required) or not set(required).issubset(properties):
            raise ToolRegistrationError("required must contain unique declared properties")
        if schema.get("additionalProperties", False) is not False:
            raise ToolRegistrationError("additionalProperties must be false")
        if "items" in schema:
            raise ToolRegistrationError("object schemas cannot define items")
        for child in properties.values():
            _validate_schema_definition(child, depth=depth + 1)
    elif value_type == "array":
        if "items" not in schema:
            raise ToolRegistrationError("array schemas must define items")
        if any(key in schema for key in ("properties", "required", "additionalProperties")):
            raise ToolRegistrationError("array schemas cannot define object keywords")
        _validate_schema_definition(schema["items"], depth=depth + 1)
    else:
        if any(
            key in schema
            for key in ("properties", "required", "additionalProperties", "items")
        ):
            raise ToolRegistrationError("scalar schemas cannot define object or array keywords")
        if value_type != "string" and any(
            key in schema for key in ("minLength", "maxLength")
        ):
            raise ToolRegistrationError("string length constraints require type=string")
        if value_type not in {"integer", "number"} and any(
            key in schema for key in ("minimum", "maximum")
        ):
            raise ToolRegistrationError("numeric bounds require a numeric type")
        if any(key in schema for key in ("minItems", "maxItems")):
            raise ToolRegistrationError("item bounds require type=array")


def _validate_value(value: Any, schema: Mapping[str, Any], *, path: str) -> None:
    value_type = schema["type"]
    if value_type == "object":
        valid = isinstance(value, dict)
    elif value_type == "array":
        valid = isinstance(value, list)
    elif value_type == "string":
        valid = isinstance(value, str) and not _contains_surrogate(value)
    elif value_type == "integer":
        valid = isinstance(value, int) and not isinstance(value, bool)
    elif value_type == "number":
        valid = (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        )
    else:
        valid = isinstance(value, bool)
    if not valid:
        raise ToolArgumentError(f"{path} must be {value_type}")

    if "enum" in schema and value not in schema["enum"]:
        raise ToolArgumentError(f"{path} is not an allowed value")

    if value_type == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if set(required) - set(value):
            raise ToolArgumentError(f"{path} is missing required properties")
        if set(value) - set(properties):
            raise ToolArgumentError(f"{path} contains unsupported properties")
        for key, child in value.items():
            _validate_value(child, properties[key], path=f"{path}.{key}")
    elif value_type == "array":
        if len(value) < schema.get("minItems", 0):
            raise ToolArgumentError(f"{path} has too few items")
        if len(value) > schema.get("maxItems", 100):
            raise ToolArgumentError(f"{path} has too many items")
        for index, child in enumerate(value):
            _validate_value(child, schema["items"], path=f"{path}[{index}]")
    elif value_type == "string":
        if len(value) < schema.get("minLength", 0):
            raise ToolArgumentError(f"{path} is too short")
        if len(value) > schema.get("maxLength", 16_000):
            raise ToolArgumentError(f"{path} is too long")
    elif value_type in {"integer", "number"}:
        if "minimum" in schema and value < schema["minimum"]:
            raise ToolArgumentError(f"{path} is below its minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise ToolArgumentError(f"{path} exceeds its maximum")


class ToolRegistry:
    """Allowlisted tool executor with strict validation, permissions and audit."""

    def __init__(
        self,
        *,
        audit_sink: AuditSink,
        max_argument_bytes: int = 64_000,
        max_result_bytes: int = 64_000,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not callable(audit_sink) or inspect.iscoroutinefunction(audit_sink):
            raise ToolRegistrationError("a synchronous audit_sink is required")
        for name, value in (
            ("max_argument_bytes", max_argument_bytes),
            ("max_result_bytes", max_result_bytes),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ToolRegistrationError(f"{name} must be a positive integer")
        if not callable(clock):
            raise ToolRegistrationError("clock must be callable")
        self.max_argument_bytes = max_argument_bytes
        self.max_result_bytes = max_result_bytes
        self._audit_sink = audit_sink
        self._clock = clock
        self._tools: dict[str, _RegisteredTool] = {}
        self._consumed_grant_ids: set[str] = set()
        self._lock = RLock()

    @staticmethod
    def argument_digest(tool_name: str, arguments: Mapping[str, Any]) -> str:
        """Return the canonical digest a trusted host binds into an approval grant."""
        if not isinstance(tool_name, str) or not _TOOL_NAME.fullmatch(tool_name):
            raise ToolArgumentError("tool_name is invalid")
        if not isinstance(arguments, dict):
            raise ToolArgumentError("tool arguments must be an object")
        encoded = _canonical_json(arguments)
        return hashlib.sha256(
            b"capri-tool-call-v1\x00" + tool_name.encode("ascii") + b"\x00" + encoded
        ).hexdigest()

    def register(self, spec: ToolSpec) -> None:
        if not isinstance(spec, ToolSpec):
            raise ToolRegistrationError("spec must be a ToolSpec")
        if not isinstance(spec.name, str) or not _TOOL_NAME.fullmatch(spec.name):
            raise ToolRegistrationError("tool name is invalid")
        if (
            not isinstance(spec.description, str)
            or not spec.description.strip()
            or len(spec.description) > 512
            or _contains_surrogate(spec.description)
        ):
            raise ToolRegistrationError("tool description must be valid text up to 512 characters")
        if not isinstance(spec.input_schema, dict):
            raise ToolRegistrationError("input_schema must be a plain dictionary")
        if (
            not isinstance(spec.required_permissions, frozenset)
            or not spec.required_permissions
        ):
            raise ToolRegistrationError("at least one exact required permission is mandatory")
        if any(
            not isinstance(permission, str) or not _PERMISSION.fullmatch(permission)
            for permission in spec.required_permissions
        ):
            raise ToolRegistrationError("required permissions must be exact valid names")
        if not isinstance(spec.effect, ToolEffect):
            raise ToolRegistrationError("effect must be a ToolEffect")
        if not callable(spec.handler):
            raise ToolRegistrationError("handler must be callable")
        if not isinstance(spec.approval_required, bool):
            raise ToolRegistrationError("approval_required must be a boolean")
        if (
            spec.effect in {ToolEffect.EXTERNAL, ToolEffect.DESTRUCTIVE}
            and not spec.approval_required
        ):
            raise ToolRegistrationError("external and destructive tools must require approval")

        schema = copy.deepcopy(spec.input_schema)
        _validate_schema_definition(schema)
        if schema["type"] != "object":
            raise ToolRegistrationError("tool input schema root must be an object")

        entry = _RegisteredTool(
            name=spec.name,
            description=spec.description,
            input_schema=schema,
            required_permissions=spec.required_permissions,
            effect=spec.effect,
            handler=spec.handler,
            approval_required=spec.approval_required,
        )
        with self._lock:
            if spec.name in self._tools:
                raise ToolRegistrationError("tool name is already registered")
            self._tools[spec.name] = entry

    def list_tools(self) -> tuple[tuple[str, str, str], ...]:
        """Return metadata only; handlers, schemas, and secrets are not exposed."""
        with self._lock:
            return tuple(
                sorted(
                    (tool.name, tool.description, tool.effect.value)
                    for tool in self._tools.values()
                )
            )

    def _emit(
        self,
        *,
        context: ToolExecutionContext,
        tool: _RegisteredTool,
        status: str,
        argument_digest: str,
        duration_ms: int | None = None,
        execution_attempted: bool = False,
        execution_completed: bool = False,
    ) -> None:
        event = ToolAuditEvent(
            timestamp=float(self._clock()),
            request_id=context.request_id,
            principal_id=context.principal_id,
            tool_name=tool.name,
            effect=tool.effect.value,
            status=status,
            argument_digest=argument_digest,
            duration_ms=duration_ms,
        )
        try:
            outcome = self._audit_sink(event)
            if inspect.isawaitable(outcome):
                close = getattr(outcome, "close", None)
                if callable(close):
                    close()
                raise TypeError("audit sink must be synchronous")
        except Exception:
            raise ToolAuditError(
                execution_attempted=execution_attempted,
                execution_completed=execution_completed,
            ) from None

    def _consume_approval(
        self,
        *,
        context: ToolExecutionContext,
        tool: _RegisteredTool,
        argument_digest: str,
    ) -> None:
        grants = [
            grant
            for grant in context.approval_grants
            if grant.principal_id == context.principal_id and grant.tool_name == tool.name
        ]
        if not grants:
            self._emit(
                context=context,
                tool=tool,
                status="approval_required",
                argument_digest=argument_digest,
            )
            raise ToolApprovalRequired(tool.name, argument_digest)

        matching = [grant for grant in grants if grant.argument_digest == argument_digest]
        if not matching:
            self._emit(
                context=context,
                tool=tool,
                status="approval_mismatch",
                argument_digest=argument_digest,
            )
            raise ToolApprovalInvalid("approval grant does not match this exact call")

        grant = matching[0]
        if grant.expires_at <= float(self._clock()):
            self._emit(
                context=context,
                tool=tool,
                status="approval_expired",
                argument_digest=argument_digest,
            )
            raise ToolApprovalInvalid("approval grant has expired")

        with self._lock:
            replay = grant.grant_id in self._consumed_grant_ids
            if not replay:
                self._consumed_grant_ids.add(grant.grant_id)
        if replay:
            self._emit(
                context=context,
                tool=tool,
                status="approval_replay",
                argument_digest=argument_digest,
            )
            raise ToolApprovalInvalid("approval grant has already been consumed")

    def execute(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        if not isinstance(context, ToolExecutionContext):
            raise ToolPermissionDenied("trusted host execution context is required")
        if not isinstance(tool_name, str) or not _TOOL_NAME.fullmatch(tool_name):
            raise ToolNotFoundError("tool is not registered")
        with self._lock:
            tool = self._tools.get(tool_name)
        if tool is None:
            raise ToolNotFoundError("tool is not registered")

        if not isinstance(arguments, dict):
            raise ToolArgumentError("tool arguments must be an object")
        encoded = _canonical_json(arguments)
        if len(encoded) > self.max_argument_bytes:
            raise ToolArgumentError("tool arguments exceed max_argument_bytes")
        _validate_value(arguments, tool.input_schema, path="arguments")
        digest = self.argument_digest(tool.name, arguments)

        if not tool.required_permissions.issubset(context.permissions):
            self._emit(
                context=context,
                tool=tool,
                status="permission_denied",
                argument_digest=digest,
            )
            raise ToolPermissionDenied("caller lacks a required tool permission")

        if tool.approval_required:
            self._consume_approval(
                context=context,
                tool=tool,
                argument_digest=digest,
            )

        self._emit(
            context=context,
            tool=tool,
            status="started",
            argument_digest=digest,
        )
        started = time.perf_counter()
        call_context = ToolCallContext(
            principal_id=context.principal_id,
            request_id=context.request_id,
            permissions=context.permissions,
        )
        try:
            output = tool.handler(copy.deepcopy(arguments), call_context)
        except Exception:
            duration = int((time.perf_counter() - started) * 1000)
            self._emit(
                context=context,
                tool=tool,
                status="handler_failed",
                argument_digest=digest,
                duration_ms=duration,
                execution_attempted=True,
            )
            raise ToolExecutionError(
                "tool handler failed; side effects may be partial",
                execution_attempted=True,
                execution_completed=False,
            ) from None

        try:
            encoded_output = _canonical_json(output)
            if len(encoded_output) > self.max_result_bytes:
                raise ToolArgumentError("tool result exceeds max_result_bytes")
        except ToolArgumentError:
            duration = int((time.perf_counter() - started) * 1000)
            self._emit(
                context=context,
                tool=tool,
                status="result_rejected",
                argument_digest=digest,
                duration_ms=duration,
                execution_attempted=True,
                execution_completed=True,
            )
            raise ToolExecutionError(
                "tool result failed JSON or size validation",
                execution_attempted=True,
                execution_completed=True,
            ) from None

        duration = int((time.perf_counter() - started) * 1000)
        self._emit(
            context=context,
            tool=tool,
            status="succeeded",
            argument_digest=digest,
            duration_ms=duration,
            execution_attempted=True,
            execution_completed=True,
        )
        return ToolExecutionResult(
            tool_name=tool.name,
            output=copy.deepcopy(output),
            argument_digest=digest,
        )
