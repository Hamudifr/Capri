"""Permissioned, provider-neutral tool execution boundary.

Handlers are injected by trusted host code. This module never imports tools dynamically
or performs shell, filesystem, or network operations on its own.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import islice
from typing import Any, Callable, Mapping, Protocol
from types import MappingProxyType
from uuid import uuid4

from capri_core.validation import contains_surrogate as _contains_surrogate

from .budgets import BudgetExceededError, SQLiteBudgetStore


class ToolBoundaryError(Exception):
    """Base class for expected tool-boundary failures."""


class ToolValidationError(ToolBoundaryError):
    """Tool name, schema, arguments, or result is invalid."""


class ToolResultValidationError(ToolValidationError):
    """A handler ran, but its result could not be safely accepted."""


class ToolNotFoundError(ToolBoundaryError):
    """The requested tool is not registered."""


class PermissionDeniedError(ToolBoundaryError):
    """The trusted host context does not grant the required permission."""


class AuditError(ToolBoundaryError):
    """Audit persistence failed; execution is blocked or its outcome is uncertain."""


class ToolExecutionError(ToolBoundaryError):
    """An injected handler failed; handler details are intentionally suppressed."""


class ToolBudgetExceededError(ToolBoundaryError):
    """A principal execution budget denied a tool call before handler dispatch."""


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
_OPERATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


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
    cooperative_cancellation: bool = False
    resource_authorizer: Callable[[dict[str, Any], ExecutionContext], bool] | None = None
    _schema_json: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not _NAME_RE.fullmatch(self.name):
            raise ToolValidationError("tool name must be a lowercase identifier")
        if not isinstance(self.permission, str) or not self.permission.strip() or len(self.permission) > 128:
            raise ToolValidationError("tool permission must be a non-empty string of at most 128 characters")
        if not isinstance(self.cooperative_cancellation, bool):
            raise ToolValidationError("cooperative_cancellation must be boolean")
        if self.resource_authorizer is not None and not callable(self.resource_authorizer):
            raise ToolValidationError("resource_authorizer must be callable when provided")
        schema = dict(self.argument_schema) if isinstance(self.argument_schema, Mapping) else None
        _validate_schema_definition(schema, root=True)
        encoded, _ = _canonical_json(schema, max_bytes=32_768, label="tool schema")
        object.__setattr__(self, "_schema_json", encoded)

    def schema(self) -> dict[str, Any]:
        """Return a fresh copy so callers cannot mutate the registered contract."""
        return json.loads(self._schema_json)


@dataclass(frozen=True, slots=True)
class ApprovalMacProvider(Protocol):
    """Trusted host adapter for non-exportable HMAC keys.

    Implementations may call a KMS/HSM/secret service. They must operate on the
    exact key ID supplied and must never silently fall back to another key.
    """

    @property
    def active_key_id(self) -> str:
        """Return the immutable version identifier used for new grants."""

    def sign(self, key_id: str, payload: bytes) -> bytes:
        """Return the raw HMAC-SHA256 tag for exactly this key ID."""

    def verify(self, key_id: str, payload: bytes, signature: bytes) -> bool:
        """Verify with exactly this key ID; return an actual bool."""


class HmacApprovalKeyRing:
    """Immutable host-configured HMAC key set with one active signing key.

    Keep keys in a secret manager and construct this object at trusted host startup.
    Retain old verification keys only for the maximum lifetime of grants they signed.
    """

    __slots__ = ("_keys", "_active_key_id")

    _KEY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

    def __init__(self, keys: Mapping[str, bytes], *, active_key_id: str) -> None:
        if not isinstance(keys, Mapping) or not 1 <= len(keys) <= 32:
            raise ToolValidationError("approval key ring must contain 1 to 32 keys")
        if (not isinstance(active_key_id, str)
                or not self._KEY_ID_RE.fullmatch(active_key_id)
                or active_key_id not in keys):
            raise ToolValidationError("active approval key ID must identify a configured key")
        copied: dict[str, bytes] = {}
        for key_id, key in keys.items():
            if not isinstance(key_id, str) or not self._KEY_ID_RE.fullmatch(key_id):
                raise ToolValidationError("approval key ID is invalid")
            if not isinstance(key, bytes) or len(key) < 32:
                raise ToolValidationError("each approval key must contain at least 32 bytes")
            copied[key_id] = bytes(key)
        object.__setattr__(self, "_keys", MappingProxyType(copied))
        object.__setattr__(self, "_active_key_id", active_key_id)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("approval key rings are immutable")

    @property
    def active_key_id(self) -> str:
        return self._active_key_id

    def _key_for(self, key_id: str) -> bytes | None:
        """Return only the specifically requested key; never try other keys."""
        return self._keys.get(key_id)

    def sign(self, key_id: str, payload: bytes) -> bytes:
        key = self._key_for(key_id)
        if key is None or not isinstance(payload, bytes):
            raise ToolValidationError("approval signing key or payload is invalid")
        return hmac.new(key, payload, hashlib.sha256).digest()

    def verify(self, key_id: str, payload: bytes, signature: bytes) -> bool:
        key = self._key_for(key_id)
        if key is None or not isinstance(payload, bytes) or not isinstance(signature, bytes):
            return False
        expected = hmac.new(key, payload, hashlib.sha256).digest()
        return hmac.compare_digest(expected, signature)


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """Trusted host identity; never construct this from model output."""

    principal_id: str
    permissions: frozenset[str]
    operation_id: str | None = None


class HostAuthorityError(ToolBoundaryError):
    """The host could not establish a valid authenticated execution context."""


class HostAuthorityResolver:
    """Build authority from trusted authentication and policy callbacks."""

    def __init__(
        self,
        authenticate: Callable[[Any], str | None],
        permissions_for: Callable[[str], Any],
    ) -> None:
        if not callable(authenticate) or not callable(permissions_for):
            raise HostAuthorityError("trusted authentication and permission callbacks are required")
        self._authenticate = authenticate
        self._permissions_for = permissions_for

    def for_operation(
        self, context: ExecutionContext, operation_id: str
    ) -> ExecutionContext:
        """Bind one trusted operation without re-authenticating."""
        if not isinstance(context, ExecutionContext):
            raise HostAuthorityError("a trusted execution context is required")
        if (not isinstance(context.principal_id, str) or not context.principal_id.strip()
                or len(context.principal_id) > 256 or _contains_surrogate(context.principal_id)
                or not isinstance(context.permissions, frozenset)
                or len(context.permissions) > 128
                or any(not isinstance(item, str) or not item or len(item) > 128
                       or _contains_surrogate(item) for item in context.permissions)):
            raise HostAuthorityError("trusted execution context is invalid")
        if not isinstance(operation_id, str) or not _OPERATION_RE.fullmatch(operation_id):
            raise HostAuthorityError("host operation identity is invalid")
        if context.operation_id is not None and context.operation_id != operation_id:
            raise HostAuthorityError("execution context belongs to a different operation")

        return ExecutionContext(context.principal_id, context.permissions, operation_id)

    def resolve(
        self, credential: Any, *, operation_id: str | None = None
    ) -> ExecutionContext:
        """Authenticate opaque host input and resolve least-privilege permissions.

        Credentials and callback exception details are deliberately not retained
        in errors or audit metadata. With an operation ID, the context is bound
        to that trusted operation identity.
        """
        if operation_id is not None and (
            not isinstance(operation_id, str) or not _OPERATION_RE.fullmatch(operation_id)
        ):
            raise HostAuthorityError("host operation identity is invalid")
        try:
            principal_id = self._authenticate(credential)
        except Exception:
            raise HostAuthorityError("host authentication failed") from None
        if (not isinstance(principal_id, str) or not principal_id.strip()
                or len(principal_id) > 256 or _contains_surrogate(principal_id)):
            raise HostAuthorityError("host authentication failed")

        try:
            raw_permissions = self._permissions_for(principal_id)
        except Exception:
            raise HostAuthorityError("host permission resolution failed") from None
        if isinstance(raw_permissions, (str, bytes, bytearray)):
            raise HostAuthorityError("host permission resolution returned an invalid grant set")
        try:
            permissions = tuple(islice(iter(raw_permissions), 129))
        except Exception:
            raise HostAuthorityError("host permission resolution returned an invalid grant set") from None
        if (len(permissions) > 128
                or any(not isinstance(item, str) or not item or len(item) > 128
                       or _contains_surrogate(item) for item in permissions)
                or len(set(permissions)) != len(permissions)):
            raise HostAuthorityError("host permission resolution returned an invalid grant set")

        context = ExecutionContext(principal_id, frozenset(permissions))
        return self.for_operation(context, operation_id) if operation_id is not None else context


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_id: str
    timestamp: str
    principal_id: str
    tool_name: str
    argument_digest: str
    status: str
    error_code: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    task_id: str | None = None
    metadata_json: str | None = None


class AuditSink:
    """Base contract for host-provided durable audit storage and restart reconciliation."""

    def write(self, event: AuditEvent) -> None:
        raise NotImplementedError

    def begin_worker_lifecycle_operation(self) -> None:
        raise NotImplementedError

    def finish_worker_lifecycle_operation(self) -> None:
        raise NotImplementedError

    def worker_lifecycle_reconciliation_required(self) -> bool:
        raise NotImplementedError

    def acknowledge_worker_lifecycle_reconciliation(self, note: str) -> bool:
        raise NotImplementedError


class InMemoryAuditSink(AuditSink):
    """Thread-safe test/development sink. Production hosts should inject durable storage."""

    def __init__(self, max_events: int = 10_000) -> None:
        if isinstance(max_events, bool) or not isinstance(max_events, int) or max_events < 1:
            raise ToolValidationError("max_events must be a positive integer")
        self._max_events = max_events
        self._events: list[AuditEvent] = []
        self._pending_worker_operations = 0
        self._lock = threading.Lock()

    def write(self, event: AuditEvent) -> None:
        with self._lock:
            if len(self._events) >= self._max_events:
                raise OSError("audit capacity reached")
            self._events.append(event)

    def begin_worker_lifecycle_operation(self) -> None:
        with self._lock:
            self._pending_worker_operations += 1

    def finish_worker_lifecycle_operation(self) -> None:
        with self._lock:
            if self._pending_worker_operations < 1:
                raise ToolValidationError("no worker lifecycle operation is pending")
            self._pending_worker_operations -= 1

    def _outstanding_worker_reservations_locked(self) -> int:
        def decode(event: AuditEvent) -> dict[str, Any] | None:
            if not isinstance(event.metadata_json, str):
                return None
            try:
                metadata = json.loads(event.metadata_json)
                canonical = json.dumps(
                    metadata, sort_keys=True, separators=(",", ":"),
                    ensure_ascii=False, allow_nan=False,
                )
            except (TypeError, ValueError, json.JSONDecodeError):
                return None
            if (
                not isinstance(metadata, dict)
                or canonical != event.metadata_json
                or hashlib.sha256(event.metadata_json.encode("utf-8")).hexdigest()
                    != event.argument_digest
            ):
                return None
            return metadata

        last_ack = -1
        for index, event in enumerate(self._events):
            if event.tool_name == "worker.reconciliation.acknowledged":
                if decode(event) is None:
                    return 1
                last_ack = index
        states: dict[str, str] = {}
        closed_events = {
            "worker.reservation.released",
            "worker.reservation.denied",
            "worker.reservation.commit_missing",
            "worker.reservation.commit_rejected",
            "worker.reservation.release_missing",
            "worker.reservation.collision_released",
            "worker.reservation.expired",
        "worker.reservation.revoked",
        }
        for event in self._events[last_ack + 1:]:
            if not event.tool_name.startswith("worker.reservation."):
                continue
            metadata = decode(event)
            if metadata is None:
                return 1
            token_hash = metadata.get("reservation_token_sha256")
            if not isinstance(token_hash, str) or len(token_hash) != 64:
                return 1
            if event.tool_name == "worker.reservation.created":
                states[token_hash] = "pending"
            elif event.tool_name == "worker.reservation.committed":
                states[token_hash] = "committed"
            elif event.tool_name in closed_events:
                states[token_hash] = "closed"
        return sum(state in {"pending", "committed"} for state in states.values())

    def worker_lifecycle_reconciliation_required(self) -> bool:
        with self._lock:
            return (
                self._pending_worker_operations > 0
                or self._outstanding_worker_reservations_locked() > 0
            )

    def acknowledge_worker_lifecycle_reconciliation(self, note: str) -> bool:
        if (
            not isinstance(note, str) or not note or len(note) > 1024
            or _contains_surrogate(note)
        ):
            raise ToolValidationError("worker lifecycle reconciliation note is invalid")
        with self._lock:
            pending = self._pending_worker_operations
            outstanding = self._outstanding_worker_reservations_locked()
            if pending == 0 and outstanding == 0:
                return False
            metadata_json = json.dumps(
                {
                    "pending_operations": pending,
                    "outstanding_reservations": outstanding,
                    "reconciliation_note": note,
                },
                sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
            )
            event = AuditEvent(
                uuid4().hex,
                datetime.now(timezone.utc).isoformat(),
                "host",
                "worker.reconciliation.acknowledged",
                hashlib.sha256(metadata_json.encode("utf-8")).hexdigest(),
                "success",
                None,
                "worker_registry",
                "registry",
                None,
                metadata_json,
            )
            if len(self._events) >= self._max_events:
                raise OSError("audit capacity reached")
            self._events.append(event)
            self._pending_worker_operations = 0
            return True

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
    """Runs allowlisted handlers after trusted permission checks."""

    def __init__(
        self,
        registry: ToolRegistry,
        audit_sink: AuditSink,
        *,
        max_argument_bytes: int = 16_384,
        max_result_bytes: int = 65_536,
        clock: Callable[[], datetime] | None = None,
        budget_store: SQLiteBudgetStore | None = None,
    ) -> None:
        if not isinstance(registry, ToolRegistry) or not callable(getattr(audit_sink, "write", None)):
            raise ToolValidationError("registry and audit sink are required")
        if budget_store is not None and not isinstance(budget_store, SQLiteBudgetStore):
            raise ToolValidationError("budget_store must be a SQLiteBudgetStore")
        for name, value in (("max_argument_bytes", max_argument_bytes), ("max_result_bytes", max_result_bytes)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ToolValidationError(f"{name} must be a positive integer")
        self.registry = registry
        self.audit_sink = audit_sink
        self.max_argument_bytes = max_argument_bytes
        self.max_result_bytes = max_result_bytes
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.budget_store = budget_store

    def set_budget_store(self, budget_store: SQLiteBudgetStore) -> None:
        if not isinstance(budget_store, SQLiteBudgetStore):
            raise ToolValidationError("budget_store must be a SQLiteBudgetStore")
        if self.budget_store is not None and self.budget_store is not budget_store:
            raise ToolValidationError("a different budget store is already configured")
        self.budget_store = budget_store

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
        if context.operation_id is not None and (
            not isinstance(context.operation_id, str) or not _OPERATION_RE.fullmatch(context.operation_id)
        ):
            raise ToolValidationError("host operation_id must be a bounded trusted identifier")
        spec, handler = self.registry.resolve(name)
        if spec.permission not in context.permissions:
            raise PermissionDeniedError("host context lacks the required tool permission")
        encoded, raw = _canonical_json(arguments, max_bytes=self.max_argument_bytes, label="arguments")
        if not isinstance(arguments, dict):
            raise ToolValidationError("tool arguments must be a JSON object")
        _assert_json_object_keys(arguments)
        _validate_value(json.loads(encoded), spec.schema())
        digest = hashlib.sha256(raw).hexdigest()
        if spec.resource_authorizer is not None:
            authorization_failed = False
            try:
                authorized = spec.resource_authorizer(json.loads(encoded), context)
            except Exception:
                authorized = False
                authorization_failed = True
            if authorized is not True:
                self._audit(
                    context.principal_id,
                    spec.name,
                    digest,
                    "permission_denied",
                    "resource_authorization_failed" if authorization_failed else "resource_authorization_denied",
                )
                raise PermissionDeniedError("host context is not authorized for this resource") from None
        if self.budget_store is not None:
            try:
                self.budget_store.reserve_for_principal(
                    context.principal_id, {"tool_calls": 1}, now=self._now(),
                )
            except BudgetExceededError:
                self._audit(context.principal_id, spec.name, digest, "budget_denied", "execution_budget_exhausted")
                raise ToolBudgetExceededError("principal tool-call budget exhausted") from None
            except Exception:
                self._audit(context.principal_id, spec.name, digest, "budget_denied", "budget_store_unavailable")
                raise ToolExecutionError("budget reservation failed; tool execution was blocked") from None
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
            raise ToolResultValidationError("tool handler result was rejected") from None
        self._audit(context.principal_id, spec.name, digest, "succeeded")
        return json.loads(result_json)
