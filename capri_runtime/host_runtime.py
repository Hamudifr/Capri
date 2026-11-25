"""Request-scoped host composition with authenticated session ownership.

This module does not start a server or background threads. The embedding host
owns authentication callbacks, process supervision, credentials, and lifecycle.
"""
from __future__ import annotations

from dataclasses import dataclass
import threading
from types import MethodType
from typing import Any, Callable

from capri_core.validation import contains_surrogate
from capri_core.strategy import StrategyEvaluation, StrategyObservation

from .memory import UntrustedMemoryContext
from .knowledge_graph import UntrustedKnowledgeContext
from .orchestration import (
    CommittedOrchestration,
    SessionTurnCoordinator,
    ToolOrchestrator,
)
from .runtime import Message, Session, SessionClosedError, SessionStore
from .sqlite_sessions import SQLiteSessionStore
from .tasks import SQLiteTaskStore, TaskNotFoundError, TaskRecord, TaskWorker
from .goals import (
    GoalPlanProposal, GoalRecord, SQLiteGoalStore,
)
from .goal_coordinator import GoalCoordinator, GoalExecution
from .goal_reports import GoalReport, build_goal_report
from .budgets import BudgetUsage, SQLiteBudgetStore
from .strategy_store import (
    ActiveStrategyRecord, SQLiteStrategyStore, StrategyActivationEvent,
    StrategyActivationGrant, StrategyVersionRecord,
)
from .execution_evidence import SQLiteExecutionEvidenceJournal
from .strategy_approval import HostStrategyApprovalAuthority, StrategyApprovalRequest
from .strategy_evidence import HostStrategyEvidenceAuthority
from .tools import ExecutionContext, HostAuthorityResolver
from .worker_registry import (
    InMemoryWorkerRegistry, WorkerDescriptor, WorkerRegistryError, WorkerReservation, WorkerSnapshot,
)


class HostRuntimeError(Exception):
    """A trusted host composition or retrieved-context resolution operation failed."""


@dataclass(frozen=True, slots=True)
class HostWorkerReservation:
    """Principal/task-scoped host wrapper around an opaque registry capacity hold."""

    principal_id: str
    task_id: str
    capability: str
    protocol_version: int
    reservation: WorkerReservation

    def __post_init__(self) -> None:
        if (
            type(self.principal_id) is not str or not self.principal_id
            or len(self.principal_id) > 256 or contains_surrogate(self.principal_id)
        ):
            raise HostRuntimeError("worker reservation principal is invalid")
        if type(self.task_id) is not str or not self.task_id or len(self.task_id) > 128:
            raise HostRuntimeError("worker reservation task is invalid")
        if type(self.capability) is not str or not self.capability or len(self.capability) > 128:
            raise HostRuntimeError("worker reservation capability is invalid")
        if type(self.protocol_version) is not int or not 1 <= self.protocol_version <= 255:
            raise HostRuntimeError("worker reservation protocol version is invalid")
        if type(self.reservation) is not WorkerReservation:
            raise HostRuntimeError("worker reservation requires an exact registry reservation")


def _is_bound_authority_method(callback: Any, authority: Any, method_name: str) -> bool:
    """Check that a store verifier is a genuine bound method of the exact host authority."""
    return (
        type(callback) is MethodType
        and callback.__self__ is authority
        and callback.__func__ is getattr(type(authority), method_name, None)
    )


class PrincipalBoundSessionStore(SessionStore):
    """SessionStore facade that binds every operation to one principal.

    This object is created inside a trusted request after authentication. It must
    never be constructed from a principal ID supplied by an untrusted client.
    """

    def __init__(self, store: SQLiteSessionStore, principal_id: str) -> None:
        if not isinstance(store, SQLiteSessionStore):
            raise HostRuntimeError("principal-bound sessions require SQLiteSessionStore")
        principal_id = store._validate_principal_id(principal_id)
        super().__init__(
            max_session_messages=store.max_session_messages,
            max_input_chars=store.max_input_chars,
            max_output_chars=store.max_output_chars,
            max_tool_chars=store.max_tool_chars,
        )
        self._store = store
        self._principal_id = principal_id

    def create(self) -> Session:
        return self._store.create_for_principal(self._principal_id)

    def get(self, session_id: str) -> Session:
        return self._store.get_for_principal(session_id, self._principal_id)

    def close(self, session_id: str) -> Session:
        return self._store.close_for_principal(session_id, self._principal_id)

    def commit_turn_messages(
        self,
        session_id: str,
        expected_version: int,
        turn_messages: tuple[Message, ...],
        *,
        lease_owner: str | None = None,
    ) -> Session:
        return self._store.commit_turn_messages_for_principal(
            session_id,
            self._principal_id,
            expected_version,
            turn_messages,
            lease_owner=lease_owner,
        )

    def claim_turn_lease(
        self,
        session_id: str,
        owner_token: str,
        lease_seconds: float = 30.0,
    ) -> str:
        return self._store.claim_turn_lease_for_principal(
            session_id, self._principal_id, owner_token, lease_seconds
        )

    def renew_turn_lease(
        self,
        session_id: str,
        owner_token: str,
        lease_seconds: float = 30.0,
    ) -> str:
        return self._store.renew_turn_lease_for_principal(
            session_id, self._principal_id, owner_token, lease_seconds
        )

    def release_turn_lease(self, session_id: str, owner_token: str) -> bool:
        return self._store.release_turn_lease_for_principal(
            session_id, self._principal_id, owner_token
        )


