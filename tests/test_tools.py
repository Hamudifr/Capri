import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone

from capri_runtime.tools import (
    ApprovalGrant,
    ApprovalRequiredError,
    AuditError,
    ExecutionContext,
    InMemoryAuditSink,
    PermissionDeniedError,
    ToolExecutionError,
    ToolExecutor,
    ToolNotFoundError,
    ToolRegistry,
    ToolSpec,
    ToolValidationError,
)


SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "minLength": 1, "maxLength": 40},
        "limit": {"type": "integer", "minimum": 1, "maximum": 5},
    },
    "required": ["query"],
    "additionalProperties": False,
}


def digest(arguments):
    raw = json.dumps(
        arguments, ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class FailingAuditSink:
    def write(self, event):
        raise OSError("private audit backend detail")


class ToolExecutionTests(unittest.TestCase):
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
        self.context = ExecutionContext("host-user-1", frozenset({"tools:search"}))

    def test_registered_handler_executes_and_audits_without_raw_arguments(self):
        result = self.executor.execute("search", {"query": "capri", "limit": 2}, self.context)
        self.assertEqual(result, {"count": 1})
        self.assertEqual(len(self.calls), 1)
        events = self.audit.events()
        self.assertEqual([event.status for event in events], ["started", "succeeded"])
        self.assertEqual(events[0].argument_digest, digest({"query": "capri", "limit": 2}))
        self.assertFalse(hasattr(events[0], "arguments"))
        self.assertFalse(hasattr(events[0], "output"))

    def test_unknown_tool_is_rejected(self):
        with self.assertRaises(ToolNotFoundError):
            self.executor.execute("missing", {}, self.context)
        self.assertEqual(self.calls, [])

    def test_model_arguments_cannot_grant_permission(self):
        context = ExecutionContext("host-user-1", frozenset())
        with self.assertRaises(PermissionDeniedError):
            self.executor.execute("search", {"query": "capri"}, context)
        self.assertEqual(self.calls, [])

    def test_schema_rejects_missing_extra_wrong_and_out_of_range_arguments(self):
        invalid = (
            {},
            {"query": "ok", "unexpected": True},
            {"query": 42},
            {"query": "", "limit": 1},
            {"query": "ok", "limit": 6},
            {"query": "ok", "limit": True},
        )
        for args in invalid:
            with self.subTest(args=args):
                with self.assertRaises(ToolValidationError):
                    self.executor.execute("search", args, self.context)
        self.assertEqual(self.calls, [])

    def test_argument_byte_limit_and_unicode_are_enforced(self):
        small = ToolExecutor(self.registry, self.audit, max_argument_bytes=8, clock=lambda: self.now)
        with self.assertRaises(ToolValidationError):
            small.execute("search", {"query": "a much longer query"}, self.context)
        with self.assertRaises(ToolValidationError):
            self.executor.execute("search", {"query": "bad-\ud800"}, self.context)
        self.assertEqual(self.calls, [])

    def test_boolean_is_not_accepted_as_integer(self):
        schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
        registry = ToolRegistry()
        calls = []
        registry.register(ToolSpec("count", "tools:count", schema), lambda args: calls.append(args))
        executor = ToolExecutor(registry, InMemoryAuditSink())
        with self.assertRaises(ToolValidationError):
            executor.execute("count", {"n": True}, ExecutionContext("u", frozenset({"tools:count"})))
        self.assertEqual(calls, [])

    def test_duplicate_and_unsupported_schema_registrations_are_rejected(self):
        with self.assertRaises(ToolValidationError):
            self.registry.register(ToolSpec("search", "tools:search", SCHEMA), lambda args: None)
        with self.assertRaises(ToolValidationError):
            ToolSpec("bad", "tools:bad", {"type": "object", "properties": {}, "patternProperties": {}})
        with self.assertRaises(ToolValidationError):
            ToolSpec("bad", "tools:bad", {"type": "object", "properties": {"x": {"type": "array"}}})
        with self.assertRaises(ToolValidationError):
            ToolSpec("bad", "tools:bad", {"type": "integer", "minimum": 0, "minLength": 1})

    def test_mutating_original_schema_does_not_change_registered_contract(self):
        schema = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
        spec = ToolSpec("immutable", "tools:immutable", schema)
        schema["properties"]["x"]["type"] = "integer"
        self.assertEqual(spec.schema()["properties"]["x"]["type"], "string")

    def test_approval_is_bound_to_principal_tool_and_exact_arguments(self):
        spec = ToolSpec("delete_item", "tools:delete", SCHEMA, requires_approval=True)
        calls = []
        registry = ToolRegistry()
        registry.register(spec, lambda args: calls.append(args) or {"deleted": True})
        executor = ToolExecutor(registry, InMemoryAuditSink(), clock=lambda: self.now)
        args = {"query": "item-1"}
        grant = ApprovalGrant(
            "grant-1", "host-user-1", "delete_item", digest(args),
            (self.now + timedelta(minutes=2)).isoformat(),
        )
        context = ExecutionContext("host-user-1", frozenset({"tools:delete"}), (grant,))
        self.assertEqual(executor.execute("delete_item", args, context), {"deleted": True})
        self.assertEqual(len(calls), 1)
        with self.assertRaises(ApprovalRequiredError):
            executor.execute("delete_item", args, context)
        self.assertEqual(len(calls), 1)

    def test_expired_mismatched_and_cross_principal_approvals_fail_closed(self):
        spec = ToolSpec("delete_item", "tools:delete", SCHEMA, requires_approval=True)
        calls = []
        registry = ToolRegistry()
        registry.register(spec, lambda args: calls.append(args))
        executor = ToolExecutor(registry, InMemoryAuditSink(), clock=lambda: self.now)
        args = {"query": "item-1"}
        grants = (
            ApprovalGrant("expired", "host-user-1", "delete_item", digest(args),
                          (self.now - timedelta(seconds=1)).isoformat()),
            ApprovalGrant("wrong-digest", "host-user-1", "delete_item", digest({"query": "other"}),
                          (self.now + timedelta(minutes=1)).isoformat()),
            ApprovalGrant("wrong-user", "someone-else", "delete_item", digest(args),
                          (self.now + timedelta(minutes=1)).isoformat()),
        )
        for grant in grants:
            with self.subTest(grant=grant.grant_id):
                context = ExecutionContext("host-user-1", frozenset({"tools:delete"}), (grant,))
                with self.assertRaises(ApprovalRequiredError):
                    executor.execute("delete_item", args, context)
        self.assertEqual(calls, [])

    def test_audit_start_failure_prevents_handler_invocation(self):
        registry = ToolRegistry()
        calls = []
        registry.register(ToolSpec("safe", "tools:safe", SCHEMA), lambda args: calls.append(args))
        executor = ToolExecutor(registry, FailingAuditSink())
        with self.assertRaises(AuditError):
            executor.execute("safe", {"query": "ok"}, ExecutionContext("u", frozenset({"tools:safe"})))
        self.assertEqual(calls, [])

    def test_handler_errors_are_suppressed_and_audited(self):
        registry = ToolRegistry()
        registry.register(ToolSpec("broken", "tools:broken", SCHEMA),
                          lambda args: (_ for _ in ()).throw(RuntimeError("secret detail")))
        audit = InMemoryAuditSink()
        executor = ToolExecutor(registry, audit)
        with self.assertRaises(ToolExecutionError) as raised:
            executor.execute("broken", {"query": "ok"}, ExecutionContext("u", frozenset({"tools:broken"})))
        self.assertNotIn("secret detail", str(raised.exception))
        self.assertIsNone(raised.exception.__context__)
        self.assertEqual([event.status for event in audit.events()], ["started", "handler_failed"])

    def test_oversized_or_non_json_handler_results_are_rejected(self):
        registry = ToolRegistry()
        registry.register(ToolSpec("large", "tools:large", SCHEMA), lambda args: {"value": "x" * 100})
        executor = ToolExecutor(registry, InMemoryAuditSink(), max_result_bytes=20)
        with self.assertRaises(ToolValidationError):
            executor.execute("large", {"query": "ok"}, ExecutionContext("u", frozenset({"tools:large"})))
        registry2 = ToolRegistry()
        registry2.register(ToolSpec("nan", "tools:nan", SCHEMA), lambda args: float("nan"))
        executor2 = ToolExecutor(registry2, InMemoryAuditSink())
        with self.assertRaises(ToolValidationError):
            executor2.execute("nan", {"query": "ok"}, ExecutionContext("u", frozenset({"tools:nan"})))

    def test_audit_capacity_failure_after_handler_reports_uncertain_outcome(self):
        registry = ToolRegistry()
        calls = []
        registry.register(ToolSpec("safe", "tools:safe", SCHEMA), lambda args: calls.append(args) or {"ok": True})
        # The first "started" event is stored; completion cannot be stored.
        audit = InMemoryAuditSink(max_events=1)
        executor = ToolExecutor(registry, audit)
        with self.assertRaises(AuditError):
            executor.execute("safe", {"query": "ok"}, ExecutionContext("u", frozenset({"tools:safe"})))
        self.assertEqual(len(calls), 1)
        self.assertEqual([event.status for event in audit.events()], ["started"])

    def test_registry_names_are_sorted(self):
        self.assertEqual(self.registry.names(), ("search",))


if __name__ == "__main__":
    unittest.main()
