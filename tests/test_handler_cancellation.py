import threading
import unittest

from capri_runtime.tool_bridge import ToolCallRequest, ToolExecutionBridge
from capri_runtime.tools import (
    ExecutionContext,
    InMemoryAuditSink,
    ToolCancelledError,
    ToolExecutor,
    ToolRegistry,
    ToolSpec,
    ToolValidationError,
)


SCHEMA = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}


class HandlerCancellationTests(unittest.TestCase):
    def setUp(self):
        self.context = ExecutionContext("host-user", frozenset({"tools:run"}))

    def test_opted_in_handler_receives_event_and_uncertain_stop_is_not_reported_as_success(self):
        event = threading.Event()
        seen = []
        registry = ToolRegistry()
        audit = InMemoryAuditSink()

        def handler(arguments, cancellation_event):
            seen.append(cancellation_event)
            cancellation_event.set()
            raise ToolCancelledError("private handler detail")

        registry.register(
            ToolSpec("long_task", "tools:run", SCHEMA, cooperative_cancellation=True),
            handler,
        )
        bridge = ToolExecutionBridge(ToolExecutor(registry, audit))
        outcomes = bridge.execute_batch(
            [ToolCallRequest("call-1", "long_task", {})],
            self.context,
            cancellation_event=event,
        )

        self.assertEqual(seen, [event])
        self.assertEqual(outcomes[0].status, "outcome_uncertain")
        self.assertEqual(outcomes[0].error_code, "handler_cancelled_outcome_uncertain")
        self.assertNotIn("private handler detail", str(outcomes[0]))
        self.assertEqual([item.status for item in audit.events()], ["started", "outcome_uncertain"])

    def test_executor_does_not_start_handler_when_already_cancelled(self):
        calls = []
        registry = ToolRegistry()
        registry.register(
            ToolSpec("long_task", "tools:run", SCHEMA, cooperative_cancellation=True),
            lambda arguments, event: calls.append(arguments),
        )
        audit = InMemoryAuditSink()
        executor = ToolExecutor(registry, audit)
        event = threading.Event()
        event.set()

        with self.assertRaises(ToolCancelledError) as raised:
            executor.execute("long_task", {}, self.context, cancellation_event=event)
        self.assertFalse(raised.exception.outcome_uncertain)
        self.assertEqual(calls, [])
        self.assertEqual(audit.events(), ())

    def test_opt_in_is_required_and_legacy_handler_signature_is_preserved(self):
        registry = ToolRegistry()
        registry.register(ToolSpec("legacy", "tools:run", SCHEMA), lambda arguments: {"ok": True})
        bridge = ToolExecutionBridge(ToolExecutor(registry, InMemoryAuditSink()))
        outcomes = bridge.execute_batch(
            [ToolCallRequest("call-1", "legacy", {})],
            self.context,
            cancellation_event=threading.Event(),
        )
        self.assertEqual(outcomes[0].status, "succeeded")
        with self.assertRaises(ToolValidationError):
            ToolSpec("bad", "tools:run", SCHEMA, cooperative_cancellation="yes")


if __name__ == "__main__":
    unittest.main()
