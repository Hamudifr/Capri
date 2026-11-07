import os
import sqlite3
import stat
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from capri_runtime import (
    AssistantTurn,
    ExecutionContext,
    InMemoryAuditSink,
    SessionTurnCoordinator,
    ToolExecutionBridge,
    ToolExecutor,
    ToolOrchestrator,
    ToolOrchestrationError,
    ToolRegistry,
    Message,
    Runtime,
    SessionClosedError,
    SessionConflictError,
    SessionLimitError,
    SessionNotFoundError,
    SQLiteSessionStore,
    ValidationError,
)


class EchoAdapter:
    def complete(self, session_id, user_text, history):
        return f"echo: {user_text}"


class SQLiteSessionStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        if os.name == "posix":
            os.chmod(self.temp.name, 0o700)
        self.path = os.path.join(self.temp.name, "sessions.sqlite3")
        self.store = SQLiteSessionStore(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_principal_owned_sessions_persist_and_are_hidden_from_other_principals(self):
        session = self.store.create_for_principal("principal-alice")
        self.assertEqual(
            self.store.get_for_principal(session.session_id, "principal-alice"),
            session,
        )
        with self.assertRaises(SessionNotFoundError):
            self.store.get_for_principal(session.session_id, "principal-bob")
        reopened = SQLiteSessionStore(self.path)
        self.assertEqual(
            reopened.get_for_principal(session.session_id, "principal-alice"),
            session,
        )
        with self.assertRaises(SessionNotFoundError):
            reopened.get_for_principal(session.session_id, "principal-bob")

    def test_legacy_unowned_sessions_cannot_be_claimed_by_principal_lookup(self):
        session = self.store.create()
        with self.assertRaises(SessionNotFoundError):
            self.store.get_for_principal(session.session_id, "principal-alice")

    def test_principal_ownership_guards_commits_and_close(self):
        session = self.store.create_for_principal("principal-alice")
        turn = (
            Message(role="user", content="hello"),
            Message(role="assistant", content="hello back"),
        )
        with self.assertRaises(SessionNotFoundError):
            self.store.commit_turn_messages_for_principal(
                session.session_id, "principal-bob", 0, turn
            )
        self.assertEqual(self.store.get(session.session_id).version, 0)
        updated = self.store.commit_turn_messages_for_principal(
            session.session_id, "principal-alice", 0, turn
        )
        self.assertEqual(updated.version, 1)
        with self.assertRaises(SessionNotFoundError):
            self.store.close_for_principal(session.session_id, "principal-bob")
        closed = self.store.close_for_principal(session.session_id, "principal-alice")
        self.assertTrue(closed.closed)
        with self.assertRaises(SessionNotFoundError):
            self.store.get_for_principal(session.session_id, "principal-bob")

    def test_principal_ownership_guards_durable_turn_leases(self):
        session = self.store.create_for_principal("principal-alice")
        with self.assertRaises(SessionNotFoundError):
            self.store.claim_turn_lease_for_principal(
                session.session_id, "principal-bob", "worker-bob", 3
            )
        self.store.claim_turn_lease_for_principal(
            session.session_id, "principal-alice", "worker-alice", 3
        )
        with self.assertRaises(SessionNotFoundError):
            self.store.renew_turn_lease_for_principal(
                session.session_id, "principal-bob", "worker-alice", 3
            )
        self.assertTrue(self.store.release_turn_lease_for_principal(
            session.session_id, "principal-alice", "worker-alice"
        ))

    def test_session_owner_rows_cannot_be_reassigned_or_deleted(self):
        session = self.store.create_for_principal("principal-alice")
        connection = sqlite3.connect(self.path)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE session_owners SET principal_id = ? WHERE session_id = ?",
                    ("principal-bob", session.session_id),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "DELETE FROM session_owners WHERE session_id = ?",
                    (session.session_id,),
                )
        finally:
            connection.close()
        self.assertEqual(
            self.store.get_for_principal(session.session_id, "principal-alice"),
            session,
        )
        with self.assertRaises(SessionNotFoundError):
            self.store.get_for_principal(session.session_id, "principal-bob")

    def test_principal_id_validation_is_bounded(self):
        for principal_id in ("", "  ", "x" * 257, "bad\\ud800"):
            with self.subTest(principal_id=principal_id):
                with self.assertRaises(ValidationError):
                    self.store.create_for_principal(principal_id)

    def test_session_and_transcript_survive_store_reopen(self):
        session = self.store.create()
        updated = self.store.commit_turn(
            session.session_id, 0, "hello", "hello back"
        )
        reopened = SQLiteSessionStore(self.path)
        self.assertEqual(reopened.get(session.session_id), updated)
        self.assertEqual(updated.version, 1)
        self.assertEqual(
            updated.messages,
            (
                Message(role="user", content="hello"),
                Message(role="assistant", content="hello back"),
            ),
        )

    def test_complete_tool_transcript_turn_persists_and_reopens(self):
        session = self.store.create()
        turn = (
            Message(role="user", content="search for something"),
            Message(role="assistant", content='{"tool_calls":[{"id":"c1"}]}'),
            Message(role="tool", content='{"call_id":"c1","status":"succeeded"}'),
            Message(role="assistant", content="Here is the result."),
        )
        updated = self.store.commit_turn_messages(session.session_id, 0, turn)
        reopened = SQLiteSessionStore(self.path)
        self.assertEqual(reopened.get(session.session_id), updated)
        self.assertEqual(updated.version, 1)
        self.assertEqual(updated.messages, turn)

    def test_invalid_tool_transcript_rejected_before_commit(self):
        session = self.store.create()
        invalid_turns = (
            (Message(role="user", content="ask"), Message(role="tool", content="bad"), Message(role="assistant", content="done")),
            (Message(role="user", content="ask"), Message(role="assistant", content="call"), Message(role="tool", content="result")),
            (Message(role="assistant", content="missing user"),),
            (Message(role="user", content="one"), Message(role="user", content="two"), Message(role="assistant", content="done")),
        )
        for turn in invalid_turns:
            with self.subTest(turn=turn):
                with self.assertRaises(ValidationError):
                    self.store.commit_turn_messages(session.session_id, 0, turn)
        self.assertEqual(self.store.get(session.session_id).version, 0)
        self.assertEqual(self.store.get(session.session_id).messages, ())

    def test_tool_messages_have_separate_persisted_size_budget(self):
        path = os.path.join(self.temp.name, "tool-size.sqlite3")
        store = SQLiteSessionStore(
            path, max_input_chars=10, max_output_chars=10, max_tool_chars=100
        )
        session = store.create()
        turn = (
            Message(role="user", content="go"),
            Message(role="assistant", content="call"),
            Message(role="tool", content="x" * 50),
            Message(role="assistant", content="done"),
        )
        updated = store.commit_turn_messages(session.session_id, 0, turn)
        self.assertEqual(len(updated.messages[2].content), 50)
        reopened = SQLiteSessionStore(
            path, max_input_chars=10, max_output_chars=10, max_tool_chars=100
        )
        self.assertEqual(reopened.get(session.session_id), updated)
        too_small = SQLiteSessionStore(
            path, max_input_chars=10, max_output_chars=10, max_tool_chars=20
        )
        with self.assertRaises(ValidationError):
            too_small.get(session.session_id)

    def test_runtime_accepts_durable_store_and_recovers_history(self):
        runtime = Runtime(EchoAdapter(), self.store)
        session = runtime.create_session()
        updated = runtime.respond(session.session_id, "first")
        restarted_runtime = Runtime(EchoAdapter(), SQLiteSessionStore(self.path))
        second = restarted_runtime.respond(session.session_id, "second")
        self.assertEqual(second.version, 2)
        self.assertEqual(second.messages[:2], updated.messages)
        self.assertEqual(second.messages[-2:], (
            Message(role="user", content="second"),
            Message(role="assistant", content="echo: second"),
        ))

    def test_close_state_survives_reopen_and_is_idempotent(self):
        session = self.store.create()
        closed = self.store.close(session.session_id)
        reopened = SQLiteSessionStore(self.path)
        self.assertEqual(reopened.get(session.session_id), closed)
        self.assertEqual(reopened.close(session.session_id), closed)
        with self.assertRaises(SessionClosedError):
            reopened.commit_turn(session.session_id, 0, "hello", "answer")

    def test_optimistic_version_conflict_across_store_instances(self):
        session = self.store.create()
        other = SQLiteSessionStore(self.path)
        self.store.commit_turn(session.session_id, 0, "first", "answer")
        with self.assertRaises(SessionConflictError):
            other.commit_turn(session.session_id, 0, "stale", "answer")
        self.assertEqual(other.get(session.session_id).version, 1)

    def test_durable_turn_lease_is_exclusive_and_fences_commits(self):
        session = self.store.create()
        other = SQLiteSessionStore(self.path)
        owner_one = "worker-one"
        owner_two = "worker-two"
        self.store.claim_turn_lease(session.session_id, owner_one, 3)
        with self.assertRaises(SessionConflictError):
            other.claim_turn_lease(session.session_id, owner_two, 3)
        turn = (
            Message(role="user", content="go"),
            Message(role="assistant", content="done"),
        )
        with self.assertRaises(SessionConflictError):
            other.commit_turn_messages(
                session.session_id, 0, turn, lease_owner=owner_two
            )
        with self.assertRaises(SessionConflictError):
            other.commit_turn_messages(session.session_id, 0, turn)
        self.assertTrue(self.store.renew_turn_lease(session.session_id, owner_one, 3))
        self.assertTrue(self.store.release_turn_lease(session.session_id, owner_one))
        other.claim_turn_lease(session.session_id, owner_two, 3)
        committed = other.commit_turn_messages(
            session.session_id, 0, turn, lease_owner=owner_two
        )
        self.assertEqual(committed.version, 1)
        self.assertTrue(other.release_turn_lease(session.session_id, owner_two))

    def test_expired_lease_can_be_reclaimed_but_old_owner_is_fenced(self):
        session = self.store.create()
        self.store.claim_turn_lease(session.session_id, "old-owner", 3)
        connection = sqlite3.connect(self.path)
        try:
            connection.execute(
                "UPDATE session_turn_leases SET expires_at = ? WHERE session_id = ?",
                ("2000-01-01T00:00:00+00:00", session.session_id),
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(SessionConflictError):
            self.store.renew_turn_lease(session.session_id, "old-owner", 3)
        with self.assertRaises(SessionConflictError):
            self.store.claim_turn_lease(session.session_id, "old-owner", 3)
        self.store.claim_turn_lease(session.session_id, "new-owner", 3)
        turn = (
            Message(role="user", content="go"),
            Message(role="assistant", content="done"),
        )
        with self.assertRaises(SessionConflictError):
            self.store.commit_turn_messages(
                session.session_id, 0, turn, lease_owner="old-owner"
            )
        committed = self.store.commit_turn_messages(
            session.session_id, 0, turn, lease_owner="new-owner"
        )
        self.assertEqual(committed.version, 1)


    def test_expired_lease_cannot_release_or_commit_without_reclaim(self):
        session = self.store.create()
        self.store.claim_turn_lease(session.session_id, "stale-owner", 3)
        connection = sqlite3.connect(self.path)
        try:
            connection.execute(
                "UPDATE session_turn_leases SET expires_at = ? WHERE session_id = ?",
                ("2000-01-01T00:00:00+00:00", session.session_id),
            )
            connection.commit()
        finally:
            connection.close()

        self.assertFalse(self.store.release_turn_lease(session.session_id, "stale-owner"))
        turn = (
            Message(role="user", content="go"),
            Message(role="assistant", content="done"),
        )
        with self.assertRaises(SessionConflictError):
            self.store.commit_turn_messages(session.session_id, 0, turn)

        self.store.claim_turn_lease(session.session_id, "new-owner", 3)
        self.assertFalse(self.store.release_turn_lease(session.session_id, "stale-owner"))
        committed = self.store.commit_turn_messages(
            session.session_id, 0, turn, lease_owner="new-owner"
        )
        self.assertEqual(committed.version, 1)

    def test_lease_renewal_samples_time_after_acquiring_sqlite_write_lock(self):
        session = self.store.create()
        self.store.claim_turn_lease(session.session_id, "worker", 3)
        connection = sqlite3.connect(self.path)
        try:
            connection.execute(
                "UPDATE session_turn_leases SET expires_at = ? WHERE session_id = ?",
                ("2030-01-01T00:00:00+00:00", session.session_id),
            )
            connection.commit()
        finally:
            connection.close()

        before_expiry = datetime(2029, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
        after_expiry = datetime(2030, 1, 1, 0, 0, 1, tzinfo=timezone.utc)
        write_lock = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        write_lock.execute("BEGIN IMMEDIATE")
        connection_opened = threading.Event()
        clock_called = threading.Event()
        lock_released = threading.Event()
        outcomes = []
        original_connect = self.store._connect

        def tracked_connect():
            connection = original_connect()
            connection_opened.set()
            return connection

        self.store._connect = tracked_connect

        def fake_now():
            clock_called.set()
            return after_expiry if lock_released.is_set() else before_expiry

        def renew():
            try:
                outcomes.append(self.store.renew_turn_lease(session.session_id, "worker", 3))
            except Exception as exc:
                outcomes.append(exc)

        with patch.object(SQLiteSessionStore, "_lease_now", new=staticmethod(fake_now)):
            worker = threading.Thread(target=renew)
            worker.start()
            self.assertTrue(connection_opened.wait(timeout=1))
            self.assertFalse(clock_called.is_set())
            lock_released.set()
            write_lock.execute("ROLLBACK")
            worker.join(timeout=3)
        self.store._connect = original_connect

        write_lock.close()
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(outcomes), 1)
        self.assertIsInstance(outcomes[0], SessionConflictError)

    def test_lease_session_ids_are_bounded_and_valid_text(self):
        for invalid in ("x" * 257, "bad\ud800"):
            with self.subTest(session_id=repr(invalid)):
                with self.assertRaises(ValidationError):
                    self.store.claim_turn_lease(invalid, "owner", 3)
                with self.assertRaises(ValidationError):
                    self.store.renew_turn_lease(invalid, "owner", 3)
                with self.assertRaises(ValidationError):
                    self.store.release_turn_lease(invalid, "owner")

    def test_coordinator_renews_durable_lease_during_long_model_call(self):
        entered = threading.Event()
        release = threading.Event()

        class BlockingAdapter:
            def complete_with_tools(self, session_id, history, tools):
                entered.set()
                if not release.wait(timeout=6):
                    raise RuntimeError("test release timeout")
                return AssistantTurn(content="completed")

        registry = ToolRegistry()
        bridge = ToolExecutionBridge(ToolExecutor(registry, InMemoryAuditSink()))
        orchestrator = ToolOrchestrator(BlockingAdapter(), bridge)
        first_coordinator = SessionTurnCoordinator(lease_seconds=3)
        second_coordinator = SessionTurnCoordinator(lease_seconds=3)
        first_store = SQLiteSessionStore(self.path, max_output_chars=131_072)
        other_store = SQLiteSessionStore(self.path, max_output_chars=131_072)
        session = first_store.create()
        context = ExecutionContext("host-user", frozenset())
        outcome = []

        def first_turn():
            try:
                outcome.append(first_coordinator.run_and_commit(
                    orchestrator, first_store, session.session_id, "first", context
                ))
            except Exception as exc:
                outcome.append(exc)

        worker = threading.Thread(target=first_turn)
        worker.start()
        self.assertTrue(entered.wait(timeout=2))
        time.sleep(3.2)
        with self.assertRaises(ToolOrchestrationError):
            second_coordinator.run_and_commit(
                ToolOrchestrator(
                    type("FinalAdapter", (), {
                        "complete_with_tools": lambda self, *args: AssistantTurn(content="second")
                    })(),
                    bridge,
                ),
                other_store,
                session.session_id,
                "second",
                context,
            )
        release.set()
        worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(outcome), 1)
        self.assertFalse(isinstance(outcome[0], Exception), repr(outcome[0]))
        self.assertEqual(other_store.get(session.session_id).version, 1)

    def test_missing_session_raises_expected_error(self):
        with self.assertRaises(SessionNotFoundError):
            self.store.get("missing-session")

    def test_message_and_input_limits_apply_to_direct_commits(self):
        limited = SQLiteSessionStore(
            self.path,
            max_session_messages=2,
            max_input_chars=3,
            max_output_chars=4,
        )
        session = limited.create()
        with self.assertRaises(SessionLimitError):
            limited.commit_turn(session.session_id, 0, "four", "ok")
        with self.assertRaises(SessionLimitError):
            limited.commit_turn(session.session_id, 0, "ok", "12345")
        limited.commit_turn(session.session_id, 0, "ok", "fine")
        with self.assertRaises(SessionLimitError):
            limited.commit_turn(session.session_id, 1, "x", "y")

    def test_rejects_symlink_database_path(self):
        target = os.path.join(self.temp.name, "target.sqlite3")
        with open(target, "wb") as handle:
            handle.write(b"")
        link = os.path.join(self.temp.name, "link.sqlite3")
        os.symlink(target, link)
        with self.assertRaises(ValidationError):
            SQLiteSessionStore(link)

    def test_rejects_missing_or_non_private_parent(self):
        missing = os.path.join(self.temp.name, "missing", "db.sqlite3")
        with self.assertRaises(ValidationError):
            SQLiteSessionStore(missing)
        if os.name == "posix":
            public = os.path.join(self.temp.name, "public")
            os.mkdir(public, 0o755)
            os.chmod(public, 0o755)
            with self.assertRaises(ValidationError):
                SQLiteSessionStore(os.path.join(public, "db.sqlite3"))

    def test_rechecks_database_permissions_on_each_connection(self):
        session = self.store.create()
        if os.name == "posix":
            os.chmod(self.path, 0o644)
            with self.assertRaises(ValidationError):
                self.store.get(session.session_id)

    def test_corrupt_persisted_transcript_fails_closed(self):
        session = self.store.create()
        connection = sqlite3.connect(self.path)
        try:
            connection.execute(
                "UPDATE sessions SET messages_json = ? WHERE session_id = ?",
                ('[{"role": 7, "content": "bad"}]', session.session_id),
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(ValidationError):
            self.store.get(session.session_id)

    def test_corrupt_version_or_role_sequence_fails_closed(self):
        session = self.store.create()
        connection = sqlite3.connect(self.path)
        try:
            connection.execute(
                "UPDATE sessions SET version = 1 WHERE session_id = ?",
                (session.session_id,),
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(ValidationError):
            self.store.get(session.session_id)

    def test_database_file_is_private_on_posix(self):
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
