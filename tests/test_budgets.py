import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone

from capri_runtime import (
    AssistantTurn,
    BudgetExceededError,
    BudgetPolicy,
    BudgetValidationError,
    ExecutionContext,
    InMemoryAuditSink,
    SQLiteBudgetStore,
    SQLiteTaskStore,
    TaskEngine,
    ToolBudgetExceededError,
    ToolExecutionBridge,
    ToolExecutor,
    ToolOrchestrator,
    ToolRegistry,
    ToolSpec,
)

NOW = datetime(2026, 11, 25, 8, 0, tzinfo=timezone.utc)
SCHEMA = {
    "type": "object",
    "properties": {"query": {"type": "string", "maxLength": 100}},
    "required": ["query"],
    "additionalProperties": False,
}
PLAN = [{"tool": "collect", "input": {"query": "x"}, "max_attempts": 2}]


class SQLiteBudgetStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        if os.name == "posix":
            os.chmod(self.temp.name, 0o700)
        self.path = os.path.join(self.temp.name, "budgets.sqlite3")
        self.policy = BudgetPolicy(
            window_seconds=60,
            max_provider_calls=2,
            max_provider_input_bytes=1_000,
            max_tool_calls=1,
            max_task_steps=1,
            max_task_input_bytes=1_000,
        )
        self.store = SQLiteBudgetStore(self.path, self.policy)

    def tearDown(self):
        self.temp.cleanup()

    def test_multi_dimension_reservation_is_atomic_and_principal_scoped(self):
        self.store.reserve_for_principal(
            "alice", {"provider_calls": 1, "provider_input_bytes": 100}, now=NOW,
        )
        self.store.reserve_for_principal(
            "alice", {"provider_calls": 1, "provider_input_bytes": 200}, now=NOW,
        )
        with self.assertRaises(BudgetExceededError) as caught:
            self.store.reserve_for_principal(
                "alice", {"provider_calls": 1, "tool_calls": 1}, now=NOW,
            )
        self.assertEqual(caught.exception.dimension, "provider_calls")
        self.assertFalse(caught.exception.permanent)
        alice = self.store.usage_for_principal("alice", now=NOW)
        bob = self.store.usage_for_principal("bob", now=NOW)
        self.assertEqual(alice.used["provider_calls"], 2)
        self.assertEqual(alice.used["provider_input_bytes"], 300)
        self.assertEqual(alice.used["tool_calls"], 0)
        self.assertEqual(bob.used["provider_calls"], 0)
        self.assertEqual(bob.used["tool_calls"], 0)

    def test_per_principal_policy_override_and_window_reset(self):
        custom = BudgetPolicy(
            window_seconds=120, max_provider_calls=1,
            max_provider_input_bytes=2_000, max_tool_calls=3,
            max_task_steps=4, max_task_input_bytes=3_000,
        )
        self.store.set_policy_for_principal("bob", custom, now=NOW)
        self.assertEqual(self.store.get_policy_for_principal("bob"), custom)
        self.store.reserve_for_principal("bob", {"provider_calls": 1}, now=NOW)
        with self.assertRaises(BudgetExceededError):
            self.store.reserve_for_principal("bob", {"provider_calls": 1}, now=NOW)
        reset = self.store.usage_for_principal("bob", now=NOW).reset_at
        self.store.reserve_for_principal("bob", {"provider_calls": 1}, now=reset)
        self.assertEqual(
            self.store.usage_for_principal("bob", now=reset).used["provider_calls"], 1,
        )
        self.assertEqual(
            self.store.get_policy_for_principal("alice").window_seconds, 60,
        )

    def test_permanent_single_request_over_limit_is_distinguished(self):
        with self.assertRaises(BudgetExceededError) as caught:
            self.store.reserve_for_principal(
                "alice", {"provider_input_bytes": 1_001}, now=NOW,
            )
        self.assertTrue(caught.exception.permanent)
        self.assertEqual(
            self.store.usage_for_principal("alice", now=NOW).used["provider_input_bytes"], 0,
        )

    def test_default_policy_survives_reopen_and_backup_is_private(self):
        self.store.reserve_for_principal(
            "alice", {"tool_calls": 1}, now=NOW,
        )
        reopened = SQLiteBudgetStore(
            self.path,
            BudgetPolicy(max_provider_calls=1, max_tool_calls=1),
        )
        self.assertEqual(reopened.default_policy, self.policy)
        backup = os.path.join(self.temp.name, "budget-backup.sqlite3")
        self.assertEqual(reopened.backup_to(backup), backup)
        restored = SQLiteBudgetStore(backup)
        self.assertEqual(restored.integrity_check(), "ok")
        self.assertEqual(restored.usage_for_principal("alice", now=NOW).used["tool_calls"], 1)
        with self.assertRaises(BudgetValidationError):
            reopened.backup_to(backup)

    def test_budget_reservation_rows_are_append_only(self):
        self.store.reserve_for_principal("alice", {"tool_calls": 1}, now=NOW)
        connection = sqlite3.connect(self.path)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "DELETE FROM budget_reservations WHERE principal_id='alice'"
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE budget_reservations SET amounts_json='{}' WHERE principal_id='alice'"
                )
        finally:
            connection.close()


class ExecutionBudgetIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        if os.name == "posix":
            os.chmod(self.temp.name, 0o700)
        self.policy = BudgetPolicy(
            window_seconds=60, max_provider_calls=1,
            max_provider_input_bytes=10_000, max_tool_calls=1,
            max_task_steps=1, max_task_input_bytes=10_000,
        )
        self.budgets = SQLiteBudgetStore(
            os.path.join(self.temp.name, "budgets.sqlite3"), self.policy,
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_tool_budget_denies_before_second_handler_invocation(self):
        calls = []
        registry = ToolRegistry()
        registry.register(
            ToolSpec("search", "tools:search", SCHEMA),
            lambda args: calls.append(args) or {"ok": True},
        )
        audit = InMemoryAuditSink()
        executor = ToolExecutor(registry, audit, budget_store=self.budgets)
        context = ExecutionContext("alice", frozenset({"tools:search"}))
        self.assertEqual(executor.execute("search", {"query": "first"}, context), {"ok": True})
        with self.assertRaises(ToolBudgetExceededError):
            executor.execute("search", {"query": "second"}, context)
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            [event.status for event in audit.events()],
            ["started", "succeeded", "budget_denied"],
        )

    def test_provider_budget_denies_before_adapter_call(self):
        class Adapter:
            def __init__(self):
                self.calls = 0

            def complete_with_tools(self, session_id, history, tools):
                self.calls += 1
                return AssistantTurn(content="bounded response")

        registry = ToolRegistry()
        executor = ToolExecutor(registry, InMemoryAuditSink())
        orchestrator = ToolOrchestrator(
            Adapter(), ToolExecutionBridge(executor), budget_store=self.budgets,
        )
        context = ExecutionContext("alice", frozenset())
        result = orchestrator.run("session", "hello", (), context)
        self.assertEqual(result.final_text, "bounded response")
        with self.assertRaises(BudgetExceededError):
            orchestrator.run("session", "hello again", (), context)
        self.assertEqual(orchestrator.adapter.calls, 1)
        self.assertEqual(
            self.budgets.usage_for_principal("alice", now=NOW).used["provider_calls"], 1,
        )

    def test_task_budget_defers_without_consuming_attempt_then_resumes(self):
        store = SQLiteTaskStore(os.path.join(self.temp.name, "tasks.sqlite3"))
        calls = []
        engine = TaskEngine(
            store, {}, "budget-worker",
            principal_handlers={
                "collect": lambda data, key, principal: calls.append(principal) or {"ok": True},
            },
            budget_store=self.budgets,
        )
        first = store.create_for_principal("alice", PLAN, "budget-task-1", NOW)
        second = store.create_for_principal("alice", PLAN, "budget-task-2", NOW)
        completed = engine.run_once(now=NOW)
        self.assertEqual(completed.task_id, first.task_id)
        self.assertEqual(completed.state, "succeeded")
        deferred = engine.run_once(now=NOW)
        self.assertEqual(deferred.task_id, second.task_id)
        self.assertEqual(deferred.state, "budget_wait")
        self.assertEqual(deferred.attempts, 0)
        self.assertEqual(len(calls), 1)
        self.assertIsNone(engine.run_once(now=NOW))
        reset = self.budgets.usage_for_principal("alice", now=NOW).reset_at
        resumed = engine.run_once(now=reset)
        self.assertEqual(resumed.task_id, second.task_id)
        self.assertEqual(resumed.state, "succeeded")
        self.assertEqual(len(calls), 2)

    def test_permanently_oversized_task_input_fails_without_running_handler(self):
        tight = BudgetPolicy(
            window_seconds=60, max_provider_calls=1,
            max_provider_input_bytes=1_000, max_tool_calls=1,
            max_task_steps=1, max_task_input_bytes=1,
        )
        budgets = SQLiteBudgetStore(
            os.path.join(self.temp.name, "tight-budgets.sqlite3"), tight,
        )
        store = SQLiteTaskStore(os.path.join(self.temp.name, "tight-tasks.sqlite3"))
        calls = []
        engine = TaskEngine(
            store, {}, "tight-worker",
            principal_handlers={"collect": lambda data, key, principal: calls.append(True)},
            budget_store=budgets,
        )
        task = store.create_for_principal("alice", PLAN, "oversized-task", NOW)
        result = engine.run_once(now=NOW)
        self.assertEqual(result.task_id, task.task_id)
        self.assertEqual(result.state, "failed")
        self.assertEqual(result.error_code, "task_input_budget_exceeded")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
