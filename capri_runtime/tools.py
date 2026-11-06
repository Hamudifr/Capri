"""Permissioned, provider-neutral tool execution boundary.

Handlers are injected by trusted host code. This module never imports tools dynamically
or performs shell, filesystem, or network operations on its own.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from uuid import uuid4


class ToolBoundaryError(Exception):
    """Base class for expected tool-boundary failures."""


class ToolValidationError(ToolBoundaryError):
    """Tool name, schema, arguments, or result is invalid."""


class ToolNotFoundError(ToolBoundaryError):
    """The requested tool is not registered."""


class PermissionDeniedError(ToolBoundaryError):
    """The trusted host context does not grant the required permission."""


class ApprovalRequiredError(ToolBoundaryError):
    """A matching, unexpired, unused host approval is required."""


class AuditError(ToolBoundaryError):
    """Audit persistence failed; execution is blocked or its outcome is uncertain."""


class ToolExecutionError(ToolBoundaryError):
    """An injected handler failed; handler details are intentionally suppressed."""


class ToolCancelledError(ToolExecutionError):
    """A cooperative handler stopped after cancellation was signaled."""

    def __init__(self, message: str = "tool handler cancelled", *, outcome_uncertain: bool = False):
        super().__init__(message)
        self.outcome_uncertain = outcome_uncertain


_SCHEMA_KEYS = {
    "type", "properties", "required", "additionalProperties", "items", "enum",
    "minLength", "maxLength", "minimum", "maximum", "minItems", "maxItems",
}
_TYPES = {"object", "array", "string", "integer", "number", "boolean", "null"}
_NAME_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def _contains_surrogate(value: str) -> bool:
    return any(0xD800 <= ord(character) <= 0xDFFF for character in value)


def _canonical_json(value: Any, *, max_bytes: int, label: str) -> tuple[str, bytes]:
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True,
            separators=(",", ":"),
        )
        raw = encoded.encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        raise ToolValidationError(f"{label} must be valid JSON with Unicode scalar values") from None
    if len(raw) > max_bytes:
        raise ToolValidationError(f"{label} exceeds the configured byte limit")
    return encoded, raw


def _validate_schema_definition(schema: Any, *, root: bool = False, depth: int = 0) -> None:
    if depth > 16:
        raise ToolValidationError("schema nesting exceeds 16 levels")
    if not isinstance(schema, dict):
        raise ToolValidationError("schema nodes must be objects")
    if set(schema) - _SCHEMA_KEYS:
        raise ToolValidationError("schema contains unsupported keywords")
    kind = schema.get("type")
    if not isinstance(kind, str) or kind not in _TYPES:
        raise ToolValidationError("schema nodes require one supported type")
    if root and kind != "object":
        raise ToolValidationError("tool argument schema must have type object")
    if "enum" in schema:
        values = schema["enum"]
        if not isinstance(values, list) or not values or len(values) > 100:
            raise ToolValidationError("enum must be a non-empty list of at most 100 values")
        _canonical_json(values, max_bytes=16_384, label="schema enum")
    for key in ("minLength", "maxLength", "minItems", "maxItems"):
        if key in schema:
            value = schema[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ToolValidationError(f"{key} must be a non-negative integer")
    for key in ("minimum", "maximum"):
        if key in schema:
            value = schema[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ToolValidationError(f"{key} must be a number")
    if kind != "string" and ({"minLength", "maxLength"} & set(schema)):
        raise ToolValidationError("string length constraints require type string")
    if kind != "array" and ({"minItems", "maxItems"} & set(schema)):
        raise ToolValidationError("item count constraints require type array")
    if kind not in {"integer", "number"} and ({"minimum", "maximum"} & set(schema)):
        raise ToolValidationError("numeric bounds require a numeric type")
    if "minLength" in schema and "maxLength" in schema and schema["minLength"] > schema["maxLength"]:
        raise ToolValidationError("minLength cannot exceed maxLength")
    if "minItems" in schema and "maxItems" in schema and schema["minItems"] > schema["maxItems"]:
        raise ToolValidationError("minItems cannot exceed maxItems")
    if "minimum" in schema and "maximum" in schema and schema["minimum"] > schema["maximum"]:
        raise ToolValidationError("minimum cannot exceed maximum")
    if kind == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(properties, dict) or len(properties) > 128 or any(not isinstance(k, str) for k in properties):
            raise ToolValidationError("object properties must be a string-keyed object of at most 128 fields")
        if not isinstance(required, list) or any(not isinstance(x, str) for x in required):
            raise ToolValidationError("required must be a list of property names")
        if len(required) != len(set(required)) or any(x not in properties for x in required):
            raise ToolValidationError("required must contain unique declared properties")
        if schema.get("additionalProperties", False) is not False:
            raise ToolValidationError("additionalProperties must be false")
        for child in properties.values():
            _validate_schema_definition(child, depth=depth + 1)
    elif kind == "array":
        if "items" not in schema:
            raise ToolValidationError("array schemas require items")
        _validate_schema_definition(schema["items"], depth=depth + 1)


def _assert_json_object_keys(value: Any, depth: int = 0) -> None:
    if depth > 16:
        raise ToolValidationError("JSON nesting exceeds 16 levels")
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ToolValidationError("JSON object keys must be strings")
        for child in value.values():
            _assert_json_object_keys(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _assert_json_object_keys(child, depth + 1)


def _matches_type(value: Any, kind: str) -> bool:
    if kind == "object":
        return isinstance(value, dict) and all(isinstance(k, str) for k in value)
    if kind == "array":
        return isinstance(value, list)
    if kind == "string":
        return isinstance(value, str)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "boolean":
        return isinstance(value, bool)
    return value is None


def _validate_value(value: Any, schema: dict[str, Any], path: str = "arguments", depth: int = 0) -> None:
    if depth > 16:
        raise ToolValidationError(f"{path} exceeds the maximum nesting depth")
    kind = schema["type"]
    if not _matches_type(value, kind):
        raise ToolValidationError(f"{path} has the wrong type")
    if "enum" in schema and value not in schema["enum"]:
        raise ToolValidationError(f"{path} is not an allowed value")
    if kind == "object":
        properties = schema.get("properties", {})
        missing = set(schema.get("required", [])) - set(value)
        extra = set(value) - set(properties)
        if missing:
            raise ToolValidationError(f"{path} is missing required properties")
        if extra:
            raise ToolValidationError(f"{path} contains undeclared properties")
        for key, item in value.items():
            _validate_value(item, properties[key], f"{path}.{key}", depth + 1)
    elif kind == "array":
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", 10_000):
            raise ToolValidationError(f"{path} has an invalid item count")
        for index, item in enumerate(value):
            _validate_value(item, schema["items"], f"{path}[{index}]", depth + 1)
    elif kind == "string":
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", 1_000_000):
            raise ToolValidationError(f"{path} has an invalid string length")
    elif kind in {"integer", "number"}:
        if "minimum" in schema and value < schema["minimum"]:
            raise ToolValidationError(f"{path} is below its minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise ToolValidationError(f"{path} exceeds its maximum")


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    permission: str
    argument_schema: Mapping[str, Any]
    requires_approval: bool = False
    cooperative_cancellation: bool = False
    _schema_json: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not _NAME_RE.fullmatch(self.name):
            raise ToolValidationError("tool name must be a lowercase identifier")
        if not isinstance(self.permission, str) or not self.permission.strip() or len(self.permission) > 128:
            raise ToolValidationError("tool permission must be a non-empty string of at most 128 characters")
        if not isinstance(self.requires_approval, bool):
            raise ToolValidationError("requires_approval must be boolean")
        if not isinstance(self.cooperative_cancellation, bool):
            raise ToolValidationError("cooperative_cancellation must be boolean")
        schema = dict(self.argument_schema) if isinstance(self.argument_schema, Mapping) else None
        _validate_schema_definition(schema, root=True)
        encoded, _ = _canonical_json(schema, max_bytes=32_768, label="tool schema")
        object.__setattr__(self, "_schema_json", encoded)

    def schema(self) -> dict[str, Any]:
        """Return a fresh copy so callers cannot mutate the registered contract."""
        return json.loads(self._schema_json)


@dataclass(frozen=True, slots=True)
class ApprovalGrant:
    """Host-issued, one-use approval bound to one principal, tool, and argument digest."""

    grant_id: str
    principal_id: str
    tool_name: str
    argument_digest: str
    expires_at: str


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """Trusted host identity and grants; never construct this from model output."""

    principal_id: str
    permissions: frozenset[str]
    approvals: tuple[ApprovalGrant, ...] = ()


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_id: str
    timestamp: str
    principal_id: str
    tool_name: str
    argument_digest: str
    status: str
    error_code: str | None = None


class AuditSink:
    """Base contract for host-provided durable audit storage."""

    def write(self, event: AuditEvent) -> None:
        raise NotImplementedError


class ApprovalStore:
    """Host-provided atomic one-use approval consumption."""

    def consume(self, grant: ApprovalGrant, now: datetime) -> bool:
        raise NotImplementedError


class InMemoryApprovalStore(ApprovalStore):
    """Process-local approval replay protection for tests and single-process prototypes."""

    def __init__(self) -> None:
        self._consumed: set[str] = set()
        self._lock = threading.Lock()

    def consume(self, grant: ApprovalGrant, now: datetime) -> bool:
        if not isinstance(grant, ApprovalGrant):
            return False
        try:
            expiry = datetime.fromisoformat(grant.expires_at.replace("Z", "+00:00"))
        except (AttributeError, TypeError, ValueError):
            return False
        if expiry.tzinfo is None or expiry.utcoffset() is None or expiry <= now:
            return False
        if not isinstance(grant.grant_id, str) or not grant.grant_id:
            return False
        with self._lock:
            if grant.grant_id in self._consumed:
                return False
            self._consumed.add(grant.grant_id)
            return True


class InMemoryAuditSink(AuditSink):
    """Thread-safe test/development sink. Production hosts should inject durable storage."""

    def __init__(self, max_events: int = 10_000) -> None:
        if isinstance(max_events, bool) or not isinstance(max_events, int) or max_events < 1:
            raise ToolValidationError("max_events must be a positive integer")
        self._max_events = max_events
        self._events: list[AuditEvent] = []
        self._lock = threading.Lock()

    def write(self, event: AuditEvent) -> None:
        with self._lock:
            if len(self._events) >= self._max_events:
                raise OSError("audit capacity reached")
            self._events.append(event)

    def events(self) -> tuple[AuditEvent, ...]:
        with self._lock:
            return tuple(self._events)


class ToolRegistry:
    """Explicit allowlist; handlers are supplied by trusted application code."""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[ToolSpec, Callable[..., Any]]] = {}
        self._lock = threading.RLock()

    def register(self, spec: ToolSpec, handler: Callable[..., Any]) -> None:
        if not isinstance(spec, ToolSpec) or not callable(handler):
            raise ToolValidationError("registration requires a ToolSpec and callable handler")
        with self._lock:
            if spec.name in self._entries:
                raise ToolValidationError("duplicate tool registration")
            self._entries[spec.name] = (spec, handler)

    def resolve(self, name: str) -> tuple[ToolSpec, Callable[..., Any]]:
        with self._lock:
            try:
                return self._entries[name]
            except KeyError:
                raise ToolNotFoundError("tool is not registered") from None

    def names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._entries))


class ToolExecutor:
    """Runs allowlisted handlers after trusted permission and approval checks."""

    def __init__(
        self,
        registry: ToolRegistry,
        audit_sink: AuditSink,
        *,
        max_argument_bytes: int = 16_384,
        max_result_bytes: int = 65_536,
        clock: Callable[[], datetime] | None = None,
        approval_store: ApprovalStore | None = None,
    ) -> None:
        if not isinstance(registry, ToolRegistry) or not callable(getattr(audit_sink, "write", None)):
            raise ToolValidationError("registry and audit sink are required")
        if approval_store is not None and not callable(getattr(approval_store, "consume", None)):
            raise ToolValidationError("approval_store must implement consume()")
        for name, value in (("max_argument_bytes", max_argument_bytes), ("max_result_bytes", max_result_bytes)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ToolValidationError(f"{name} must be a positive integer")
        self.registry = registry
        self.audit_sink = audit_sink
        self.max_argument_bytes = max_argument_bytes
        self.max_result_bytes = max_result_bytes
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.approval_store = approval_store if approval_store is not None else InMemoryApprovalStore()

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ToolValidationError("executor clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc)

    def _audit(self, principal: str, tool: str, digest: str, status: str, error: str | None = None) -> None:
        event = AuditEvent(
            event_id=str(uuid4()),
            timestamp=self._now().isoformat(),
            principal_id=principal,
            tool_name=tool,
            argument_digest=digest,
            status=status,
            error_code=error,
        )
        try:
            self.audit_sink.write(event)
        except Exception:
            raise AuditError("audit persistence failed; execution was blocked or outcome is uncertain") from None

    def _consume_approval(self, context: ExecutionContext, spec: ToolSpec, digest: str) -> None:
        now = self._now()
        matching = [
            grant for grant in context.approvals
            if isinstance(grant, ApprovalGrant)
            and isinstance(grant.grant_id, str) and 0 < len(grant.grant_id) <= 128
            and isinstance(grant.principal_id, str) and len(grant.principal_id) <= 256
            and isinstance(grant.tool_name, str) and _NAME_RE.fullmatch(grant.tool_name)
            and isinstance(grant.argument_digest, str) and _DIGEST_RE.fullmatch(grant.argument_digest)
            and isinstance(grant.expires_at, str) and len(grant.expires_at) <= 64
            and grant.principal_id == context.principal_id
            and grant.tool_name == spec.name
            and grant.argument_digest == digest
        ]
        for grant in matching:
            try:
                if self.approval_store.consume(grant, now):
                    return
            except Exception:
                raise AuditError("approval state persistence failed; execution was blocked") from None
        raise ApprovalRequiredError("a matching, unexpired, unused host approval is required")

    def execute(
        self,
        name: str,
        arguments: Any,
        context: ExecutionContext,
        *,
        cancellation_event: threading.Event | None = None,
    ) -> Any:
        if cancellation_event is not None and not callable(getattr(cancellation_event, "is_set", None)):
            raise ToolValidationError("cancellation_event must expose is_set()")
        if cancellation_event is not None and cancellation_event.is_set():
            raise ToolCancelledError(outcome_uncertain=False)
        if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
            raise ToolValidationError("tool name must be a lowercase identifier")
        if not isinstance(context, ExecutionContext):
            raise ToolValidationError("a trusted ExecutionContext is required")
        if (not isinstance(context.principal_id, str) or not context.principal_id.strip()
                or len(context.principal_id) > 256 or _contains_surrogate(context.principal_id)):
            raise ToolValidationError("host principal_id must be valid non-empty text of at most 256 characters")
        if (not isinstance(context.permissions, frozenset)
                or any(not isinstance(x, str) or not x or len(x) > 128 or _contains_surrogate(x)
                       for x in context.permissions)):
            raise ToolValidationError("host permissions must be a frozenset of bounded valid strings")
        if not isinstance(context.approvals, tuple) or len(context.approvals) > 32:
            raise ToolValidationError("host approvals must be a tuple of at most 32 grants")
        spec, handler = self.registry.resolve(name)
        if spec.permission not in context.permissions:
            raise PermissionDeniedError("host context lacks the required tool permission")
        encoded, raw = _canonical_json(arguments, max_bytes=self.max_argument_bytes, label="arguments")
        if not isinstance(arguments, dict):
            raise ToolValidationError("tool arguments must be a JSON object")
        _assert_json_object_keys(arguments)
        _validate_value(json.loads(encoded), spec.schema())
        digest = hashlib.sha256(raw).hexdigest()
        if spec.requires_approval:
            self._consume_approval(context, spec, digest)
        self._audit(context.principal_id, spec.name, digest, "started")
        if cancellation_event is not None and cancellation_event.is_set():
            self._audit(context.principal_id, spec.name, digest, "cancelled", "cancelled_before_handler")
            raise ToolCancelledError(outcome_uncertain=False) from None
        handler_failed = False
        handler_cancelled = False
        try:
            if spec.cooperative_cancellation:
                result = handler(
                    json.loads(encoded),
                    cancellation_event if cancellation_event is not None else threading.Event(),
                )
            else:
                result = handler(json.loads(encoded))
        except ToolCancelledError:
            handler_cancelled = True
        except Exception:
            # Leave the except block before raising so exception details are not
            # retained as an inspectable __context__ on the public error.
            handler_failed = True
        if handler_cancelled:
            self._audit(context.principal_id, spec.name, digest, "outcome_uncertain", "handler_cancelled_after_start")
            raise ToolCancelledError(outcome_uncertain=True) from None
        if handler_failed:
            self._audit(context.principal_id, spec.name, digest, "handler_failed", "handler_error")
            raise ToolExecutionError("tool handler failed; details suppressed")
        try:
            _assert_json_object_keys(result)
            result_json, _ = _canonical_json(
                result, max_bytes=self.max_result_bytes, label="tool result"
            )
            _assert_json_object_keys(json.loads(result_json))
        except ToolValidationError:
            self._audit(context.principal_id, spec.name, digest, "result_rejected", "invalid_or_oversized_result")
            raise
        self._audit(context.principal_id, spec.name, digest, "succeeded")
        return json.loads(result_json)
