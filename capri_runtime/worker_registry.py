"""Host-owned, in-memory catalogue for bounded Nexus worker discovery.

This module is metadata and liveness bookkeeping only. It does not authenticate
transports, authorize principals, dispatch requests, launch processes, or sandbox
workers. Callers must pass worker identities established by a trusted host
supervisor/transport and must re-check policy immediately before dispatch.
"""
from __future__ import annotations

import re
import secrets
import threading
import time
from dataclasses import dataclass, replace
from typing import Callable

_WORKER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CAPABILITY = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")
_MAX_WORKERS = 1024
_MAX_CAPABILITIES = 64
_MAX_PROTOCOL_VERSIONS = 16
_MAX_RESERVATIONS = 4096


class WorkerRegistryError(ValueError):
    """Base error for invalid registry operations."""


class WorkerNotFoundError(WorkerRegistryError):
    """The requested worker is not registered."""


class WorkerConflictError(WorkerRegistryError):
    """A registration or compare-and-swap revision conflicts with current state."""


def _identifier(value: object, field: str) -> str:
    if type(value) is not str or _WORKER_ID.fullmatch(value) is None:
        raise WorkerRegistryError(f"{field} is invalid")
    return value


def _capabilities(value: object) -> tuple[str, ...]:
    if type(value) is not tuple or not 1 <= len(value) <= _MAX_CAPABILITIES:
        raise WorkerRegistryError("capabilities must be a bounded non-empty tuple")
    if any(type(item) is not str or _CAPABILITY.fullmatch(item) is None for item in value):
        raise WorkerRegistryError("capabilities contain an invalid label")
    if len(set(value)) != len(value):
        raise WorkerRegistryError("capabilities must be unique")
    return value


def _now_ns(value: object | None, clock: Callable[[], int]) -> int:
    result = clock() if value is None else value
    if type(result) is not int or result < 0:
        raise WorkerRegistryError("monotonic timestamp must be a non-negative integer")
    return result


@dataclass(frozen=True, slots=True)
class WorkerDescriptor:
    """Host-approved, non-secret worker metadata; never an authorization grant."""

    worker_id: str
    protocol_versions: tuple[int, ...]
    capabilities: tuple[str, ...]
    priority: int = 0
    max_concurrency: int = 1
    enabled: bool = True
    revision: int = 1

    def __post_init__(self) -> None:
        _identifier(self.worker_id, "worker_id")
        if (type(self.protocol_versions) is not tuple
                or not 1 <= len(self.protocol_versions) <= _MAX_PROTOCOL_VERSIONS
                or any(type(v) is not int or not 1 <= v <= 255 for v in self.protocol_versions)
                or len(set(self.protocol_versions)) != len(self.protocol_versions)):
            raise WorkerRegistryError("protocol_versions must be unique supported integer versions")
        _capabilities(self.capabilities)
        if type(self.priority) is not int or not -1000 <= self.priority <= 1000:
            raise WorkerRegistryError("priority must be an integer from -1000 through 1000")
        if type(self.max_concurrency) is not int or not 1 <= self.max_concurrency <= 256:
            raise WorkerRegistryError("max_concurrency must be from 1 through 256")
        if type(self.enabled) is not bool:
            raise WorkerRegistryError("enabled must be a boolean")
        if type(self.revision) is not int or self.revision < 1:
            raise WorkerRegistryError("revision must be a positive integer")


@dataclass(frozen=True, slots=True)
class WorkerHealth:
    """Health observations supplied by trusted host code, never by worker payloads."""

    state: str
    last_heartbeat_ns: int | None
    consecutive_failures: int
    in_flight: int
    revision: int


