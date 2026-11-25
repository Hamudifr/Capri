import os
import time
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

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
    TaskWorker,
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

    def test_usage_read_reuses_one_connection_for_policy_and_usage(self):
        self.store.reserve_for_principal(
            "alice", {"provider_calls": 1, "tool_calls": 1}, now=NOW,
        )
        custom = BudgetPolicy(
            window_seconds=120, max_provider_calls=3,
            max_provider_input_bytes=2_000, max_tool_calls=4,
            max_task_steps=5, max_task_input_bytes=3_000,
        )
        self.store.set_policy_for_principal("alice", custom, now=NOW)
        original_connect = self.store._connect
        with patch.object(self.store, "_connect", wraps=original_connect) as connect:
            usage = self.store.usage_for_principal("alice", now=NOW)
        self.assertEqual(connect.call_count, 1)
        self.assertEqual(usage.policy, custom)
        self.assertEqual(usage.used["provider_calls"], 1)
        self.assertEqual(usage.used["tool_calls"], 1)
        self.assertEqual(usage.reset_at.timestamp() - NOW.timestamp(), 120)

    def test_multi_dimension_reservation_reads_usage_with_one_query(self):
        statements = []
        original_connect = self.store._connect

        def traced_connect():
            connection = original_connect()
            connection.set_trace_callback(statements.append)
            return connection

        with patch.object(self.store, "_connect", side_effect=traced_connect):
            self.store.reserve_for_principal(
                "alice",
                {"provider_calls": 1, "provider_input_bytes": 100, "tool_calls": 1,
                 "task_steps": 1, "task_input_bytes": 100},
                now=NOW,
            )
        usage_reads = [
            statement for statement in statements
            if "SELECT dimension,used FROM budget_usage" in statement
        ]
        self.assertEqual(len(usage_reads), 1)
        usage = self.store.usage_for_principal("alice", now=NOW)
        self.assertEqual(usage.used["provider_calls"], 1)
        self.assertEqual(usage.used["provider_input_bytes"], 100)
        self.assertEqual(usage.used["tool_calls"], 1)
        self.assertEqual(usage.used["task_steps"], 1)
        self.assertEqual(usage.used["task_input_bytes"], 100)

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

    def test_default_budget_metadata_is_immutable(self):
        connection = sqlite3.connect(self.path)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE budget_meta SET value='{}' WHERE key='default_policy'"
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "DELETE FROM budget_meta WHERE key='default_policy'"
                )
        finally:
            connection.close()

    def test_sqlite_connections_enable_durable_private_trigger_settings(self):
        connection = self.store._connect()
        try:
            self.assertEqual(connection.execute("PRAGMA synchronous").fetchone()[0], 2)
            self.assertEqual(connection.execute("PRAGMA recursive_triggers").fetchone()[0], 1)
            self.assertEqual(connection.execute("PRAGMA trusted_schema").fetchone()[0], 0)
        finally:
            connection.close()

    def test_integrity_check_detects_usage_ledger_mismatch(self):
        self.store.reserve_for_principal("alice", {"tool_calls": 1}, now=NOW)
        connection = sqlite3.connect(self.path)
        try:
            connection.execute(
                "UPDATE budget_usage SET used=0 WHERE principal_id='alice' AND dimension='tool_calls'"
            )
            connection.commit()
        finally:
            connection.close()
        self.assertEqual(self.store.integrity_check(), "budget ledger validation failed")

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


    def test_concurrent_connections_cannot_over_reserve_a_principal(self):
        self.store.set_policy_for_principal(
            "alice",
            BudgetPolicy(
                window_seconds=60, max_provider_calls=10,
                max_provider_input_bytes=10_000, max_tool_calls=3,
                max_task_steps=10, max_task_input_bytes=10_000,
            ),
            now=NOW,
        )
        stores = [SQLiteBudgetStore(self.path) for _ in range(10)]

        def reserve(store):
            try:
                store.reserve_for_principal("alice", {"tool_calls": 1}, now=NOW)
                return "reserved"
            except BudgetExceededError:
                return "denied"

        with ThreadPoolExecutor(max_workers=10) as pool:
            outcomes = list(pool.map(reserve, stores))
        self.assertEqual(outcomes.count("reserved"), 3)
        self.assertEqual(outcomes.count("denied"), 7)
        self.assertEqual(
            self.store.usage_for_principal("alice", now=NOW).used["tool_calls"], 3,
        )


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
            self.budgets.usage_for_principal("alice").used["provider_calls"], 1,
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
        second = store.create_for_principal("alice", PLAN, "budget-task-2", NOW + timedelta(seconds=1))
        completed = engine.run_once(now=NOW)
        self.assertEqual(completed.task_id, first.task_id)
        self.assertEqual(completed.state, "succeeded")
        deferred = engine.run_once(now=NOW + timedelta(seconds=1))
        self.assertEqual(deferred.task_id, second.task_id)
        self.assertEqual(deferred.state, "budget_wait")
        self.assertEqual(deferred.attempts, 0)
        self.assertEqual(store.events(second.task_id)[-1]["attempt"], 1)
        self.assertEqual(len(calls), 1)
        self.assertIsNone(engine.run_once(now=NOW + timedelta(seconds=1)))
        reset = self.budgets.usage_for_principal("alice", now=NOW + timedelta(seconds=1)).reset_at
        self.assertIsNone(store.claim_next(
            "unbudgeted-worker", now=reset, principal_tools=frozenset({"collect"}),
        ))
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


    def test_managed_worker_resumes_budget_wait_tasks(self):
        store = SQLiteTaskStore(os.path.join(self.temp.name, "worker-tasks.sqlite3"))
        calls = []
        task = store.create_for_principal("alice", PLAN, "worker-budget-wait", datetime.now(timezone.utc))
        now = datetime.now(timezone.utc)
        claim = store.claim_next(
            "budget-worker", now=now, principal_tools=frozenset({"collect"}),
        )
        self.assertIsNotNone(claim)
        deferred = store.defer_claim_for_budget(
            claim, now + timedelta(seconds=0.1), now=now,
        )
        self.assertEqual(deferred.state, "budget_wait")
        time.sleep(0.15)
        engine = TaskEngine(
            store, {}, "budget-worker",
            principal_handlers={
                "collect": lambda data, key, principal: calls.append(principal) or {"ok": True},
            },
            budget_store=self.budgets,
        )
        result = TaskWorker(
            engine, poll_interval_seconds=0.05, heartbeat_interval_seconds=0.1,
        ).run_once()
        self.assertEqual(result.task_id, task.task_id)
        self.assertEqual(result.state, "succeeded")
        self.assertEqual(calls, ["alice"])


if __name__ == "__main__":
    unittest.main()