class CapriHostRuntime:
    """Compose trusted identity, principal-owned sessions, model turns, and a task worker.

    All provider/model execution remains injected through ToolOrchestrator.
    Memory and knowledge-graph resolvers are trusted host code and must enforce
    principal-scoped access. TaskWorker remains opt-in; CapriHostService provides
    cooperative in-process lifecycle management, while an external process
    supervisor remains responsible for process restart and OS-level limits.
    The optional Nexus registry gateway requires separate worker-identity,
    descriptor, supervisor-observation, host-load and task-policy resolvers.
    It returns advisory candidates only and never dispatches work or grants permissions.
    """

    def __init__(
        self,
        authority: HostAuthorityResolver,
        session_store: SQLiteSessionStore,
        orchestrator: ToolOrchestrator,
        *,
        coordinator: SessionTurnCoordinator | None = None,
        memory_context_resolver: Callable[
            [str, str, str], UntrustedMemoryContext | None
        ] | None = None,
        knowledge_context_resolver: Callable[
            [str, str, str], UntrustedKnowledgeContext | None
        ] | None = None,
        task_worker: TaskWorker | None = None,
        task_store: SQLiteTaskStore | None = None,
        goal_store: SQLiteGoalStore | None = None,
        budget_store: SQLiteBudgetStore | None = None,
        strategy_store: SQLiteStrategyStore | None = None,
        execution_evidence_journal: SQLiteExecutionEvidenceJournal | None = None,
        strategy_approval_authority: HostStrategyApprovalAuthority | None = None,
        strategy_evidence_authority: HostStrategyEvidenceAuthority | None = None,
        worker_registry: InMemoryWorkerRegistry | None = None,
        worker_identity_resolver: Callable[[Any], str | None] | None = None,
        worker_descriptor_resolver: Callable[[str, WorkerDescriptor], WorkerDescriptor] | None = None,
        worker_observer_authorizer: Callable[[Any, str], bool] | None = None,
        worker_in_flight_resolver: Callable[[str], int] | None = None,
        worker_policy_resolver: Callable[[str, str, str], set[str] | frozenset[str]] | None = None,
    ) -> None:
        if not isinstance(authority, HostAuthorityResolver):
            raise HostRuntimeError("a trusted HostAuthorityResolver is required")
        if not isinstance(session_store, SQLiteSessionStore):
            raise HostRuntimeError("a durable SQLiteSessionStore is required")
        if not isinstance(orchestrator, ToolOrchestrator):
            raise HostRuntimeError("a configured ToolOrchestrator is required")
        required_assistant_chars = max(
            orchestrator.max_output_chars,
            orchestrator.max_tool_message_bytes,
        )
        if session_store.max_output_chars < required_assistant_chars:
            raise HostRuntimeError(
                "session max_output_chars must cover assistant and tool-call message limits"
            )
        if session_store.max_tool_chars < orchestrator.max_tool_message_bytes:
            raise HostRuntimeError(
                "session max_tool_chars must cover the orchestrator tool-message limit"
            )
        if coordinator is None:
            coordinator = SessionTurnCoordinator()
        if not isinstance(coordinator, SessionTurnCoordinator):
            raise HostRuntimeError("coordinator must be a SessionTurnCoordinator")
        if memory_context_resolver is not None and not callable(memory_context_resolver):
            raise HostRuntimeError("memory_context_resolver must be callable")
        if knowledge_context_resolver is not None and not callable(knowledge_context_resolver):
            raise HostRuntimeError("knowledge_context_resolver must be callable")
        if task_worker is not None and not isinstance(task_worker, TaskWorker):
            raise HostRuntimeError("task_worker must be a TaskWorker")
        if task_store is not None and not isinstance(task_store, SQLiteTaskStore):
            raise HostRuntimeError("task_store must be a SQLiteTaskStore")
        if goal_store is not None and not isinstance(goal_store, SQLiteGoalStore):
            raise HostRuntimeError("goal_store must be a SQLiteGoalStore")
        if budget_store is not None and not isinstance(budget_store, SQLiteBudgetStore):
            raise HostRuntimeError("budget_store must be a SQLiteBudgetStore")
        if strategy_store is not None and not isinstance(strategy_store, SQLiteStrategyStore):
            raise HostRuntimeError("strategy_store must be a SQLiteStrategyStore")
        if (
            execution_evidence_journal is not None
            and not isinstance(execution_evidence_journal, SQLiteExecutionEvidenceJournal)
        ):
            raise HostRuntimeError("execution_evidence_journal must be a SQLiteExecutionEvidenceJournal")
        if (
            strategy_approval_authority is not None
            and not isinstance(strategy_approval_authority, HostStrategyApprovalAuthority)
        ):
            raise HostRuntimeError("strategy_approval_authority must be a HostStrategyApprovalAuthority")
        if (
            strategy_evidence_authority is not None
            and not isinstance(strategy_evidence_authority, HostStrategyEvidenceAuthority)
        ):
            raise HostRuntimeError("strategy_evidence_authority must be a HostStrategyEvidenceAuthority")
        if (strategy_approval_authority is None) != (strategy_evidence_authority is None):
            raise HostRuntimeError(
                "strategy approval and evidence authorities must be configured together"
            )
        if worker_registry is not None and not isinstance(worker_registry, InMemoryWorkerRegistry):
            raise HostRuntimeError("worker_registry must be an InMemoryWorkerRegistry")
        if worker_identity_resolver is not None and not callable(worker_identity_resolver):
            raise HostRuntimeError("worker_identity_resolver must be callable")
        if worker_descriptor_resolver is not None and not callable(worker_descriptor_resolver):
            raise HostRuntimeError("worker_descriptor_resolver must be callable")
        if worker_observer_authorizer is not None and not callable(worker_observer_authorizer):
            raise HostRuntimeError("worker_observer_authorizer must be callable")
        if worker_in_flight_resolver is not None and not callable(worker_in_flight_resolver):
            raise HostRuntimeError("worker_in_flight_resolver must be callable")
        if worker_policy_resolver is not None and not callable(worker_policy_resolver):
            raise HostRuntimeError("worker_policy_resolver must be callable")
        if worker_registry is None and any((
            worker_identity_resolver is not None,
            worker_descriptor_resolver is not None,
            worker_observer_authorizer is not None,
            worker_in_flight_resolver is not None,
            worker_policy_resolver is not None,
        )):
            raise HostRuntimeError("worker registry callbacks require a configured worker_registry")
        if worker_registry is not None and any((
            worker_identity_resolver is None,
            worker_descriptor_resolver is None,
            worker_observer_authorizer is None,
            worker_in_flight_resolver is None,
            worker_policy_resolver is None,
        )):
            raise HostRuntimeError(
                "worker_registry requires identity, descriptor, supervisor-observer, host-load and policy resolvers"
            )
        if (
            task_store is not None and task_worker is not None
            and task_store.path != task_worker.engine.store.path
        ):
            raise HostRuntimeError("task_store and task_worker must use the same database")
        self._authority = authority
        self._session_store = session_store
        self._orchestrator = orchestrator
        self._coordinator = coordinator
        self._memory_context_resolver = memory_context_resolver
        self._knowledge_context_resolver = knowledge_context_resolver
        self._task_worker = task_worker
        self._task_store = (
            task_store if task_store is not None
            else (task_worker.engine.store if task_worker is not None else None)
        )
        engine = task_worker.engine if task_worker is not None else None
        engine_journal = engine.execution_evidence_journal if engine is not None else None
        if execution_evidence_journal is None and engine_journal is not None:
            raise HostRuntimeError(
                "host runtime must receive the exact execution evidence journal configured on TaskEngine"
            )
        if execution_evidence_journal is not None:
            if self._task_store is None or engine is None:
                raise HostRuntimeError(
                    "execution evidence requires the configured principal task store and task worker"
                )
            if (
                engine.store is not self._task_store
                or engine_journal is not execution_evidence_journal
                or not callable(engine.execution_evidence_credential)
                or getattr(execution_evidence_journal, "_tasks", None) is not self._task_store
            ):
                raise HostRuntimeError(
                    "execution evidence journal, TaskEngine, TaskWorker and host runtime must share exact trusted components"
                )
        if strategy_approval_authority is not None:
            if self._task_store is None:
                raise HostRuntimeError("strategy authorities require the configured principal task store")
            if strategy_store is None:
                try:
                    strategy_store = SQLiteStrategyStore(
                        self._task_store,
                        approval_verifier=strategy_approval_authority.verify,
                        evidence_verifier=strategy_evidence_authority.verify,
                    )
                except Exception:
                    raise HostRuntimeError("trusted strategy store could not be composed") from None
            if (
                strategy_store.task_store is not self._task_store
                or not _is_bound_authority_method(
                    strategy_store._approval_verifier, strategy_approval_authority, "verify",
                )
                or not _is_bound_authority_method(
                    strategy_store._evidence_verifier, strategy_evidence_authority, "verify",
                )
            ):
                raise HostRuntimeError(
                    "strategy store must use the exact host approval and evidence authority verifiers"
                )
        elif strategy_store is not None and (
            self._task_store is None or strategy_store.task_store is not self._task_store
        ):
            raise HostRuntimeError("strategy_store must share the exact configured task store")
        self._execution_evidence_journal = execution_evidence_journal
        self._strategy_approval_authority = strategy_approval_authority
        self._strategy_evidence_authority = strategy_evidence_authority
        self._strategy_store = strategy_store
        self._worker_registry = worker_registry
        self._worker_identity_resolver = worker_identity_resolver
        self._worker_descriptor_resolver = worker_descriptor_resolver
        self._worker_observer_authorizer = worker_observer_authorizer
        self._worker_in_flight_resolver = worker_in_flight_resolver
        self._worker_policy_resolver = worker_policy_resolver
        self._worker_reservation_lock = threading.RLock()
        self._worker_reservation_contexts: dict[str, HostWorkerReservation] = {}
        self._goal_store = goal_store
        configured_budgets = [
            item for item in (
                budget_store, orchestrator.budget_store,
                orchestrator.bridge.executor.budget_store,
                task_worker.engine.budget_store if task_worker is not None else None,
            ) if item is not None
        ]
        if configured_budgets and any(item is not configured_budgets[0] for item in configured_budgets):
            raise HostRuntimeError("provider, tool and task execution must share one budget store")
        self._budget_store = configured_budgets[0] if configured_budgets else None
        if self._budget_store is not None:
            try:
                orchestrator.set_budget_store(self._budget_store)
                if task_worker is not None:
                    task_worker.engine.set_budget_store(self._budget_store)
            except Exception:
                raise HostRuntimeError("execution budget store could not be applied consistently") from None

    def _context(self, credential: Any) -> ExecutionContext:
        return self._authority.resolve(credential)

    def _worker_identity(self, credential: Any) -> str:
        if self._worker_registry is None or self._worker_identity_resolver is None:
            raise HostRuntimeError("no host worker registry is configured")
        try:
            identity = self._worker_identity_resolver(credential)
        except Exception:
            raise HostRuntimeError("worker transport authentication failed") from None
        if type(identity) is not str:
            raise HostRuntimeError("worker transport identity is invalid")
        return identity

    def register_worker(self, credential: Any, descriptor: WorkerDescriptor) -> WorkerSnapshot:
        """Register a worker only after the trusted host transport resolves its identity."""
        identity = self._worker_identity(credential)
        try:
            approved = self._worker_descriptor_resolver(identity, descriptor)
        except Exception:
            raise HostRuntimeError("host worker descriptor approval failed") from None
        if type(approved) is not WorkerDescriptor or approved.worker_id != identity:
            raise HostRuntimeError("host worker descriptor approval returned an invalid identity")
        try:
            return self._worker_registry.register(
                approved, authenticated_worker_id=identity,
            )
        except WorkerRegistryError:
            raise HostRuntimeError("worker registration was rejected") from None

    def _authorize_worker_observer(self, credential: Any, worker_id: str) -> None:
        if self._worker_registry is None or self._worker_observer_authorizer is None:
            raise HostRuntimeError("no host worker observer is configured")
        try:
            authorized = self._worker_observer_authorizer(credential, worker_id)
        except Exception:
            raise HostRuntimeError("host worker observer authentication failed") from None
        if authorized is not True:
            raise HostRuntimeError("host worker observer is not authorized")

    def _worker_in_flight(self, worker_id: str) -> int:
        if self._worker_registry is None or self._worker_in_flight_resolver is None:
            raise HostRuntimeError("no host worker load resolver is configured")
        try:
            in_flight = self._worker_in_flight_resolver(worker_id)
        except Exception:
            raise HostRuntimeError("host worker load observation failed") from None
        if type(in_flight) is not int or in_flight < 0:
            raise HostRuntimeError("host worker load observation is invalid")
        return in_flight

    def heartbeat_worker(
        self, observer_credential: Any, worker_id: str,
    ) -> WorkerSnapshot:
        """Record liveness only from a trusted supervisor and host-derived load."""
        self._authorize_worker_observer(observer_credential, worker_id)
        in_flight = self._worker_in_flight(worker_id)
        try:
            return self._worker_registry.heartbeat(
                worker_id, authenticated_worker_id=worker_id, in_flight=in_flight,
            )
        except WorkerRegistryError:
            raise HostRuntimeError("worker heartbeat was rejected") from None

    def record_worker_failure(
        self, observer_credential: Any, worker_id: str,
    ) -> WorkerSnapshot:
        """Record failure only from a trusted host supervisor/monitor."""
        self._authorize_worker_observer(observer_credential, worker_id)
        try:
            return self._worker_registry.record_failure(
                worker_id, authenticated_worker_id=worker_id,
            )
        except WorkerRegistryError:
            raise HostRuntimeError("worker failure observation was rejected") from None

    def _worker_policy_allowlist(
        self, principal_id: str, task_id: str, capability: str,
    ) -> set[str] | frozenset[str]:
        if self._worker_policy_resolver is None:
            raise HostRuntimeError("no host worker policy resolver is configured")
        try:
            allowed = self._worker_policy_resolver(principal_id, task_id, capability)
        except Exception:
            raise HostRuntimeError("host worker policy resolution failed") from None
        if type(allowed) not in (set, frozenset):
            raise HostRuntimeError("host worker policy returned an invalid allow-list")
        return allowed

    @staticmethod
    def _same_host_reservation_context(
        left: HostWorkerReservation, right: HostWorkerReservation,
    ) -> bool:
        return (
            left.principal_id == right.principal_id
            and left.task_id == right.task_id
            and left.capability == right.capability
            and left.protocol_version == right.protocol_version
            and left.reservation.token == right.reservation.token
            and left.reservation.worker_id == right.reservation.worker_id
        )

    def _purge_worker_reservation_contexts(self) -> None:
        if self._worker_registry is None:
            self._worker_reservation_contexts.clear()
            return
        for token, context in tuple(self._worker_reservation_contexts.items()):
            current = self._worker_registry.get_reservation(token)
            if current is None:
                self._worker_reservation_contexts.pop(token, None)
            elif current != context.reservation:
                if (
                    current.worker_id == context.reservation.worker_id
                    and current.committed and not context.reservation.committed
                ):
                    self._worker_reservation_contexts[token] = HostWorkerReservation(
                        context.principal_id, context.task_id, context.capability,
                        context.protocol_version, current,
                    )
                else:
                    self._worker_reservation_contexts.pop(token, None)

    def get_worker_candidates(
        self, credential: Any, task_id: str, capability: str, protocol_version: int,
    ) -> tuple[WorkerSnapshot, ...]:
        """Return advisory candidates filtered by a separate host task-policy decision."""
        context = self._context(credential)
        if self._worker_registry is None or self._worker_policy_resolver is None:
            raise HostRuntimeError("no host worker registry is configured")
        if self._task_store is None:
            raise HostRuntimeError("worker selection requires a configured task store")
        try:
            self._task_store.get_for_principal(task_id, context.principal_id)
        except Exception:
            raise HostRuntimeError("task is unavailable to the authenticated principal") from None
        allowed = self._worker_policy_allowlist(context.principal_id, task_id, capability)
        try:
            return self._worker_registry.eligible(
                capability,
                protocol_version=protocol_version,
                authorized_worker_ids=allowed,
            )
        except WorkerRegistryError:
            raise HostRuntimeError("host worker candidate lookup was rejected") from None

    def reserve_worker_candidate(
        self, credential: Any, task_id: str, capability: str, protocol_version: int,
    ) -> HostWorkerReservation | None:
        """Reserve one candidate for an authenticated principal-owned task."""
        context = self._context(credential)
        if self._worker_registry is None or self._worker_policy_resolver is None:
            raise HostRuntimeError("no host worker registry is configured")
        if self._task_store is None:
            raise HostRuntimeError("worker reservation requires a configured task store")
        try:
            self._task_store.get_for_principal(task_id, context.principal_id)
        except Exception:
            raise HostRuntimeError("task is unavailable to the authenticated principal") from None
        allowed = self._worker_policy_allowlist(context.principal_id, task_id, capability)
        with self._worker_reservation_lock:
            self._purge_worker_reservation_contexts()
            try:
                reservation = self._worker_registry.reserve_eligible(
                    capability,
                    protocol_version=protocol_version,
                    authorized_worker_ids=allowed,
                )
            except WorkerRegistryError:
                raise HostRuntimeError("host worker reservation was rejected") from None
            if reservation is None:
                return None
            wrapped = HostWorkerReservation(
                context.principal_id, task_id, capability, protocol_version, reservation,
            )
            if reservation.token in self._worker_reservation_contexts:
                try:
                    self._worker_registry.release_reservation(
                        reservation, authenticated_worker_id=reservation.worker_id,
                    )
                except WorkerRegistryError:
                    pass
                raise HostRuntimeError("worker reservation context collision")
            self._worker_reservation_contexts[reservation.token] = wrapped
            return wrapped

    def commit_worker_reservation(
        self,
        credential: Any,
        observer_credential: Any,
        reservation: HostWorkerReservation,
    ) -> HostWorkerReservation:
        """Recheck principal/task policy and commit a pending hold under supervisor authority."""
        if type(reservation) is not HostWorkerReservation:
            raise HostRuntimeError("an exact host worker reservation is required")
        context = self._context(credential)
        if context.principal_id != reservation.principal_id:
            raise HostRuntimeError("worker reservation belongs to another principal")
        if self._worker_registry is None or self._task_store is None:
            raise HostRuntimeError("worker reservation requires the configured host registry and task store")
        try:
            self._task_store.get_for_principal(reservation.task_id, context.principal_id)
        except Exception:
            raise HostRuntimeError("task is unavailable to the authenticated principal") from None
        worker_id = reservation.reservation.worker_id
        self._authorize_worker_observer(observer_credential, worker_id)
        with self._worker_reservation_lock:
            self._purge_worker_reservation_contexts()
            stored = self._worker_reservation_contexts.get(reservation.reservation.token)
            if stored is None or not self._same_host_reservation_context(stored, reservation):
                raise HostRuntimeError("worker reservation is unavailable or belongs to another task")
            if stored.reservation.committed:
                return stored
            try:
                allowed = self._worker_policy_allowlist(
                    stored.principal_id, stored.task_id, stored.capability,
                )
            except HostRuntimeError:
                try:
                    self._worker_registry.release_reservation(
                        stored.reservation, authenticated_worker_id=worker_id,
                    )
                except WorkerRegistryError:
                    pass
                self._worker_reservation_contexts.pop(stored.reservation.token, None)
                raise
            if worker_id not in allowed:
                try:
                    self._worker_registry.release_reservation(
                        stored.reservation, authenticated_worker_id=worker_id,
                    )
                except WorkerRegistryError:
                    pass
                self._worker_reservation_contexts.pop(stored.reservation.token, None)
                raise HostRuntimeError("worker reservation is no longer authorized for this task")
            self.heartbeat_worker(observer_credential, worker_id)
            try:
                committed = self._worker_registry.commit_reservation(
                    stored.reservation, authenticated_worker_id=worker_id,
                )
            except WorkerRegistryError:
                self._purge_worker_reservation_contexts()
                raise HostRuntimeError("worker reservation commit was rejected") from None
            if committed is None:
                self._purge_worker_reservation_contexts()
                raise HostRuntimeError("worker reservation expired or is no longer eligible")
            wrapped = HostWorkerReservation(
                stored.principal_id, stored.task_id, stored.capability,
                stored.protocol_version, committed,
            )
            self._worker_reservation_contexts[committed.token] = wrapped
            return wrapped

    def mark_worker_reservation_started(
        self, observer_credential: Any, reservation: HostWorkerReservation,
    ) -> bool:
        """Handoff a committed hold after worker acceptance under supervisor authority."""
        if type(reservation) is not HostWorkerReservation:
            raise HostRuntimeError("an exact host worker reservation is required")
        worker_id = reservation.reservation.worker_id
        self._authorize_worker_observer(observer_credential, worker_id)
        if self._worker_registry is None:
            raise HostRuntimeError("no host worker registry is configured")
        with self._worker_reservation_lock:
            self._purge_worker_reservation_contexts()
            stored = self._worker_reservation_contexts.get(reservation.reservation.token)
            if stored is None:
                return False
            if not self._same_host_reservation_context(stored, reservation):
                raise HostRuntimeError("worker reservation belongs to another task")
            if not stored.reservation.committed:
                raise HostRuntimeError("worker reservation must be committed before worker start")
            observed_in_flight = self._worker_in_flight(worker_id)
            try:
                started = self._worker_registry.handoff_reservation_to_in_flight(
                    stored.reservation,
                    authenticated_worker_id=worker_id,
                    observed_in_flight=observed_in_flight,
                )
            except WorkerRegistryError:
                raise HostRuntimeError("worker reservation start handoff was rejected") from None
            self._worker_reservation_contexts.pop(stored.reservation.token, None)
            return started

    def release_worker_reservation(
        self, observer_credential: Any, reservation: HostWorkerReservation,
    ) -> bool:
        """Release a reservation only when dispatch did not start or was rejected."""
        if type(reservation) is not HostWorkerReservation:
            raise HostRuntimeError("an exact host worker reservation is required")
        worker_id = reservation.reservation.worker_id
        self._authorize_worker_observer(observer_credential, worker_id)
        if self._worker_registry is None:
            raise HostRuntimeError("no host worker registry is configured")
        with self._worker_reservation_lock:
            self._purge_worker_reservation_contexts()
            stored = self._worker_reservation_contexts.get(reservation.reservation.token)
            if stored is None:
                return False
            if not self._same_host_reservation_context(stored, reservation):
                raise HostRuntimeError("worker reservation belongs to another task")
            try:
                released = self._worker_registry.release_reservation(
                    stored.reservation, authenticated_worker_id=worker_id,
                )
            except WorkerRegistryError:
                raise HostRuntimeError("worker reservation release was rejected") from None
            self._worker_reservation_contexts.pop(stored.reservation.token, None)
            return released

    def get_budget_usage(self, credential: Any) -> BudgetUsage:
        """Return only the authenticated principal's current budget-window usage."""
        context = self._context(credential)
        if self._budget_store is None:
            raise HostRuntimeError("no execution budget store is configured")
        return self._budget_store.usage_for_principal(context.principal_id)

    def create_session(self, credential: Any) -> Session:
        """Authenticate and atomically create a session owned by that principal."""
        context = self._context(credential)
        return self._session_store.create_for_principal(context.principal_id)

    def get_session(self, credential: Any, session_id: str) -> Session:
        """Return only a session owned by the authenticated principal."""
        context = self._context(credential)
        return self._session_store.get_for_principal(session_id, context.principal_id)

    def close_session(self, credential: Any, session_id: str) -> Session:
        """Close only a session owned by the authenticated principal."""
        context = self._context(credential)
        return self._session_store.close_for_principal(session_id, context.principal_id)

    def create_task(
        self, credential: Any, plan: Any, idempotency_key: str | None = None
    ) -> TaskRecord:
        """Create a durable task owned by the authenticated principal.

        Task creation requires a configured worker registry so plans cannot
        enqueue handler names that are not currently approved for principal work.
        """
        context = self._context(credential)
        if self._task_store is None:
            raise HostRuntimeError("no task store is configured")
        if self._task_worker is None:
            raise HostRuntimeError("principal task creation requires a configured task worker")
        allowed = self._task_worker.engine.principal_handlers
        if type(plan) is list:
            for step in plan:
                if type(step) is dict and type(step.get("tool")) is str:
                    if step["tool"] not in allowed:
                        raise HostRuntimeError("task plan references an unavailable principal handler")
        return self._task_store.create_for_principal(
            context.principal_id, plan, idempotency_key=idempotency_key
        )

    def get_task(self, credential: Any, task_id: str) -> TaskRecord:
        """Read only a task owned by the authenticated principal."""
        context = self._context(credential)
        if self._task_store is None:
            raise HostRuntimeError("no task store is configured")
        return self._task_store.get_for_principal(task_id, context.principal_id)

    def get_execution_evidence_ref(
        self, credential: Any, task_id: str, step_index: int, attempt: int,
    ) -> str | None:
        """Return a verified completed event reference for the authenticated task owner."""
        context = self._context(credential)
        if self._task_store is None or self._execution_evidence_journal is None:
            raise HostRuntimeError("host execution evidence is not configured")
        try:
            self._task_store.get_for_principal(task_id, context.principal_id)
            return self._execution_evidence_journal.get_completed_event_ref(
                context.principal_id, task_id, step_index, attempt,
            )
        except Exception:
            raise HostRuntimeError("execution evidence is unavailable to the authenticated principal") from None

    def register_strategy_baseline(
        self, credential: Any, strategy_class: str, strategy_id: str,
        version: str, config: dict[str, Any],
    ) -> StrategyVersionRecord:
        """Register an immutable baseline config for the authenticated principal."""
        context = self._context(credential)
        if self._strategy_store is None:
            raise HostRuntimeError("no strategy store is configured")
        return self._strategy_store.register_baseline_for_principal(
            context.principal_id, strategy_class, strategy_id, version, config,
        )

    def register_strategy_candidate(
        self, credential: Any, strategy_class: str, strategy_id: str,
        version: str, config: dict[str, Any], evaluation: StrategyEvaluation, *,
        observations: tuple[StrategyObservation, ...],
        evidence_manifest_ref: str,
    ) -> StrategyVersionRecord:
        """Persist a recomputed, evidence-referenced candidate without activating it."""
        context = self._context(credential)
        if self._strategy_store is None:
            raise HostRuntimeError("no strategy store is configured")
        return self._strategy_store.register_candidate_for_principal(
            context.principal_id, strategy_class, strategy_id, version, config,
            evaluation, observations=observations,
            evidence_manifest_ref=evidence_manifest_ref,
        )

    def get_active_strategy(
        self, credential: Any, strategy_class: str,
    ) -> ActiveStrategyRecord | None:
        """Read only the authenticated principal's active strategy configuration."""
        context = self._context(credential)
        if self._strategy_store is None:
            raise HostRuntimeError("no strategy store is configured")
        return self._strategy_store.get_active_for_principal(
            context.principal_id, strategy_class,
        )

    def issue_strategy_activation_grant(
        self, credential: Any, request: StrategyApprovalRequest,
    ) -> StrategyActivationGrant:
        """Issue a one-use grant only through the configured host approval authority.

        This is a trusted host API. Do not register it as a model-visible tool.
        The authority re-authenticates the approver and applies host approval policy.
        """
        context = self._context(credential)
        if self._strategy_approval_authority is None:
            raise HostRuntimeError("trusted strategy approval authority is not configured")
        if type(request) is not StrategyApprovalRequest or request.principal_id != context.principal_id:
            raise HostRuntimeError("strategy approval request is unavailable to the authenticated principal")
        try:
            return self._strategy_approval_authority.issue_grant(credential, request)
        except Exception:
            raise HostRuntimeError("host strategy approval was denied") from None

    def activate_strategy(
        self, credential: Any, grant: StrategyActivationGrant,
    ) -> ActiveStrategyRecord:
        """Activate one registered version using a host-authenticated one-use grant."""
        context = self._context(credential)
        if self._strategy_store is None:
            raise HostRuntimeError("no strategy store is configured")
        return self._strategy_store.activate_for_principal(context.principal_id, grant)

    def rollback_strategy(
        self, credential: Any, grant: StrategyActivationGrant,
    ) -> ActiveStrategyRecord:
        """Restore a previously active version as a new approved history event."""
        context = self._context(credential)
        if self._strategy_store is None:
            raise HostRuntimeError("no strategy store is configured")
        return self._strategy_store.rollback_for_principal(context.principal_id, grant)

    def get_strategy_events(
        self, credential: Any, strategy_class: str,
    ) -> tuple[StrategyActivationEvent, ...]:
        """Return the authenticated principal's verified append-only strategy history."""
        context = self._context(credential)
        if self._strategy_store is None:
            raise HostRuntimeError("no strategy store is configured")
        return self._strategy_store.events_for_principal(
            context.principal_id, strategy_class,
        )

    def cancel_task(self, credential: Any, task_id: str) -> TaskRecord:
        """Cancel only a task owned by the authenticated principal."""
        context = self._context(credential)
        if self._task_store is None:
            raise HostRuntimeError("no task store is configured")
        return self._task_store.request_cancel_for_principal(
            task_id, context.principal_id
        )

    def create_goal(
        self, credential: Any, outcome: str, *,
        acceptance_criteria: list[str] | tuple[str, ...],
        constraints: dict[str, Any] | None = None,
        deadline: str | None = None,
        idempotency_key: str | None = None,
    ) -> GoalRecord:
        """Create a durable goal owned by the authenticated principal."""
        context = self._context(credential)
        if self._goal_store is None:
            raise HostRuntimeError("no goal store is configured")
        return self._goal_store.create_for_principal(
            context.principal_id, outcome, constraints=constraints,
            deadline=deadline, acceptance_criteria=acceptance_criteria,
            idempotency_key=idempotency_key,
        )

    def get_goal(self, credential: Any, goal_id: str) -> GoalRecord:
        """Read only a goal owned by the authenticated principal."""
        context = self._context(credential)
        if self._goal_store is None:
            raise HostRuntimeError("no goal store is configured")
        return self._goal_store.get_for_principal(goal_id, context.principal_id)

    def get_goal_report(self, credential: Any, goal_id: str) -> GoalReport:
        """Return a read-only owner-scoped summary without raw task results."""
        context = self._context(credential)
        if self._goal_store is None:
            raise HostRuntimeError("no goal store is configured")
        goal = self._goal_store.get_for_principal(goal_id, context.principal_id)
        task = None
        if goal.task_id is not None and self._task_store is not None:
            try:
                task = self._task_store.get_for_principal(goal.task_id, context.principal_id)
            except TaskNotFoundError:
                task = None
        return build_goal_report(goal, task)

    def save_goal_plan(
        self, credential: Any, goal_id: str, proposal: GoalPlanProposal, *,
        expected_version: int,
    ) -> GoalRecord:
        """Persist a validated data-only plan; this method never executes it."""
        context = self._context(credential)
        if self._goal_store is None:
            raise HostRuntimeError("no goal store is configured")
        if self._task_worker is None:
            raise HostRuntimeError("goal planning requires a configured principal task registry")
        return self._goal_store.save_plan_for_principal(
            goal_id, context.principal_id, proposal,
            frozenset(self._task_worker.engine.principal_handlers),
            expected_version=expected_version,
        )

    def _goal_coordinator(self) -> GoalCoordinator:
        if self._goal_store is None or self._task_store is None or self._task_worker is None:
            raise HostRuntimeError("goal coordination requires goal and principal task stores plus a task worker")
        return GoalCoordinator(
            self._goal_store,
            self._task_store,
            frozenset(self._task_worker.engine.principal_handlers),
        )

    def prepare_goal(
        self, credential: Any, goal_id: str, *, expected_version: int,
    ) -> GoalExecution:
        """Durably link a planned goal to a deferred task, then activate it."""
        context = self._context(credential)
        return self._goal_coordinator().prepare(
            goal_id, context.principal_id, expected_version=expected_version,
        )

    def reconcile_goal(self, credential: Any, goal_id: str) -> GoalExecution:
        """Reconcile a terminal task outcome and persist hashed step evidence."""
        context = self._context(credential)
        return self._goal_coordinator().reconcile(goal_id, context.principal_id)

    def verify_goal(
        self, credential: Any, goal_id: str, *, accepted: bool,
        evidence_reference: str, expected_version: int,
    ) -> GoalRecord:
        """Record the authenticated owner's explicit acceptance decision."""
        context = self._context(credential)
        return self._goal_coordinator().verify(
            goal_id, context.principal_id, accepted=accepted,
            evidence_reference=evidence_reference,
            expected_version=expected_version,
        )

    def cancel_goal(
        self, credential: Any, goal_id: str, *, expected_version: int,
    ) -> GoalExecution | GoalRecord:
        """Cancel a linked task safely, retaining uncertainty for reconciliation."""
        context = self._context(credential)
        return self._goal_coordinator().cancel(
            goal_id, context.principal_id, expected_version=expected_version,
        )

    def get_goal_events(self, credential: Any, goal_id: str) -> tuple[dict[str, Any], ...]:
        context = self._context(credential)
        if self._goal_store is None:
            raise HostRuntimeError("no goal store is configured")
        return self._goal_store.events_for_principal(goal_id, context.principal_id)

    def transition_goal(
        self, credential: Any, goal_id: str, new_state: str, *,
        expected_version: int,
    ) -> GoalRecord:
        """Apply an owner-scoped, compare-and-swap goal lifecycle transition."""
        context = self._context(credential)
        if self._goal_store is None:
            raise HostRuntimeError("no goal store is configured")
        if new_state in {"cancelled", "paused", "succeeded", "failed"}:
            current = self._goal_store.get_for_principal(goal_id, context.principal_id)
            if current.task_id is not None:
                raise HostRuntimeError("use cancel_goal or verify_goal; direct transitions bypass task coordination or acceptance evidence")
        return self._goal_store.transition_for_principal(
            goal_id, context.principal_id, new_state,
            expected_version=expected_version,
        )

    def run_turn(
        self,
        credential: Any,
        session_id: str,
        user_text: str,
    ) -> CommittedOrchestration:
        """Run and durably commit one turn after authenticating session ownership."""
        context = self._context(credential)
        if (
            not isinstance(user_text, str)
            or not user_text.strip()
            or len(user_text) > self._session_store.max_input_chars
            or contains_surrogate(user_text)
        ):
            raise HostRuntimeError("user_text is invalid or exceeds the host input limit")
        # Authenticate ownership before memory retrieval or model invocation. A
        # caller cannot use a foreign session ID to trigger scoped memory work.
        snapshot = self._session_store.get_for_principal(
            session_id, context.principal_id
        )
        if snapshot.closed:
            raise SessionClosedError("session is closed")
        memory_context = None
        if self._memory_context_resolver is not None:
            try:
                memory_context = self._memory_context_resolver(
                    context.principal_id, session_id, user_text
                )
            except Exception:
                raise HostRuntimeError("host memory retrieval failed") from None
            if memory_context is not None and type(memory_context) is not UntrustedMemoryContext:
                raise HostRuntimeError("host memory resolver returned an invalid context")
        knowledge_context = None
        if self._knowledge_context_resolver is not None:
            try:
                knowledge_context = self._knowledge_context_resolver(
                    context.principal_id, session_id, user_text
                )
            except Exception:
                raise HostRuntimeError("host knowledge-graph retrieval failed") from None
            if knowledge_context is not None and type(knowledge_context) is not UntrustedKnowledgeContext:
                raise HostRuntimeError("host knowledge resolver returned an invalid context")
        bound_store = PrincipalBoundSessionStore(
            self._session_store, context.principal_id
        )
        return self._coordinator.run_and_commit(
            self._orchestrator,
            bound_store,
            session_id,
            user_text,
            context,
            memory_context=memory_context,
            knowledge_context=knowledge_context,
        )

    @property
    def task_worker_configured(self) -> bool:
        """Whether this host has an explicitly configured task worker."""
        return self._task_worker is not None

    def storage_health(self) -> dict[str, str]:
        """Return redacted integrity states for configured durable stores."""
        stores = {
            "sessions": self._session_store,
            "tasks": self._task_store,
            "execution_evidence": self._execution_evidence_journal,
            "goals": self._goal_store,
            "budgets": self._budget_store,
        }
        health: dict[str, str] = {}
        for name, store in stores.items():
            if store is None:
                health[name] = "not_configured"
                continue
            try:
                result = store.integrity_check()
            except Exception:
                health[name] = "unavailable"
            else:
                health[name] = "healthy" if result == "ok" else "degraded"
        return health

    def run_task_worker(self, stop_event: Any) -> None:
        """Run the configured task worker until the host sets stop_event."""
        if self._task_worker is None:
            raise HostRuntimeError("no task worker is configured")
        try:
            self._task_worker.run_forever(stop_event)
        except Exception:
            raise HostRuntimeError("host task worker stopped after an execution failure") from None
