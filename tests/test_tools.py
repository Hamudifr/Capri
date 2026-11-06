import math
import unittest

from capri_runtime.tools import (
    ApprovalGrant,
    ToolApprovalInvalid,
    ToolApprovalRequired,
    ToolArgumentError,
    ToolAuditError,
    ToolEffect,
    ToolExecutionContext,
    ToolExecutionError,
    ToolPermissionDenied,
    ToolRegistrationError,
    ToolRegistry,
    ToolSpec,
)


TEXT_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "minLength": 1, "maxLength": 40},
        "count": {"type": "integer", "minimum": 0, "maximum": 5},
    },
    "required": ["text"],
    "additionalProperties": False,
}


def host_context(
    permissions=frozenset({"capri.read.notes"}),
    grants=(),
    principal_id="alice",
    request_id="request-1",
):
    return ToolExecutionContext(
        principal_id=principal_id,
        permissions=permissions,
        request_id=request_id,
        approval_grants=tuple(grants),
    )


def read_spec(handler=None, schema=None):
    return ToolSpec(
        name="notes.read",
        description="Read a note by its exact identifier.",
        input_schema=schema or TEXT_SCHEMA,
        required_permissions=frozenset({"capri.read.notes"}),
        effect=ToolEffect.READ,
        handler=handler or (lambda args, context: {"text": args["text"]}),
    )


class ToolRegistryTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.registry = ToolRegistry(audit_sink=self.events.append)

    def test_read_tool_executes_with_exact_permission_and_audit(self):
        self.registry.register(read_spec())
        result = self.registry.execute(
            "notes.read", {"text": "alpha"}, host_context()
        )
        self.assertEqual(result.output, {"text": "alpha"})
        self.assertEqual(len(result.argument_digest), 64)
        self.assertEqual(
            [event.status for event in self.events],
            ["started", "succeeded"],
        )
        self.assertEqual(self.events[-1].principal_id, "alice")
        self.assertEqual(self.events[-1].tool_name, "notes.read")

    def test_handler_is_not_called_without_permission(self):
        calls = []
        self.registry.register(read_spec(lambda args, ctx: calls.append(args)))
        with self.assertRaises(ToolPermissionDenied):
            self.registry.execute(
                "notes.read",
                {"text": "alpha"},
                host_context(permissions=frozenset({"capri.read.other"})),
            )
        self.assertEqual(calls, [])
        self.assertEqual(self.events[-1].status, "permission_denied")

    def test_permission_wildcard_does_not_grant_exact_permission(self):
        calls = []
        self.registry.register(read_spec(lambda args, ctx: calls.append(args)))
        with self.assertRaises(ToolPermissionDenied):
            self.registry.execute(
                "notes.read",
                {"text": "alpha"},
                host_context(permissions=frozenset({"capri.read.*"})),
            )
        self.assertEqual(calls, [])

    def test_unknown_tool_is_not_dispatched(self):
        with self.assertRaises(Exception):
            self.registry.execute("shell.run", {}, host_context())

    def test_duplicate_tool_registration_rejected(self):
        self.registry.register(read_spec())
        with self.assertRaises(ToolRegistrationError):
            self.registry.register(read_spec())

    def test_tool_listing_exposes_metadata_only(self):
        self.registry.register(read_spec())
        self.assertEqual(
            self.registry.list_tools(),
            (("notes.read", "Read a note by its exact identifier.", "read"),),
        )

    def test_unknown_argument_is_rejected_before_handler(self):
        calls = []
        self.registry.register(read_spec(lambda args, ctx: calls.append(args)))
        with self.assertRaises(ToolArgumentError):
            self.registry.execute(
                "notes.read", {"text": "alpha", "unexpected": "value"}, host_context()
            )
        self.assertEqual(calls, [])

    def test_missing_required_argument_is_rejected_before_handler(self):
        calls = []
        self.registry.register(read_spec(lambda args, ctx: calls.append(args)))
        with self.assertRaises(ToolArgumentError):
            self.registry.execute("notes.read", {}, host_context())
        self.assertEqual(calls, [])

    def test_boolean_is_not_accepted_as_integer(self):
        schema = {
            "type": "object",
            "properties": {"count": {"type": "integer"}},
            "required": ["count"],
            "additionalProperties": False,
        }
        calls = []
        self.registry.register(read_spec(lambda args, ctx: calls.append(args), schema))
        with self.assertRaises(ToolArgumentError):
            self.registry.execute("notes.read", {"count": True}, host_context())
        self.assertEqual(calls, [])

    def test_nested_array_items_are_validated(self):
        schema = {
            "type": "object",
            "properties": {
                "ids": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 2,
                    "items": {"type": "integer", "minimum": 1},
                }
            },
            "required": ["ids"],
            "additionalProperties": False,
        }
        self.registry.register(read_spec(lambda args, ctx: args["ids"], schema))
        self.assertEqual(
            self.registry.execute("notes.read", {"ids": [1, 2]}, host_context()).output,
            [1, 2],
        )
        with self.assertRaises(ToolArgumentError):
            self.registry.execute("notes.read", {"ids": [1, "2"]}, host_context())

    def test_schema_with_additional_properties_enabled_is_rejected(self):
        schema = {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        }
        with self.assertRaises(ToolRegistrationError):
            self.registry.register(read_spec(schema=schema))

    def test_schema_with_unknown_keyword_is_rejected(self):
        schema = {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
            "patternProperties": {},
        }
        with self.assertRaises(ToolRegistrationError):
            self.registry.register(read_spec(schema=schema))

    def test_schema_with_unhashable_type_is_rejected_cleanly(self):
        schema = {"type": [], "properties": {}, "additionalProperties": False}
        with self.assertRaises(ToolRegistrationError):
            self.registry.register(read_spec(schema=schema))

    def test_argument_byte_limit_is_enforced_before_handler(self):
        calls = []
        registry = ToolRegistry(audit_sink=self.events.append, max_argument_bytes=10)
        registry.register(read_spec(lambda args, ctx: calls.append(args)))
        with self.assertRaises(ToolArgumentError):
            registry.execute("notes.read", {"text": "this is too long"}, host_context())
        self.assertEqual(calls, [])

    def test_non_finite_and_cyclic_arguments_are_rejected(self):
        self.registry.register(
            ToolSpec(
                name="notes.raw",
                description="Accept a JSON object.",
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                required_permissions=frozenset({"capri.read.notes"}),
                effect=ToolEffect.READ,
                handler=lambda args, ctx: None,
            )
        )
        with self.assertRaises(ToolArgumentError):
            self.registry.execute("notes.raw", {"x": math.inf}, host_context())
        cyclic = {}
        cyclic["self"] = cyclic
        with self.assertRaises(ToolArgumentError):
            self.registry.execute("notes.raw", cyclic, host_context())

    def test_lone_surrogate_arguments_are_rejected(self):
        self.registry.register(read_spec())
        with self.assertRaises(ToolArgumentError):
            self.registry.execute("notes.read", {"text": "bad-" + chr(0xD800)}, host_context())

    def test_handler_receives_copy_not_mutable_caller_arguments(self):
        def mutate(args, context):
            args["text"] = "mutated"
            return {"ok": True}

        self.registry.register(read_spec(mutate))
        arguments = {"text": "original"}
        self.registry.execute("notes.read", arguments, host_context())
        self.assertEqual(arguments, {"text": "original"})

    def test_handler_exception_is_sanitized_and_audited(self):
        def fail(args, context):
            raise RuntimeError("secret provider token")

        self.registry.register(read_spec(fail))
        with self.assertRaises(ToolExecutionError) as caught:
            self.registry.execute("notes.read", {"text": "alpha"}, host_context())
        self.assertNotIn("secret provider token", str(caught.exception))
        self.assertTrue(caught.exception.execution_attempted)
        self.assertFalse(caught.exception.execution_completed)
        self.assertEqual(self.events[-1].status, "handler_failed")

    def test_invalid_handler_result_is_rejected_after_execution(self):
        self.registry.register(read_spec(lambda args, ctx: object()))
        with self.assertRaises(ToolExecutionError) as caught:
            self.registry.execute("notes.read", {"text": "alpha"}, host_context())
        self.assertTrue(caught.exception.execution_completed)
        self.assertEqual(self.events[-1].status, "result_rejected")

    def test_result_byte_limit_is_enforced(self):
        registry = ToolRegistry(audit_sink=self.events.append, max_result_bytes=8)
        registry.register(read_spec(lambda args, ctx: {"text": "far too large"}))
        with self.assertRaises(ToolExecutionError):
            registry.execute("notes.read", {"text": "alpha"}, host_context())
        self.assertEqual(self.events[-1].status, "result_rejected")

    def test_audit_events_do_not_contain_arguments_or_results(self):
        self.registry.register(read_spec(lambda args, ctx: {"secret": "output"}))
        self.registry.execute("notes.read", {"text": "private-input"}, host_context())
        rendered = repr(self.events)
        self.assertNotIn("private-input", rendered)
        self.assertNotIn("output", rendered)
        self.assertNotIn("secret", rendered)

    def test_audit_failure_before_handler_aborts_execution(self):
        calls = []

        def fail_audit(event):
            raise OSError("audit unavailable")

        registry = ToolRegistry(audit_sink=fail_audit)
        registry.register(read_spec(lambda args, ctx: calls.append(args)))
        with self.assertRaises(ToolAuditError) as caught:
            registry.execute("notes.read", {"text": "alpha"}, host_context())
        self.assertFalse(caught.exception.execution_attempted)
        self.assertEqual(calls, [])

    def test_audit_failure_after_handler_reports_completed_execution(self):
        calls = []
        count = 0

        def flaky_audit(event):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError("audit unavailable")

        registry = ToolRegistry(audit_sink=flaky_audit)
        registry.register(read_spec(lambda args, ctx: calls.append(args) or {"ok": True}))
        with self.assertRaises(ToolAuditError) as caught:
            registry.execute("notes.read", {"text": "alpha"}, host_context())
        self.assertTrue(caught.exception.execution_attempted)
        self.assertTrue(caught.exception.execution_completed)
        self.assertEqual(len(calls), 1)

    def test_external_tool_requires_approval_at_registration(self):
        spec = ToolSpec(
            name="mail.send",
            description="Send a message.",
            input_schema=TEXT_SCHEMA,
            required_permissions=frozenset({"capri.external.mail"}),
            effect=ToolEffect.EXTERNAL,
            handler=lambda args, ctx: {"sent": True},
            approval_required=False,
        )
        with self.assertRaises(ToolRegistrationError):
            self.registry.register(spec)

    def test_external_tool_waits_for_action_specific_approval(self):
        calls = []
        spec = ToolSpec(
            name="mail.send",
            description="Send a message.",
            input_schema=TEXT_SCHEMA,
            required_permissions=frozenset({"capri.external.mail"}),
            effect=ToolEffect.EXTERNAL,
            handler=lambda args, ctx: calls.append(args) or {"sent": True},
            approval_required=True,
        )
        self.registry.register(spec)
        arguments = {"text": "hello"}
        context = host_context(
            permissions=frozenset({"capri.external.mail"}),
        )
        with self.assertRaises(ToolApprovalRequired) as caught:
            self.registry.execute("mail.send", arguments, context)
        self.assertEqual(calls, [])
        self.assertEqual(caught.exception.argument_digest, ToolRegistry.argument_digest("mail.send", arguments))
        self.assertEqual(self.events[-1].status, "approval_required")

    def test_approval_is_bound_to_principal_tool_and_exact_arguments(self):
        calls = []
        spec = ToolSpec(
            name="mail.send",
            description="Send a message.",
            input_schema=TEXT_SCHEMA,
            required_permissions=frozenset({"capri.external.mail"}),
            effect=ToolEffect.EXTERNAL,
            handler=lambda args, ctx: calls.append(args) or {"sent": True},
            approval_required=True,
        )
        self.registry.register(spec)
        digest = ToolRegistry.argument_digest("mail.send", {"text": "hello"})
        grant = ApprovalGrant("grant-1", "alice", "mail.send", digest, 110.0)
        context = host_context(
            permissions=frozenset({"capri.external.mail"}),
            grants=(grant,),
        )
        result = self.registry.execute("mail.send", {"text": "hello"}, context)
        self.assertEqual(result.output, {"sent": True})
        self.assertEqual(len(calls), 1)
        with self.assertRaises(ToolApprovalInvalid):
            self.registry.execute("mail.send", {"text": "hello"}, context)

    def test_mismatched_approval_does_not_execute(self):
        calls = []
        self.registry.register(
            ToolSpec(
                name="mail.send",
                description="Send a message.",
                input_schema=TEXT_SCHEMA,
                required_permissions=frozenset({"capri.external.mail"}),
                effect=ToolEffect.EXTERNAL,
                handler=lambda args, ctx: calls.append(args),
                approval_required=True,
            )
        )
        digest = ToolRegistry.argument_digest("mail.send", {"text": "different"})
        grant = ApprovalGrant("grant-2", "alice", "mail.send", digest, 110.0)
        with self.assertRaises(ToolApprovalInvalid):
            self.registry.execute(
                "mail.send",
                {"text": "requested"},
                host_context(
                    permissions=frozenset({"capri.external.mail"}),
                    grants=(grant,),
                ),
            )
        self.assertEqual(calls, [])

    def test_expired_approval_does_not_execute(self):
        now = [100.0]
        registry = ToolRegistry(audit_sink=self.events.append, clock=lambda: now[0])
        calls = []
        registry.register(
            ToolSpec(
                name="file.delete",
                description="Delete a file.",
                input_schema=TEXT_SCHEMA,
                required_permissions=frozenset({"capri.destructive.files"}),
                effect=ToolEffect.DESTRUCTIVE,
                handler=lambda args, ctx: calls.append(args),
                approval_required=True,
            )
        )
        digest = ToolRegistry.argument_digest("file.delete", {"text": "file-1"})
        grant = ApprovalGrant("grant-3", "alice", "file.delete", digest, 99.0)
        with self.assertRaises(ToolApprovalInvalid):
            registry.execute(
                "file.delete",
                {"text": "file-1"},
                host_context(
                    permissions=frozenset({"capri.destructive.files"}),
                    grants=(grant,),
                ),
            )
        self.assertEqual(calls, [])

    def test_approval_for_another_principal_is_not_accepted(self):
        calls = []
        self.registry.register(
            ToolSpec(
                name="mail.send",
                description="Send a message.",
                input_schema=TEXT_SCHEMA,
                required_permissions=frozenset({"capri.external.mail"}),
                effect=ToolEffect.EXTERNAL,
                handler=lambda args, ctx: calls.append(args),
                approval_required=True,
            )
        )
        digest = ToolRegistry.argument_digest("mail.send", {"text": "hello"})
        grant = ApprovalGrant("grant-4", "bob", "mail.send", digest, 110.0)
        with self.assertRaises(ToolApprovalRequired):
            self.registry.execute(
                "mail.send",
                {"text": "hello"},
                host_context(
                    permissions=frozenset({"capri.external.mail"}),
                    grants=(grant,),
                    principal_id="alice",
                ),
            )
        self.assertEqual(calls, [])

    def test_invalid_host_context_is_rejected(self):
        with self.assertRaises(ValueError):
            ToolExecutionContext("alice", {"capri.read.notes"}, "request-1")
        with self.assertRaises(ValueError):
            ToolExecutionContext("alice", frozenset({"*"}), "request-1")


if __name__ == "__main__":
    unittest.main()
