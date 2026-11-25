import os
import sqlite3
import tempfile
import threading
import time
import unittest

from capri_runtime import (
    AssistantTurn,
    CapriHostRuntime,
    CapriHostService,
    ExecutionContext,
    HostAuthorityResolver,
    HostServiceError,
    HostServiceState,
    InMemoryAuditSink,
    RuntimeHealthState,
    SQLiteSessionStore,
    SQLiteTaskStore,
    TaskEngine,
    TaskWorker,
    ToolExecutionBridge,
    ToolExecutor,
    ToolOrchestrator,
    ToolRegistry,
)
from capri_runtime.budgets import SQLiteBudgetStore


class OfflineAdapter:
    def complete_with_tools(self, session_id, history, tools):
        return AssistantTurn(content="offline")


class HostServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        if os.name == "posix":
            os.chmod(self.temp.name, 0o700)
        self.session_store = SQLiteSessionStore(
            os.path.join(self.temp.name, "sessions.sqlite3"),
            max_output_chars=131_072,
        )
        self.task_store = SQLiteTaskStore(
            os.path.join(self.temp.name, "tasks.sqlite3")
        )
        self.authority = HostAuthorityResolver(
            authenticate=lambda credential: (
                {"alice-token": "alice", "bob-token": "bob"}.get(credential)
            ),
            permissions_for=lambda principal_id: (),
        )
        executor = ToolExecutor(ToolRegistry(), InMemoryAuditSink())
        self.orchestrator = ToolOrchestrator(
            OfflineAdapter(), ToolExecutionBridge(executor),
        )

    def tearDown(self):
        self.temp.cleanup()

    def make_host(self, **kwargs):
        return CapriHostRuntime(
            self.authority,
            self.session_store,
            self.orchestrator,
            **kwargs,
        )

    def test_service_lifecycle_is_explicit_idempotent_and_health_is_read_only(self):
        host = self.make_host()
        service = CapriHostService(host)
        initial = service.health()
        self.assertEqual(initial.service_state, HostServiceState.NEW)
        self.assertEqual(initial.status, RuntimeHealthState.UNAVAILABLE)
        self.assertFalse(initial.worker_alive)

        started = service.start()
        self.assertEqual(started.service_state, HostServiceState.RUNNING)
        self.assertEqual(started.status, RuntimeHealthState.HEALTHY)
        self.assertEqual(dict(started.components)["sessions"], "healthy")
        self.assertEqual(dict(started.components)["tasks"], "not_configured")
        self.assertTrue(service.is_running)
        self.assertTrue(service.start().healthy)

        stopped = service.stop()
        self.assertEqual(stopped.service_state, HostServiceState.STOPPED)
        self.assertFalse(service.is_running)
        self.assertTrue(service.shutdown_complete)
        self.assertEqual(stopped.status, RuntimeHealthState.UNAVAILABLE)

        restarted = service.start()
        self.assertEqual(restarted.service_state, HostServiceState.RUNNING)
        self.assertTrue(restarted.healthy)
        service.stop()

    def test_worker_is_not_started_by_construction_and_stop_is_cooperative(self):
        handler_started = threading.Event()
        release_handler = threading.Event()

        def wait_handler(arguments, idempotency_key, principal_id):
            handler_started.set()
            release_handler.wait(3)
            return {"ok": True}

        engine = TaskEngine(
            self.task_store,
            {},
            "service-worker",
            principal_handlers={"wait": wait_handler},
        )
        worker = TaskWorker(
            engine, poll_interval_seconds=0.05, heartbeat_interval_seconds=0.1,
        )
        host = self.make_host(task_worker=worker)
        task = host.create_task(
            "alice-token",
            [{"tool": "wait", "input": {}, "max_attempts": 1}],
            "service-wait-task",
        )
        service = CapriHostService(host)

        initial = service.health()
        self.assertEqual(initial.service_state, HostServiceState.NEW)
        self.assertTrue(initial.worker_configured)
        self.assertFalse(initial.worker_alive)

        started = service.start()
        self.assertTrue(started.worker_alive)
        self.assertTrue(handler_started.wait(2))

        pending = service.stop(timeout_seconds=0.05)
        self.assertEqual(pending.service_state, HostServiceState.STOPPING)
        self.assertTrue(pending.worker_alive)
        self.assertFalse(service.shutdown_complete)

        release_handler.set()
        stopped = service.stop(timeout_seconds=2)
        self.assertEqual(stopped.service_state, HostServiceState.STOPPED)
        self.assertFalse(stopped.worker_alive)
        self.assertTrue(service.shutdown_complete)
        self.assertEqual(host.get_task("alice-token", task.task_id).state, "succeeded")

    def test_worker_failure_is_redacted_and_marks_service_degraded(self):
        class FailingTaskStore(SQLiteTaskStore):
            def claim_next(self, *args, **kwargs):
                raise RuntimeError("sensitive database detail")

        store = FailingTaskStore(os.path.join(self.temp.name, "failing-tasks.sqlite3"))
        engine = TaskEngine(store, {}, "failing-worker")
        worker = TaskWorker(
            engine, poll_interval_seconds=0.05, heartbeat_interval_seconds=0.1,
        )
        service = CapriHostService(self.make_host(task_worker=worker))
        service.start()

        deadline = time.monotonic() + 2
        health = service.health()
        while health.service_state is not HostServiceState.FAILED and time.monotonic() < deadline:
            time.sleep(0.01)
            health = service.health()

        self.assertEqual(health.service_state, HostServiceState.FAILED)
        self.assertEqual(health.status, RuntimeHealthState.DEGRADED)
        self.assertEqual(health.failure_code, "task_worker_failed")
        self.assertEqual(dict(health.components)["task_worker"], "failed")
        self.assertNotIn("sensitive database detail", str(health.as_dict()))
        service.stop(timeout_seconds=1)
        self.assertTrue(service.shutdown_complete)

    def test_budget_ledger_tampering_degrades_runtime_health(self):
        budgets = SQLiteBudgetStore(
            os.path.join(self.temp.name, "health-budgets.sqlite3")
        )
        budgets.reserve_for_principal("alice", {"tool_calls": 1})
        connection = sqlite3.connect(budgets.path)
        try:
            connection.execute(
                "UPDATE budget_usage SET used=0 WHERE principal_id='alice' AND dimension='tool_calls'"
            )
            connection.commit()
        finally:
            connection.close()

        service = CapriHostService(self.make_host(budget_store=budgets))
        started = service.start()
        self.assertEqual(started.status, RuntimeHealthState.DEGRADED)
        self.assertEqual(dict(started.components)["budgets"], "degraded")
        service.stop()

    def test_invalid_shutdown_timeout_is_rejected(self):
        service = CapriHostService(self.make_host())
        with self.assertRaises(HostServiceError):
            service.stop(float("inf"))
        with self.assertRaises(HostServiceError):
            service.stop(-1)


if __name__ == "__main__":
    unittest.main()
