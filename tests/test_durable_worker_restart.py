"""Durable worker-registry restart and lifecycle-audit integration tests."""

import os
import tempfile
import unittest

from capri_runtime import (
    AssistantTurn,
    HostAuthorityResolver,
    InMemoryAuditSink,
    SQLiteSecurityStore,
    SQLiteSessionStore,
    SQLiteTaskStore,
    SQLiteWorkerRegistry,
    ToolExecutionBridge,
    ToolExecutor,
    ToolOrchestrator,
    ToolRegistry,
    WorkerDescriptor,
)
from capri_runtime.host_runtime import CapriHostRuntime, HostRuntimeError


class _Adapter:
    def complete_with_tools(self, session_id, history, tools):
        return AssistantTurn(content="restart-test")


class DurableWorkerRestartTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        if os.name == "posix":
            os.chmod(self.temp.name, 0o700)
        self.sessions_path = os.path.join(self.temp.name, "sessions.sqlite3")
        self.tasks_path = os.path.join(self.temp.name, "tasks.sqlite3")
        self.audit_path = os.path.join(self.temp.name, "worker-audit.sqlite3")

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _authority():
        return HostAuthorityResolver(
            authenticate=lambda credential: (
                {"alice-token": "alice"}.get(credential)
            ),
            permissions_for=lambda principal_id: (),
        )

    @staticmethod
    def _host(task_store, audit_store):
        sessions = SQLiteSessionStore(
            os.path.join(os.path.dirname(task_store.path), "sessions.sqlite3"),
            max_output_chars=131_072,
        )
        bridge = ToolExecutionBridge(
            ToolExecutor(ToolRegistry(), InMemoryAuditSink())
        )
        orchestrator = ToolOrchestrator(_Adapter(), bridge)
        return CapriHostRuntime(
            DurableWorkerRestartTests._authority(),
            sessions,
            orchestrator,
            task_store=task_store,
            worker_registry=SQLiteWorkerRegistry(task_store),
            worker_identity_resolver=lambda credential: (
                {"worker-token": "worker-1"}.get(credential)
            ),
            worker_descriptor_resolver=lambda worker_id, proposed: WorkerDescriptor(
                worker_id, (1,), ("math.factorial",), priority=5,
                max_concurrency=1, enabled=True, revision=1,
            ),
            worker_observer_authorizer=lambda credential, worker_id: (
                credential == "monitor-token" and worker_id == "worker-1"
            ),
            worker_unreserved_in_flight_resolver=lambda worker_id: 0,
            worker_policy_resolver=lambda principal_id, task_id, capability: {"worker-1"},
            worker_lifecycle_audit_sink=audit_store,
        )

    def test_restart_requires_durable_supervisor_reconciliation_before_recovery(self):
        task_store = SQLiteTaskStore(self.tasks_path)
        audit_store = SQLiteSecurityStore(self.audit_path)
        host = self._host(task_store, audit_store)

        host.register_worker(
            "worker-token",
            WorkerDescriptor("worker-1", (1,), ("math.factorial",), max_concurrency=1),
        )
        host.heartbeat_worker("monitor-token", "worker-1")
        task = task_store.create_for_principal(
            "alice", [{"tool": "collect", "input": {"scope": "restart"}}],
        )
        pending = host.reserve_worker_candidate(
            "alice-token", task.task_id, "math.factorial", 1,
        )
        self.assertIsNotNone(pending)
        self.assertTrue(audit_store.worker_lifecycle_reconciliation_required())

        # Simulate a process restart by reopening both durable stores.
        reopened_tasks = SQLiteTaskStore(self.tasks_path)
        reopened_audit = SQLiteSecurityStore(self.audit_path)
        self.assertTrue(reopened_audit.worker_lifecycle_reconciliation_required())

        with self.assertRaisesRegex(
            HostRuntimeError, "pending operations or reservations"
        ):
            self._host(reopened_tasks, reopened_audit)

        self.assertTrue(
            reopened_audit.acknowledge_worker_lifecycle_reconciliation(
                "Supervisor verified worker identity and actual in-flight load after restart",
            )
        )
        self.assertFalse(reopened_audit.worker_lifecycle_reconciliation_required())

        recovered_host = self._host(reopened_tasks, reopened_audit)
        recovered = recovered_host.get_worker_reservation_for_task(
            "alice-token", task.task_id,
        )
        self.assertIsNotNone(recovered)
        self.assertEqual(recovered.reservation.token, pending.reservation.token)
        self.assertEqual(recovered.principal_id, "alice")
        self.assertEqual(recovered.task_id, task.task_id)

        committed = recovered_host.commit_worker_reservation(
            "alice-token", "monitor-token", recovered,
        )
        self.assertTrue(committed.reservation.committed)
        self.assertTrue(
            recovered_host.release_worker_reservation("monitor-token", committed)
        )
        self.assertFalse(reopened_audit.worker_lifecycle_reconciliation_required())
        self.assertIsNone(
            SQLiteWorkerRegistry(reopened_tasks).get_reservation(pending.reservation.token)
        )
        event_types = [event.tool_name for event in reopened_audit.events()]
        self.assertIn("worker.reconciliation.acknowledged", event_types)
        self.assertIn("worker.reservation.committed", event_types)
        self.assertIn("worker.reservation.released", event_types)


if __name__ == "__main__":
    unittest.main()
