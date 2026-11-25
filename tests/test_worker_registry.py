import threading
import unittest

from capri_runtime.worker_registry import (
    InMemoryWorkerRegistry,
    WorkerConflictError,
    WorkerDescriptor,
    WorkerNotFoundError,
    WorkerRegistryError,
    WorkerReservation,
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
                authorized_worker_ids={"worker-1", "worker-2", "worker-3", "worker-a", "worker-b", "worker-c"},
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
        with self.assertRaises(WorkerConflictError):
            self.registry.update_descriptor(
                self.descriptor(enabled=True, revision=2),
                authenticated_worker_id="worker-1",
                expected_revision=1,
            )

    def test_descriptor_updates_use_revision_compare_and_swap(self):
        self.register_healthy()
        updated = self.registry.update_descriptor(
            self.descriptor(priority=10, max_concurrency=1, revision=2),
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


    def test_atomic_reservations_prevent_concurrent_overselection(self):
        registry = InMemoryWorkerRegistry(clock_ns=lambda: self.now)
        registry.register(
            self.descriptor(max_concurrency=1),
            authenticated_worker_id="worker-1",
            now_ns=self.now,
        )
        registry.heartbeat(
            "worker-1", authenticated_worker_id="worker-1",
            in_flight=0, now_ns=self.now,
        )
        barrier = threading.Barrier(2)
        reservations = []

        def reserve():
            barrier.wait()
            reservations.append(registry.reserve_eligible(
                "math.factorial", protocol_version=1,
                authorized_worker_ids={"worker-1"}, now_ns=self.now,
            ))

        threads = [threading.Thread(target=reserve) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        acquired = [item for item in reservations if item is not None]
        self.assertEqual(len(acquired), 1)
        self.assertEqual(registry.eligible(
            "math.factorial", protocol_version=1,
            authorized_worker_ids={"worker-1"}, now_ns=self.now,
        ), ())
        self.assertTrue(registry.release_reservation(
            acquired[0], authenticated_worker_id="worker-1", now_ns=self.now,
        ))
        self.assertFalse(registry.release_reservation(
            acquired[0], authenticated_worker_id="worker-1", now_ns=self.now,
        ))

    def test_reservation_expiry_releases_capacity(self):
        registry = InMemoryWorkerRegistry(
            clock_ns=lambda: self.now, reservation_ttl_ms=1_000,
        )
        registry.register(
            self.descriptor(max_concurrency=1),
            authenticated_worker_id="worker-1", now_ns=self.now,
        )
        registry.heartbeat(
            "worker-1", authenticated_worker_id="worker-1",
            in_flight=0, now_ns=self.now,
        )
        first = registry.reserve_eligible(
            "math.factorial", protocol_version=1,
            authorized_worker_ids={"worker-1"}, now_ns=self.now,
        )
        self.assertIsNotNone(first)
        self.now += 1_000_000_000
        second = registry.reserve_eligible(
            "math.factorial", protocol_version=1,
            authorized_worker_ids={"worker-1"}, now_ns=self.now,
        )
        self.assertIsNotNone(second)
        self.assertFalse(registry.release_reservation(
            first, authenticated_worker_id="worker-1", now_ns=self.now,
        ))
        self.assertTrue(registry.release_reservation(
            second, authenticated_worker_id="worker-1", now_ns=self.now,
        ))

    def test_reservation_is_revoked_when_worker_fails(self):
        self.register_healthy()
        reservation = self.registry.reserve_eligible(
            "math.factorial", protocol_version=1,
            authorized_worker_ids={"worker-1"}, now_ns=self.now,
        )
        self.assertIsNotNone(reservation)
        self.registry.record_failure(
            "worker-1", authenticated_worker_id="worker-1",
        )
        self.assertFalse(self.registry.release_reservation(
            reservation, authenticated_worker_id="worker-1", now_ns=self.now,
        ))

    def test_reservation_is_revoked_on_quarantine_and_descriptor_change(self):
        healthy = self.register_healthy()
        reservation = self.registry.reserve_eligible(
            "math.factorial", protocol_version=1,
            authorized_worker_ids={"worker-1"}, now_ns=self.now,
        )
        self.assertIsNotNone(reservation)
        updated = self.registry.update_descriptor(
            self.descriptor(priority=10, revision=2),
            authenticated_worker_id="worker-1",
            expected_revision=1,
        )
        self.assertEqual(updated.descriptor.revision, 2)
        self.assertFalse(self.registry.release_reservation(
            reservation, authenticated_worker_id="worker-1", now_ns=self.now,
        ))
        reservation = self.registry.reserve_eligible(
            "math.factorial", protocol_version=1,
            authorized_worker_ids={"worker-1"}, now_ns=self.now,
        )
        self.assertIsNotNone(reservation)
        self.registry.quarantine(
            "worker-1", expected_health_revision=healthy.health.revision,
        )
        self.assertFalse(self.registry.release_reservation(
            reservation, authenticated_worker_id="worker-1", now_ns=self.now,
        ))

    def test_reservation_release_rejects_wrong_authenticated_worker(self):
        self.register_healthy()
        reservation = self.registry.reserve_eligible(
            "math.factorial", protocol_version=1,
            authorized_worker_ids={"worker-1"}, now_ns=self.now,
        )
        with self.assertRaises(WorkerRegistryError):
            self.registry.release_reservation(
                reservation, authenticated_worker_id="worker-2", now_ns=self.now,
            )

    def test_committed_reservation_survives_ttl_until_explicit_release(self):
        registry = InMemoryWorkerRegistry(
            clock_ns=lambda: self.now, reservation_ttl_ms=1_000,
        )
        registry.register(
            self.descriptor(max_concurrency=1),
            authenticated_worker_id="worker-1", now_ns=self.now,
        )
        registry.heartbeat(
            "worker-1", authenticated_worker_id="worker-1",
            in_flight=0, now_ns=self.now,
        )
        pending = registry.reserve_eligible(
            "math.factorial", protocol_version=1,
            authorized_worker_ids={"worker-1"}, now_ns=self.now,
        )
        self.assertIsNotNone(pending)
        committed = registry.commit_reservation(
            pending, authenticated_worker_id="worker-1", now_ns=self.now,
        )
        self.assertIsNotNone(committed)
        self.assertTrue(committed.committed)
        self.assertEqual(
            registry.commit_reservation(
                committed, authenticated_worker_id="worker-1", now_ns=self.now,
            ),
            committed,
        )
        self.now += 2_000_000_000
        self.assertIsNone(registry.reserve_eligible(
            "math.factorial", protocol_version=1,
            authorized_worker_ids={"worker-1"}, now_ns=self.now,
        ))
        with self.assertRaises(WorkerRegistryError):
            registry.release_reservation(
                committed, authenticated_worker_id="worker-1", now_ns=self.now,
            )
        self.assertIsNone(registry.reserve_eligible(
            "math.factorial", protocol_version=1,
            authorized_worker_ids={"worker-1"}, now_ns=self.now,
        ))
        self.assertTrue(registry.release_reservation(
            committed, authenticated_worker_id="worker-1",
            observed_in_flight=0, now_ns=self.now,
        ))
        self.assertIsNotNone(registry.reserve_eligible(
            "math.factorial", protocol_version=1,
            authorized_worker_ids={"worker-1"}, now_ns=self.now,
        ))

    def test_committed_release_atomically_hands_off_to_host_observed_load(self):
        registry = InMemoryWorkerRegistry(clock_ns=lambda: self.now)
        registry.register(
            self.descriptor(max_concurrency=1),
            authenticated_worker_id="worker-1", now_ns=self.now,
        )
        registry.heartbeat(
            "worker-1", authenticated_worker_id="worker-1",
            in_flight=0, now_ns=self.now,
        )
        pending = registry.reserve_eligible(
            "math.factorial", protocol_version=1,
            authorized_worker_ids={"worker-1"}, now_ns=self.now,
        )
        committed = registry.commit_reservation(
            pending, authenticated_worker_id="worker-1", now_ns=self.now,
        )
        self.assertTrue(committed.committed)
        with self.assertRaises(WorkerRegistryError):
            registry.release_reservation(
                committed, authenticated_worker_id="worker-1", now_ns=self.now,
            )
        self.assertIsNone(registry.reserve_eligible(
            "math.factorial", protocol_version=1,
            authorized_worker_ids={"worker-1"}, now_ns=self.now,
        ))

        # Replacing the committed hold with the host-observed active load
        # happens under the same lock as removing the hold.
        self.assertTrue(registry.release_reservation(
            committed, authenticated_worker_id="worker-1",
            observed_in_flight=1, now_ns=self.now,
        ))
        self.assertEqual(registry.get("worker-1").health.in_flight, 1)
        self.assertIsNone(registry.reserve_eligible(
            "math.factorial", protocol_version=1,
            authorized_worker_ids={"worker-1"}, now_ns=self.now,
        ))
        registry.heartbeat(
            "worker-1", authenticated_worker_id="worker-1",
            in_flight=0, now_ns=self.now + 1,
        )
        self.assertIsNotNone(registry.reserve_eligible(
            "math.factorial", protocol_version=1,
            authorized_worker_ids={"worker-1"}, now_ns=self.now + 1,
        ))

    def test_committed_release_rejects_invalid_host_observed_load(self):
        self.register_healthy(max_concurrency=1)
        pending = self.registry.reserve_eligible(
            "math.factorial", protocol_version=1,
            authorized_worker_ids={"worker-1"}, now_ns=self.now,
        )
        committed = self.registry.commit_reservation(
            pending, authenticated_worker_id="worker-1", now_ns=self.now,
        )
        for invalid in (True, -1):
            with self.assertRaises(WorkerRegistryError):
                self.registry.release_reservation(
                    committed, authenticated_worker_id="worker-1",
                    observed_in_flight=invalid, now_ns=self.now,
                )
        self.assertTrue(self.registry.release_reservation(
            committed, authenticated_worker_id="worker-1",
            observed_in_flight=0, now_ns=self.now,
        ))

    def test_pending_release_rejects_in_flight_observation(self):
        self.register_healthy(max_concurrency=1)
        pending = self.registry.reserve_eligible(
            "math.factorial", protocol_version=1,
            authorized_worker_ids={"worker-1"}, now_ns=self.now,
        )
        with self.assertRaises(WorkerRegistryError):
            self.registry.release_reservation(
                pending, authenticated_worker_id="worker-1",
                observed_in_flight=0, now_ns=self.now,
            )
        self.assertTrue(self.registry.release_reservation(
            pending, authenticated_worker_id="worker-1", now_ns=self.now,
        ))

    def test_reservation_lookup_prunes_expired_pending_but_keeps_committed(self):
        registry = InMemoryWorkerRegistry(
            clock_ns=lambda: self.now, reservation_ttl_ms=1_000,
        )
        registry.register(
            self.descriptor(max_concurrency=1),
            authenticated_worker_id="worker-1", now_ns=self.now,
        )
        registry.heartbeat(
            "worker-1", authenticated_worker_id="worker-1",
            in_flight=0, now_ns=self.now,
        )
        pending = registry.reserve_eligible(
            "math.factorial", protocol_version=1,
            authorized_worker_ids={"worker-1"}, now_ns=self.now,
        )
        self.assertEqual(registry.get_reservation(pending.token, now_ns=self.now), pending)
        self.now += 2_000_000_000
        self.assertIsNone(registry.get_reservation(pending.token, now_ns=self.now))

        registry.heartbeat(
            "worker-1", authenticated_worker_id="worker-1",
            in_flight=0, now_ns=self.now,
        )
        pending = registry.reserve_eligible(
            "math.factorial", protocol_version=1,
            authorized_worker_ids={"worker-1"}, now_ns=self.now,
        )
        committed = registry.commit_reservation(
            pending, authenticated_worker_id="worker-1", now_ns=self.now,
        )
        self.now += 2_000_000_000
        self.assertEqual(
            registry.get_reservation(committed.token, now_ns=self.now), committed,
        )

    def test_expired_pending_reservation_cannot_be_committed(self):
        registry = InMemoryWorkerRegistry(
            clock_ns=lambda: self.now, reservation_ttl_ms=1_000,
        )
        registry.register(
            self.descriptor(max_concurrency=1),
            authenticated_worker_id="worker-1", now_ns=self.now,
        )
        registry.heartbeat(
            "worker-1", authenticated_worker_id="worker-1",
            in_flight=0, now_ns=self.now,
        )
        pending = registry.reserve_eligible(
            "math.factorial", protocol_version=1,
            authorized_worker_ids={"worker-1"}, now_ns=self.now,
        )
        self.assertIsNotNone(pending)
        self.now += 1_000_000_000
        self.assertIsNone(registry.commit_reservation(
            pending, authenticated_worker_id="worker-1", now_ns=self.now,
        ))

    def test_commit_rechecks_host_observed_load_after_pending_reservation(self):
        self.register_healthy(max_concurrency=1)
        pending = self.registry.reserve_eligible(
            "math.factorial", protocol_version=1,
            authorized_worker_ids={"worker-1"}, now_ns=self.now,
        )
        self.assertIsNotNone(pending)
        self.registry.heartbeat(
            "worker-1", authenticated_worker_id="worker-1",
            in_flight=1, now_ns=self.now + 1,
        )
        self.assertIsNone(self.registry.commit_reservation(
            pending, authenticated_worker_id="worker-1", now_ns=self.now + 1,
        ))
        self.assertFalse(self.registry.release_reservation(
            pending, authenticated_worker_id="worker-1", now_ns=self.now + 1,
        ))
        self.assertEqual(self.registry.eligible(
            "math.factorial", protocol_version=1,
            authorized_worker_ids={"worker-1"}, now_ns=self.now + 1,
        ), ())

    def test_committed_hold_survives_worker_failure_and_descriptor_change(self):
        self.register_healthy(max_concurrency=1)
        pending = self.registry.reserve_eligible(
            "math.factorial", protocol_version=1,
            authorized_worker_ids={"worker-1"}, now_ns=self.now,
        )
        committed = self.registry.commit_reservation(
            pending, authenticated_worker_id="worker-1", now_ns=self.now,
        )
        self.assertIsNotNone(committed)
        self.registry.update_descriptor(
            self.descriptor(priority=10, revision=2, max_concurrency=1),
            authenticated_worker_id="worker-1",
            expected_revision=1,
        )
        self.registry.record_failure(
            "worker-1", authenticated_worker_id="worker-1",
        )
        with self.assertRaises(WorkerConflictError):
            self.registry.release_reservation(
                pending, authenticated_worker_id="worker-1", now_ns=self.now,
            )
        # A fresh heartbeat restores health, but the committed in-flight hold
        # continues to consume capacity until the host reconciles completion.
        self.registry.heartbeat(
            "worker-1", authenticated_worker_id="worker-1",
            in_flight=0, now_ns=self.now,
        )
        self.assertIsNone(self.registry.reserve_eligible(
            "math.factorial", protocol_version=1,
            authorized_worker_ids={"worker-1"}, now_ns=self.now,
        ))
        self.assertTrue(self.registry.release_reservation(
            committed, authenticated_worker_id="worker-1",
            observed_in_flight=0, now_ns=self.now,
        ))

    def test_reservation_configuration_and_token_are_bounded(self):
        for value in (True, 0, 60_001):
            with self.subTest(value=value), self.assertRaises(WorkerRegistryError):
                InMemoryWorkerRegistry(reservation_ttl_ms=value)
        with self.assertRaises(WorkerRegistryError):
            InMemoryWorkerRegistry(max_reservations=4097)
        with self.assertRaises(WorkerRegistryError):
            WorkerReservation(
                token="not-a-valid-token", worker_id="worker-1",
                expires_at_ns=0, descriptor_revision=1,
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


    def test_task_bound_reservations_are_unique_and_recoverable_by_task(self):
        self.register_healthy(max_concurrency=2)
        pending = self.registry.reserve_eligible(
            "math.factorial",
            protocol_version=1,
            authorized_worker_ids={"worker-1"},
            principal_id="alice",
            task_id="task-1",
            now_ns=self.now,
        )
        self.assertEqual(pending.principal_id, "alice")
        self.assertEqual(pending.task_id, "task-1")
        self.assertEqual(
            self.registry.get_reservation_for_task("alice", "task-1"),
            pending,
        )
        with self.assertRaises(WorkerConflictError):
            self.registry.reserve_eligible(
                "math.factorial",
                protocol_version=1,
                authorized_worker_ids={"worker-1"},
                principal_id="alice",
                task_id="task-1",
                now_ns=self.now,
            )
        self.assertEqual(self.registry.integrity_check(), "ephemeral")

    def test_expire_reservations_returns_expired_pending_holds(self):
        self.register_healthy()
        pending = self.registry.reserve_eligible(
            "math.factorial",
            protocol_version=1,
            authorized_worker_ids={"worker-1"},
            principal_id="alice",
            task_id="task-expiring",
            now_ns=self.now,
        )
        expired = self.registry.expire_reservations(
            now_ns=self.now + 10_000_000_001,
        )
        self.assertEqual(expired, (pending,))
        self.assertIsNone(self.registry.get_reservation(pending.token, now_ns=self.now + 10_000_000_001))


if __name__ == "__main__":
    unittest.main()