@dataclass(frozen=True, slots=True)
class WorkerReservation:
    """Opaque host capacity hold; pending holds expire, committed holds do not."""

    token: str
    worker_id: str
    expires_at_ns: int
    descriptor_revision: int
    committed: bool = False

    def __post_init__(self) -> None:
        if type(self.token) is not str or re.fullmatch(r"[A-Za-z0-9_-]{32,128}", self.token) is None:
            raise WorkerRegistryError("reservation token is invalid")
        _identifier(self.worker_id, "worker_id")
        if type(self.expires_at_ns) is not int or self.expires_at_ns < 0:
            raise WorkerRegistryError("reservation expiry must be a non-negative integer")
        if type(self.descriptor_revision) is not int or self.descriptor_revision < 1:
            raise WorkerRegistryError("reservation descriptor revision must be positive")
        if type(self.committed) is not bool:
            raise WorkerRegistryError("reservation committed state must be a boolean")


@dataclass(frozen=True, slots=True)
class WorkerSnapshot:
    descriptor: WorkerDescriptor
    health: WorkerHealth


class InMemoryWorkerRegistry:
    """Thread-safe, bounded registry for one host process.

    Registration and health methods are host APIs. The authenticated_worker_id
    argument must come from an authenticated host transport/supervisor, not from
    the worker's JSON message. authorized_worker_ids in selection must be the
    result of a separate host policy decision. Registry results are advisory and
    do not authorize dispatch.
    """

    def __init__(
        self,
        *,
        heartbeat_ttl_ms: int = 30_000,
        failure_threshold: int = 3,
        clock_ns: Callable[[], int] = time.monotonic_ns,
        max_workers: int = _MAX_WORKERS,
        reservation_ttl_ms: int = 10_000,
        max_reservations: int = _MAX_RESERVATIONS,
    ) -> None:
        if type(heartbeat_ttl_ms) is not int or not 1_000 <= heartbeat_ttl_ms <= 300_000:
            raise WorkerRegistryError("heartbeat_ttl_ms must be from 1000 through 300000")
        if type(failure_threshold) is not int or not 1 <= failure_threshold <= 100:
            raise WorkerRegistryError("failure_threshold must be from 1 through 100")
        if not callable(clock_ns):
            raise WorkerRegistryError("clock_ns must be callable")
        if type(max_workers) is not int or not 1 <= max_workers <= _MAX_WORKERS:
            raise WorkerRegistryError(f"max_workers must be from 1 through {_MAX_WORKERS}")
        if type(reservation_ttl_ms) is not int or not 1_000 <= reservation_ttl_ms <= 60_000:
            raise WorkerRegistryError("reservation_ttl_ms must be from 1000 through 60000")
        if type(max_reservations) is not int or not 1 <= max_reservations <= _MAX_RESERVATIONS:
            raise WorkerRegistryError(f"max_reservations must be from 1 through {_MAX_RESERVATIONS}")
        self._ttl_ns = heartbeat_ttl_ms * 1_000_000
        self._failure_threshold = failure_threshold
        self._clock_ns = clock_ns
        self._max_workers = max_workers
        self._reservation_ttl_ns = reservation_ttl_ms * 1_000_000
        self._max_reservations = max_reservations
        self._workers: dict[str, WorkerSnapshot] = {}
        self._reservations: dict[str, WorkerReservation] = {}
        self._lock = threading.RLock()

    def register(
        self,
        descriptor: WorkerDescriptor,
        *,
        authenticated_worker_id: str,
        now_ns: int | None = None,
    ) -> WorkerSnapshot:
        if type(descriptor) is not WorkerDescriptor:
            raise WorkerRegistryError("descriptor must be an exact WorkerDescriptor")
        identity = _identifier(authenticated_worker_id, "authenticated_worker_id")
        if identity != descriptor.worker_id:
            raise WorkerRegistryError("authenticated identity does not match worker descriptor")
        if descriptor.revision != 1:
            raise WorkerRegistryError("new worker descriptors must start at revision 1")
        _now_ns(now_ns, self._clock_ns)
        with self._lock:
            if descriptor.worker_id in self._workers:
                raise WorkerConflictError("worker is already registered")
            if len(self._workers) >= self._max_workers:
                raise WorkerRegistryError("worker registry capacity is exhausted")
            snapshot = WorkerSnapshot(
                descriptor=descriptor,
                health=WorkerHealth("starting", None, 0, 0, 1),
            )
            self._workers[descriptor.worker_id] = snapshot
            return snapshot

    def get(self, worker_id: str) -> WorkerSnapshot:
        identity = _identifier(worker_id, "worker_id")
        with self._lock:
            snapshot = self._workers.get(identity)
            if snapshot is None:
                raise WorkerNotFoundError("worker is not registered")
            return snapshot

    def update_descriptor(
        self,
        descriptor: WorkerDescriptor,
        *,
        authenticated_worker_id: str,
        expected_revision: int,
    ) -> WorkerSnapshot:
        if type(descriptor) is not WorkerDescriptor:
            raise WorkerRegistryError("descriptor must be an exact WorkerDescriptor")
        identity = _identifier(authenticated_worker_id, "authenticated_worker_id")
        if identity != descriptor.worker_id:
            raise WorkerRegistryError("authenticated identity does not match worker descriptor")
        if type(expected_revision) is not int or expected_revision < 1:
            raise WorkerRegistryError("expected_revision must be a positive integer")
        with self._lock:
            current = self._workers.get(identity)
            if current is None:
                raise WorkerNotFoundError("worker is not registered")
            if current.descriptor.revision != expected_revision:
                raise WorkerConflictError("worker descriptor revision changed")
            if current.health.state == "retired":
                raise WorkerConflictError("retired workers cannot be updated or re-enabled")
            if descriptor.revision != expected_revision + 1:
                raise WorkerRegistryError("new descriptor revision must increment exactly once")
            self._revoke_worker_reservations(identity)
            updated = WorkerSnapshot(descriptor, current.health)
            self._workers[identity] = updated
            return updated

    def heartbeat(
        self,
        worker_id: str,
        *,
        authenticated_worker_id: str,
        in_flight: int,
        now_ns: int | None = None,
    ) -> WorkerSnapshot:
        identity = _identifier(worker_id, "worker_id")
        authenticated = _identifier(authenticated_worker_id, "authenticated_worker_id")
        if identity != authenticated:
            raise WorkerRegistryError("authenticated identity does not match worker ID")
        timestamp = _now_ns(now_ns, self._clock_ns)
        if type(in_flight) is not int or in_flight < 0:
            raise WorkerRegistryError("in_flight must be a non-negative integer")
        with self._lock:
            current = self._workers.get(identity)
            if current is None:
                raise WorkerNotFoundError("worker is not registered")
            if current.health.state in {"quarantined", "retired"}:
                raise WorkerConflictError("quarantined or retired workers cannot heartbeat into eligibility")
            if in_flight > current.descriptor.max_concurrency:
                raise WorkerRegistryError("in_flight exceeds configured worker capacity")
            health = replace(
                current.health,
                state="healthy",
                last_heartbeat_ns=timestamp,
                consecutive_failures=0,
                in_flight=in_flight,
                revision=current.health.revision + 1,
            )
            updated = WorkerSnapshot(current.descriptor, health)
            self._workers[identity] = updated
            return updated

    def record_failure(
        self,
        worker_id: str,
        *,
        authenticated_worker_id: str,
    ) -> WorkerSnapshot:
        identity = _identifier(worker_id, "worker_id")
        authenticated = _identifier(authenticated_worker_id, "authenticated_worker_id")
        if identity != authenticated:
            raise WorkerRegistryError("authenticated identity does not match worker ID")
        with self._lock:
            current = self._workers.get(identity)
            if current is None:
                raise WorkerNotFoundError("worker is not registered")
            if current.health.state in {"quarantined", "retired"}:
                raise WorkerConflictError("quarantined or retired worker state is terminal here")
            failures = current.health.consecutive_failures + 1
            state = "unavailable" if failures >= self._failure_threshold else "degraded"
            self._revoke_worker_reservations(identity)
            health = replace(
                current.health,
                state=state,
                consecutive_failures=failures,
                revision=current.health.revision + 1,
            )
            updated = WorkerSnapshot(current.descriptor, health)
            self._workers[identity] = updated
            return updated

    def quarantine(
        self,
        worker_id: str,
        *,
        expected_health_revision: int,
    ) -> WorkerSnapshot:
        return self._set_terminal_health(
            worker_id, state="quarantined", expected_health_revision=expected_health_revision,
        )

    def retire(
        self,
        worker_id: str,
        *,
        expected_health_revision: int,
    ) -> WorkerSnapshot:
        identity = _identifier(worker_id, "worker_id")
        if type(expected_health_revision) is not int or expected_health_revision < 1:
            raise WorkerRegistryError("expected_health_revision must be positive")
        with self._lock:
            current = self._workers.get(identity)
            if current is None:
                raise WorkerNotFoundError("worker is not registered")
            if current.health.revision != expected_health_revision:
                raise WorkerConflictError("worker health revision changed")
            self._revoke_worker_reservations(identity)
            descriptor = replace(
                current.descriptor, enabled=False, revision=current.descriptor.revision + 1,
            )
            health = replace(
                current.health, state="retired",
                revision=current.health.revision + 1,
            )
            updated = WorkerSnapshot(descriptor, health)
            self._workers[identity] = updated
            return updated

    def clear_quarantine(
        self,
        worker_id: str,
        *,
        expected_health_revision: int,
    ) -> WorkerSnapshot:
        identity = _identifier(worker_id, "worker_id")
        if type(expected_health_revision) is not int or expected_health_revision < 1:
            raise WorkerRegistryError("expected_health_revision must be positive")
        with self._lock:
            current = self._workers.get(identity)
            if current is None:
                raise WorkerNotFoundError("worker is not registered")
            if current.health.revision != expected_health_revision:
                raise WorkerConflictError("worker health revision changed")
            if current.health.state != "quarantined":
                raise WorkerConflictError("worker is not quarantined")
            health = replace(
                current.health, state="starting", last_heartbeat_ns=None,
                consecutive_failures=0,
                revision=current.health.revision + 1,
            )
            updated = WorkerSnapshot(current.descriptor, health)
            self._workers[identity] = updated
            return updated

    def _set_terminal_health(
        self,
        worker_id: str,
        *,
        state: str,
        expected_health_revision: int,
    ) -> WorkerSnapshot:
        identity = _identifier(worker_id, "worker_id")
        if type(expected_health_revision) is not int or expected_health_revision < 1:
            raise WorkerRegistryError("expected_health_revision must be positive")
        with self._lock:
            current = self._workers.get(identity)
            if current is None:
                raise WorkerNotFoundError("worker is not registered")
            if current.health.revision != expected_health_revision:
                raise WorkerConflictError("worker health revision changed")
            if current.health.state == "retired":
                raise WorkerConflictError("retired workers cannot change health state")
            self._revoke_worker_reservations(identity)
            health = replace(
                current.health, state=state,
                revision=current.health.revision + 1,
            )
            updated = WorkerSnapshot(current.descriptor, health)
            self._workers[identity] = updated
            return updated


    def _purge_expired_reservations(self, now_ns: int) -> None:
        """Remove expired capacity holds. Caller must hold _lock."""
        expired = [
            token for token, reservation in self._reservations.items()
            if not reservation.committed and now_ns >= reservation.expires_at_ns
        ]
        for token in expired:
            del self._reservations[token]

    def _revoke_worker_reservations(self, worker_id: str) -> None:
        """Invalidate pending holds, preserving committed in-flight work. Caller holds _lock."""
        revoked = [
            token for token, reservation in self._reservations.items()
            if reservation.worker_id == worker_id and not reservation.committed
        ]
        for token in revoked:
            del self._reservations[token]

    def reserve_eligible(
        self,
        capability: str,
        *,
        protocol_version: int,
        authorized_worker_ids: set[str] | frozenset[str],
        now_ns: int | None = None,
    ) -> WorkerReservation | None:
        """Atomically select and reserve one eligible worker capacity slot.

        The caller must independently authorize the task and re-check policy at
        dispatch. Reservations are process-local, expire lazily on subsequent selection/release operations, and are
        invalidated by worker failure, quarantine, retirement or descriptor change.
        """
        if type(capability) is not str or _CAPABILITY.fullmatch(capability) is None:
            raise WorkerRegistryError("capability is invalid")
        if type(protocol_version) is not int or not 1 <= protocol_version <= 255:
            raise WorkerRegistryError("protocol_version is invalid")
        if type(authorized_worker_ids) not in (set, frozenset):
            raise WorkerRegistryError("authorized_worker_ids must be a host policy set")
        if len(authorized_worker_ids) > self._max_workers:
            raise WorkerRegistryError("authorized worker set exceeds the registry bound")
        allowed = frozenset(
            _identifier(item, "authorized worker ID") for item in authorized_worker_ids
        )
        timestamp = _now_ns(now_ns, self._clock_ns)
        with self._lock:
            self._purge_expired_reservations(timestamp)
            reserved_counts: dict[str, int] = {}
            for reservation in self._reservations.values():
                reserved_counts[reservation.worker_id] = (
                    reserved_counts.get(reservation.worker_id, 0) + 1
                )
            candidates = []
            for snapshot in self._workers.values():
                descriptor, health = snapshot.descriptor, snapshot.health
                heartbeat = health.last_heartbeat_ns
                reserved = reserved_counts.get(descriptor.worker_id, 0)
                fresh = (
                    heartbeat is not None and heartbeat <= timestamp
                    and timestamp - heartbeat <= self._ttl_ns
                )
                if (
                    descriptor.worker_id in allowed
                    and descriptor.enabled
                    and capability in descriptor.capabilities
                    and protocol_version in descriptor.protocol_versions
                    and health.state == "healthy"
                    and fresh
                    and health.in_flight + reserved < descriptor.max_concurrency
                ):
                    candidates.append((snapshot, reserved))
            candidates.sort(key=lambda item: (
                -item[0].descriptor.priority,
                item[0].health.in_flight + item[1],
                item[0].descriptor.worker_id,
            ))
            if not candidates:
                return None
            if len(self._reservations) >= self._max_reservations:
                raise WorkerRegistryError("worker reservation capacity is exhausted")
            snapshot = candidates[0][0]
            token = secrets.token_urlsafe(32)
            reservation = WorkerReservation(
                token=token,
                worker_id=snapshot.descriptor.worker_id,
                expires_at_ns=timestamp + self._reservation_ttl_ns,
                descriptor_revision=snapshot.descriptor.revision,
            )
            self._reservations[token] = reservation
            return reservation

    def commit_reservation(
        self,
        reservation: WorkerReservation,
        *,
        authenticated_worker_id: str,
        now_ns: int | None = None,
    ) -> WorkerReservation | None:
        """Convert a pending expiring hold into a non-expiring in-flight hold.

        Commit before dispatch. The returned token remains capacity-accounted
        until explicitly released after host-observed load has been updated,
        or until trusted host reconciliation revokes it.
        """
        if type(reservation) is not WorkerReservation:
            raise WorkerRegistryError("reservation must be an exact WorkerReservation")
        identity = _identifier(authenticated_worker_id, "authenticated_worker_id")
        if identity != reservation.worker_id:
            raise WorkerRegistryError("authenticated identity does not match reservation worker")
        timestamp = _now_ns(now_ns, self._clock_ns)
        with self._lock:
            self._purge_expired_reservations(timestamp)
            current = self._reservations.get(reservation.token)
            if current is None:
                return None
            if current != reservation:
                raise WorkerConflictError("reservation token does not match current reservation")
            if current.committed:
                return current
            snapshot = self._workers.get(current.worker_id)
            if snapshot is None or snapshot.descriptor.revision != current.descriptor_revision:
                del self._reservations[current.token]
                return None
            heartbeat = snapshot.health.last_heartbeat_ns
            fresh = (
                heartbeat is not None and heartbeat <= timestamp
                and timestamp - heartbeat <= self._ttl_ns
            )
            if (
                not snapshot.descriptor.enabled
                or snapshot.health.state != "healthy"
                or not fresh
            ):
                del self._reservations[current.token]
                return None
            committed = replace(current, committed=True)
            self._reservations[current.token] = committed
            return committed

    def release_reservation(
        self,
        reservation: WorkerReservation,
        *,
        authenticated_worker_id: str,
        now_ns: int | None = None,
    ) -> bool:
        """Release a pending or committed hold after capacity is reflected elsewhere.

        Expired, revoked or already released tokens return False. For committed
        work, update host-observed in-flight load before releasing this hold.
        """
        if type(reservation) is not WorkerReservation:
            raise WorkerRegistryError("reservation must be an exact WorkerReservation")
        identity = _identifier(authenticated_worker_id, "authenticated_worker_id")
        if identity != reservation.worker_id:
            raise WorkerRegistryError("authenticated identity does not match reservation worker")
        timestamp = _now_ns(now_ns, self._clock_ns)
        with self._lock:
            self._purge_expired_reservations(timestamp)
            current = self._reservations.get(reservation.token)
            if current is None:
                return False
            if current != reservation:
                raise WorkerConflictError("reservation token does not match current reservation")
            del self._reservations[reservation.token]
            return True

    def eligible(
        self,
        capability: str,
        *,
        protocol_version: int,
        authorized_worker_ids: set[str] | frozenset[str],
        now_ns: int | None = None,
        limit: int = 20,
    ) -> tuple[WorkerSnapshot, ...]:
        if type(capability) is not str or _CAPABILITY.fullmatch(capability) is None:
            raise WorkerRegistryError("capability is invalid")
        if type(protocol_version) is not int or not 1 <= protocol_version <= 255:
            raise WorkerRegistryError("protocol_version is invalid")
        if type(authorized_worker_ids) not in (set, frozenset):
            raise WorkerRegistryError("authorized_worker_ids must be a host policy set")
        if len(authorized_worker_ids) > self._max_workers:
            raise WorkerRegistryError("authorized worker set exceeds the registry bound")
        allowed = frozenset(
            _identifier(item, "authorized worker ID") for item in authorized_worker_ids
        )
        if type(limit) is not int or not 1 <= limit <= 100:
            raise WorkerRegistryError("limit must be from 1 through 100")
        timestamp = _now_ns(now_ns, self._clock_ns)
        with self._lock:
            self._purge_expired_reservations(timestamp)
            reserved_counts: dict[str, int] = {}
            for reservation in self._reservations.values():
                reserved_counts[reservation.worker_id] = reserved_counts.get(reservation.worker_id, 0) + 1
            candidates = []
            for snapshot in self._workers.values():
                descriptor, health = snapshot.descriptor, snapshot.health
                heartbeat = health.last_heartbeat_ns
                reserved = reserved_counts.get(descriptor.worker_id, 0)
                fresh = (
                    heartbeat is not None and heartbeat <= timestamp
                    and timestamp - heartbeat <= self._ttl_ns
                )
                if (
                    descriptor.worker_id in allowed
                    and descriptor.enabled
                    and capability in descriptor.capabilities
                    and protocol_version in descriptor.protocol_versions
                    and health.state == "healthy"
                    and fresh
                    and health.in_flight + reserved < descriptor.max_concurrency
                ):
                    candidates.append(snapshot)
            candidates.sort(key=lambda item: (
                -item.descriptor.priority,
                item.health.in_flight + reserved_counts.get(item.descriptor.worker_id, 0),
                item.descriptor.worker_id,
            ))
            return tuple(candidates[:limit])
