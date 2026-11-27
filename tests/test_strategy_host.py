import os
import tempfile
import unittest

from capri_runtime import (
    AssistantTurn, HostAuthorityResolver, InMemoryAuditSink, SQLiteSessionStore,
    SQLiteTaskStore, ToolExecutionBridge, ToolExecutor, ToolOrchestrator, ToolRegistry,
)
from capri_runtime.host_runtime import CapriHostRuntime, HostRuntimeError
from capri_runtime.strategy_store import SQLiteStrategyStore, StrategyActivationRequest, StrategyAuthorizationError


class Adapter:
    def complete_with_tools(self, session_id, history, tools):
        return AssistantTurn(content="ok")


class StrategyHostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        if os.name == "posix":
            os.chmod(self.temp.name, 0o700)
        self.sessions = SQLiteSessionStore(os.path.join(self.temp.name, "sessions.sqlite3"), max_output_chars=131072)
        self.tasks = SQLiteTaskStore(os.path.join(self.temp.name, "tasks.sqlite3"))
        bridge = ToolExecutionBridge(ToolExecutor(ToolRegistry(), InMemoryAuditSink()))
        self.orchestrator = ToolOrchestrator(Adapter(), bridge)
        self.authority = HostAuthorityResolver(
            authenticate=lambda token: {"alice-token": "alice", "bob-token": "bob"}.get(token),
            permissions_for=lambda principal: (),
        )

    def tearDown(self):
        self.temp.cleanup()

    def make_host(self, store, tasks=None):
        return CapriHostRuntime(
            self.authority, self.sessions, self.orchestrator,
            task_store=tasks or self.tasks, strategy_store=store,
        )

    def test_authenticated_principal_is_required(self):
        store = SQLiteStrategyStore(self.tasks)
        host = self.make_host(store)
        baseline = host.register_strategy_baseline("alice-token", "reasoning", "baseline", "1.0", {"mode": "standard"})
        self.assertIsNone(host.get_active_strategy("bob-token", "reasoning"))
        request = StrategyActivationRequest(
            principal_id="alice", strategy_class="reasoning",
            strategy_id="baseline", version="1.0", evaluation_sha256=None,
            config_sha256=baseline.config_sha256, expected_generation=0, action="activate",
        )
        with self.assertRaises(StrategyAuthorizationError):
            host.activate_strategy("bob-token", request)
        self.assertEqual(host.activate_strategy("alice-token", request).strategy_id, "baseline")
        self.assertEqual(len(host.get_strategy_events("alice-token", "reasoning")), 1)
        self.assertEqual(host.get_strategy_events("bob-token", "reasoning"), ())

    def test_registry_must_share_exact_task_store(self):
        store = SQLiteStrategyStore(self.tasks)
        other = SQLiteTaskStore(os.path.join(self.temp.name, "other.sqlite3"))
        with self.assertRaises(HostRuntimeError):
            self.make_host(store, tasks=other)


if __name__ == "__main__":
    unittest.main()
