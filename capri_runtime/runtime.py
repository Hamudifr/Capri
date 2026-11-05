"""Provider-neutral in-memory session runtime.

No provider SDK, network access, tool execution, or durable memory is included.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from threading import RLock
from typing import Protocol
from uuid import uuid4


def _contains_surrogate(value: str) -> bool:
    """Return True for lone UTF-16 surrogate code points."""
    return any(0xD800 <= ord(character) <= 0xDFFF for character in value)


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


class SessionLimitError(RuntimeErrorBase):
    """A configured session resource limit has been reached."""


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

    def __init__(self, max_session_messages: int = 200) -> None:
        if (
            isinstance(max_session_messages, bool)
            or not isinstance(max_session_messages, int)
            or max_session_messages < 2
        ):
            raise ValidationError(
                "max_session_messages must be an integer of at least 2"
            )
        self.max_session_messages = max_session_messages
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
        if isinstance(expected_version, bool) or not isinstance(expected_version, int):
            raise ValidationError("expected_version must be a non-negative integer")
        if expected_version < 0:
            raise ValidationError("expected_version must be a non-negative integer")
        if not isinstance(user_text, str) or not user_text.strip():
            raise ValidationError("user_text must be a non-empty string")
        if not isinstance(assistant_text, str) or not assistant_text.strip():
            raise ValidationError("assistant_text must be a non-empty string")
        if _contains_surrogate(user_text) or _contains_surrogate(assistant_text):
            raise ValidationError("messages must contain valid Unicode scalar values")

        with self._lock:
            current = self.get(session_id)
            if current.closed:
                raise SessionClosedError("session is closed")
            if current.version != expected_version:
                raise SessionConflictError("session changed during model execution")
            if len(current.messages) + 2 > self.max_session_messages:
                raise SessionLimitError("session message limit reached")
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
        max_output_chars: int = 64_000,
        max_session_messages: int = 200,
    ) -> None:
        if not callable(getattr(adapter, "complete", None)):
            raise ValidationError("adapter must implement complete()")
        limits = {
            "max_input_chars": max_input_chars,
            "max_output_chars": max_output_chars,
            "max_session_messages": max_session_messages,
        }
        for name, value in limits.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValidationError(f"{name} must be a positive integer")
        if max_session_messages < 2:
            raise ValidationError("max_session_messages must allow at least one turn")
        if store is not None and not isinstance(store, SessionStore):
            raise ValidationError("store must be a SessionStore instance")
        if store is not None and store.max_session_messages != max_session_messages:
            raise ValidationError(
                "store max_session_messages must match runtime configuration"
            )
        self.adapter = adapter
        self.store = store if store is not None else SessionStore(
            max_session_messages=max_session_messages
        )
        self.max_input_chars = max_input_chars
        self.max_output_chars = max_output_chars
        self.max_session_messages = max_session_messages

    def create_session(self) -> Session:
        return self.store.create()

    def get_session(self, session_id: str) -> Session:
        return self.store.get(session_id)

    def close_session(self, session_id: str) -> Session:
        return self.store.close(session_id)

    def respond(self, session_id: str, user_text: str) -> Session:
        if not isinstance(user_text, str) or not user_text.strip():
            raise ValidationError("user_text must be a non-empty string")
        if _contains_surrogate(user_text):
            raise ValidationError("user_text must contain valid Unicode scalar values")
        if len(user_text) > self.max_input_chars:
            raise ValidationError("user_text exceeds max_input_chars")

        session = self.store.get(session_id)
        if session.closed:
            raise SessionClosedError("session is closed")
        if len(session.messages) + 2 > self.max_session_messages:
            raise SessionLimitError("session message limit reached")

        try:
            answer = self.adapter.complete(
                session_id,
                user_text,
                session.messages,
            )
        except Exception:
            # Provider exception text can contain secrets or personal data.
            raise RuntimeExecutionError("model adapter failed") from None

        if not isinstance(answer, str) or not answer.strip():
            raise ValidationError("adapter must return non-empty assistant text")
        if _contains_surrogate(answer):
            raise ValidationError("adapter output must contain valid Unicode scalar values")
        if len(answer) > self.max_output_chars:
            raise SessionLimitError("adapter output exceeds max_output_chars")

        return self.store.commit_turn(
            session_id=session_id,
            expected_version=session.version,
            user_text=user_text,
            assistant_text=answer,
        )
