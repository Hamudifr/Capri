import threading
import unittest

from capri_runtime import (
    Message,
    Runtime,
    RuntimeExecutionError,
    SessionClosedError,
    SessionConflictError,
    SessionNotFoundError,
    SessionLimitError,
    SessionStore,
    ValidationError,
)


class EchoAdapter:
    def complete(self, session_id, user_text, history):
        return f"echo: {user_text}"


class FailingAdapter:
    def complete(self, session_id, user_text, history):
        raise OSError("provider detail must not leak")


class EmptyAdapter:
    def complete(self, session_id, user_text, history):
        return "  "


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime(EchoAdapter())

    def test_create_session_has_unique_id_and_empty_history(self):
        first = self.runtime.create_session()
        second = self.runtime.create_session()
        self.assertNotEqual(first.session_id, second.session_id)
        self.assertEqual(first.messages, ())
        self.assertEqual(first.version, 0)
        self.assertFalse(first.closed)

    def test_respond_commits_user_and_assistant_messages(self):
        session = self.runtime.create_session()
        updated = self.runtime.respond(session.session_id, "hello")
        self.assertEqual(updated.version, 1)
        self.assertEqual(
            updated.messages,
            (
                Message(role="user", content="hello"),
                Message(role="assistant", content="echo: hello"),
            ),
        )

    def test_history_is_passed_as_immutable_snapshot(self):
        class InspectingAdapter:
            def complete(inner, session_id, user_text, history):
                self.assertEqual(len(history), 2)
                self.assertEqual(history[0].role, "user")
                return "second answer"

        session = self.runtime.create_session()
        self.runtime.respond(session.session_id, "first")
        result = Runtime(InspectingAdapter(), self.runtime.store).respond(
            session.session_id, "second"
        )
        self.assertEqual(result.version, 2)

    def test_blank_and_non_string_input_rejected(self):
        session = self.runtime.create_session()
        for value in (" ", "", None, 42):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    self.runtime.respond(session.session_id, value)

    def test_oversized_input_rejected_before_adapter(self):
        class NeverCall:
            def complete(self, *args):
                raise AssertionError("adapter must not be called")

        runtime = Runtime(NeverCall(), max_input_chars=3)
        session = runtime.create_session()
        with self.assertRaises(ValidationError):
            runtime.respond(session.session_id, "four")

    def test_lone_surrogate_input_rejected_before_adapter(self):
        class NeverCall:
            def complete(self, *args):
                raise AssertionError("adapter must not be called")

        runtime = Runtime(NeverCall())
        session = runtime.create_session()
        with self.assertRaises(ValidationError):
            runtime.respond(session.session_id, "bad-\ud800")
        self.assertEqual(runtime.get_session(session.session_id).messages, ())

    def test_lone_surrogate_adapter_output_rejected_without_commit(self):
        class InvalidUnicodeAdapter:
            def complete(self, *args):
                return "bad-\ud800"

        runtime = Runtime(InvalidUnicodeAdapter())
        session = runtime.create_session()
        with self.assertRaises(ValidationError):
            runtime.respond(session.session_id, "hello")
        unchanged = runtime.get_session(session.session_id)
        self.assertEqual(unchanged.version, 0)
        self.assertEqual(unchanged.messages, ())

    def test_direct_store_commit_rejects_lone_surrogates(self):
        session = self.runtime.create_session()
        for user_text, assistant_text in (
            ("bad-\ud800", "answer"),
            ("user", "bad-\ud800"),
        ):
            with self.subTest(user_text=user_text, assistant_text=assistant_text):
                with self.assertRaises(ValidationError):
                    self.runtime.store.commit_turn(
                        session.session_id, 0, user_text, assistant_text
                    )
        self.assertEqual(self.runtime.get_session(session.session_id).messages, ())

    def test_missing_session_rejected(self):
        with self.assertRaises(SessionNotFoundError):
            self.runtime.respond("not-a-session", "hello")

    def test_closed_session_rejects_turn(self):
        session = self.runtime.create_session()
        closed = self.runtime.close_session(session.session_id)
        self.assertTrue(closed.closed)
        with self.assertRaises(SessionClosedError):
            self.runtime.respond(session.session_id, "hello")

    def test_close_is_idempotent(self):
        session = self.runtime.create_session()
        first = self.runtime.close_session(session.session_id)
        second = self.runtime.close_session(session.session_id)
        self.assertEqual(first, second)

    def test_adapter_failure_does_not_commit_partial_turn(self):
        runtime = Runtime(FailingAdapter())
        session = runtime.create_session()
        with self.assertRaises(RuntimeExecutionError) as caught:
            runtime.respond(session.session_id, "hello")
        self.assertNotIn("provider detail", str(caught.exception))
        unchanged = runtime.get_session(session.session_id)
        self.assertEqual(unchanged.version, 0)
        self.assertEqual(unchanged.messages, ())

    def test_empty_adapter_output_rejected_without_commit(self):
        runtime = Runtime(EmptyAdapter())
        session = runtime.create_session()
        with self.assertRaises(ValidationError):
            runtime.respond(session.session_id, "hello")
        self.assertEqual(runtime.get_session(session.session_id).messages, ())

    def test_concurrent_turns_cannot_overwrite_each_other(self):
        entered = threading.Event()
        release = threading.Event()

        class BlockingAdapter:
            def complete(self, session_id, user_text, history):
                entered.set()
                release.wait(timeout=2)
                return f"answer: {user_text}"

        runtime = Runtime(BlockingAdapter())
        session = runtime.create_session()
        outcome = []

        def run_turn():
            try:
                outcome.append(runtime.respond(session.session_id, "first"))
            except Exception as exc:
                outcome.append(exc)

        worker = threading.Thread(target=run_turn)
        worker.start()
        self.assertTrue(entered.wait(timeout=2))
        runtime.store.commit_turn(
            session.session_id,
            expected_version=0,
            user_text="external",
            assistant_text="external answer",
        )
        release.set()
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(outcome), 1)
        self.assertIsInstance(outcome[0], SessionConflictError)
        self.assertEqual(runtime.get_session(session.session_id).version, 1)

    def test_invalid_store_and_input_limit_configuration_rejected(self):
        with self.assertRaises(ValidationError):
            Runtime(EchoAdapter(), max_input_chars=0)
        with self.assertRaises(ValidationError):
            Runtime(EchoAdapter(), max_input_chars=True)


    def test_output_limit_rejects_without_committing_turn(self):
        class LargeAdapter:
            def complete(self, session_id, user_text, history):
                return "12345"

        runtime = Runtime(LargeAdapter(), max_output_chars=4)
        session = runtime.create_session()
        with self.assertRaises(SessionLimitError):
            runtime.respond(session.session_id, "hello")
        unchanged = runtime.get_session(session.session_id)
        self.assertEqual(unchanged.version, 0)
        self.assertEqual(unchanged.messages, ())

    def test_session_message_limit_rejects_before_adapter(self):
        class NeverCall:
            def complete(self, *args):
                raise AssertionError("adapter must not be called")

        runtime = Runtime(NeverCall(), max_session_messages=2)
        session = runtime.create_session()
        runtime.store.commit_turn(session.session_id, 0, "first", "answer")
        with self.assertRaises(SessionLimitError):
            runtime.respond(session.session_id, "second")
        self.assertEqual(runtime.get_session(session.session_id).version, 1)

    def test_direct_commit_rejects_invalid_version_and_empty_messages(self):
        session = self.runtime.create_session()
        invalid_calls = (
            (True, "user", "assistant"),
            (-1, "user", "assistant"),
            (0, " ", "assistant"),
            (0, "user", ""),
        )
        for version, user_text, assistant_text in invalid_calls:
            with self.subTest(version=version, user_text=user_text):
                with self.assertRaises(ValidationError):
                    self.runtime.store.commit_turn(
                        session.session_id, version, user_text, assistant_text
                    )
        self.assertEqual(self.runtime.get_session(session.session_id).version, 0)

    def test_close_during_generation_prevents_turn_commit(self):
        entered = threading.Event()
        release = threading.Event()

        class BlockingAdapter:
            def complete(self, session_id, user_text, history):
                entered.set()
                release.wait(timeout=2)
                return "late answer"

        runtime = Runtime(BlockingAdapter())
        session = runtime.create_session()
        outcome = []

        def run_turn():
            try:
                outcome.append(runtime.respond(session.session_id, "hello"))
            except Exception as exc:
                outcome.append(exc)

        worker = threading.Thread(target=run_turn)
        worker.start()
        self.assertTrue(entered.wait(timeout=2))
        runtime.close_session(session.session_id)
        release.set()
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(outcome), 1)
        self.assertIsInstance(outcome[0], SessionClosedError)
        closed = runtime.get_session(session.session_id)
        self.assertTrue(closed.closed)
        self.assertEqual(closed.messages, ())

    def test_session_store_preserves_positional_history_limit_argument(self):
        store = SessionStore(2)
        self.assertEqual(store.max_session_messages, 2)
        self.assertEqual(store.max_input_chars, 16_000)
        self.assertEqual(store.max_output_chars, 64_000)

    def test_session_store_enforces_history_limit_for_direct_commits(self):
        store = SessionStore(max_session_messages=2)
        session = store.create()
        store.commit_turn(session.session_id, 0, "first", "answer")
        with self.assertRaises(SessionLimitError):
            store.commit_turn(session.session_id, 1, "second", "answer")
        unchanged = store.get(session.session_id)
        self.assertEqual(unchanged.version, 1)
        self.assertEqual(len(unchanged.messages), 2)

    def test_runtime_rejects_store_with_mismatched_resource_limits(self):
        stores = (
            SessionStore(max_input_chars=10),
            SessionStore(max_output_chars=10),
            SessionStore(max_session_messages=10),
        )
        for store, kwargs in (
            (stores[0], {"max_input_chars": 20}),
            (stores[1], {"max_output_chars": 20}),
            (stores[2], {"max_session_messages": 20}),
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValidationError):
                    Runtime(EchoAdapter(), store, **kwargs)

    def test_direct_store_commit_enforces_input_and_output_character_limits(self):
        store = SessionStore(
            max_input_chars=3,
            max_output_chars=4,
            max_session_messages=4,
        )
        session = store.create()
        with self.assertRaises(SessionLimitError):
            store.commit_turn(session.session_id, 0, "four", "ok")
        with self.assertRaises(SessionLimitError):
            store.commit_turn(session.session_id, 0, "ok", "12345")
        unchanged = store.get(session.session_id)
        self.assertEqual(unchanged.version, 0)
        self.assertEqual(unchanged.messages, ())

    def test_session_store_rejects_invalid_message_limits(self):
        for kwargs in (
            {"max_input_chars": True},
            {"max_input_chars": 0},
            {"max_output_chars": False},
            {"max_output_chars": -1},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValidationError):
                    SessionStore(**kwargs)

    def test_session_store_rejects_invalid_history_limit(self):
        for value in (True, 1, 0, -1, 2.5):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    SessionStore(max_session_messages=value)

    def test_all_resource_limits_reject_boolean_values(self):
        for kwargs in (
            {"max_input_chars": True},
            {"max_output_chars": True},
            {"max_session_messages": True},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValidationError):
                    Runtime(EchoAdapter(), **kwargs)


if __name__ == "__main__":
    unittest.main()
