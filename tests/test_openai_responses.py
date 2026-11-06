import json
import unittest

from capri_runtime.openai_responses import (
    OpenAIResponsesAdapter,
    OpenAIResponsesAdapterError,
)
from capri_runtime.runtime import Message
from capri_runtime.tool_bridge import ToolDefinition


class FakeResponses:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeClient:
    def __init__(self, responses):
        self.responses = FakeResponses(responses)


class OpenAIResponsesAdapterTests(unittest.TestCase):
    def setUp(self):
        self.definition = ToolDefinition(
            name="lookup",
            parameters_json=json.dumps({
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            }),
            requires_approval=False,
        )

    def test_maps_tool_calls_and_preserves_reasoning_items(self):
        client = FakeClient([{
            "status": "completed",
            "error": None,
            "output": [
                {"type": "reasoning", "id": "rs_1", "summary": []},
                {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "lookup",
                    "arguments": '{"query":"capri"}',
                },
            ],
        }])
        adapter = OpenAIResponsesAdapter(
            client, model="gpt-6-astra", instructions="Use tools when appropriate."
        )
        turn = adapter.complete_with_tools(
            "session-1",
            (Message(role="user", content="Find Capri"),),
            (self.definition,),
        )
        self.assertEqual(len(turn.tool_calls), 1)
        self.assertEqual(turn.tool_calls[0].call_id, "call_1")
        self.assertEqual(turn.tool_calls[0].arguments, {"query": "capri"})
        self.assertEqual(turn.provider_data[0]["type"], "reasoning")
        request = client.responses.calls[0]
        self.assertEqual(request["model"], "gpt-6-astra")
        self.assertEqual(request["instructions"], "Use tools when appropriate.")
        self.assertFalse(request["store"])
        self.assertFalse(request["parallel_tool_calls"])
        self.assertEqual(request["tools"][0]["name"], "lookup")
        self.assertFalse(request["tools"][0]["strict"])

    def test_reconstructs_tool_history_and_reasoning_for_stateless_continuation(self):
        reasoning = {"type": "reasoning", "id": "rs_previous", "summary": []}
        call_envelope = {
            "content": "",
            "provider_data": [reasoning],
            "tool_calls": [{
                "id": "call_previous",
                "name": "lookup",
                "arguments": {"query": "capri"},
            }],
        }
        tool_outcome = {
            "call_id": "call_previous",
            "name": "lookup",
            "status": "succeeded",
            "result": {"found": True},
            "error_code": None,
            "argument_digest": "a" * 64,
        }
        client = FakeClient([{
            "status": "completed",
            "error": None,
            "output_text": "Found it.",
            "output": [{
                "type": "message",
                "content": [{"type": "output_text", "text": "Found it."}],
            }],
        }])
        adapter = OpenAIResponsesAdapter(client, model="gpt-6-astra")
        turn = adapter.complete_with_tools(
            "session-1",
            (
                Message(role="user", content="Find Capri"),
                Message(role="assistant", content=json.dumps(call_envelope)),
                Message(role="tool", content=json.dumps(tool_outcome)),
            ),
            (self.definition,),
        )
        self.assertEqual(turn.content, "Found it.")
        sent = client.responses.calls[0]["input"]
        self.assertEqual(sent[0], {"role": "user", "content": "Find Capri"})
        self.assertEqual(sent[1], reasoning)
        self.assertEqual(sent[2]["type"], "function_call")
        self.assertEqual(sent[2]["call_id"], "call_previous")
        self.assertEqual(sent[3]["type"], "function_call_output")
        self.assertEqual(sent[3]["call_id"], "call_previous")
        self.assertIn('"status":"succeeded"', sent[3]["output"])

    def test_rejects_duplicate_argument_keys(self):
        client = FakeClient([{
            "status": "completed",
            "error": None,
            "output": [{
                "type": "function_call",
                "call_id": "call_1",
                "name": "lookup",
                "arguments": '{"query":"first","query":"second"}',
            }],
        }])
        adapter = OpenAIResponsesAdapter(client, model="gpt-6-astra")
        with self.assertRaises(OpenAIResponsesAdapterError):
            adapter.complete_with_tools(
                "session-1",
                (Message(role="user", content="Find Capri"),),
                (self.definition,),
            )

    def test_rejects_incomplete_response(self):
        client = FakeClient([{
            "status": "incomplete",
            "error": None,
            "output": [],
        }])
        adapter = OpenAIResponsesAdapter(client, model="gpt-6-astra")
        with self.assertRaises(OpenAIResponsesAdapterError):
            adapter.complete_with_tools(
                "session-1",
                (Message(role="user", content="Hello"),),
                (),
            )

    def test_provider_errors_are_sanitized(self):
        client = FakeClient([RuntimeError("secret-token-value")])
        adapter = OpenAIResponsesAdapter(client, model="gpt-6-astra")
        with self.assertRaises(OpenAIResponsesAdapterError) as raised:
            adapter.complete_with_tools(
                "session-1",
                (Message(role="user", content="Hello"),),
                (),
            )
        self.assertNotIn("secret-token-value", str(raised.exception))

    def test_rejects_malformed_tool_result_history(self):
        adapter = OpenAIResponsesAdapter(FakeClient([]), model="gpt-6-astra")
        with self.assertRaises(OpenAIResponsesAdapterError):
            adapter._history((
                Message(role="tool", content='{"name":"lookup"}'),
            ))


if __name__ == "__main__":
    unittest.main()
