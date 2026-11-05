"""Provider-neutral in-memory session runtime.

No provider SDK, network access, tool execution, or durable memory is included.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from threading import RLock
from typing import Protocol
from uuid import uuid4


class RuntimeErrorBase(Exception):
    """Base class for expected runtime failures."""


class ValidationError(RuntimeErrorBase):
    """Input or adapter output did not satisfy the runtime contract."""


class SessionNotFoundError(RuntimeErrorBase):
    """The requested session does not exist in this store."""


class SessionClosedError(RuntimeErrorBase):
    """A closed session cannot accept new turns."""


class SessionConflictError(RuntimeErrorBase):
    """The session changed while a model response was being generated."""


class RuntimeExecutionError(RuntimeErrorBase):
    """The injected model adapter failed."""


@dataclass(frozen=True, slots=True)
class Message:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class Session:
    session_id: str
    created_at: str
    updated_at: str
    version: int = 0
    closed: bool = False
    messages: tuple[Message, ...] = ()


class ModelAdapter(Protocol):
    """Host-supplied model adapter; implementation owns provider credentials."""

    def complete(
        self,
        session_id: str,
        user_text: str,
        history: tuple[Message, ...],
    ) -> str:
        """Return assistant text for the request and immutable prior history."""
        ...


class SessionStore:
    """Thread-safe, process-local session store with optimistic turn commits."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = RLock()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def create(self) -> Session:
        now = self._now()
        session = Session(
            session_id=str(uuid4()),
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> Session:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValidationError("session_id must be a non-empty string")
        with self._lock:
            try:
                return self._sessions[session_id]
            except KeyError as exc:
                raise SessionNotFoundError("session does not exist") from exc

    def close(self, session_id: str) -> Session:
        with self._lock:
            current = self.get(session_id)
            if current.closed:
                return current
            closed = replace(current, closed=True, updated_at=self._now())
            self._sessions[session_id] = closed
            return closed

    def commit_turn(
        self,
        session_id: str,
        expected_version: int,
        user_text: str,
        assistant_text: str,
    ) -> Session:
        with self._lock:
            current = self.get(session_id)
            if current.closed:
                raise SessionClosedError("session is closed")
            if current.version != expected_version:
                raise SessionConflictError("session changed during model execution")
            updated = replace(
                current,
                updated_at=self._now(),
                version=current.version + 1,
                messages=current.messages + (
                    Message(role="user", content=user_text),
                    Message(role="assistant", content=assistant_text),
                ),
            )
            self._sessions[session_id] = updated
            return updated


class Runtime:
    """Small synchronous runtime that delegates text generation to a host adapter."""

    def __init__(
        self,
        adapter: ModelAdapter,
        store: SessionStore | None = None,
        max_input_chars: int = 16_000,
    ) -> None:
        if not callable(getattr(adapter, "complete", None)):
            raise ValidationError("adapter must implement complete()")
        if isinstance(max_input_chars, bool) or not isinstance(max_input_chars, int):
            raise ValidationError("max_input_chars must be an integer")
        if max_input_chars < 1:
            raise ValidationError("max_input_chars must be positive")
        self.adapter = adapter
        self.store = store if store is not None else SessionStore()
        self.max_input_chars = max_input_chars

    def create_session(self) -> Session:
        return self.store.create()

    def get_session(self, session_id: str) -> Session:
        return self.store.get(session_id)

    def close_session(self, session_id: str) -> Session:
        return self.store.close(session_id)

    def respond(self, session_id: str, user_text: str) -> Session:
        if not isinstance(user_text, str) or not user_text.strip():
            raise ValidationError("user_text must be a non-empty string")
        if len(user_text) > self.max_input_chars:
            raise ValidationError("user_text exceeds max_input_chars")

        session = self.store.get(session_id)
        if session.closed:
            raise SessionClosedError("session is closed")

        try:
            answer = self.adapter.complete(
                session_id,
                user_text,
                session.messages,
            )
        except Exception as exc:
            raise RuntimeExecutionError("model adapter failed") from exc

        if not isinstance(answer, str) or not answer.strip():
            raise ValidationError("adapter must return non-empty assistant text")

        return self.store.commit_turn(
            session_id=session_id,
            expected_version=session.version,
            user_text=user_text,
            assistant_text=answer,
        )
