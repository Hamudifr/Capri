"""Explicit in-process lifecycle and health reporting for CapriHostRuntime.

This service does not start background work during construction. Hosts must call
start() and stop() deliberately; an external process supervisor remains
responsible for process restart and operating-system resource limits.
"""
from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from .host_runtime import CapriHostRuntime


class HostServiceError(Exception):
    """Raised when the host service lifecycle is invalid or cannot start."""


class HostServiceState(str, Enum):
    NEW = "new"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class RuntimeHealthState(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class HostServiceHealth:
    service_state: HostServiceState
    status: RuntimeHealthState
    observed_at: str
    started_at: str | None
    stopped_at: str | None
    components: tuple[tuple[str, str], ...]
    worker_configured: bool
    worker_alive: bool
    failure_code: str | None

    @property
    def healthy(self) -> bool:
        return self.status is RuntimeHealthState.HEALTHY

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-safe snapshot without exposing exception details."""
        return {
            "service_state": self.service_state.value,
            "status": self.status.value,
            "observed_at": self.observed_at,
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "components": dict(self.components),
            "worker_configured": self.worker_configured,
            "worker_alive": self.worker_alive,
            "failure_code": self.failure_code,
        }


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class CapriHostService:
    """Supervise the optional TaskWorker with cooperative start/stop semantics.

    The service is deliberately in-process: it does not create an HTTP server,
    auto-start threads, or attempt to interrupt a running handler. A timed-out
    stop remains STOPPING until the worker returns; callers can retry stop().
    """

    def __init__(
        self,
        runtime: CapriHostRuntime,
        *,
        worker_thread_name: str = "capri-host-task-worker",
    ) -> None:
        if not isinstance(runtime, CapriHostRuntime):
            raise HostServiceError("runtime must be a CapriHostRuntime")
        if (type(worker_thread_name) is not str or not worker_thread_name.strip()
                or len(worker_thread_name) > 128):
            raise HostServiceError("worker_thread_name is invalid")
        self.runtime = runtime
        self.worker_thread_name = worker_thread_name
        self._lock = threading.RLock()
        self._state = HostServiceState.NEW
        self._stop_event: threading.Event | None = None
        self._worker_thread: threading.Thread | None = None
        self._started_at: str | None = None
        self._stopped_at: str | None = None
        self._failure_code: str | None = None

    @property
    def state(self) -> HostServiceState:
        with self._lock:
            return self._state

    @property
    def is_running(self) -> bool:
        return self.state is HostServiceState.RUNNING

    @property
    def shutdown_complete(self) -> bool:
        with self._lock:
            thread = self._worker_thread
            return (
                self._state in {HostServiceState.STOPPED, HostServiceState.FAILED}
                and (thread is None or not thread.is_alive())
            )

    def start(self) -> HostServiceHealth:
        with self._lock:
            if self._state is HostServiceState.RUNNING:
                already_running = True
            else:
                already_running = False
                if self._state in {HostServiceState.STOPPING, HostServiceState.FAILED}:
                    raise HostServiceError("service cannot start from its current state")
                self._stop_event = threading.Event()
                self._worker_thread = None
                self._failure_code = None
                self._started_at = _timestamp()
                self._stopped_at = None
                self._state = HostServiceState.RUNNING
                if self.runtime.task_worker_configured:
                    thread = threading.Thread(
                        target=self._run_worker,
                        args=(self._stop_event,),
                        name=self.worker_thread_name,
                        daemon=True,
                    )
                    self._worker_thread = thread
                    try:
                        thread.start()
                    except Exception:
                        self._state = HostServiceState.FAILED
                        self._failure_code = "worker_start_failed"
                        self._stopped_at = _timestamp()
                        raise HostServiceError("task worker could not be started") from None
        return self.health()

    def stop(self, timeout_seconds: float = 10.0) -> HostServiceHealth:
        if (isinstance(timeout_seconds, bool)
                or not isinstance(timeout_seconds, (int, float))
                or not math.isfinite(timeout_seconds)
                or not 0 <= timeout_seconds <= 300):
            raise HostServiceError("timeout_seconds must be between 0 and 300")

        with self._lock:
            if self._state is HostServiceState.NEW:
                self._state = HostServiceState.STOPPED
                self._stopped_at = _timestamp()
            elif self._state is HostServiceState.RUNNING:
                self._state = HostServiceState.STOPPING
            if self._stop_event is not None:
                self._stop_event.set()
            thread = self._worker_thread

        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=float(timeout_seconds))

        with self._lock:
            if thread is None or not thread.is_alive():
                if self._state is not HostServiceState.FAILED:
                    self._state = HostServiceState.STOPPED
                    if self._stopped_at is None:
                        self._stopped_at = _timestamp()
        return self.health()

    def health(self) -> HostServiceHealth:
        try:
            storage = self.runtime.storage_health()
        except Exception:
            storage = {
                "sessions": "unavailable",
                "tasks": "unavailable",
                "goals": "unavailable",
                "budgets": "unavailable",
            }

        with self._lock:
            state = self._state
            thread = self._worker_thread
            worker_configured = self.runtime.task_worker_configured
            worker_alive = thread is not None and thread.is_alive()
            started_at = self._started_at
            stopped_at = self._stopped_at
            failure_code = self._failure_code

        if not worker_configured:
            worker_status = "not_configured"
        elif state is HostServiceState.RUNNING:
            worker_status = "healthy" if worker_alive else "failed"
        elif state is HostServiceState.STOPPING:
            worker_status = "stopping" if worker_alive else "not_running"
        elif state is HostServiceState.FAILED:
            worker_status = "failed"
        else:
            worker_status = "not_running"

        components = dict(storage)
        components["task_worker"] = worker_status
        components["service"] = state.value

        storage_degraded = any(
            value in {"degraded", "unavailable"}
            for value in storage.values()
        )
        if state in {HostServiceState.NEW, HostServiceState.STOPPING, HostServiceState.STOPPED}:
            status = RuntimeHealthState.UNAVAILABLE
        elif state is HostServiceState.FAILED:
            status = RuntimeHealthState.DEGRADED
        elif storage_degraded or (worker_configured and worker_status != "healthy"):
            status = RuntimeHealthState.DEGRADED
        else:
            status = RuntimeHealthState.HEALTHY

        return HostServiceHealth(
            service_state=state,
            status=status,
            observed_at=_timestamp(),
            started_at=started_at,
            stopped_at=stopped_at,
            components=tuple(sorted(components.items())),
            worker_configured=worker_configured,
            worker_alive=worker_alive,
            failure_code=failure_code,
        )

    def _run_worker(self, stop_event: threading.Event) -> None:
        try:
            self.runtime.run_task_worker(stop_event)
        except Exception:
            with self._lock:
                self._state = HostServiceState.FAILED
                self._failure_code = "task_worker_failed"
                self._stopped_at = _timestamp()
            return

        with self._lock:
            if stop_event.is_set():
                if self._state is not HostServiceState.FAILED:
                    self._state = HostServiceState.STOPPED
                    self._stopped_at = _timestamp()
            else:
                self._state = HostServiceState.FAILED
                self._failure_code = "task_worker_exited_unexpectedly"
                self._stopped_at = _timestamp()
