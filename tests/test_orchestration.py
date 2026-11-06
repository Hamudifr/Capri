import unittest

from capri_runtime.orchestration import (
    AssistantTurn,
    ToolOrchestrationError,
    ToolOrchestrator,
)
from capri_runtime.runtime import Message
from capri_runtime.tool_bridge import ToolCallRequest, ToolExecutionBridge
from capri_runtime.tools import ExecutionContext, InMemoryAuditSink, ToolExecutor, ToolRegistry, ToolSpec


SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "string", "minLength": 1, "maxLength": 20}},
    "required": ["value"],
    "additionalProperties": False,
}


class ScriptedAdapter:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.histories = []
        self.tool_definitions = []

    def complete_with_tools(self, session_id, user_text, history, tools):
        self.histories.append(history)
        self.tool_definitions.append(tools)
        if not self.responses:
            raise AssertionError("adapter called more times than expected")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class ToolOrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        registry = ToolRegistry()
        registry.register(
            ToolSpec("echo", "tools:echo", SCHEMA),
            lambda args: self.calls.append(args) or {"echo": args["value"]},
        )
        self.executor = ToolExecutor(registry, InMemoryAuditSink())
        self.bridge = ToolExecutionBridge(self.executor)
        self.context = ExecutionContext("host-user", frozenset({"tools:echo"}))

    def test_executes_tool_then_returns_final_text_and_transcript(self):
        adapter = ScriptedAdapter(
            AssistantTurn(tool_calls=(ToolCallRequest("call-1", "echo", {"value": "hi"}),)),
            AssistantTurn(content="The result is hi."),
        )
        result = ToolOrchestrator(adapter, self.bridge).run(
            "session-1", "echo hi", (), self.context
        )
        self.assertEqual(result.final_text, "The result is hi.")
        self.assertEqual(result.tool_rounds, 1)
        self.assertEqual(result.tool_outcomes[0].status, "succeeded")
        self.assertEqual(self.calls, [{"value": "hi"}])
        self.assertEqual([m.role for m in result.messages], ["assistant", "tool", "assistant"])
        self.assertIn('"echo":"hi"', adapter.histories[1][-1].content)
        self.assertEqual([tool.name for tool in adapter.tool_definitions[0]], ["echo"])

    def test_permission_denied_is_returned_to_model_without_running_handler(self):
        adapter = ScriptedAdapter(
            AssistantTurn(tool_calls=(ToolCallRequest("call-1", "echo", {"value": "x"}),)),
            AssistantTurn(content="I cannot access that tool."),
        )
        context = ExecutionContext("host-user", frozenset())
        result = ToolOrchestrator(adapter, self.bridge).run(
            "session-1", "try", (), context
        )
        self.assertEqual(result.tool_outcomes[0].status, "permission_denied")
        self.assertEqual(adapter.tool_definitions[0], ())
        self.assertEqual(self.calls, [])

    def test_round_limit_stops_before_executing_excess_batch(self):
        adapter = ScriptedAdapter(
            AssistantTurn(tool_calls=(ToolCallRequest("one", "echo", {"value": "1"}),)),
            AssistantTurn(tool_calls=(ToolCallRequest("two", "echo", {"value": "2"}),)),
        )
        orchestrator = ToolOrchestrator(adapter, self.bridge, max_tool_rounds=1)
        with self.assertRaises(ToolOrchestrationError):
            orchestrator.run("s", "go", (), self.context)
        self.assertEqual(self.calls, [{"value": "1"}])

    def test_reused_call_id_across_rounds_is_reported_without_reexecution(self):
        adapter = ScriptedAdapter(
            AssistantTurn(tool_calls=(ToolCallRequest("same", "echo", {"value": "first"}),)),
            AssistantTurn(tool_calls=(ToolCallRequest("same", "echo", {"value": "second"}),)),
            AssistantTurn(content="Finished."),
        )
        result = ToolOrchestrator(adapter, self.bridge).run("s", "go", (), self.context)
        self.assertEqual([x.status for x in result.tool_outcomes], ["succeeded", "invalid_request"])
        self.assertEqual(result.tool_outcomes[1].error_code, "duplicate_call_id")
        self.assertEqual(self.calls, [{"value": "first"}])

    def test_invalid_batch_fails_before_any_handler_runs(self):
        adapter = ScriptedAdapter(
            AssistantTurn(tool_calls=(
                ToolCallRequest("same", "echo", {"value": "one"}),
                ToolCallRequest("same", "echo", {"value": "two"}),
            ))
        )
        with self.assertRaises(ToolOrchestrationError):
            ToolOrchestrator(adapter, self.bridge).run("s", "go", (), self.context)
        self.assertEqual(self.calls, [])

    def test_history_limit_is_checked_before_tool_execution(self):
        adapter = ScriptedAdapter(
            AssistantTurn(tool_calls=(ToolCallRequest("call", "echo", {"value": "x"}),))
        )
        orchestrator = ToolOrchestrator(
            adapter, self.bridge, max_history_messages=1
        )
        with self.assertRaises(ToolOrchestrationError):
            orchestrator.run("s", "go", (), self.context)
        self.assertEqual(self.calls, [])

    def test_adapter_errors_are_suppressed(self):
        adapter = ScriptedAdapter(RuntimeError("provider secret"))
        with self.assertRaises(ToolOrchestrationError) as raised:
            ToolOrchestrator(adapter, self.bridge).run("s", "go", (), self.context)
        self.assertNotIn("provider secret", str(raised.exception))
        self.assertIsNone(raised.exception.__context__)

    def test_invalid_adapter_response_is_rejected(self):
        adapter = ScriptedAdapter({"content": "not a typed response"})
        with self.assertRaises(ToolOrchestrationError):
            ToolOrchestrator(adapter, self.bridge).run("s", "go", (), self.context)
        self.assertEqual(self.calls, [])

    def test_invalid_final_response_is_rejected(self):
        adapter = ScriptedAdapter(AssistantTurn(content="  "))
        with self.assertRaises(ToolOrchestrationError):
            ToolOrchestrator(adapter, self.bridge).run("s", "go", (), self.context)

    def test_existing_history_is_forwarded(self):
        prior = (Message(role="user", content="earlier"),)
        adapter = ScriptedAdapter(AssistantTurn(content="done"))
        result = ToolOrchestrator(adapter, self.bridge).run("s", "go", prior, self.context)
        self.assertEqual(adapter.histories[0], prior)
        self.assertEqual(result.messages[0], prior[0])

    def test_tool_message_limit_cannot_be_smaller_than_executor_result_limit(self):
        with self.assertRaises(ToolOrchestrationError):
            ToolOrchestrator(
                ScriptedAdapter(), self.bridge, max_tool_message_bytes=65_536
            )


if __name__ == "__main__":
    unittest.main()
