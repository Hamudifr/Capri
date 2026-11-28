import unittest

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

    def test_gateway_binds_host_generated_operation_id(self):
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                "operation_bound",
                "records:read",
                SCHEMA,
                resource_authorizer=lambda args, context: (
                    context.operation_id == "trusted-op-1"
                ),
            ),
            lambda args: {"ok": True},
        )
        bridge = ToolExecutionBridge(
            ToolExecutor(registry, InMemoryAuditSink())
        )
        gateway = HostToolGateway(self.authority, bridge)

        allowed = gateway.execute_batch(
            "alice-token",
            [ToolCallRequest("call-1", "operation_bound", {})],
            operation_id="trusted-op-1",
        )
        self.assertEqual(allowed[0].status, "succeeded")

        denied = gateway.execute_batch(
            "alice-token",
            [ToolCallRequest("call-2", "operation_bound", {})],
            operation_id="different-op",
        )
        self.assertEqual(denied[0].status, "permission_denied")

    def test_gateway_requires_trusted_dependencies(self):
        with self.assertRaises(HostAuthorityError):
            HostToolGateway("resolver", self.gateway._bridge)
        with self.assertRaises(HostAuthorityError):
            HostToolGateway(self.authority, "bridge")



if __name__ == "__main__":
    unittest.main()
