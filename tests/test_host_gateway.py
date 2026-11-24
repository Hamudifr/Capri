import os
import tempfile
import unittest
from datetime import datetime, timezone

from capri_runtime import (
    HmacApprovalAuthority,
    HostApprovalService,
    SQLiteApprovalChallengeStore,
    SQLiteSecurityStore,
)
from capri_runtime.host import HostToolGateway
from capri_runtime.tool_bridge import ToolCallRequest, ToolExecutionBridge
from capri_runtime.tools import (
    ExecutionContext,
    HostAuthorityError,
    HostAuthorityResolver,
    InMemoryAuditSink,
    ToolExecutor,
    ToolRegistry,
    ToolSpec,
)


SCHEMA = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}


class HostToolGatewayTests(unittest.TestCase):
    def setUp(self):
        registry = ToolRegistry()
        self.calls = []
        registry.register(
            ToolSpec("public_read", "records:read", SCHEMA),
            lambda args: self.calls.append("public") or {"value": "public"},
        )
        registry.register(
            ToolSpec("admin_delete", "records:delete", SCHEMA),
            lambda args: self.calls.append("delete") or {"deleted": True},
        )
        bridge = ToolExecutionBridge(ToolExecutor(registry, InMemoryAuditSink()))
        self.authority = HostAuthorityResolver(
            lambda credential: {
                "alice-token": "alice",
                "admin-token": "admin",
            }.get(credential),
            lambda principal: {
                "alice": ("records:read",),
                "admin": ("records:read", "records:delete"),
            }[principal],
        )
        self.gateway = HostToolGateway(self.authority, bridge)

    def test_tool_discovery_and_execution_resolve_authority_internally(self):
        self.assertEqual(
            [item.name for item in self.gateway.available_tools("alice-token")],
            ["public_read"],
        )
        self.assertEqual(
            [item.name for item in self.gateway.available_tools("admin-token")],
            ["admin_delete", "public_read"],
        )
        result = self.gateway.execute_batch(
            "alice-token",
            [ToolCallRequest("call-1", "public_read", {})],
        )
        self.assertEqual(result[0].status, "succeeded")
        self.assertEqual(self.calls, ["public"])

    def test_untrusted_request_cannot_supply_execution_context(self):
        forged = ExecutionContext("admin", frozenset({"records:delete"}))
        with self.assertRaises(HostAuthorityError):
            self.gateway.available_tools(forged)
        with self.assertRaises(HostAuthorityError):
            self.gateway.execute_batch(
                forged,
                [ToolCallRequest("call-1", "admin_delete", {})],
            )
        self.assertEqual(self.calls, [])

    def test_lower_privilege_caller_cannot_execute_admin_tool(self):
        result = self.gateway.execute_batch(
            "alice-token",
            [ToolCallRequest("call-1", "admin_delete", {})],
        )
        self.assertEqual(result[0].status, "permission_denied")
        self.assertEqual(self.calls, [])

    def test_gateway_requires_trusted_dependencies(self):
        with self.assertRaises(HostAuthorityError):
            HostToolGateway("resolver", self.gateway._bridge)
        with self.assertRaises(HostAuthorityError):
            HostToolGateway(self.authority, "bridge")



class HostGatewayApprovalIntegrationTests(unittest.TestCase):
    def test_gateway_persists_challenge_and_executes_only_after_host_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            now = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
            security = SQLiteSecurityStore(os.path.join(directory, "security.sqlite3"))
            signer = HmacApprovalAuthority(b"k" * 32, clock=lambda: now)
            registry = ToolRegistry()
            calls = []
            registry.register(
                ToolSpec(
                    "delete_item",
                    "records:delete",
                    {
                        "type": "object",
                        "properties": {"item": {"type": "string", "minLength": 1, "maxLength": 32}},
                        "required": ["item"],
                        "additionalProperties": False,
                    },
                    requires_approval=True,
                ),
                lambda args: calls.append(args) or {"deleted": True},
            )
            executor = ToolExecutor(
                registry,
                security,
                approval_store=security,
                approval_verifier=signer.verify,
                require_signed_approvals=True,
                clock=lambda: now,
            )
            bridge = ToolExecutionBridge(executor)
            challenge_store = SQLiteApprovalChallengeStore(security)
            approval_service = HostApprovalService(
                challenge_store,
                signer,
                lambda credential: "reviewer" if credential == "reviewer-token" else None,
                lambda approver, challenge: approver == "reviewer" and challenge.principal_id == "alice",
                clock=lambda: now,
            )
            issued = []
            delivered_grants = []
            authority = HostAuthorityResolver(
                lambda credential: "alice" if credential in {"session-token", "reviewer-token"} else None,
                lambda principal: ("records:delete",),
                lambda principal, operation_id: tuple(
                    grant for grant in delivered_grants
                    if principal == "alice" and grant.operation_id == operation_id
                ),
            )
            gateway = HostToolGateway(
                authority,
                bridge,
                approval_service=approval_service,
                operation_id_resolver=lambda credential, context, request: (
                    f"session-42:{request.call_id}"
                ),
                on_approval_challenge=issued.append,
            )
            request = ToolCallRequest("call-1", "delete_item", {"item": "target-1"})
            first = gateway.execute_batch("session-token", [request])
            self.assertEqual(first[0].status, "approval_required")
            self.assertEqual(len(calls), 0)
            self.assertEqual(len(issued), 1)
            self.assertEqual(issued[0].status, "pending")

            approved = approval_service.approve("reviewer-token", issued[0].challenge_id)
            delivered_grants.append(approved.grant)
            second = gateway.execute_batch("session-token", [request])
            self.assertEqual(second[0].status, "succeeded")
            self.assertEqual(second[0].result, {"deleted": True})
            self.assertEqual(calls, [{"item": "target-1"}])
            self.assertEqual(len(issued), 1)

            second_operation = gateway.execute_batch(
                "session-token",
                [ToolCallRequest("call-2", "delete_item", {"item": "target-1"})],
            )
            self.assertEqual(second_operation[0].status, "approval_required")
            self.assertEqual(calls, [{"item": "target-1"}])
            self.assertEqual(len(issued), 2)
            self.assertEqual(issued[1].operation_id, "session-42:call-2")

    def test_approval_integration_requires_all_host_callbacks(self):
        authority = HostAuthorityResolver(lambda credential: "alice", lambda principal: ())
        bridge = ToolExecutionBridge(ToolExecutor(ToolRegistry(), InMemoryAuditSink()))
        with self.assertRaises(HostAuthorityError):
            HostToolGateway(
                authority,
                bridge,
                operation_id_resolver=lambda *args: "op-1",
            )


if __name__ == "__main__":
    unittest.main()
