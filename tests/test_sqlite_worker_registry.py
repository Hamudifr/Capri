import os
import sqlite3
import tempfile
import threading
import unittest

from capri_runtime.sqlite_worker_registry import SQLiteWorkerRegistry
from capri_runtime.tasks import SQLiteTaskStore
from capri_runtime.worker_registry import (
    WorkerConflictError,
    WorkerDescriptor,
    WorkerRegistryError,
)


class FakeClock:
    def __init__(self):
        self.mono_ns = 10_000_000_000
        self.wall_ns = 1_800_000_000_000_000_000

    def monotonic_ns(self):
        return self.mono_ns

    def wall_time_ns(self):
        return self.wall_ns

    def advance_ms(self, milliseconds):
        delta = milliseconds * 1_000_000
        self.mono_ns += delta
        self.wall_ns += delta


class SQLiteWorkerRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "tasks.sqlite3")
        self.clock = FakeClock()
        self.store = SQLiteTaskStore(self.path)
        self.registry = self.make_registry(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def make_registry(self, store):
        return SQLiteWorkerRegistry(
            store,
            heartbeat_ttl_ms=5_000,
            reservation_ttl_ms=1_000,
            max_reservations=16,
            clock_ns=self.clock.monotonic_ns,
            clock_wall_ns=self.clock.wall_time_ns,
        )

    def descriptor(self, worker_id="worker-1", max_concurrency=2, **changes):
        values = {
            "worker_id": worker_id,
            "protocol_versions": (1,),
            "capabilities": ("math.factorial",),
            "max_concurrency": max_concurrency,
        }
        values.update(changes)
        return WorkerDescriptor(**values)

    def register_healthy(self, registry=None, worker_id="worker-1", max_concurrency=2):
        registry = registry or self.registry
        registry.register(
            self.descriptor(worker_id, max_concurrency),
            authenticated_worker_id=worker_id,
        )
        return registry.heartbeat(
            worker_id,
            authenticated_worker_id=worker_id,
            in_flight=0,
        )

    def reserve(self, registry, task_id, principal_id="alice"):
        return registry.reserve_eligible(
            "math.factorial",
            protocol_version=1,
            authorized_worker_ids={"worker-1"},
            principal_id=principal_id,
            task_id=task_id,
        )

    def test_worker_and_active_reservation_survive_registry_reopen(self):
        self.register_healthy()
        pending = self.reserve(self.registry, "task-1")
        self.assertIsNotNone(pending)

        reopened_store = SQLiteTaskStore(self.path)
        reopened = self.make_registry(reopened_store)
        snapshot = reopened.get("worker-1")
        recovered = reopened.get_reservation_for_task("alice", "task-1")

        self.assertEqual(snapshot.descriptor.worker_id, "worker-1")
        self.assertEqual(snapshot.health.state, "healthy")
        self.assertEqual(recovered.token, pending.token)
        self.assertEqual(recovered.principal_id, "alice")
        self.assertEqual(recovered.task_id, "task-1")
        self.assertFalse(recovered.committed)
        self.assertEqual(reopened.integrity_check(), "ok")

    def test_commit_and_release_are_durable_and_capacity_safe(self):
        self.register_healthy(max_concurrency=2)
        first = self.reserve(self.registry, "task-1")
        second = self.reserve(self.registry, "task-2")
        committed_first = self.registry.commit_reservation(
            first, authenticated_worker_id="worker-1",
        )
        committed_second = self.registry.commit_reservation(
            second, authenticated_worker_id="worker-1",
        )
        self.assertTrue(committed_first.committed)
        self.assertTrue(committed_second.committed)

        reopened = self.make_registry(SQLiteTaskStore(self.path))
        recovered_first = reopened.get_reservation_for_task("alice", "task-1")
        self.assertTrue(recovered_first.committed)

        # The first task has completed; only unreserved work is reported as 0.
        self.assertTrue(reopened.release_reservation(
            recovered_first,
            authenticated_worker_id="worker-1",
            observed_unreserved_in_flight=0,
        ))
        third = self.reserve(reopened, "task-3")
        self.assertIsNotNone(third)
        self.assertEqual(reopened.get("worker-1").health.in_flight, 0)

    def test_one_active_reservation_per_principal_task(self):
        self.register_healthy()
        first = self.reserve(self.registry, "task-1")
        self.assertIsNotNone(first)
        with self.assertRaises(WorkerConflictError):
            self.reserve(self.registry, "task-1")
        self.assertEqual(
            self.registry.get_reservation_for_task("alice", "task-1"),
            first,
        )

    def test_commit_revalidates_capacity_after_external_load_changes(self):
        self.register_healthy(max_concurrency=1)
        pending = self.reserve(self.registry, "task-1")
        self.registry.heartbeat(
            "worker-1",
            authenticated_worker_id="worker-1",
            in_flight=1,
        )
        self.assertIsNone(self.registry.commit_reservation(
            pending, authenticated_worker_id="worker-1",
        ))
        self.assertIsNone(self.registry.get_reservation(pending.token))
        events = self.registry.events_for_worker("worker-1")
        self.assertTrue(any(
            event["event_type"] == "reservation_revoked"
            and event["payload"]["reason"] == "commit_reservation"
            for event in events
        ))

    def test_pending_expiry_is_persisted_and_committed_holds_do_not_expire(self):
        self.register_healthy(max_concurrency=2)
        pending = self.reserve(self.registry, "task-expiring")
        self.clock.advance_ms(1_001)
        self.assertIsNone(self.registry.get_reservation(pending.token))
        event_types = [event["event_type"] for event in self.registry.events_for_worker("worker-1")]
        self.assertIn("reservation_expired", event_types)

        # A fresh reservation can be committed and remains held beyond its TTL.
        pending2 = self.reserve(self.registry, "task-committed")
        committed = self.registry.commit_reservation(
            pending2, authenticated_worker_id="worker-1",
        )
        self.clock.advance_ms(60_000)
        reopened = self.make_registry(SQLiteTaskStore(self.path))
        recovered = reopened.get_reservation_for_task("alice", "task-committed")
        self.assertTrue(recovered.committed)
        self.assertEqual(recovered.token, committed.token)

    def test_two_registry_instances_cannot_overbook_one_capacity_slot(self):
        self.register_healthy(max_concurrency=1)
        second_store = SQLiteTaskStore(self.path)
        second_registry = self.make_registry(second_store)
        barrier = threading.Barrier(2)
        outcomes = []

        def reserve(registry, task_id):
            barrier.wait()
            outcomes.append(self.reserve(registry, task_id))

        threads = [
            threading.Thread(target=reserve, args=(self.registry, "task-a")),
            threading.Thread(target=reserve, args=(second_registry, "task-b")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(sum(item is not None for item in outcomes), 1)
        self.assertEqual(self.registry.integrity_check(), "ok")

    def test_audit_events_are_append_only_and_hash_chain_is_verified(self):
        self.register_healthy()
        events = self.registry.events_for_worker("worker-1")
        self.assertTrue(events)
        connection = self.store._connect()
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE worker_registry_events SET event_type='tampered' WHERE sequence=1"
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "DELETE FROM worker_registry_events WHERE sequence=1"
                )
        finally:
            connection.close()
        self.assertEqual(self.registry.integrity_check(), "ok")

    def test_backup_restore_preserves_registry_and_detects_audit_tampering(self):
        self.register_healthy()
        pending = self.reserve(self.registry, "task-1")
        backup_path = os.path.join(self.temp.name, "registry-backup.sqlite3")
        self.store.backup_to(backup_path)

        restored_store = SQLiteTaskStore(backup_path)
        restored = self.make_registry(restored_store)
        self.assertEqual(restored.get("worker-1").health.state, "healthy")
        self.assertEqual(
            restored.get_reservation_for_task("alice", "task-1").token,
            pending.token,
        )
        self.assertEqual(restored.integrity_check(), "ok")

        connection = sqlite3.connect(backup_path)
        try:
            connection.execute("DROP TRIGGER worker_registry_events_immutable_update")
            connection.execute(
                "UPDATE worker_registry_events SET payload_json='{}' WHERE sequence=1"
            )
            connection.commit()
        finally:
            connection.close()
        tampered_store = SQLiteTaskStore(backup_path)
        self.assertEqual(tampered_store.integrity_check(), "task store validation failed")

    def test_missing_active_reservation_unique_index_fails_closed(self):
        connection = self.store._connect()
        try:
            connection.execute("DROP INDEX worker_registry_one_active_task_reservation")
            connection.commit()
        finally:
            connection.close()

        self.assertEqual(self.registry.integrity_check(), "worker registry validation failed")
        with self.assertRaises(WorkerRegistryError):
            self.make_registry(SQLiteTaskStore(self.path))

    def test_missing_reservation_foreign_key_fails_closed(self):
        connection = self.store._connect()
        try:
            connection.execute("PRAGMA foreign_keys=OFF")
            connection.execute(
                "ALTER TABLE worker_registry_reservations "
                "RENAME TO worker_registry_reservations_old"
            )
            connection.execute(
                """
                CREATE TABLE worker_registry_reservations (
                    token TEXT PRIMARY KEY,
                    worker_id TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    protocol_version INTEGER NOT NULL,
                    descriptor_revision INTEGER NOT NULL,
                    expires_at_wall_ns INTEGER NOT NULL,
                    committed INTEGER NOT NULL CHECK(committed IN (0, 1)),
                    revision INTEGER NOT NULL,
                    created_at_wall_ns INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT INTO worker_registry_reservations SELECT * "
                "FROM worker_registry_reservations_old"
            )
            connection.execute("DROP TABLE worker_registry_reservations_old")
            connection.execute(
                "CREATE UNIQUE INDEX worker_registry_one_active_task_reservation "
                "ON worker_registry_reservations(principal_id, task_id)"
            )
            connection.execute(
                "CREATE INDEX worker_registry_reservations_worker_idx "
                "ON worker_registry_reservations(worker_id)"
            )
            connection.commit()
        finally:
            connection.close()

        self.assertEqual(self.registry.integrity_check(), "worker registry validation failed")
        with self.assertRaises(WorkerRegistryError):
            self.make_registry(SQLiteTaskStore(self.path))

    def test_wall_clock_rollback_fails_worker_freshness_closed(self):
        self.register_healthy()
        self.clock.wall_ns -= 1_000_000_000
        self.assertEqual(
            self.registry.eligible(
                "math.factorial",
                protocol_version=1,
                authorized_worker_ids={"worker-1"},
            ),
            (),
        )


if __name__ == "__main__":
    unittest.main()
