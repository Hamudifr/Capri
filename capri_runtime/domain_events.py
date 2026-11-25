"""Read-only CloudEvents-style projection over Capri's domain-local histories.

This module owns no database. Goal, task, SQLite-memory, and Notion-memory stores
remain their own sources of truth; projection order is for display only and does
not imply a total order or cross-store transaction.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import re
from typing import Iterable

from capri_core.validation import contains_surrogate


class DomainEventValidationError(ValueError):
    """A projected domain event violates the bounded provenance contract."""


_ALLOWED_DATA_FIELDS = frozenset({
    "state", "status", "version", "step_index", "attempt", "error_code",
    "actor_id", "supersedes_id", "reason_code", "evidence_reference",
    "evidence_digest", "evidence_type", "derived_from", "record_type",
})
_MAX_EVENT_DATA_BYTES = 2048


def _plain_text(value: object, field: str, maximum: int) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise DomainEventValidationError(f"{field} must be a non-empty plain string")
    if contains_surrogate(value) or len(value.encode("utf-8")) > maximum:
        raise DomainEventValidationError(f"{field} exceeds its bound or contains invalid Unicode")
    return value


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """Immutable event envelope using CloudEvents 1.0 identity conventions.

    Data is deliberately restricted to bounded metadata and opaque references.
    Raw memory content, prompts, tool arguments, credentials, and free-form notes
    are not valid event data.
    """

    id: str
    source: str
    type: str
    subject: str
    time: str
    data: tuple[tuple[str, str | int | None], ...] = ()
    specversion: str = "1.0"

    def __post_init__(self) -> None:
        _plain_text(self.id, "event id", 128)
        _plain_text(self.source, "event source", 256)
        _plain_text(self.type, "event type", 128)
        _plain_text(self.subject, "event subject", 128)
        if type(self.specversion) is not str or self.specversion != "1.0":
            raise DomainEventValidationError("only CloudEvents specversion 1.0 is supported")
        if re.fullmatch(r"urn:capri:[a-z0-9-]+:[A-Za-z0-9._:-]+", self.source) is None:
            raise DomainEventValidationError("event source must use a bounded Capri URN")
        if re.fullmatch(r"com\\.capri\\.[a-z0-9]+(?:[.-][a-z0-9]+)*", self.type) is None:
            raise DomainEventValidationError("event type must use a bounded com.capri name")
        if type(self.time) is not str:
            raise DomainEventValidationError("event time must be a timezone-aware ISO timestamp")
        try:
            parsed = datetime.fromisoformat(self.time.replace("Z", "+00:00"))
        except ValueError:
            raise DomainEventValidationError("event time must be a timezone-aware ISO timestamp") from None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise DomainEventValidationError("event time must include a timezone")
        if type(self.data) is not tuple or len(self.data) > 12:
            raise DomainEventValidationError("event data must be a tuple of at most 12 fields")
        seen: set[str] = set()
        total = 0
        for item in self.data:
            if type(item) is not tuple or len(item) != 2:
                raise DomainEventValidationError("event data entries must be key/value pairs")
            key, value = item
            if type(key) is not str or key not in _ALLOWED_DATA_FIELDS or key in seen:
                raise DomainEventValidationError("event data contains an unsupported or duplicate field")
            seen.add(key)
            if value is not None and type(value) not in (str, int):
                raise DomainEventValidationError("event data values must be bounded strings, integers, or None")
            if type(value) is str:
                _plain_text(value, f"event data {key}", 512)
                total += len(value.encode("utf-8"))
            elif type(value) is int:
                if not -(2**63) <= value < 2**63:
                    raise DomainEventValidationError("event integer is outside the supported range")
                total += 8
            total += len(key)
        if total > _MAX_EVENT_DATA_BYTES:
            raise DomainEventValidationError("event data exceeds the total byte budget")

    def as_dict(self) -> dict[str, object]:
        return {
            "specversion": self.specversion,
            "id": self.id,
            "source": self.source,
            "type": self.type,
            "subject": self.subject,
            "time": self.time,
            "data": dict(self.data),
        }


def goal_event(
    *, event_id: int | str, goal_id: str, timestamp: str, state: str,
    version: int, event_type: str, principal_id: str,
) -> DomainEvent:
    return DomainEvent(
        id=str(event_id), source=f"urn:capri:goal:{goal_id}",
        type=f"com.capri.goal.{event_type}", subject=goal_id, time=timestamp,
        data=(("state", state), ("version", version), ("actor_id", principal_id)),
    )


def task_event(
    *, event_id: int | str, task_id: str, timestamp: str, state: str,
    step_index: int, attempt: int, error_code: str | None, principal_id: str,
) -> DomainEvent:
    return DomainEvent(
        id=str(event_id), source=f"urn:capri:task:{task_id}",
        type="com.capri.task.state_changed", subject=task_id, time=timestamp,
        data=(
            ("state", state), ("step_index", step_index), ("attempt", attempt),
            ("error_code", error_code), ("actor_id", principal_id),
        ),
    )


def memory_event(
    *, event_id: str, memory_id: str, event_type: str, timestamp: str,
    supersedes_id: str | None = None, status: str | None = None,
    derived_from: str | None = None, source_namespace: str = "memory",
) -> DomainEvent:
    data: list[tuple[str, str | int | None]] = []
    if status is not None:
        data.append(("status", status))
    if supersedes_id is not None:
        data.append(("supersedes_id", supersedes_id))
    if derived_from is not None:
        if type(derived_from) is not str:
            raise DomainEventValidationError("derived_from must be a plain string")
        if contains_surrogate(derived_from):
            raise DomainEventValidationError("derived_from contains invalid Unicode")
        if len(derived_from.encode("utf-8")) <= 512:
            data.append(("derived_from", derived_from))
        else:
            data.append(("evidence_digest", hashlib.sha256(
                derived_from.encode("utf-8")
            ).hexdigest()))
    if source_namespace not in {"memory", "notion-memory"}:
        raise DomainEventValidationError("unsupported memory event source namespace")
    return DomainEvent(
        id=event_id, source=f"urn:capri:{source_namespace}:{memory_id}",
        type=f"com.capri.memory.{event_type}", subject=memory_id,
        time=timestamp, data=tuple(data),
    )


def project_domain_events(*streams: Iterable[DomainEvent]) -> tuple[DomainEvent, ...]:
    """Merge read-only domain streams for display, never as a global write log.

    Sorting is deterministic for presentation. Events from separate stores have
    no shared transaction or guaranteed global causal order.
    """
    projected: dict[tuple[str, str], DomainEvent] = {}
    for stream in streams:
        for event in stream:
            if type(event) is not DomainEvent:
                raise DomainEventValidationError("projection accepts only exact DomainEvent values")
            identity = (event.source, event.id)
            if identity in projected:
                raise DomainEventValidationError("duplicate CloudEvents source/id identity")
            projected[identity] = event
    return tuple(sorted(
        projected.values(), key=lambda item: (item.time, item.source, item.id),
    ))
