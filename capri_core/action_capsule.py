"""Pure, host-neutral contract for proof-carrying action execution.

This module validates action metadata and lifecycle transitions only. It does not
issue approvals, execute tools, authenticate workers, persist events, or verify
external side effects. Those responsibilities remain with the trusted host.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable, Mapping
from uuid import uuid4


ZERO_HASH = "0" * 64
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_CAPABILITY = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")
_BUDGET_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_MAX_SCOPE_ITEMS = 128
_MAX_EVIDENCE_REFS = 128
_MAX_BUDGET_ITEMS = 32
_MAX_BUDGET_VALUE = 10**12
_MAX_EVENTS = 5


class ActionCapsuleError(ValueError):
    """Raised when an action capsule or lifecycle transition is invalid."""


class CapsuleIntegrityError(ActionCapsuleError):
    """Raised when an event chain does not match its saved capsule state."""


class CapsuleState(str, Enum):
    DRAFT = "draft"
    AUTHORIZED = "authorized"
    DISPATCHED = "dispatched"
    RECEIVED = "received"
    VERIFIED = "verified"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    INDETERMINATE = "indeterminate"


_ALLOWED_TRANSITIONS = {
    CapsuleState.DRAFT: frozenset({
        CapsuleState.AUTHORIZED, CapsuleState.REJECTED, CapsuleState.CANCELLED,
    }),
    CapsuleState.AUTHORIZED: frozenset({
        CapsuleState.DISPATCHED, CapsuleState.REJECTED,
        CapsuleState.EXPIRED, CapsuleState.CANCELLED,
    }),
    CapsuleState.DISPATCHED: frozenset({
        CapsuleState.RECEIVED, CapsuleState.INDETERMINATE,
    }),
    CapsuleState.RECEIVED: frozenset({
        CapsuleState.VERIFIED, CapsuleState.REJECTED, CapsuleState.INDETERMINATE,
    }),
    CapsuleState.VERIFIED: frozenset({
        CapsuleState.ACCEPTED, CapsuleState.REJECTED, CapsuleState.INDETERMINATE,
    }),
}


def _text(value: object, field: str, *, maximum: int = 256) -> str:
    if type(value) is not str or not value or len(value) > maximum or value != value.strip():
        raise ActionCapsuleError(f"{field} must be a non-empty bounded normalized string")
    if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise ActionCapsuleError(f"{field} must contain Unicode scalar values")
    return value


def _identifier(value: object, field: str) -> str:
    result = _text(value, field, maximum=128)
    if not _ID.fullmatch(result):
        raise ActionCapsuleError(f"{field} must use a bounded identifier syntax")
    return result


def _digest(value: object, field: str, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise ActionCapsuleError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _timestamp(value: object, field: str) -> datetime:
    if type(value) is not str or not value or len(value) > 64:
        raise ActionCapsuleError(f"{field} must be a timezone-aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ActionCapsuleError(f"{field} must be a timezone-aware ISO timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ActionCapsuleError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError):
        raise ActionCapsuleError("capsule event contains unsupported JSON data") from None


def _normalize_scope(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ActionCapsuleError("resource_scope must be a collection of identifiers")
    unique: set[str] = set()
    try:
        for count, value in enumerate(values, start=1):
            if count > _MAX_SCOPE_ITEMS:
                raise ActionCapsuleError("resource_scope exceeds the input item limit")
            unique.add(_identifier(value, "resource_scope item"))
    except TypeError:
        raise ActionCapsuleError("resource_scope must be iterable") from None
    scope = tuple(sorted(unique))
    if not scope:
        raise ActionCapsuleError("resource_scope must contain 1–128 unique items")
    return scope


def _normalize_budgets(values: Mapping[str, int]) -> tuple[tuple[str, int], ...]:
    if not isinstance(values, Mapping) or not values or len(values) > _MAX_BUDGET_ITEMS:
        raise ActionCapsuleError("budgets must be a non-empty mapping of at most 32 limits")
    result: list[tuple[str, int]] = []
    for count, (key, value) in enumerate(values.items(), start=1):
        if count > _MAX_BUDGET_ITEMS:
            raise ActionCapsuleError("budgets exceed the input item limit")
        if type(key) is not str or not _BUDGET_KEY.fullmatch(key):
            raise ActionCapsuleError("budget names must be lowercase identifiers")
        if type(value) is not int or not 0 <= value <= _MAX_BUDGET_VALUE:
            raise ActionCapsuleError("budget values must be bounded non-negative integers")
        result.append((key, value))
    return tuple(sorted(result))


def _capsule_payload(capsule: ActionCapsule) -> dict[str, object]:
    return {
        "capsule_id": capsule.capsule_id,
        "intent_digest": capsule.intent_digest,
        "principal_id": capsule.principal_id,
        "capability": capsule.capability,
        "resource_scope": list(capsule.resource_scope),
        "policy_version": capsule.policy_version,
        "budgets": [[key, value] for key, value in capsule.budgets],
        "deadline_at": capsule.deadline_at,
        "idempotency_key": capsule.idempotency_key,
        "input_digest": capsule.input_digest,
        "created_at": capsule.created_at,
    }


def _validate_capsule(capsule: object) -> ActionCapsule:
    if type(capsule) is not ActionCapsule:
        raise ActionCapsuleError("capsule must be an ActionCapsule")
    _identifier(capsule.capsule_id, "capsule_id")
    _digest(capsule.intent_digest, "intent_digest")
    _identifier(capsule.principal_id, "principal_id")
    if type(capsule.capability) is not str or not _CAPABILITY.fullmatch(capsule.capability):
        raise ActionCapsuleError("capability must be a lowercase capability identifier")
    if type(capsule.resource_scope) is not tuple or not capsule.resource_scope:
        raise ActionCapsuleError("resource_scope must be a non-empty tuple")
    if len(capsule.resource_scope) > _MAX_SCOPE_ITEMS:
        raise ActionCapsuleError("resource_scope exceeds its item limit")
    normalized_scope = tuple(sorted({_identifier(item, "resource_scope item") for item in capsule.resource_scope}))
    if normalized_scope != capsule.resource_scope:
        raise ActionCapsuleError("resource_scope must be sorted and unique")
    _identifier(capsule.policy_version, "policy_version")
    if type(capsule.budgets) is not tuple or not capsule.budgets or len(capsule.budgets) > _MAX_BUDGET_ITEMS:
        raise ActionCapsuleError("budgets must be a non-empty tuple")
    checked_budgets: list[tuple[str, int]] = []
    for item in capsule.budgets:
        if type(item) is not tuple or len(item) != 2:
            raise ActionCapsuleError("each budget must be a name/value pair")
        key, value = item
        if type(key) is not str or not _BUDGET_KEY.fullmatch(key):
            raise ActionCapsuleError("budget names must be lowercase identifiers")
        if type(value) is not int or not 0 <= value <= _MAX_BUDGET_VALUE:
            raise ActionCapsuleError("budget values must be bounded non-negative integers")
        checked_budgets.append((key, value))
    if tuple(sorted(checked_budgets)) != capsule.budgets or len({key for key, _ in checked_budgets}) != len(checked_budgets):
        raise ActionCapsuleError("budgets must be sorted and unique")
    _identifier(capsule.idempotency_key, "idempotency_key")
    _digest(capsule.input_digest, "input_digest")
    expected_capsule_digest = hashlib.sha256(_canonical(_capsule_payload(capsule))).hexdigest()
    if capsule.capsule_digest != expected_capsule_digest:
        raise CapsuleIntegrityError("capsule immutable metadata digest does not match")
    created = _timestamp(capsule.created_at, "created_at")
    updated = _timestamp(capsule.updated_at, "updated_at")
    deadline = _timestamp(capsule.deadline_at, "deadline_at")
    if updated < created or deadline <= created:
        raise ActionCapsuleError("capsule timestamps are not chronologically valid")
    if type(capsule.state) is not CapsuleState:
        raise ActionCapsuleError("state must be a CapsuleState")
    if type(capsule.event_sequence) is not int or not 0 <= capsule.event_sequence <= _MAX_EVENTS:
        raise ActionCapsuleError("event_sequence must be between 0 and the maximum lifecycle length")
    if type(capsule.last_event_hash) is not str or not _SHA256.fullmatch(capsule.last_event_hash):
        raise ActionCapsuleError("last_event_hash must be a SHA-256 digest")
    for field in ("approval_ref", "worker_binding", "verifier_id", "verifier_version"):
        value = getattr(capsule, field)
        if value is not None:
            _identifier(value, field)
    _digest(capsule.result_digest, "result_digest", optional=True)
    if type(capsule.evidence_refs) is not tuple or len(capsule.evidence_refs) > _MAX_EVIDENCE_REFS:
        raise ActionCapsuleError("evidence_refs must be a bounded tuple")
    for reference in capsule.evidence_refs:
        _identifier(reference, "evidence reference")
    if len(set(capsule.evidence_refs)) != len(capsule.evidence_refs):
        raise ActionCapsuleError("evidence_refs must be unique")

    if capsule.state in {
        CapsuleState.AUTHORIZED, CapsuleState.DISPATCHED, CapsuleState.RECEIVED,
        CapsuleState.VERIFIED, CapsuleState.ACCEPTED, CapsuleState.EXPIRED,
        CapsuleState.INDETERMINATE,
    } and capsule.approval_ref is None:
        raise ActionCapsuleError("authorized and later states require an approval reference")
    if capsule.state in {
        CapsuleState.DISPATCHED, CapsuleState.RECEIVED, CapsuleState.VERIFIED,
        CapsuleState.ACCEPTED, CapsuleState.INDETERMINATE,
    } and capsule.worker_binding is None:
        raise ActionCapsuleError("dispatched and later states require a worker binding")
    if capsule.state in {
        CapsuleState.RECEIVED, CapsuleState.VERIFIED, CapsuleState.ACCEPTED,
    } and capsule.result_digest is None:
        raise ActionCapsuleError("received and later accepted states require a result digest")
    if capsule.state in {CapsuleState.VERIFIED, CapsuleState.ACCEPTED}:
        if not capsule.evidence_refs or capsule.verifier_id is None or capsule.verifier_version is None:
            raise ActionCapsuleError("verified states require evidence and verifier identity")
    if capsule.state is CapsuleState.DRAFT:
        if capsule.event_sequence != 0 or capsule.last_event_hash != ZERO_HASH or updated != created:
            raise ActionCapsuleError("draft capsules must not have transition history")
        if any((
            capsule.approval_ref, capsule.worker_binding, capsule.result_digest,
            capsule.evidence_refs, capsule.verifier_id, capsule.verifier_version,
        )):
            raise ActionCapsuleError("draft capsules cannot contain execution or verification results")
    return capsule


@dataclass(frozen=True, slots=True)
class ActionCapsule:
    """Immutable action envelope; all payload content remains outside the capsule."""

    capsule_id: str
    intent_digest: str
    principal_id: str
    capability: str
    resource_scope: tuple[str, ...]
    policy_version: str
    budgets: tuple[tuple[str, int], ...]
    deadline_at: str
    idempotency_key: str
    input_digest: str
    created_at: str
    updated_at: str
    state: CapsuleState = CapsuleState.DRAFT
    approval_ref: str | None = None
    worker_binding: str | None = None
    result_digest: str | None = None
    evidence_refs: tuple[str, ...] = ()
    verifier_id: str | None = None
    verifier_version: str | None = None
    event_sequence: int = 0
    last_event_hash: str = ZERO_HASH
    capsule_digest: str = ""


@dataclass(frozen=True, slots=True)
class CapsuleEvent:
    """Append-only, data-only transition receipt; it does not prove execution truth."""

    event_id: str
    capsule_id: str
    capsule_digest: str
    sequence: int
    from_state: CapsuleState
    to_state: CapsuleState
    occurred_at: str
    actor: str
    approval_ref: str | None
    worker_binding: str | None
    result_digest: str | None
    evidence_refs: tuple[str, ...]
    verifier_id: str | None
    verifier_version: str | None
    reason_code: str | None
    previous_event_hash: str
    event_hash: str


def create_action_capsule(
    *,
    capsule_id: str,
    intent_digest: str,
    principal_id: str,
    capability: str,
    resource_scope: Iterable[str],
    policy_version: str,
    budgets: Mapping[str, int],
    deadline_at: str,
    idempotency_key: str,
    input_digest: str,
    created_at: str,
) -> ActionCapsule:
    """Create and validate a DRAFT capsule without granting authority or dispatching work."""
    created = _timestamp(created_at, "created_at")
    deadline = _timestamp(deadline_at, "deadline_at")
    if deadline <= created:
        raise ActionCapsuleError("deadline_at must be later than created_at")
    capsule = ActionCapsule(
        capsule_id=capsule_id,
        intent_digest=intent_digest,
        principal_id=principal_id,
        capability=capability,
        resource_scope=_normalize_scope(resource_scope),
        policy_version=policy_version,
        budgets=_normalize_budgets(budgets),
        deadline_at=deadline.isoformat(),
        idempotency_key=idempotency_key,
        input_digest=input_digest,
        created_at=created.isoformat(),
        updated_at=created.isoformat(),
    )
    capsule = replace(capsule, capsule_digest=hashlib.sha256(_canonical(_capsule_payload(capsule))).hexdigest())
    return _validate_capsule(capsule)


def _event_payload(event: CapsuleEvent) -> dict[str, object]:
    return {
        "event_id": event.event_id,
        "capsule_id": event.capsule_id,
        "capsule_digest": event.capsule_digest,
        "sequence": event.sequence,
        "from_state": event.from_state.value,
        "to_state": event.to_state.value,
        "occurred_at": event.occurred_at,
        "actor": event.actor,
        "approval_ref": event.approval_ref,
        "worker_binding": event.worker_binding,
        "result_digest": event.result_digest,
        "evidence_refs": list(event.evidence_refs),
        "verifier_id": event.verifier_id,
        "verifier_version": event.verifier_version,
        "reason_code": event.reason_code,
        "previous_event_hash": event.previous_event_hash,
    }


def _validate_event(event: object) -> CapsuleEvent:
    if type(event) is not CapsuleEvent:
        raise CapsuleIntegrityError("history must contain CapsuleEvent records")
    _identifier(event.event_id, "event_id")
    _identifier(event.capsule_id, "capsule_id")
    _digest(event.capsule_digest, "capsule_digest")
    if type(event.sequence) is not int or event.sequence < 1:
        raise CapsuleIntegrityError("event sequence must be a positive integer")
    if type(event.from_state) is not CapsuleState or type(event.to_state) is not CapsuleState:
        raise CapsuleIntegrityError("event states must be CapsuleState values")
    _timestamp(event.occurred_at, "occurred_at")
    _identifier(event.actor, "actor")
    for field in ("approval_ref", "worker_binding", "verifier_id", "verifier_version", "reason_code"):
        value = getattr(event, field)
        if value is not None:
            _identifier(value, field)
    _digest(event.result_digest, "result_digest", optional=True)
    if type(event.evidence_refs) is not tuple or len(event.evidence_refs) > _MAX_EVIDENCE_REFS:
        raise CapsuleIntegrityError("event evidence references must be a bounded tuple")
    for reference in event.evidence_refs:
        _identifier(reference, "evidence reference")
    if len(set(event.evidence_refs)) != len(event.evidence_refs):
        raise CapsuleIntegrityError("event evidence references must be unique")
    _digest(event.previous_event_hash, "previous_event_hash")
    _digest(event.event_hash, "event_hash")
    if event.to_state is CapsuleState.AUTHORIZED:
        if event.approval_ref is None:
            raise CapsuleIntegrityError("authorization event requires an approval reference")
    elif event.approval_ref is not None:
        raise CapsuleIntegrityError("approval reference is only valid on authorization events")
    if event.to_state is CapsuleState.DISPATCHED:
        if event.worker_binding is None:
            raise CapsuleIntegrityError("dispatch event requires a worker binding")
    elif event.worker_binding is not None:
        raise CapsuleIntegrityError("worker binding is only valid on dispatch events")
    if event.to_state is CapsuleState.RECEIVED:
        if event.result_digest is None:
            raise CapsuleIntegrityError("receipt event requires a result digest")
    elif event.result_digest is not None:
        raise CapsuleIntegrityError("result digest is only valid on receipt events")
    if event.to_state is CapsuleState.VERIFIED:
        if not event.evidence_refs or event.verifier_id is None or event.verifier_version is None:
            raise CapsuleIntegrityError("verification event requires evidence and verifier identity")
    elif event.evidence_refs or event.verifier_id is not None or event.verifier_version is not None:
        raise CapsuleIntegrityError("verification metadata is only valid on verification events")
    if event.to_state in {CapsuleState.REJECTED, CapsuleState.INDETERMINATE}:
        if event.reason_code is None:
            raise CapsuleIntegrityError("rejection and indeterminate events require a reason code")
    elif event.reason_code is not None:
        raise CapsuleIntegrityError("reason_code is only valid for rejected or indeterminate events")
    return event


def transition_action_capsule(
    capsule: ActionCapsule,
    target_state: CapsuleState,
    *,
    history: Iterable[CapsuleEvent] = (),
    occurred_at: str,
    actor: str,
    approval_ref: str | None = None,
    worker_binding: str | None = None,
    result_digest: str | None = None,
    evidence_refs: Iterable[str] = (),
    verifier_id: str | None = None,
    verifier_version: str | None = None,
    reason_code: str | None = None,
) -> tuple[ActionCapsule, CapsuleEvent]:
    """Apply one legal transition and return the new capsule plus its hash receipt.

    The caller must persist the event append-only and atomically with the new
    capsule projection. This pure helper does not perform that persistence.
    """
    current = _validate_capsule(capsule)
    verify_action_capsule_history(current, history)
    if type(target_state) is not CapsuleState:
        raise ActionCapsuleError("target_state must be a CapsuleState")
    if target_state not in _ALLOWED_TRANSITIONS.get(current.state, frozenset()):
        raise ActionCapsuleError(f"transition {current.state.value} -> {target_state.value} is not permitted")
    when = _timestamp(occurred_at, "occurred_at")
    previous_time = _timestamp(current.updated_at, "updated_at")
    deadline = _timestamp(current.deadline_at, "deadline_at")
    if when < previous_time:
        raise ActionCapsuleError("transition timestamps must be monotonic")
    if target_state is CapsuleState.EXPIRED:
        if current.state is not CapsuleState.AUTHORIZED or when < deadline:
            raise ActionCapsuleError("only an authorized capsule may expire at or after its deadline")
    elif when >= deadline and not (
        target_state is CapsuleState.INDETERMINATE
        or (current.state is CapsuleState.DRAFT and target_state is CapsuleState.CANCELLED)
    ):
        raise ActionCapsuleError("an overdue action must expire, close an undispatched draft, or be reconciled as indeterminate")

    _identifier(actor, "actor")
    next_approval = current.approval_ref
    next_worker = current.worker_binding
    next_result = current.result_digest
    next_evidence = current.evidence_refs
    next_verifier = current.verifier_id
    next_verifier_version = current.verifier_version

    if target_state is CapsuleState.AUTHORIZED:
        next_approval = _identifier(approval_ref, "approval_ref")
    elif approval_ref is not None:
        raise ActionCapsuleError("approval_ref may only be set during authorization")

    if target_state is CapsuleState.DISPATCHED:
        next_worker = _identifier(worker_binding, "worker_binding")
    elif worker_binding is not None:
        raise ActionCapsuleError("worker_binding may only be set during dispatch")

    if target_state is CapsuleState.RECEIVED:
        next_result = _digest(result_digest, "result_digest")
    elif result_digest is not None:
        raise ActionCapsuleError("result_digest may only be set when a result is received")

    if target_state is CapsuleState.VERIFIED:
        if isinstance(evidence_refs, (str, bytes)):
            raise ActionCapsuleError("evidence_refs must be a collection")
        collected: list[str] = []
        seen_evidence: set[str] = set()
        try:
            for count, item in enumerate(evidence_refs, start=1):
                if count > _MAX_EVIDENCE_REFS:
                    raise ActionCapsuleError("evidence_refs exceed the input item limit")
                reference = _identifier(item, "evidence reference")
                if reference not in seen_evidence:
                    seen_evidence.add(reference)
                    collected.append(reference)
        except TypeError:
            raise ActionCapsuleError("evidence_refs must be iterable") from None
        next_evidence = tuple(collected)
        if not next_evidence:
            raise ActionCapsuleError("verification requires 1–128 unique evidence references")
        next_verifier = _identifier(verifier_id, "verifier_id")
        next_verifier_version = _identifier(verifier_version, "verifier_version")
    else:
        if isinstance(evidence_refs, (str, bytes)):
            raise ActionCapsuleError("evidence_refs must be a collection")
        try:
            iterator = iter(evidence_refs)
            sentinel = object()
            has_extra_evidence = next(iterator, sentinel) is not sentinel
        except TypeError:
            raise ActionCapsuleError("evidence_refs must be iterable") from None
        if any(value is not None for value in (verifier_id, verifier_version)) or has_extra_evidence:
            raise ActionCapsuleError("verifier identity and evidence may only be set during verification")

    if target_state in {CapsuleState.REJECTED, CapsuleState.INDETERMINATE}:
        reason_code = _identifier(reason_code, "reason_code")
    elif reason_code is not None:
        raise ActionCapsuleError("reason_code is only valid for rejected or indeterminate outcomes")

    sequence = current.event_sequence + 1
    event = CapsuleEvent(
        event_id=uuid4().hex,
        capsule_id=current.capsule_id,
        capsule_digest=current.capsule_digest,
        sequence=sequence,
        from_state=current.state,
        to_state=target_state,
        occurred_at=when.isoformat(),
        actor=actor,
        approval_ref=next_approval if target_state is CapsuleState.AUTHORIZED else None,
        worker_binding=next_worker if target_state is CapsuleState.DISPATCHED else None,
        result_digest=next_result if target_state is CapsuleState.RECEIVED else None,
        evidence_refs=next_evidence if target_state is CapsuleState.VERIFIED else (),
        verifier_id=next_verifier if target_state is CapsuleState.VERIFIED else None,
        verifier_version=next_verifier_version if target_state is CapsuleState.VERIFIED else None,
        reason_code=reason_code,
        previous_event_hash=current.last_event_hash,
        event_hash=ZERO_HASH,
    )
    digest = hashlib.sha256(_canonical(_event_payload(event))).hexdigest()
    event = replace(event, event_hash=digest)
    updated = replace(
        current,
        state=target_state,
        updated_at=when.isoformat(),
        approval_ref=next_approval,
        worker_binding=next_worker,
        result_digest=next_result,
        evidence_refs=next_evidence,
        verifier_id=next_verifier,
        verifier_version=next_verifier_version,
        event_sequence=sequence,
        last_event_hash=digest,
    )
    return _validate_capsule(updated), event


def verify_action_capsule_history(
    capsule: ActionCapsule,
    events: Iterable[CapsuleEvent],
) -> None:
    """Raise CapsuleIntegrityError unless events reconstruct the exact capsule.

    SHA-256 chaining detects accidental/partial tampering. It is not a signature
    and does not authenticate the history against a privileged database writer.
    """
    current = _validate_capsule(capsule)
    if isinstance(events, (str, bytes)):
        raise CapsuleIntegrityError("events must be an iterable of CapsuleEvent records")
    try:
        collected: list[CapsuleEvent] = []
        for event in events:
            if len(collected) >= _MAX_EVENTS:
                raise CapsuleIntegrityError("event history exceeds the maximum lifecycle length")
            collected.append(event)
        history = tuple(collected)
    except TypeError:
        raise CapsuleIntegrityError("events must be iterable") from None
    if len(history) != current.event_sequence:
        raise CapsuleIntegrityError("event count does not match capsule sequence")

    state = CapsuleState.DRAFT
    previous_hash = ZERO_HASH
    previous_time = _timestamp(current.created_at, "created_at")
    approval_ref = None
    worker_binding = None
    result_digest = None
    evidence_refs: tuple[str, ...] = ()
    verifier_id = None
    verifier_version = None
    deadline = _timestamp(current.deadline_at, "deadline_at")
    seen_ids: set[str] = set()
    for index, raw in enumerate(history, start=1):
        event = _validate_event(raw)
        if event.capsule_id != current.capsule_id or event.capsule_digest != current.capsule_digest:
            raise CapsuleIntegrityError("event belongs to a different capsule or immutable input")
        if event.event_id in seen_ids:
            raise CapsuleIntegrityError("duplicate event identifier")
        seen_ids.add(event.event_id)
        if event.sequence != index or event.from_state is not state:
            raise CapsuleIntegrityError("event sequence or state transition is discontinuous")
        if event.to_state not in _ALLOWED_TRANSITIONS.get(state, frozenset()):
            raise CapsuleIntegrityError("history contains a forbidden state transition")
        event_time = _timestamp(event.occurred_at, "occurred_at")
        if event_time < previous_time:
            raise CapsuleIntegrityError("event timestamps are not monotonic")
        if event.to_state is CapsuleState.EXPIRED:
            if state is not CapsuleState.AUTHORIZED or event_time < deadline:
                raise CapsuleIntegrityError("expiry event is inconsistent with the capsule deadline")
        elif event_time >= deadline and not (
            event.to_state is CapsuleState.INDETERMINATE
            or (state is CapsuleState.DRAFT and event.to_state is CapsuleState.CANCELLED)
        ):
            raise CapsuleIntegrityError("overdue action must expire, close an undispatched draft, or be indeterminate")
        if event.previous_event_hash != previous_hash:
            raise CapsuleIntegrityError("event previous hash does not match")
        expected_hash = hashlib.sha256(_canonical(_event_payload(event))).hexdigest()
        if event.event_hash != expected_hash:
            raise CapsuleIntegrityError("event hash does not match its content")
        previous_hash = event.event_hash
        previous_time = event_time
        state = event.to_state
        if event.to_state is CapsuleState.AUTHORIZED:
            approval_ref = event.approval_ref
        elif event.to_state is CapsuleState.DISPATCHED:
            worker_binding = event.worker_binding
        elif event.to_state is CapsuleState.RECEIVED:
            result_digest = event.result_digest
        elif event.to_state is CapsuleState.VERIFIED:
            evidence_refs = event.evidence_refs
            verifier_id = event.verifier_id
            verifier_version = event.verifier_version

    if state is not current.state or previous_hash != current.last_event_hash:
        raise CapsuleIntegrityError("event history does not match the capsule projection")
    if previous_time != _timestamp(current.updated_at, "updated_at"):
        raise CapsuleIntegrityError("capsule updated_at does not match the final event")
    if (
        approval_ref != current.approval_ref
        or worker_binding != current.worker_binding
        or result_digest != current.result_digest
        or evidence_refs != current.evidence_refs
        or verifier_id != current.verifier_id
        or verifier_version != current.verifier_version
    ):
        raise CapsuleIntegrityError("capsule projection does not match its event history")


__all__ = [
    "ZERO_HASH", "ActionCapsuleError", "CapsuleIntegrityError", "CapsuleState",
    "ActionCapsule", "CapsuleEvent", "create_action_capsule",
    "transition_action_capsule", "verify_action_capsule_history",
]
