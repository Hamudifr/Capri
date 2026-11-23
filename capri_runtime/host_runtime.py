"""Request-scoped host composition with authenticated session ownership.

This module does not start a server or background threads. The embedding host
owns authentication callbacks, process supervision, credentials, and lifecycle.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from .memory import UntrustedMemoryContext
from .orchestration import (
    CommittedOrchestration,
    SessionTurnCoordinator,
    ToolOrchestrator,
)
from .runtime import Message, Session, SessionClosedError, SessionStore
from .sqlite_sessions import SQLiteSessionStore
from .tasks import SQLiteTaskStore, TaskRecord, TaskWorker
from .tools import ExecutionContext, HostAuthorityResolver


class HostRuntimeError(Exception):
    """A trusted host composition or memory-resolution operation failed."""


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

    All provider/model execution remains injected through ToolOrchestrator. The
    memory resolver is trusted host code and must enforce principal-scoped access.
    TaskWorker remains explicitly host-managed; run_task_worker() blocks until its
    stop event is set and should be run under an external process supervisor.
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
        task_worker: TaskWorker | None = None,
        task_store: SQLiteTaskStore | None = None,
        task_reconciliation_verifier: Callable[
            [str, str, str, str, str, dict[str, Any]], bool
        ] | None = None,
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
        if task_worker is not None and not isinstance(task_worker, TaskWorker):
            raise HostRuntimeError("task_worker must be a TaskWorker")
        if task_store is not None and not isinstance(task_store, SQLiteTaskStore):
            raise HostRuntimeError("task_store must be a SQLiteTaskStore")
        if task_reconciliation_verifier is not None and not callable(task_reconciliation_verifier):
            raise HostRuntimeError("task_reconciliation_verifier must be callable")
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
        self._task_worker = task_worker
        self._task_reconciliation_verifier = task_reconciliation_verifier
        self._task_store = (
            task_store if task_store is not None
            else (task_worker.engine.store if task_worker is not None else None)
        )

    def _context(self, credential: Any) -> ExecutionContext:
        return self._authority.resolve(credential)

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

    def reconcile_task(
        self,
        credential: Any,
        task_id: str,
        decision_id: str,
        outcome: str,
        evidence_ref: str,
        result: Any = None,
    ) -> TaskRecord:
        """Resolve an owned quarantined task through authenticated host policy.

        The caller cannot supply an actor identity. The evidence verifier is
        trusted host code and must verify that the referenced evidence supports
        this exact actor, task, decision, outcome, and checkpoint result.
        """
        context = self._context(credential)
        if "task.reconcile.owned" not in context.permissions:
            raise HostRuntimeError("task reconciliation permission is required")
        if self._task_store is None:
            raise HostRuntimeError("no task store is configured")
        if self._task_reconciliation_verifier is None:
            raise HostRuntimeError("no trusted task evidence verifier is configured")
        # Check immutable task ownership before invoking any host evidence
        # callback. The store repeats ownership/state checks transactionally
        # when it records the decision.
        current = self._task_store.get_for_principal(task_id, context.principal_id)
        if current.state != "reconciliation_required":
            raise HostRuntimeError("task does not require reconciliation")
        for value, limit, label in (
            (task_id, 64, "task_id"),
            (decision_id, 128, "decision_id"),
            (evidence_ref, 512, "evidence_ref"),
        ):
            if (type(value) is not str or not value or len(value) > limit
                    or any(0xD800 <= ord(character) <= 0xDFFF for character in value)):
                raise HostRuntimeError(f"task reconciliation {label} is invalid")
        if type(outcome) is not str or outcome not in {"succeeded", "failed", "unresolved"}:
            raise HostRuntimeError("unsupported task reconciliation outcome")
        if outcome != "succeeded" and result is not None:
            raise HostRuntimeError("only a succeeded reconciliation may include a result")
        try:
            payload = {
                "task_id": task_id,
                "decision_id": decision_id,
                "outcome": outcome,
                "evidence_ref": evidence_ref,
                "result": result,
            }
            encoded = json.dumps(
                payload, ensure_ascii=False, allow_nan=False, sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8", errors="strict")
            if len(encoded) > 65_536:
                raise ValueError("decision too large")
            snapshot = json.loads(encoded.decode("utf-8"))
        except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
            raise HostRuntimeError("task reconciliation decision is invalid") from None
        verifier_payload = json.loads(encoded.decode("utf-8"))
        try:
            verified = self._task_reconciliation_verifier(
                context.principal_id,
                task_id,
                decision_id,
                outcome,
                evidence_ref,
                verifier_payload,
            )
        except Exception:
            raise HostRuntimeError("task reconciliation evidence verification failed") from None
        if verified is not True:
            raise HostRuntimeError("task reconciliation evidence was not verified")
        return self._task_store.reconcile_for_principal(
            task_id,
            context.principal_id,
            decision_id,
            outcome,
            evidence_ref,
            result=snapshot["result"],
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
            or any(0xD800 <= ord(character) <= 0xDFFF for character in user_text)
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
        )

    def run_task_worker(self, stop_event: Any) -> None:
        """Run the configured task worker until the host sets stop_event."""
        if self._task_worker is None:
            raise HostRuntimeError("no task worker is configured")
        try:
            self._task_worker.run_forever(stop_event)
        except Exception:
            raise HostRuntimeError("host task worker stopped after an execution failure") from None
