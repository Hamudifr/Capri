import os
import tempfile
import threading
import unittest

from capri_runtime.orchestration import AssistantTurn, SessionTurnCoordinator, ToolOrchestrationError, ToolOrchestrator
from capri_runtime.runtime import SessionConflictError
from capri_runtime.sqlite_sessions import SQLiteSessionStore
from capri_runtime.tool_bridge import ToolCallRequest, ToolExecutionBridge
from capri_runtime.tools import ExecutionContext, InMemoryAuditSink, ToolCancelledError, ToolExecutor, ToolRegistry, ToolSpec


SCHEMA = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}


class LeaseLossStore(SQLiteSessionStore):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.renew_attempted = threading.Event()

    def renew_turn_lease(self, session_id, owner_token, lease_seconds):
        self.renew_attempted.set()
        raise SessionConflictError("simulated lease renewal failure")


class TwoCallAdapter:
    def __init__(self):
        self.calls = 0

    def complete_with_tools(self, session_id, history, tools):
        self.calls += 1
        return AssistantTurn(
            tool_calls=(
                ToolCallRequest("first-call", "long_task", {}),
                ToolCallRequest("second-call", "long_task", {}),
            )
        )


class CoordinatorLeaseLossCancellationTests(unittest.TestCase):
    def test_lease_loss_reaches_handler_blocks_next_call_and_prevents_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            os.chmod(directory, 0o700)
            store = LeaseLossStore(
                os.path.join(directory, "sessions.sqlite"),
                max_output_chars=131_072,
                max_tool_chars=131_072,
            )
            session = store.create()
            calls = []
            audit = InMemoryAuditSink()
            registry = ToolRegistry()

            def long_task(arguments, cancellation_event):
                calls.append("started")
                if not cancellation_event.wait(timeout=5):
                    raise AssertionError("lease-loss cancellation was not delivered")
                raise ToolCancelledError("handler stopped cooperatively")

            registry.register(
                ToolSpec("long_task", "tools:run", SCHEMA, cooperative_cancellation=True),
                long_task,
            )
            bridge = ToolExecutionBridge(ToolExecutor(registry, audit))
            adapter = TwoCallAdapter()
            orchestrator = ToolOrchestrator(adapter, bridge)

            with self.assertRaisesRegex(ToolOrchestrationError, "cancelled"):
                SessionTurnCoordinator(lease_seconds=3).run_and_commit(
                    orchestrator,
                    store,
                    session.session_id,
                    "start work",
                    ExecutionContext("host-user", frozenset({"tools:run"})),
                )

            self.assertTrue(store.renew_attempted.is_set())
            self.assertEqual(calls, ["started"])
            self.assertEqual(adapter.calls, 1)
            self.assertEqual(store.get(session.session_id).version, 0)
            self.assertEqual(
                [event.status for event in audit.events()],
                ["started", "outcome_uncertain"],
            )


if __name__ == "__main__":
    unittest.main()
