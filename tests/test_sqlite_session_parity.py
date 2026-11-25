import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from capri_runtime.runtime import ValidationError

from capri_runtime import (
    Message,
    SessionConflictError,
    SessionNotFoundError,
    SQLiteSessionStore,
)


ROOT = Path(__file__).resolve().parents[1]
PARITY_BIN = ROOT / "c" / "build" / "session_store_parity"
TURN_ONE = (
    Message(role="user", content="Parity check: café ☕"),
    Message(role="assistant", content="Committed by the first runtime."),
)
TURN_TWO = (
    Message(role="user", content="Second turn"),
    Message(role="assistant", content="Committed by the other runtime."),
)

TOOL_TURN = (
    Message(role="user", content="Inspect this Unicode payload: 🧪"),
    Message(role="assistant", content="I will inspect the payload."),
    Message(role="tool", content="Tool result: café ☕ and 🧬"),
    Message(role="assistant", content="The tool exchange was preserved."),
)


def encode_turn(messages):
    return json.dumps(
        [{"role": item.role, "content": item.content} for item in messages],
        ensure_ascii=False,
        separators=(",", ":"),
    )


class NativeSQLiteSessionParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run(
            ["make", "-C", str(ROOT / "c"), "build/session_store_parity"],
            check=True,
            capture_output=True,
            text=True,
        )

    def invoke(self, *arguments):
        result = subprocess.run(
            [str(PARITY_BIN), *map(str, arguments)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            self.fail(
                f"native parity command {arguments[0]!r} failed "
                f"({result.returncode}): {result.stderr.strip()}"
            )
        fields = result.stdout.splitlines()
        self.assertEqual(len(fields), 4, result.stdout)
        return {
            "session_id": fields[0],
            "version": int(fields[1]),
            "closed": fields[2] == "1",
            "messages": json.loads(fields[3]),
        }

    def invoke_error(self, expected_error, *arguments):
        result = subprocess.run(
            [str(PARITY_BIN), *map(str, arguments)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 20 + expected_error, result.stderr)

    def test_native_created_principal_session_is_python_readable_and_conflict_fenced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "sessions.sqlite3")
            native = self.invoke("create-principal", path, "principal-alice", encode_turn(TURN_ONE))
            python_store = SQLiteSessionStore(path)
            recovered = python_store.get_for_principal(native["session_id"], "principal-alice")
            self.assertEqual(recovered.version, native["version"])
            self.assertFalse(recovered.closed)
            self.assertEqual(recovered.messages, TURN_ONE)
            self.assertEqual(native["messages"], [
                {"role": item.role, "content": item.content} for item in TURN_ONE
            ])

            with self.assertRaises(SessionConflictError):
                python_store.commit_turn_messages(native["session_id"], 0, TURN_TWO)
            self.invoke_error(
                6, "commit-principal", path, native["session_id"],
                "principal-alice", "0", encode_turn(TURN_TWO),
            )
            self.assertEqual(python_store.get_for_principal(
                native["session_id"], "principal-alice"
            ).version, 1)

            closed = python_store.close_for_principal(native["session_id"], "principal-alice")
            native_closed = self.invoke(
                "read-principal", path, native["session_id"], "principal-alice"
            )
            self.assertTrue(closed.closed)
            self.assertTrue(native_closed["closed"])
            self.assertEqual(native_closed["version"], closed.version)

    def test_python_created_principal_session_is_native_readable_and_writable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "sessions.sqlite3")
            python_store = SQLiteSessionStore(path)
            created = python_store.create_for_principal("principal-bob")
            python_state = python_store.commit_turn_messages(
                created.session_id, 0, TURN_ONE
            )
            native = self.invoke(
                "read-principal", path, created.session_id, "principal-bob"
            )
            self.assertEqual(native["version"], python_state.version)
            self.assertFalse(native["closed"])
            self.assertEqual(native["messages"], [
                {"role": item.role, "content": item.content} for item in TURN_ONE
            ])

            native_state = self.invoke(
                "commit-principal", path, created.session_id, "principal-bob",
                "1", encode_turn(TURN_TWO),
            )
            recovered = python_store.get_for_principal(
                created.session_id, "principal-bob"
            )
            self.assertEqual(native_state["version"], 2)
            self.assertEqual(recovered.version, 2)
            self.assertEqual(recovered.messages, TURN_ONE + TURN_TWO)

    def test_legacy_unowned_session_compatibility_is_cross_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "sessions.sqlite3")
            native = self.invoke("create-legacy", path, encode_turn(TURN_ONE))
            python_store = SQLiteSessionStore(path)
            recovered = python_store.get(native["session_id"])
            self.assertEqual(recovered.version, 1)
            self.assertEqual(recovered.messages, TURN_ONE)
            with self.assertRaises(SessionNotFoundError):
                python_store.get_for_principal(native["session_id"], "principal-alice")

            python_state = python_store.commit_turn_messages(
                native["session_id"], 1, TURN_TWO
            )
            native_state = self.invoke("read-legacy", path, native["session_id"])
            self.assertEqual(native_state["version"], python_state.version)
            self.assertEqual(native_state["messages"], [
                {"role": item.role, "content": item.content}
                for item in TURN_ONE + TURN_TWO
            ])

            closed = python_store.close(native["session_id"])
            native_closed = self.invoke("read-legacy", path, native["session_id"])
            self.assertTrue(closed.closed)
            self.assertTrue(native_closed["closed"])
            self.invoke_error(
                4, "read-principal", path, native["session_id"], "principal-alice"
            )

    def test_native_legacy_session_can_be_closed_by_python_and_python_session_by_native(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "sessions.sqlite3")
            python_store = SQLiteSessionStore(path)
            created = python_store.create()
            python_store.commit_turn_messages(created.session_id, 0, TURN_ONE)
            native_closed = self.invoke("close-legacy", path, created.session_id)
            self.assertTrue(native_closed["closed"])
            self.assertTrue(python_store.get(created.session_id).closed)

            second_path = str(Path(directory) / "native.sqlite3")
            native = self.invoke("create-legacy", second_path, encode_turn(TURN_ONE))
            python_state = SQLiteSessionStore(second_path)
            self.assertEqual(python_state.get(native["session_id"]).version, 1)
            closed = self.invoke("close-legacy", second_path, native["session_id"])
            self.assertTrue(closed["closed"])
            self.assertTrue(python_state.get(native["session_id"]).closed)

    def test_tool_exchange_and_unicode_transcript_are_cross_runtime_compatible(self):
        with tempfile.TemporaryDirectory() as directory:
            native_path = str(Path(directory) / "native.sqlite3")
            native = self.invoke(
                "create-principal", native_path, "principal-tool", encode_turn(TOOL_TURN)
            )
            python_store = SQLiteSessionStore(native_path)
            recovered = python_store.get_for_principal(
                native["session_id"], "principal-tool"
            )
            self.assertEqual(recovered.messages, TOOL_TURN)
            self.assertEqual(
                native["messages"],
                [{"role": item.role, "content": item.content} for item in TOOL_TURN],
            )

            python_path = str(Path(directory) / "python.sqlite3")
            reverse_store = SQLiteSessionStore(python_path)
            created = reverse_store.create_for_principal("principal-tool")
            python_state = reverse_store.commit_turn_messages(
                created.session_id, 0, TOOL_TURN
            )
            native_state = self.invoke(
                "read-principal", python_path, created.session_id, "principal-tool"
            )
            self.assertEqual(native_state["version"], python_state.version)
            self.assertEqual(
                native_state["messages"],
                [{"role": item.role, "content": item.content} for item in TOOL_TURN],
            )

    def test_multibyte_principal_identifier_uses_character_limits_in_both_runtimes(self):
        principal = "🧪" * 100
        with tempfile.TemporaryDirectory() as directory:
            native_path = str(Path(directory) / "native.sqlite3")
            native = self.invoke(
                "create-principal", native_path, principal, encode_turn(TURN_ONE)
            )
            python_store = SQLiteSessionStore(native_path)
            self.assertEqual(
                python_store.get_for_principal(native["session_id"], principal).messages,
                TURN_ONE,
            )

            python_path = str(Path(directory) / "python.sqlite3")
            reverse_store = SQLiteSessionStore(python_path)
            created = reverse_store.create_for_principal(principal)
            reverse_store.commit_turn_messages(created.session_id, 0, TURN_ONE)
            native_state = self.invoke(
                "read-principal", python_path, created.session_id, principal
            )
            self.assertEqual(native_state["version"], 1)
            self.assertEqual(native_state["messages"], [
                {"role": item.role, "content": item.content} for item in TURN_ONE
            ])

    def test_python_whitespace_control_characters_match_native_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "sessions.sqlite3")
            python_store = SQLiteSessionStore(path)
            created = python_store.create_for_principal("principal-whitespace")
            invalid_turn = (
                Message(role="user", content="\x1c"),
                Message(role="assistant", content="reply"),
            )
            with self.assertRaises(ValidationError):
                python_store.commit_turn_messages(created.session_id, 0, invalid_turn)
            self.invoke_error(
                1, "commit-principal", path, created.session_id,
                "principal-whitespace", "0", encode_turn(invalid_turn),
            )
            self.assertEqual(
                python_store.get_for_principal(
                    created.session_id, "principal-whitespace"
                ).version,
                0,
            )


if __name__ == "__main__":
    unittest.main()
