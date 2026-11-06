import os
import sqlite3
import stat
import tempfile
import unittest

from capri_runtime import (
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
