import threading
import unittest

from capri_runtime.orchestration import AssistantTurn, ToolOrchestrationError, ToolOrchestrator
from capri_runtime.tool_bridge import ToolCallRequest, ToolExecutionBridge
from capri_runtime.tools import ExecutionContext, InMemoryAuditSink, ToolExecutor, ToolRegistry, ToolSpec


SCHEMA = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}


class Adapter:
    def __init__(self, response=None):
        self.calls = 0
        self.response = response or AssistantTurn(content="done")

    def complete_with_tools(self, session_id, history, tools):
        self.calls += 1
        return self.response


class CooperativeCancellationTests(unittest.TestCase):
    def setUp(self):
        self.context = ExecutionContext("host-user", frozenset({"tools:run"}))

    def test_pre_cancelled_orchestration_does_not_invoke_model(self):
        adapter = Adapter()
        registry = ToolRegistry()
        executor = ToolExecutor(registry, InMemoryAuditSink())
        orchestrator = ToolOrchestrator(adapter, ToolExecutionBridge(executor))
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaisesRegex(ToolOrchestrationError, "cancelled"):
            orchestrator.run("session", "hello", (), self.context, cancellation_event=cancelled)
        self.assertEqual(adapter.calls, 0)

    def test_lease_loss_after_one_handler_prevents_later_batch_calls(self):
        cancelled = threading.Event()
        calls = []
        registry = ToolRegistry()

        def first(args):
            calls.append("first")
            cancelled.set()
            return {"ok": True}

        def second(args):
            calls.append("second")
            return {"ok": True}

        registry.register(ToolSpec("first", "tools:run", SCHEMA), first)
        registry.register(ToolSpec("second", "tools:run", SCHEMA), second)
        bridge = ToolExecutionBridge(ToolExecutor(registry, InMemoryAuditSink()))
        outcomes = bridge.execute_batch(
            [
                ToolCallRequest("call-1", "first", {}),
                ToolCallRequest("call-2", "second", {}),
            ],
            self.context,
            cancellation_event=cancelled,
        )
        self.assertEqual(calls, ["first"])
        self.assertEqual([item.status for item in outcomes], ["succeeded", "cancelled"])
        self.assertEqual(outcomes[1].error_code, "cancelled")

    def test_cancellation_event_contract_is_validated(self):
        registry = ToolRegistry()
        bridge = ToolExecutionBridge(ToolExecutor(registry, InMemoryAuditSink()))
        with self.assertRaisesRegex(Exception, "cancellation_event"):
            bridge.execute_batch(
                [ToolCallRequest("call-1", "missing", {})], self.context,
                cancellation_event=object(),
            )


if __name__ == "__main__":
    unittest.main()
