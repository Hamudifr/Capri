import itertools
import unittest

from capri_runtime.tools import (
    ExecutionContext,
    HostAuthorityError,
    HostAuthorityResolver,
    InMemoryAuditSink,
    PermissionDeniedError,
    ToolExecutor,
    ToolRegistry,
    ToolSpec,
)


SCHEMA = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}


class HostAuthorityResolverTests(unittest.TestCase):
    def test_permissions_come_from_authenticated_principal_not_request_fields(self):
        registry = ToolRegistry()
        calls = []
        registry.register(ToolSpec("read_private", "private:read", SCHEMA), lambda args: calls.append(True) or {"ok": True})
        executor = ToolExecutor(registry, InMemoryAuditSink())
        seen_principals = []

        def authenticate(credential):
            return {"valid-session-token": "alice", "bob-session-token": "bob"}.get(credential)

        def permissions_for(principal_id):
            seen_principals.append(principal_id)
            return {"alice": ("private:read",), "bob": ()}[principal_id]

        resolver = HostAuthorityResolver(authenticate, permissions_for)
        alice = resolver.resolve("valid-session-token")
        self.assertEqual(alice, ExecutionContext("alice", frozenset({"private:read"})))
        self.assertEqual(executor.execute("read_private", {}, alice), {"ok": True})

        bob = resolver.resolve("bob-session-token")
        with self.assertRaises(PermissionDeniedError):
            executor.execute("read_private", {}, bob)
        self.assertEqual(calls, [True])
        self.assertEqual(seen_principals, ["alice", "bob"])

    def test_authentication_and_policy_failures_fail_closed_without_leaking_details(self):
        resolver = HostAuthorityResolver(
            lambda credential: (_ for _ in ()).throw(RuntimeError("credential secret")),
            lambda principal: ("admin:*",),
        )
        with self.assertRaises(HostAuthorityError) as raised:
            resolver.resolve("credential secret")
        self.assertNotIn("credential secret", str(raised.exception))

        resolver = HostAuthorityResolver(lambda credential: "alice", lambda principal: "admin:all")
        with self.assertRaises(HostAuthorityError):
            resolver.resolve("opaque")

        resolver = HostAuthorityResolver(lambda credential: None, lambda principal: ("admin:all",))
        with self.assertRaises(HostAuthorityError):
            resolver.resolve("invalid")

    def test_operation_binding_is_host_scoped(self):
        resolver = HostAuthorityResolver(
            lambda credential: "alice",
            lambda principal: ("records:delete",),
        )
        context = resolver.resolve("opaque-host-credential", operation_id="op-1")
        self.assertEqual(context.operation_id, "op-1")
        self.assertEqual(context.principal_id, "alice")

        with self.assertRaises(HostAuthorityError):
            resolver.for_operation(
                ExecutionContext("alice", frozenset({"records:delete"}), operation_id="op-2"),
                "op-1",
            )

    def test_unbounded_permission_iterables_are_consumed_only_to_limit(self):
        resolver = HostAuthorityResolver(
            lambda credential: "alice",
            lambda principal: itertools.repeat("records:read"),
        )
        with self.assertRaises(HostAuthorityError):
            resolver.resolve("opaque")

    def test_callback_construction_is_trusted_host_configuration(self):
        with self.assertRaises(HostAuthorityError):
            HostAuthorityResolver("authenticate", lambda principal: ())
        with self.assertRaises(HostAuthorityError):
            HostAuthorityResolver(lambda credential: "alice", "permissions")


if __name__ == "__main__":
    unittest.main()
