import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone

from capri_runtime.tool_bridge import (
    ToolBridgeValidationError,
    ToolCallRequest,
    ToolExecutionBridge,
)
from capri_runtime.tools import (
    ApprovalGrant,
    AuditError,
    ExecutionContext,
    InMemoryAuditSink,
    PermissionDeniedError,
    ToolExecutor,
    ToolRegistry,
    ToolSpec,
)


SCHEMA = {
    "type": "object",
    "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 40}},
    "required": ["query"],
    "additionalProperties": False,
}


def digest(arguments):
    raw = json.dumps(
        arguments, ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class ToolExecutionBridgeTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.registry = ToolRegistry()
        self.registry.register(
            ToolSpec("search", "tools:search", SCHEMA),
            lambda args: self.calls.append(args) or {"count": 1},
        )
        self.audit = InMemoryAuditSink()
        self.now = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
        self.executor = ToolExecutor(
            self.registry, self.audit, clock=lambda: self.now
        )
        self.bridge = ToolExecutionBridge(self.executor)
        self.context = ExecutionContext("host-user", frozenset({"tools:search"}))

    def test_success_routes_through_executor_and_returns_result(self):
        outcomes = self.bridge.execute_batch(
            [ToolCallRequest("call-1", "search", {"query": "capri"})],
            self.context,
        )
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].status, "succeeded")
        self.assertEqual(outcomes[0].result, {"count": 1})
        self.assertEqual(self.calls, [{"query": "capri"}])
        self.assertEqual([e.status for e in self.audit.events()], ["started", "succeeded"])

    def test_available_tools_exposes_only_host_permitted_schemas(self):
        self.registry.register(
            ToolSpec("delete_item", "tools:delete", SCHEMA, requires_approval=True),
            lambda args: {"deleted": True},
        )
        definitions = self.bridge.available_tools(self.context)
        self.assertEqual([item.name for item in definitions], ["search"])
        self.assertEqual(definitions[0].parameters()["type"], "object")

    def test_permission_denial_never_invokes_handler(self):
        denied = self.bridge.execute_batch(
            [ToolCallRequest("c1", "search", {"query": "no"})],
            ExecutionContext("host-user", frozenset()),
        )
        self.assertEqual(denied[0].status, "permission_denied")
        self.assertEqual(self.calls, [])

    def test_model_request_cannot_forge_execution_context_or_approval(self):
        with self.assertRaises(ToolBridgeValidationError):
            self.bridge.execute_batch(
                [ToolCallRequest("c1", "search", {"query": "x"})],
                {"principal_id": "attacker", "permissions": ["tools:search"]},
            )
        self.assertEqual(self.calls, [])

    def test_duplicate_call_ids_reject_entire_batch_before_execution(self):
        with self.assertRaises(ToolBridgeValidationError):
            self.bridge.execute_batch(
                [
                    ToolCallRequest("same", "search", {"query": "first"}),
                    ToolCallRequest("same", "search", {"query": "second"}),
                ],
                self.context,
            )
        self.assertEqual(self.calls, [])

    def test_malformed_later_request_rejects_batch_before_first_side_effect(self):
        with self.assertRaises(ToolBridgeValidationError):
            self.bridge.execute_batch(
                [
                    ToolCallRequest("first", "search", {"query": "first"}),
                    ToolCallRequest("bad id!", "search", {"query": "second"}),
                ],
                self.context,
            )
        self.assertEqual(self.calls, [])

    def test_call_count_and_batch_byte_limits(self):
        small_count = ToolExecutionBridge(self.executor, max_calls=1)
        with self.assertRaises(ToolBridgeValidationError):
            small_count.execute_batch(
                [
                    ToolCallRequest("a", "search", {"query": "1"}),
                    ToolCallRequest("b", "search", {"query": "2"}),
                ],
                self.context,
            )
        small_bytes = ToolExecutionBridge(self.executor, max_batch_bytes=24)
        with self.assertRaises(ToolBridgeValidationError):
            small_bytes.execute_batch(
                [ToolCallRequest("a", "search", {"query": "a" * 40})],
                self.context,
            )
        self.assertEqual(self.calls, [])

    def test_unknown_tool_and_bad_arguments_return_safe_outcomes(self):
        outcomes = self.bridge.execute_batch(
            [
                ToolCallRequest("unknown", "missing", {}),
                ToolCallRequest("invalid", "search", {"unexpected": True}),
            ],
            self.context,
        )
        self.assertEqual([x.status for x in outcomes], ["tool_not_found", "invalid_arguments"])
        self.assertTrue(all(x.result is None for x in outcomes))
        self.assertEqual(self.calls, [])

    def test_approval_required_returns_digest_without_auto_approval(self):
        self.registry.register(
            ToolSpec("delete_item", "tools:delete", SCHEMA, requires_approval=True),
            lambda args: self.calls.append(args) or {"deleted": True},
        )
        context = ExecutionContext("host-user", frozenset({"tools:delete"}))
        args = {"query": "item-7"}
        outcome = self.bridge.execute_batch(
            [ToolCallRequest("delete", "delete_item", args)], context
        )[0]
        self.assertEqual(outcome.status, "approval_required")
        self.assertEqual(outcome.argument_digest, digest(args))
        self.assertEqual(self.calls, [])

    def test_exact_host_approval_allows_action(self):
        self.registry.register(
            ToolSpec("delete_item", "tools:delete", SCHEMA, requires_approval=True),
            lambda args: self.calls.append(args) or {"deleted": True},
        )
        args = {"query": "item-7"}
        grant = ApprovalGrant(
            "grant-1", "host-user", "delete_item", digest(args),
            (self.now + timedelta(minutes=2)).isoformat(),
        )
        context = ExecutionContext("host-user", frozenset({"tools:delete"}), (grant,))
        outcome = self.bridge.execute_batch(
            [ToolCallRequest("delete", "delete_item", args)], context
        )[0]
        self.assertEqual(outcome.status, "succeeded")
        self.assertEqual(self.calls, [args])

    def test_audit_failure_is_uncertain_and_never_retried(self):
        class CapacityAudit:
            def __init__(self):
                self.events = []
            def write(self, event):
                if self.events:
                    raise OSError("private audit detail")
                self.events.append(event)

        calls = []
        registry = ToolRegistry()
        registry.register(
            ToolSpec("mutate", "tools:mutate", SCHEMA),
            lambda args: calls.append(args) or {"ok": True},
        )
        executor = ToolExecutor(registry, CapacityAudit())
        bridge = ToolExecutionBridge(executor)
        context = ExecutionContext("host-user", frozenset({"tools:mutate"}))
        outcome = bridge.execute_batch(
            [ToolCallRequest("mutation", "mutate", {"query": "x"})], context
        )[0]
        self.assertEqual(outcome.status, "outcome_uncertain")
        self.assertEqual(outcome.error_code, "audit_outcome_uncertain")
        self.assertEqual(len(calls), 1)
        self.assertNotIn("private audit detail", repr(outcome))

    def test_invalid_batch_shapes_and_limits_are_rejected(self):
        for requests in (None, (), [], [object()]):
            with self.subTest(requests=requests):
                with self.assertRaises(ToolBridgeValidationError):
                    self.bridge.execute_batch(requests, self.context)
        with self.assertRaises(ToolBridgeValidationError):
            ToolExecutionBridge(self.executor, max_calls=65)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
