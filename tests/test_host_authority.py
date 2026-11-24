import itertools
import unittest
from datetime import datetime, timedelta, timezone

from capri_runtime.tools import (
    ApprovalGrant,
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

    def test_approval_grants_are_host_resolved_and_principal_scoped(self):
        now = datetime.now(timezone.utc)
        grant = ApprovalGrant(
            "grant-1", "alice", "delete_record", "a" * 64,
            (now + timedelta(minutes=1)).isoformat(),
            operation_id="op-1",
        )
        resolver = HostAuthorityResolver(
            lambda credential: "alice",
            lambda principal: ("records:delete",),
            lambda principal, operation_id: (grant,) if operation_id == "op-1" else (),
        )
        context = resolver.resolve("opaque-host-credential", operation_id="op-1")
        self.assertEqual(context.approvals, (grant,))
        self.assertEqual(context.operation_id, "op-1")

        bad_resolver = HostAuthorityResolver(
            lambda credential: "alice",
            lambda principal: ("records:delete",),
            lambda principal, operation_id: (ApprovalGrant(
                "grant-2", "bob", "delete_record", "a" * 64,
                (now + timedelta(minutes=1)).isoformat(),
                operation_id="op-1",
            ),),
        )
        with self.assertRaises(HostAuthorityError):
            bad_resolver.resolve("opaque-host-credential", operation_id="op-1")

        wrong_operation = ApprovalGrant(
            "grant-3", "alice", "delete_record", "a" * 64,
            (now + timedelta(minutes=1)).isoformat(), operation_id="op-other",
        )
        wrong_operation_resolver = HostAuthorityResolver(
            lambda credential: "alice",
            lambda principal: ("records:delete",),
            lambda principal, operation_id: (wrong_operation,),
        )
        with self.assertRaises(HostAuthorityError):
            wrong_operation_resolver.resolve("opaque-host-credential", operation_id="op-1")

    def test_unbounded_permission_and_approval_iterables_are_consumed_only_to_limit(self):
        resolver = HostAuthorityResolver(
            lambda credential: "alice",
            lambda principal: itertools.repeat("records:read"),
        )
        with self.assertRaises(HostAuthorityError):
            resolver.resolve("opaque")

        grant = ApprovalGrant(
            "grant-1", "alice", "delete_record", "a" * 64,
            "2099-01-01T00:00:00+00:00", operation_id="op-1",
        )
        resolver = HostAuthorityResolver(
            lambda credential: "alice",
            lambda principal: ("records:delete",),
            lambda principal, operation_id: __import__("itertools").repeat(grant),
        )
        with self.assertRaises(HostAuthorityError):
            resolver.resolve("opaque", operation_id="op-1")

    def test_callback_construction_is_trusted_host_configuration(self):
        with self.assertRaises(HostAuthorityError):
            HostAuthorityResolver("authenticate", lambda principal: ())
        with self.assertRaises(HostAuthorityError):
            HostAuthorityResolver(lambda credential: "alice", lambda principal: (), approvals_for="grants")


if __name__ == "__main__":
    unittest.main()
