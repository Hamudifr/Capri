import threading
import unittest
from dataclasses import replace

from capri_runtime.worker_registry import (
    InMemoryWorkerRegistry,
    WorkerConflictError,
    WorkerDescriptor,
    WorkerNotFoundError,
    WorkerRegistryError,
)


class WorkerRegistryTests(unittest.TestCase):
    def setUp(self):
        self.now = 10_000_000_000
        self.registry = InMemoryWorkerRegistry(
            heartbeat_ttl_ms=5_000,
            failure_threshold=2,
            clock_ns=lambda: self.now,
        )

    def descriptor(self, worker_id="worker-1", **changes):
        values = {
            "worker_id": worker_id,
            "protocol_versions": (1,),
            "capabilities": ("math.factorial",),
            "priority": 0,
            "max_concurrency": 2,
        }
        values.update(changes)
        return WorkerDescriptor(**values)

    def register_healthy(self, worker_id="worker-1", **changes):
        descriptor = self.descriptor(worker_id, **changes)
        self.registry.register(descriptor, authenticated_worker_id=worker_id, now_ns=self.now)
        return self.registry.heartbeat(
            worker_id,
            authenticated_worker_id=worker_id,
            in_flight=0,
            now_ns=self.now,
        )

    def eligible_ids(self, **kwargs):
        return [
            item.descriptor.worker_id
            for item in self.registry.eligible(
                "math.factorial",
                protocol_version=1,
                authorized_worker_ids={"worker-1", "worker-2", "worker-3"},
                now_ns=self.now,
                **kwargs,
            )
        ]

    def test_registration_starts_ineligible_until_authenticated_heartbeat(self):
        snapshot = self.registry.register(
            self.descriptor(), authenticated_worker_id="worker-1", now_ns=self.now,
        )
        self.assertEqual(snapshot.health.state, "starting")
        self.assertEqual(self.eligible_ids(), [])
        healthy = self.registry.heartbeat(
            "worker-1", authenticated_worker_id="worker-1",
            in_flight=0, now_ns=self.now,
        )
        self.assertEqual(healthy.health.state, "healthy")
        self.assertEqual(self.eligible_ids(), ["worker-1"])

    def test_registration_rejects_identity_mismatch(self):
        with self.assertRaises(WorkerRegistryError):
            self.registry.register(
                self.descriptor(), authenticated_worker_id="worker-2", now_ns=self.now,
            )
        with self.assertRaises(WorkerNotFoundError):
            self.registry.get("worker-1")

    def test_duplicate_registration_is_rejected(self):
        self.registry.register(self.descriptor(), authenticated_worker_id="worker-1")
        with self.assertRaises(WorkerConflictError):
            self.registry.register(self.descriptor(), authenticated_worker_id="worker-1")

    def test_registry_capacity_is_bounded(self):
        registry = InMemoryWorkerRegistry(max_workers=1, clock_ns=lambda: self.now)
        registry.register(self.descriptor("worker-1"), authenticated_worker_id="worker-1")
        with self.assertRaises(WorkerRegistryError):
            registry.register(self.descriptor("worker-2"), authenticated_worker_id="worker-2")

    def test_descriptor_rejects_invalid_fields_and_boolean_integers(self):
        invalid = (
            {"priority": True},
            {"max_concurrency": True},
            {"revision": True},
            {"protocol_versions": (True,)},
            {"protocol_versions": ()},
            {"capabilities": ()},
            {"capabilities": ("Math.Factorial",)},
            {"capabilities": ("math.factorial", "math.factorial")},
            {"enabled": 1},
        )
        for changes in invalid:
            with self.subTest(changes=changes):
                with self.assertRaises(WorkerRegistryError):
                    self.descriptor(**changes)

    def test_only_host_policy_allowlisted_workers_are_returned(self):
        self.register_healthy("worker-1")
        self.register_healthy("worker-2")
        result = self.registry.eligible(
            "math.factorial", protocol_version=1,
            authorized_worker_ids={"worker-2"}, now_ns=self.now,
        )
        self.assertEqual([x.descriptor.worker_id for x in result], ["worker-2"])

    def test_capability_and_protocol_compatibility_are_filters(self):
        self.register_healthy("worker-1")
        self.register_healthy(
            "worker-2", capabilities=("text.summarize",), protocol_versions=(2,),
        )
        self.assertEqual(self.eligible_ids(), ["worker-1"])
        result = self.registry.eligible(
            "math.factorial", protocol_version=2,
            authorized_worker_ids={"worker-1", "worker-2"}, now_ns=self.now,
        )
        self.assertEqual(result, ())

    def test_deterministic_order_uses_priority_load_then_worker_id(self):
        self.register_healthy("worker-b", priority=5)
        self.register_healthy("worker-a", priority=5)
        self.register_healthy("worker-c", priority=9)
        self.registry.heartbeat(
            "worker-a", authenticated_worker_id="worker-a",
            in_flight=1, now_ns=self.now,
        )
        self.registry.heartbeat(
            "worker-b", authenticated_worker_id="worker-b",
            in_flight=0, now_ns=self.now,
        )
        self.assertEqual(self.eligible_ids(), ["worker-c", "worker-b", "worker-a"])

    def test_stale_and_future_heartbeats_fail_closed(self):
        self.register_healthy()
        stale_now = self.now + 5_000_000_001
        self.assertEqual(
            self.registry.eligible(
                "math.factorial", protocol_version=1,
                authorized_worker_ids={"worker-1"}, now_ns=stale_now,
            ),
            (),
        )
        self.registry.heartbeat(
            "worker-1", authenticated_worker_id="worker-1",
            in_flight=0, now_ns=self.now + 100,
        )
        self.assertEqual(
            self.registry.eligible(
                "math.factorial", protocol_version=1,
                authorized_worker_ids={"worker-1"}, now_ns=self.now,
            ),
            (),
        )

    def test_capacity_exhausted_worker_is_not_eligible(self):
        self.register_healthy(max_concurrency=1)
        self.registry.heartbeat(
            "worker-1", authenticated_worker_id="worker-1",
            in_flight=1, now_ns=self.now,
        )
        self.assertEqual(self.eligible_ids(), [])

    def test_failure_threshold_degrades_then_marks_unavailable(self):
        self.register_healthy()
        degraded = self.registry.record_failure(
            "worker-1", authenticated_worker_id="worker-1",
        )
        self.assertEqual(degraded.health.state, "degraded")
        self.assertEqual(self.eligible_ids(), [])
        unavailable = self.registry.record_failure(
            "worker-1", authenticated_worker_id="worker-1",
        )
        self.assertEqual(unavailable.health.state, "unavailable")
        self.assertEqual(unavailable.health.consecutive_failures, 2)

    def test_fresh_authenticated_heartbeat_recovers_unavailable_worker(self):
        self.register_healthy()
        self.registry.record_failure("worker-1", authenticated_worker_id="worker-1")
        self.registry.record_failure("worker-1", authenticated_worker_id="worker-1")
        recovered = self.registry.heartbeat(
            "worker-1", authenticated_worker_id="worker-1",
            in_flight=0, now_ns=self.now + 1,
        )
        self.assertEqual(recovered.health.state, "healthy")
        self.assertEqual(recovered.health.consecutive_failures, 0)

    def test_worker_cannot_claim_another_identity_or_overflow_capacity(self):
        self.registry.register(
            self.descriptor(max_concurrency=1), authenticated_worker_id="worker-1",
        )
        with self.assertRaises(WorkerRegistryError):
            self.registry.heartbeat(
                "worker-1", authenticated_worker_id="worker-2",
                in_flight=0, now_ns=self.now,
            )
        with self.assertRaises(WorkerRegistryError):
            self.registry.heartbeat(
                "worker-1", authenticated_worker_id="worker-1",
                in_flight=2, now_ns=self.now,
            )

    def test_quarantine_requires_explicit_compare_and_swap_recovery(self):
        healthy = self.register_healthy()
        quarantined = self.registry.quarantine(
            "worker-1", expected_health_revision=healthy.health.revision,
        )
        self.assertEqual(quarantined.health.state, "quarantined")
        with self.assertRaises(WorkerConflictError):
            self.registry.heartbeat(
                "worker-1", authenticated_worker_id="worker-1",
                in_flight=0, now_ns=self.now,
            )
        with self.assertRaises(WorkerConflictError):
            self.registry.clear_quarantine(
                "worker-1", expected_health_revision=healthy.health.revision,
            )
        reset = self.registry.clear_quarantine(
            "worker-1", expected_health_revision=quarantined.health.revision,
        )
        self.assertEqual(reset.health.state, "starting")
        self.assertIsNone(reset.health.last_heartbeat_ns)
        self.assertEqual(self.eligible_ids(), [])

    def test_retired_worker_is_permanently_ineligible(self):
        healthy = self.register_healthy()
        retired = self.registry.retire(
            "worker-1", expected_health_revision=healthy.health.revision,
        )
        self.assertEqual(retired.health.state, "retired")
        self.assertFalse(retired.descriptor.enabled)
        self.assertEqual(self.eligible_ids(), [])
        with self.assertRaises(WorkerConflictError):
            self.registry.heartbeat(
                "worker-1", authenticated_worker_id="worker-1",
                in_flight=0, now_ns=self.now,
            )

    def test_descriptor_updates_use_revision_compare_and_swap(self):
        self.register_healthy()
        updated = self.registry.update_descriptor(
            self.descriptor(priority=10, revision=2),
            authenticated_worker_id="worker-1",
            expected_revision=1,
        )
        self.assertEqual(updated.descriptor.revision, 2)
        with self.assertRaises(WorkerConflictError):
            self.registry.update_descriptor(
                self.descriptor(priority=20, revision=3),
                authenticated_worker_id="worker-1",
                expected_revision=1,
            )

    def test_descriptor_update_cannot_change_worker_identity(self):
        self.register_healthy()
        with self.assertRaises(WorkerRegistryError):
            self.registry.update_descriptor(
                self.descriptor("worker-2", revision=2),
                authenticated_worker_id="worker-1",
                expected_revision=1,
            )

    def test_selection_bounds_and_input_types_are_strict(self):
        self.register_healthy()
        for version in (True, 0, 256):
            with self.subTest(version=version), self.assertRaises(WorkerRegistryError):
                self.registry.eligible(
                    "math.factorial", protocol_version=version,
                    authorized_worker_ids={"worker-1"}, now_ns=self.now,
                )
        with self.assertRaises(WorkerRegistryError):
            self.registry.eligible(
                "math.factorial", protocol_version=1,
                authorized_worker_ids=["worker-1"], now_ns=self.now,
            )
        with self.assertRaises(WorkerRegistryError):
            self.registry.eligible(
                "math.factorial", protocol_version=1,
                authorized_worker_ids={"worker-1"}, now_ns=self.now, limit=0,
            )

    def test_concurrent_duplicate_registration_has_one_winner(self):
        registry = InMemoryWorkerRegistry(clock_ns=lambda: self.now)
        barrier = threading.Barrier(2)
        outcomes = []

        def register():
            barrier.wait()
            try:
                registry.register(
                    self.descriptor(), authenticated_worker_id="worker-1",
                    now_ns=self.now,
                )
                outcomes.append("registered")
            except WorkerConflictError:
                outcomes.append("conflict")

        threads = [threading.Thread(target=register) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertCountEqual(outcomes, ["registered", "conflict"])
        self.assertEqual(registry.get("worker-1").health.state, "starting")


if __name__ == "__main__":
    unittest.main()
