"""Request-scoped host composition with authenticated session ownership.

This module does not start a server or background threads. The embedding host
owns authentication callbacks, process supervision, credentials, and lifecycle.
"""
from __future__ import annotations

from typing import Any, Callable

from capri_core.validation import contains_surrogate

from .memory import UntrustedMemoryContext
from .knowledge_graph import UntrustedKnowledgeContext
from .orchestration import (
    CommittedOrchestration,
    SessionTurnCoordinator,
    ToolOrchestrator,
)
from .runtime import Message, Session, SessionClosedError, SessionStore
from .sqlite_sessions import SQLiteSessionStore
from .tasks import SQLiteTaskStore, TaskRecord, TaskWorker
from .goals import (
    GoalPlanProposal, GoalRecord, SQLiteGoalStore,
)
from .goal_coordinator import GoalCoordinator, GoalExecution
from .budgets import BudgetUsage, SQLiteBudgetStore
from .tools import ExecutionContext, HostAuthorityResolver


class HostRuntimeError(Exception):
    """A trusted host composition or retrieved-context resolution operation failed."""


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
    principal-scoped access. TaskWorker remains explicitly host-managed;
    run_task_worker() blocks until its stop event is set and should be run under
    an external process supervisor.
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
        self._goal_store = goal_store
        configured_budgets = [
            item for item in (
                budget_store, orchestrator.budget_store,
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

    def run_task_worker(self, stop_event: Any) -> None:
        """Run the configured task worker until the host sets stop_event."""
        if self._task_worker is None:
            raise HostRuntimeError("no task worker is configured")
        try:
            self._task_worker.run_forever(stop_event)
        except Exception:
            raise HostRuntimeError("host task worker stopped after an execution failure") from None
