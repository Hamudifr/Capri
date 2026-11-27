import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone

from capri_runtime.tools import (
    ExecutionContext,
    InMemoryAuditSink,
    PermissionDeniedError,
    ToolExecutor,
    ToolRegistry,
    ToolSpec,
    ToolValidationError,
)


SCHEMA = {
    "type": "object",
    "properties": {"resource_id": {"type": "string", "minLength": 1, "maxLength": 64}},
    "required": ["resource_id"],
    "additionalProperties": False,
}


def digest(arguments):
    raw = json.dumps(arguments, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class ResourceAuthorizationTests(unittest.TestCase):
    def test_resource_denial_happens_before_execution(self):
        now = datetime.now(timezone.utc)
        allowed = {"resource-1"}
        calls = []
        registry = ToolRegistry()
        spec = ToolSpec(
            "update_resource",
            "resources:update",
            SCHEMA,
            resource_authorizer=lambda arguments, context: (
                context.principal_id == "user-1" and arguments["resource_id"] in allowed
            ),
        )
        registry.register(spec, lambda arguments: calls.append(arguments) or {"updated": True})
        audit = InMemoryAuditSink()
        executor = ToolExecutor(registry, audit, clock=lambda: now)
        authorized_arguments = {"resource_id": "resource-1"}
        context = ExecutionContext("user-1", frozenset({"resources:update"}))

        with self.assertRaises(PermissionDeniedError):
            executor.execute("update_resource", {"resource_id": "resource-2"}, context)
        self.assertEqual(calls, [])
        self.assertEqual([event.status for event in audit.events()], ["permission_denied"])
        self.assertEqual(audit.events()[0].error_code, "resource_authorization_denied")

        self.assertEqual(executor.execute("update_resource", authorized_arguments, context), {"updated": True})
        self.assertEqual(calls, [authorized_arguments])
        self.assertEqual(
            [event.status for event in audit.events()],
            ["permission_denied", "started", "succeeded"],
        )

    def test_authorizer_exceptions_and_non_boolean_results_fail_closed(self):
        for authorizer in (
            lambda arguments, context: (_ for _ in ()).throw(RuntimeError("private lookup detail")),
            lambda arguments, context: 1,
        ):
            with self.subTest(authorizer=authorizer):
                calls = []
                registry = ToolRegistry()
                registry.register(
                    ToolSpec("read_resource", "resources:read", SCHEMA, resource_authorizer=authorizer),
                    lambda arguments: calls.append(arguments),
                )
                audit = InMemoryAuditSink()
                executor = ToolExecutor(registry, audit)
                with self.assertRaises(PermissionDeniedError) as raised:
                    executor.execute(
                        "read_resource",
                        {"resource_id": "resource-1"},
                        ExecutionContext("user-1", frozenset({"resources:read"})),
                    )
                self.assertNotIn("private lookup detail", str(raised.exception))
                self.assertEqual(calls, [])
                self.assertEqual(audit.events()[0].status, "permission_denied")

    def test_authorizer_must_be_a_trusted_callable(self):
        with self.assertRaises(ToolValidationError):
            ToolSpec("bad", "resources:read", SCHEMA, resource_authorizer="allow-all")


if __name__ == "__main__":
    unittest.main()
