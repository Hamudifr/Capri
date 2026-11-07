"""Request-scoped host composition with authenticated session ownership.

This module does not start a server or background threads. The embedding host
owns authentication callbacks, process supervision, credentials, and lifecycle.
"""
from __future__ import annotations

from typing import Any, Callable

from .memory import UntrustedMemoryContext
from .orchestration import (
    CommittedOrchestration,
    SessionTurnCoordinator,
    ToolOrchestrator,
)
from .runtime import Message, Session, SessionClosedError, SessionStore
from .sqlite_sessions import SQLiteSessionStore
from .tasks import TaskWorker
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
        self._authority = authority
        self._session_store = session_store
        self._orchestrator = orchestrator
        self._coordinator = coordinator
        self._memory_context_resolver = memory_context_resolver
        self._task_worker = task_worker

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
