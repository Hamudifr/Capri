"""Durable worker-registry restart and lifecycle-audit integration tests."""

import os
import tempfile
import threading
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
    def _host(task_store, audit_store, registry=None, load_resolver=None):
        if registry is None:
            registry = SQLiteWorkerRegistry(task_store)
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
            worker_registry=registry,
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
            worker_unreserved_in_flight_resolver=load_resolver or (lambda worker_id: 0),
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


    def test_heartbeat_samples_host_load_after_sqlite_writer_lock_wait(self):
        task_store = SQLiteTaskStore(self.tasks_path)
        audit_store = SQLiteSecurityStore(self.audit_path)
        registry = SQLiteWorkerRegistry(task_store)
        load_samples = 0
        sampled_after_lock = threading.Event()
        blocker_acquired = threading.Event()
        release_blocker = threading.Event()
        blocker = task_store._connect()

        def load_resolver(worker_id):
            nonlocal load_samples
            load_samples += 1
            if load_samples >= 2:
                sampled_after_lock.set()
            return 0

        host = self._host(
            task_store, audit_store, registry=registry, load_resolver=load_resolver,
        )
        host.register_worker(
            "worker-token",
            WorkerDescriptor("worker-1", (1,), ("math.factorial",), max_concurrency=1),
        )
        host.heartbeat_worker("monitor-token", "worker-1")
        original_sweep = registry.active_reservations_with_expired

        def sweep_then_hold_writer():
            result = original_sweep()
            blocker.execute("BEGIN IMMEDIATE")
            blocker_acquired.set()
            if not release_blocker.wait(timeout=3):
                raise RuntimeError("test did not release the SQLite writer lock")
            return result

        registry.active_reservations_with_expired = sweep_then_hold_writer
        errors = []

        def heartbeat():
            try:
                host.heartbeat_worker("monitor-token", "worker-1")
            except Exception as exc:
                errors.append(exc)

        worker = threading.Thread(target=heartbeat)
        worker.start()
        try:
            self.assertTrue(blocker_acquired.wait(timeout=2))
            self.assertFalse(
                sampled_after_lock.wait(timeout=0.15),
                "host load was sampled before the registry acquired its write lock",
            )
        finally:
            release_blocker.set()
        worker.join(timeout=3)
        blocker.close()
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(sampled_after_lock.is_set())
        self.assertEqual(load_samples, 2)
        self.assertEqual(registry.get("worker-1").health.in_flight, 0)
        self.assertEqual(registry.integrity_check(), "ok")
        self.assertFalse(audit_store.worker_lifecycle_reconciliation_required())

    def test_candidate_lookup_audits_expired_reservation_with_local_context(self):
        now = {"value": 1_000_000_000}
        task_store = SQLiteTaskStore(self.tasks_path)
        audit_store = SQLiteSecurityStore(self.audit_path)
        registry = SQLiteWorkerRegistry(
            task_store,
            heartbeat_ttl_ms=5_000,
            reservation_ttl_ms=1_000,
            clock_ns=lambda: now["value"],
            clock_wall_ns=lambda: now["value"],
        )
        host = self._host(task_store, audit_store, registry=registry)
        host.register_worker(
            "worker-token",
            WorkerDescriptor("worker-1", (1,), ("math.factorial",), max_concurrency=1),
        )
        host.heartbeat_worker("monitor-token", "worker-1")
        first_task = task_store.create_for_principal(
            "alice", [{"tool": "collect", "input": {"scope": "first"}}],
        )
        pending = host.reserve_worker_candidate(
            "alice-token", first_task.task_id, "math.factorial", 1,
        )
        self.assertIsNotNone(pending)

        now["value"] += 2_000_000_000
        next_task = task_store.create_for_principal(
            "alice", [{"tool": "collect", "input": {"scope": "next"}}],
        )
        candidates = host.get_worker_candidates(
            "alice-token", next_task.task_id, "math.factorial", 1,
        )
        self.assertEqual(len(candidates), 1)
        self.assertIsNone(registry.get_reservation(pending.reservation.token))
        self.assertTrue(any(
            event.tool_name == "worker.reservation.expired"
            for event in audit_store.events()
        ))
        self.assertFalse(audit_store.worker_lifecycle_reconciliation_required())

    def test_post_restart_heartbeat_audits_expiry_without_local_context(self):
        now = {"value": 1_000_000_000}
        task_store = SQLiteTaskStore(self.tasks_path)
        audit_store = SQLiteSecurityStore(self.audit_path)
        registry = SQLiteWorkerRegistry(
            task_store,
            heartbeat_ttl_ms=5_000,
            reservation_ttl_ms=1_000,
            clock_ns=lambda: now["value"],
            clock_wall_ns=lambda: now["value"],
        )
        host = self._host(task_store, audit_store, registry=registry)
        host.register_worker(
            "worker-token",
            WorkerDescriptor("worker-1", (1,), ("math.factorial",), max_concurrency=1),
        )
        host.heartbeat_worker("monitor-token", "worker-1")
        task = task_store.create_for_principal(
            "alice", [{"tool": "collect", "input": {"scope": "restart-expiry"}}],
        )
        pending = host.reserve_worker_candidate(
            "alice-token", task.task_id, "math.factorial", 1,
        )
        self.assertIsNotNone(pending)

        reopened_tasks = SQLiteTaskStore(self.tasks_path)
        reopened_audit = SQLiteSecurityStore(self.audit_path)
        self.assertTrue(
            reopened_audit.acknowledge_worker_lifecycle_reconciliation(
                "Supervisor reconciled worker identity and load after process restart",
            )
        )
        now["value"] += 2_000_000_000
        reopened_registry = SQLiteWorkerRegistry(
            reopened_tasks,
            heartbeat_ttl_ms=5_000,
            reservation_ttl_ms=1_000,
            clock_ns=lambda: now["value"],
            clock_wall_ns=lambda: now["value"],
        )
        restarted_host = self._host(
            reopened_tasks, reopened_audit, registry=reopened_registry,
        )
        self.assertEqual(restarted_host._worker_reservation_contexts, {})

        restarted_host.heartbeat_worker("monitor-token", "worker-1")
        self.assertIsNone(reopened_registry.get_reservation(pending.reservation.token))
        self.assertTrue(any(
            event.tool_name == "worker.reservation.expired"
            for event in reopened_audit.events()
        ))
        self.assertFalse(reopened_audit.worker_lifecycle_reconciliation_required())


if __name__ == "__main__":
    unittest.main()
