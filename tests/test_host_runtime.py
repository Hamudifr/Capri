import hashlib
import json
import os
import tempfile
import unittest
from dataclasses import replace

from capri_core.strategy import StrategyObservation
from capri_runtime import (
    HmacApprovalKeyRing,
    HostStrategyApprovalAuthority,
    HostStrategyEvidenceAuthority,
    SQLiteExecutionEvidenceJournal,
    SQLiteStrategyEvidenceManifestStore,
    SQLiteStrategyStore,
    StrategyApprovalIdentity,
    StrategyApprovalRequest,
    StrategyBinding,
    TaskClassification,
    VerifiedExecutionResult,
    AssistantTurn,
    HostAuthorityError,
    HostAuthorityResolver,
    InMemoryAuditSink,
    InMemoryWorkerRegistry,
    SQLiteWorkerRegistry,
    WorkerDescriptor,
    SessionClosedError,
    SessionNotFoundError,
    SQLiteSessionStore,
    SQLiteTaskStore,
    TaskEngine,
    TaskWorker,
    ToolExecutionBridge,
    ToolExecutor,
    ToolOrchestrator,
    ToolRegistry,
    UntrustedMemoryContext,
    UntrustedKnowledgeContext,
)
from capri_runtime.host_runtime import CapriHostRuntime, HostRuntimeError, HostWorkerReservation
from capri_runtime.security_store import SQLiteSecurityStore
from capri_runtime.tools import AuditSink
from capri_runtime.tasks import TaskNotFoundError, TaskValidationError
from capri_runtime.goals import GoalNotFoundError, GoalPlanProposal, GoalValidationError, SQLiteGoalStore
from capri_runtime.budgets import BudgetExceededError, BudgetPolicy, SQLiteBudgetStore


class RecordingAdapter:
    def __init__(self):
        self.calls = []
        self.memory_contexts = []
        self.knowledge_contexts = []

    def complete_with_tools(self, session_id, history, tools):
        self.calls.append((session_id, history, tools))
        return AssistantTurn(content="answer: " + history[-1].content)

    def complete_with_tools_and_memory(self, session_id, history, tools, memory_context):
        self.calls.append((session_id, history, tools))
        self.memory_contexts.append(memory_context)
        return AssistantTurn(content="memory-aware answer")

    def complete_with_tools_and_knowledge(self, session_id, history, tools, knowledge_context):
        self.calls.append((session_id, history, tools))
        self.knowledge_contexts.append(knowledge_context)
        return AssistantTurn(content="knowledge-aware answer")

    def complete_with_tools_and_memory_and_knowledge(
        self, session_id, history, tools, memory_context, knowledge_context
    ):
        self.calls.append((session_id, history, tools))
        self.memory_contexts.append(memory_context)
        self.knowledge_contexts.append(knowledge_context)
        return AssistantTurn(content="memory-and-knowledge-aware answer")


class CapriHostRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        if os.name == "posix":
            os.chmod(self.temp.name, 0o700)
        self.store = SQLiteSessionStore(
            os.path.join(self.temp.name, "sessions.sqlite3"),
            max_output_chars=131_072,
        )
        self.task_store = SQLiteTaskStore(
            os.path.join(self.temp.name, "tasks.sqlite3")
        )
        self.adapter = RecordingAdapter()
        bridge = ToolExecutionBridge(
            ToolExecutor(ToolRegistry(), InMemoryAuditSink())
        )
        self.orchestrator = ToolOrchestrator(self.adapter, bridge)
        self.authority = HostAuthorityResolver(
            authenticate=lambda credential: {
                "alice-token": "alice",
                "bob-token": "bob",
            }.get(credential),
            permissions_for=lambda principal_id: (),
        )

    def tearDown(self):
        self.temp.cleanup()

    def make_host(self, **kwargs):
        if kwargs.get("worker_registry") is not None:
            kwargs.setdefault("worker_lifecycle_audit_sink", InMemoryAuditSink())
        return CapriHostRuntime(
            self.authority,
            self.store,
            self.orchestrator,
            **kwargs,
        )

    @staticmethod
    def approve_worker_descriptor(worker_id, proposed):
        # This is fixed host configuration, not a copy of worker-advertised fields.
        return WorkerDescriptor(
            worker_id,
            (1,),
            ("math.factorial",),
            priority=5,
            max_concurrency=2,
            enabled=True,
            revision=1,
        )

    def make_worker_host(self, registry, identities, policy, audit_sink=None):
        known_ids = frozenset(identities.values())
        options = {
            "task_store": self.task_store,
            "worker_registry": registry,
            "worker_identity_resolver": identities.get,
            "worker_descriptor_resolver": self.approve_worker_descriptor,
            "worker_observer_authorizer": lambda credential, worker_id: (
                credential == "monitor-token" and worker_id in known_ids
            ),
            "worker_unreserved_in_flight_resolver": lambda worker_id: 0,
            "worker_policy_resolver": policy,
        }
        if audit_sink is not None:
            options["worker_lifecycle_audit_sink"] = audit_sink
        return self.make_host(**options)

    def test_worker_registry_rejects_placeholder_audit_sink(self):
        with self.assertRaisesRegex(HostRuntimeError, "trusted AuditSink"):
            self.make_host(
                task_store=self.task_store,
                worker_registry=InMemoryWorkerRegistry(),
                worker_identity_resolver=lambda credential: "worker-1",
                worker_descriptor_resolver=self.approve_worker_descriptor,
                worker_observer_authorizer=lambda credential, worker_id: True,
                worker_unreserved_in_flight_resolver=lambda worker_id: 0,
                worker_policy_resolver=lambda *args: {"worker-1"},
                worker_lifecycle_audit_sink=AuditSink(),
            )

    def test_worker_registry_requires_audit_sink(self):
        with self.assertRaisesRegex(HostRuntimeError, "lifecycle audit sink"):
            self.make_host(
                task_store=self.task_store,
                worker_registry=InMemoryWorkerRegistry(),
                worker_identity_resolver=lambda credential: "worker-1",
                worker_descriptor_resolver=self.approve_worker_descriptor,
                worker_observer_authorizer=lambda credential, worker_id: True,
                worker_unreserved_in_flight_resolver=lambda worker_id: 0,
                worker_policy_resolver=lambda *args: {"worker-1"},
                worker_lifecycle_audit_sink=None,
            )

    def test_worker_lifecycle_audit_persists_structured_metadata(self):
        audit = SQLiteSecurityStore(os.path.join(self.temp.name, "worker-audit.sqlite3"))
        registry = InMemoryWorkerRegistry()
        host = self.make_worker_host(
            registry, {"worker-token": "worker-1"}, lambda *args: {"worker-1"},
            audit_sink=audit,
        )
        host.register_worker(
            "worker-token", WorkerDescriptor("worker-1", (1,), ("math.factorial",)),
        )
        host.heartbeat_worker("monitor-token", "worker-1")
        task = self.task_store.create_for_principal(
            "alice", [{"tool": "collect", "input": {}}],
        )
        pending = host.reserve_worker_candidate(
            "alice-token", task.task_id, "math.factorial", 1,
        )
        self.assertTrue(audit.worker_lifecycle_reconciliation_required())
        committed = host.commit_worker_reservation(
            "alice-token", "monitor-token", pending,
        )
        self.assertTrue(audit.worker_lifecycle_reconciliation_required())
        self.assertTrue(host.release_worker_reservation("monitor-token", committed))
        self.assertFalse(audit.worker_lifecycle_reconciliation_required())

        events = audit.events()
        event_types = [event.tool_name for event in events]
        self.assertIn("worker.registered", event_types)
        self.assertIn("worker.heartbeat", event_types)
        self.assertIn("worker.reservation.created", event_types)
        self.assertIn("worker.reservation.committed", event_types)
        self.assertIn("worker.reservation.released", event_types)
        reservation_events = [
            event for event in events if event.tool_name.startswith("worker.reservation.")
        ]
        self.assertEqual(len(reservation_events), 3)
        for event in reservation_events:
            self.assertEqual(event.principal_id, "alice")
            self.assertEqual(event.resource_type, "worker")
            self.assertEqual(event.resource_id, "worker-1")
            self.assertEqual(event.task_id, task.task_id)
            metadata = json.loads(event.metadata_json)
            self.assertEqual(metadata["worker_id"], "worker-1")
            self.assertNotIn(pending.reservation.token, event.metadata_json)
            self.assertEqual(
                event.argument_digest,
                hashlib.sha256(event.metadata_json.encode("utf-8")).hexdigest(),
            )
        committed_event = next(
            event for event in reservation_events
            if event.tool_name == "worker.reservation.committed"
        )
        self.assertEqual(json.loads(committed_event.metadata_json)["observed_in_flight"], 0)

    def test_worker_runtime_startup_requires_reconciliation_for_unreleased_reservation(self):
        audit = SQLiteSecurityStore(os.path.join(self.temp.name, "restart-audit.sqlite3"))
        identities = {"worker-token": "worker-1"}
        registry = InMemoryWorkerRegistry()
        host = self.make_worker_host(
            registry, identities, lambda *args: {"worker-1"}, audit_sink=audit,
        )
        host.register_worker(
            "worker-token", WorkerDescriptor("worker-1", (1,), ("math.factorial",)),
        )
        host.heartbeat_worker("monitor-token", "worker-1")
        task = self.task_store.create_for_principal(
            "alice", [{"tool": "collect", "input": {}}],
        )
        pending = host.reserve_worker_candidate(
            "alice-token", task.task_id, "math.factorial", 1,
        )
        host.commit_worker_reservation("alice-token", "monitor-token", pending)
        self.assertTrue(audit.worker_lifecycle_reconciliation_required())

        with self.assertRaisesRegex(HostRuntimeError, "reconcile and acknowledge"):
            self.make_worker_host(
                InMemoryWorkerRegistry(), identities,
                lambda *args: {"worker-1"}, audit_sink=audit,
            )
        self.assertTrue(
            audit.acknowledge_worker_lifecycle_reconciliation(
                "Supervisor reconciled active worker load and discarded process-local reservations",
            )
        )
        self.assertFalse(audit.worker_lifecycle_reconciliation_required())
        restarted = self.make_worker_host(
            InMemoryWorkerRegistry(), identities,
            lambda *args: {"worker-1"}, audit_sink=audit,
        )
        self.assertIsNotNone(restarted)

    def test_worker_audit_failure_requires_reconciliation_before_restart(self):
        class FailingHeartbeatAuditSink(InMemoryAuditSink):
            def write(self, event):
                if event.tool_name == "worker.heartbeat":
                    raise OSError("simulated durable audit outage")
                super().write(event)

        audit = FailingHeartbeatAuditSink()
        identities = {"worker-token": "worker-1"}
        registry = InMemoryWorkerRegistry()
        host = self.make_worker_host(
            registry, identities, lambda *args: {"worker-1"}, audit_sink=audit,
        )
        host.register_worker(
            "worker-token", WorkerDescriptor("worker-1", (1,), ("math.factorial",)),
        )
        with self.assertRaisesRegex(HostRuntimeError, "audit persistence failed"):
            host.heartbeat_worker("monitor-token", "worker-1")
        self.assertTrue(audit.worker_lifecycle_reconciliation_required())

        with self.assertRaisesRegex(HostRuntimeError, "reconcile and acknowledge"):
            self.make_worker_host(
                InMemoryWorkerRegistry(), identities,
                lambda *args: {"worker-1"}, audit_sink=audit,
            )
        self.assertTrue(
            audit.acknowledge_worker_lifecycle_reconciliation(
                "Supervisor checked worker process state and host load; stale in-memory registry discarded",
            )
        )
        restarted = self.make_worker_host(
            InMemoryWorkerRegistry(), identities,
            lambda *args: {"worker-1"}, audit_sink=audit,
        )
        self.assertIsNotNone(restarted)

    def test_worker_audit_failure_disables_registry_gateway(self):
        audit = InMemoryAuditSink(max_events=1)
        registry = InMemoryWorkerRegistry()
        host = self.make_worker_host(
            registry, {"worker-token": "worker-1"}, lambda *args: {"worker-1"},
            audit_sink=audit,
        )
        host.register_worker(
            "worker-token", WorkerDescriptor("worker-1", (1,), ("math.factorial",)),
        )
        with self.assertRaisesRegex(HostRuntimeError, "audit persistence failed"):
            host.heartbeat_worker("monitor-token", "worker-1")
        with self.assertRaisesRegex(HostRuntimeError, "disabled"):
            host.get_worker_candidates(
                "alice-token", "task-does-not-exist", "math.factorial", 1,
            )
        self.assertEqual(len(audit.events()), 1)
        self.assertTrue(audit.worker_lifecycle_reconciliation_required())

    def test_worker_registry_requires_all_host_callbacks(self):
        with self.assertRaises(HostRuntimeError):
            self.make_host(worker_registry=InMemoryWorkerRegistry())
        with self.assertRaises(HostRuntimeError):
            self.make_host(
                worker_registry=InMemoryWorkerRegistry(),
                worker_identity_resolver=lambda credential: "worker-1",
                worker_descriptor_resolver=self.approve_worker_descriptor,
                worker_policy_resolver=lambda *args: set(),
            )

    def test_worker_registration_and_heartbeat_require_distinct_trusted_identities(self):
        identities = {"worker-token": "worker-1"}
        registry = InMemoryWorkerRegistry()
        host = self.make_worker_host(
            registry, identities, lambda principal, task_id, capability: set(),
        )
        descriptor = WorkerDescriptor(
            "worker-1", (1,), ("math.factorial",), max_concurrency=2,
        )
        initial = host.register_worker("worker-token", descriptor)
        self.assertEqual(initial.health.state, "starting")
        # A worker transport credential cannot assert host-observed liveness.
        with self.assertRaises(HostRuntimeError):
            host.heartbeat_worker("worker-token", "worker-1")
        with self.assertRaises(HostRuntimeError):
            host.heartbeat_worker("monitor-token", "worker-2")
        healthy = host.heartbeat_worker("monitor-token", "worker-1")
        self.assertEqual(healthy.health.state, "healthy")
        # Callers cannot supply or spoof the host-observed load count.
        with self.assertRaises(TypeError):
            host.heartbeat_worker("monitor-token", "worker-1", in_flight=0)

    def test_worker_candidates_are_scoped_to_task_owner_and_host_policy(self):
        identities = {
            "worker-one-token": "worker-1",
            "worker-two-token": "worker-2",
        }
        policy_calls = []

        def policy(principal_id, task_id, capability):
            policy_calls.append((principal_id, task_id, capability))
            return {"worker-1"}

        registry = InMemoryWorkerRegistry()
        host = self.make_worker_host(registry, identities, policy)
        for worker_id, token in (
            ("worker-1", "worker-one-token"),
            ("worker-2", "worker-two-token"),
        ):
            host.register_worker(
                token,
                WorkerDescriptor(worker_id, (1,), ("math.factorial",)),
            )
            host.heartbeat_worker("monitor-token", worker_id)
        task = self.task_store.create_for_principal(
            "alice", [{"tool": "collect", "input": {"scope": "owned"}}],
        )

        candidates = host.get_worker_candidates(
            "alice-token", task.task_id, "math.factorial", 1,
        )
        self.assertEqual(
            [item.descriptor.worker_id for item in candidates],
            ["worker-1"],
        )
        self.assertEqual(policy_calls, [("alice", task.task_id, "math.factorial")])
        with self.assertRaises(HostRuntimeError):
            host.get_worker_candidates(
                "bob-token", task.task_id, "math.factorial", 1,
            )
        self.assertEqual(len(policy_calls), 1)

    def test_host_worker_reservation_is_principal_task_scoped_and_supervisor_committed(self):
        registry = InMemoryWorkerRegistry()
        audit = InMemoryAuditSink()
        host = self.make_worker_host(
            registry, {"worker-token": "worker-1"}, lambda *args: {"worker-1"},
            audit_sink=audit,
        )
        host.register_worker(
            "worker-token",
            WorkerDescriptor("worker-1", (1,), ("math.factorial",), max_concurrency=1),
        )
        host.heartbeat_worker("monitor-token", "worker-1")
        task = self.task_store.create_for_principal(
            "alice", [{"tool": "collect", "input": {"scope": "owned"}}],
        )

        pending = host.reserve_worker_candidate(
            "alice-token", task.task_id, "math.factorial", 1,
        )
        self.assertIsInstance(pending, HostWorkerReservation)
        self.assertFalse(pending.reservation.committed)
        self.assertEqual(pending.principal_id, "alice")
        self.assertEqual(pending.task_id, task.task_id)
        self.assertEqual(registry.get_reservation(pending.reservation.token), pending.reservation)

        with self.assertRaises(HostRuntimeError):
            host.commit_worker_reservation("bob-token", "monitor-token", pending)
        with self.assertRaises(HostRuntimeError):
            host.commit_worker_reservation("alice-token", "worker-token", pending)

        committed = host.commit_worker_reservation(
            "alice-token", "monitor-token", pending,
        )
        self.assertTrue(committed.reservation.committed)
        # Repeated commit with the original pending wrapper returns the current committed wrapper.
        self.assertEqual(
            host.commit_worker_reservation("alice-token", "monitor-token", pending),
            committed,
        )
        with self.assertRaises(HostRuntimeError):
            host.release_worker_reservation("worker-token", committed)
        self.assertTrue(host.release_worker_reservation("monitor-token", committed))
        self.assertIsNone(registry.get_reservation(committed.reservation.token))

    def test_host_worker_reservation_cannot_be_rebound_to_another_task(self):
        registry = InMemoryWorkerRegistry()
        host = self.make_worker_host(
            registry, {"worker-token": "worker-1"}, lambda *args: {"worker-1"},
        )
        host.register_worker(
            "worker-token", WorkerDescriptor("worker-1", (1,), ("math.factorial",)),
        )
        host.heartbeat_worker("monitor-token", "worker-1")
        first = self.task_store.create_for_principal(
            "alice", [{"tool": "collect", "input": {"task": "first"}}],
        )
        second = self.task_store.create_for_principal(
            "alice", [{"tool": "collect", "input": {"task": "second"}}],
        )
        pending = host.reserve_worker_candidate(
            "alice-token", first.task_id, "math.factorial", 1,
        )
        rebound = replace(pending, task_id=second.task_id)
        with self.assertRaisesRegex(HostRuntimeError, "another task"):
            host.commit_worker_reservation("alice-token", "monitor-token", rebound)
        self.assertTrue(host.release_worker_reservation("monitor-token", pending))

    def test_host_worker_reservation_rechecks_policy_before_commit(self):
        registry = InMemoryWorkerRegistry()
        policy_state = {"allowed": {"worker-1"}}
        host = self.make_worker_host(
            registry, {"worker-token": "worker-1"},
            lambda principal, task_id, capability: set(policy_state["allowed"]),
        )
        host.register_worker(
            "worker-token", WorkerDescriptor("worker-1", (1,), ("math.factorial",)),
        )
        host.heartbeat_worker("monitor-token", "worker-1")
        task = self.task_store.create_for_principal(
            "alice", [{"tool": "collect", "input": {}}],
        )
        pending = host.reserve_worker_candidate(
            "alice-token", task.task_id, "math.factorial", 1,
        )
        policy_state["allowed"] = set()
        with self.assertRaisesRegex(HostRuntimeError, "no longer authorized"):
            host.commit_worker_reservation("alice-token", "monitor-token", pending)
        self.assertIsNone(registry.get_reservation(pending.reservation.token))

    def test_host_worker_reservation_release_uses_host_observed_load(self):
        registry = InMemoryWorkerRegistry()
        load = {"worker-1": 0}
        host = self.make_host(
            task_store=self.task_store,
            worker_registry=registry,
            worker_identity_resolver=lambda credential: (
                "worker-1" if credential == "worker-token" else None
            ),
            worker_descriptor_resolver=lambda worker_id, proposed: WorkerDescriptor(
                worker_id, (1,), ("math.factorial",), max_concurrency=1,
            ),
            worker_observer_authorizer=lambda credential, worker_id: (
                credential == "monitor-token" and worker_id == "worker-1"
            ),
            worker_unreserved_in_flight_resolver=lambda worker_id: load[worker_id],
            worker_policy_resolver=lambda *args: {"worker-1"},
        )
        host.register_worker(
            "worker-token",
            WorkerDescriptor("worker-1", (1,), ("math.factorial",), max_concurrency=1),
        )
        host.heartbeat_worker("monitor-token", "worker-1")
        task = self.task_store.create_for_principal(
            "alice", [{"tool": "collect", "input": {}}],
        )
        pending = host.reserve_worker_candidate(
            "alice-token", task.task_id, "math.factorial", 1,
        )
        committed = host.commit_worker_reservation(
            "alice-token", "monitor-token", pending,
        )

        # A different task remains active after the committed task completes.
        load["worker-1"] = 1
        self.assertTrue(host.release_worker_reservation("monitor-token", committed))
        self.assertEqual(registry.get("worker-1").health.in_flight, 1)
        self.assertEqual(
            registry.eligible(
                "math.factorial", protocol_version=1,
                authorized_worker_ids={"worker-1"},
            ),
            (),
        )
        load["worker-1"] = 0
        host.heartbeat_worker("monitor-token", "worker-1")
        self.assertEqual(
            len(registry.eligible(
                "math.factorial", protocol_version=1,
                authorized_worker_ids={"worker-1"},
            )),
            1,
        )

    def test_host_worker_reservation_expiry_requires_reconciliation(self):
        now = {"value": 10_000_000_000}
        registry = InMemoryWorkerRegistry(
            clock_ns=lambda: now["value"], reservation_ttl_ms=1_000,
        )
        audit = InMemoryAuditSink()
        identities = {"worker-token": "worker-1"}
        host = self.make_worker_host(
            registry, identities, lambda *args: {"worker-1"}, audit_sink=audit,
        )
        host.register_worker(
            "worker-token", WorkerDescriptor("worker-1", (1,), ("math.factorial",)),
        )
        host.heartbeat_worker("monitor-token", "worker-1")
        task = self.task_store.create_for_principal(
            "alice", [{"tool": "collect", "input": {}}],
        )
        expired = host.reserve_worker_candidate(
            "alice-token", task.task_id, "math.factorial", 1,
        )
        self.assertIsNotNone(expired)
        now["value"] += 2_000_000_000
        with self.assertRaisesRegex(HostRuntimeError, "expired or disappeared"):
            host.release_worker_reservation("monitor-token", expired)
        with self.assertRaisesRegex(HostRuntimeError, "disabled"):
            host.reserve_worker_candidate(
                "alice-token", task.task_id, "math.factorial", 1,
            )
        self.assertTrue(audit.worker_lifecycle_reconciliation_required())
        self.assertTrue(
            audit.acknowledge_worker_lifecycle_reconciliation(
                "Supervisor confirmed the pending hold expired and no worker execution remained",
            )
        )
        restarted = self.make_worker_host(
            InMemoryWorkerRegistry(), identities,
            lambda *args: {"worker-1"}, audit_sink=audit,
        )
        self.assertIsNotNone(restarted)

    def test_host_worker_reservation_returns_none_when_no_policy_candidate(self):
        registry = InMemoryWorkerRegistry()
        host = self.make_worker_host(registry, {"worker-token": "worker-1"}, lambda *args: set())
        host.register_worker(
            "worker-token", WorkerDescriptor("worker-1", (1,), ("math.factorial",)),
        )
        host.heartbeat_worker("monitor-token", "worker-1")
        task = self.task_store.create_for_principal(
            "alice", [{"tool": "collect", "input": {}}],
        )
        self.assertIsNone(host.reserve_worker_candidate(
            "alice-token", task.task_id, "math.factorial", 1,
        ))

    def test_worker_policy_failure_and_invalid_allowlist_fail_closed(self):
        identities = {"worker-token": "worker-1"}
        registry = InMemoryWorkerRegistry()
        task = self.task_store.create_for_principal(
            "alice", [{"tool": "collect", "input": {}}],
        )
        failing = self.make_worker_host(
            registry, identities,
            lambda *args: (_ for _ in ()).throw(RuntimeError("private policy error")),
        )
        failing.register_worker(
            "worker-token", WorkerDescriptor("worker-1", (1,), ("math.factorial",)),
        )
        failing.heartbeat_worker("monitor-token", "worker-1")
        with self.assertRaisesRegex(HostRuntimeError, "policy resolution failed"):
            failing.get_worker_candidates(
                "alice-token", task.task_id, "math.factorial", 1,
            )

        invalid = self.make_worker_host(
            registry, identities, lambda *args: ["worker-1"],
        )
        with self.assertRaisesRegex(HostRuntimeError, "invalid allow-list"):
            invalid.get_worker_candidates(
                "alice-token", task.task_id, "math.factorial", 1,
            )

    def test_worker_descriptor_capabilities_are_host_approved_not_self_advertised(self):
        registry = InMemoryWorkerRegistry()
        host = self.make_worker_host(
            registry, {"worker-token": "worker-1"}, lambda *args: {"worker-1"},
        )
        proposed = WorkerDescriptor(
            "worker-1", (2, 3), ("math.factorial", "admin.execute"),
            priority=999, max_concurrency=256, enabled=False, revision=9,
        )
        host.register_worker("worker-token", proposed)
        stored = registry.get("worker-1")
        self.assertEqual(stored.descriptor.protocol_versions, (1,))
        self.assertEqual(stored.descriptor.capabilities, ("math.factorial",))
        self.assertEqual(stored.descriptor.priority, 5)
        self.assertEqual(stored.descriptor.max_concurrency, 2)
        self.assertTrue(stored.descriptor.enabled)
        self.assertEqual(stored.descriptor.revision, 1)

    def test_worker_failure_observation_requires_host_supervisor_identity(self):
        registry = InMemoryWorkerRegistry()
        host = self.make_worker_host(
            registry, {"worker-token": "worker-1"}, lambda *args: set(),
        )
        host.register_worker(
            "worker-token", WorkerDescriptor("worker-1", (1,), ("math.factorial",)),
        )
        with self.assertRaises(HostRuntimeError):
            host.record_worker_failure("worker-token", "worker-1")
        with self.assertRaises(HostRuntimeError):
            host.record_worker_failure("invalid-monitor-token", "worker-1")
        failed = host.record_worker_failure("monitor-token", "worker-1")
        self.assertEqual(failed.health.state, "degraded")

    def test_worker_load_observation_is_host_derived_and_fails_closed(self):
        registry = InMemoryWorkerRegistry()
        host = self.make_host(
            task_store=self.task_store,
            worker_registry=registry,
            worker_identity_resolver=lambda credential: (
                "worker-1" if credential == "worker-token" else None
            ),
            worker_descriptor_resolver=self.approve_worker_descriptor,
            worker_observer_authorizer=lambda credential, worker_id: (
                credential == "monitor-token" and worker_id == "worker-1"
            ),
            worker_unreserved_in_flight_resolver=lambda worker_id: True,
            worker_policy_resolver=lambda *args: set(),
        )
        host.register_worker(
            "worker-token", WorkerDescriptor("worker-1", (1,), ("math.factorial",)),
        )
        with self.assertRaisesRegex(HostRuntimeError, "load observation is invalid"):
            host.heartbeat_worker("monitor-token", "worker-1")

    def test_execution_budget_usage_is_wired_and_principal_scoped(self):
        budgets = SQLiteBudgetStore(
            os.path.join(self.temp.name, "host-budgets.sqlite3"),
            BudgetPolicy(
                window_seconds=60, max_provider_calls=2,
                max_provider_input_bytes=10_000, max_tool_calls=2,
                max_task_steps=2, max_task_input_bytes=10_000,
            ),
        )
        host = self.make_host(budget_store=budgets)
        self.assertEqual(
            host.get_budget_usage("alice-token").used["provider_calls"], 0,
        )
        session = host.create_session("alice-token")
        host.run_turn("alice-token", session.session_id, "count this call")
        self.assertEqual(
            host.get_budget_usage("alice-token").used["provider_calls"], 1,
        )
        self.assertEqual(
            host.get_budget_usage("bob-token").used["provider_calls"], 0,
        )
        with self.assertRaises(HostAuthorityError):
            host.get_budget_usage("invalid-token")

    def test_host_discovers_budget_store_already_configured_on_tool_executor(self):
        budgets = SQLiteBudgetStore(
            os.path.join(self.temp.name, "preconfigured-budgets.sqlite3"),
            BudgetPolicy(max_provider_calls=2),
        )
        self.orchestrator.bridge.executor.set_budget_store(budgets)
        host = self.make_host()
        self.assertEqual(
            host.get_budget_usage("alice-token").used["provider_calls"], 0,
        )
        session = host.create_session("alice-token")
        host.run_turn("alice-token", session.session_id, "use inherited budget")
        self.assertEqual(
            host.get_budget_usage("alice-token").used["provider_calls"], 1,
        )

    def test_create_get_and_run_turn_are_bound_to_authenticated_principal(self):
        host = self.make_host()
        session = host.create_session("alice-token")
        self.assertEqual(host.get_session("alice-token", session.session_id), session)
        with self.assertRaises(SessionNotFoundError):
            host.get_session("bob-token", session.session_id)
        with self.assertRaises(SessionNotFoundError):
            host.run_turn("bob-token", session.session_id, "unauthorized")
        self.assertEqual(self.adapter.calls, [])

        result = host.run_turn("alice-token", session.session_id, "hello")
        self.assertEqual(result.result.final_text, "answer: hello")
        self.assertEqual(result.session.version, 1)
        self.assertEqual(
            host.get_session("alice-token", session.session_id),
            result.session,
        )
        with self.assertRaises(SessionNotFoundError):
            host.get_session("bob-token", session.session_id)

    def test_unauthorized_session_is_rejected_before_memory_retrieval(self):
        memory_calls = []
        host = self.make_host(
            memory_context_resolver=lambda principal, session_id, text: (
                memory_calls.append((principal, session_id, text))
                or UntrustedMemoryContext(())
            )
        )
        session = host.create_session("alice-token")
        with self.assertRaises(SessionNotFoundError):
            host.run_turn("bob-token", session.session_id, "try foreign session")
        self.assertEqual(memory_calls, [])
        self.assertEqual(self.adapter.calls, [])

        host.run_turn("alice-token", session.session_id, "allowed")
        self.assertEqual(memory_calls, [("alice", session.session_id, "allowed")])
        self.assertEqual(len(self.adapter.memory_contexts), 1)

    def test_unauthorized_session_is_rejected_before_graph_retrieval(self):
        graph_calls = []
        host = self.make_host(
            knowledge_context_resolver=lambda principal, session_id, text: (
                graph_calls.append((principal, session_id, text))
                or UntrustedKnowledgeContext((), (), text)
            )
        )
        session = host.create_session("alice-token")
        with self.assertRaises(SessionNotFoundError):
            host.run_turn("bob-token", session.session_id, "foreign graph query")
        self.assertEqual(graph_calls, [])
        self.assertEqual(self.adapter.knowledge_contexts, [])

        result = host.run_turn("alice-token", session.session_id, "allowed graph query")
        self.assertEqual(result.result.final_text, "knowledge-aware answer")
        self.assertEqual(graph_calls, [("alice", session.session_id, "allowed graph query")])
        self.assertEqual(len(self.adapter.knowledge_contexts), 1)

    def test_host_can_pass_memory_and_graph_as_separate_contexts(self):
        memory = UntrustedMemoryContext(())
        knowledge = UntrustedKnowledgeContext((), (), "combined query")
        host = self.make_host(
            memory_context_resolver=lambda *_: memory,
            knowledge_context_resolver=lambda *_: knowledge,
        )
        session = host.create_session("alice-token")
        result = host.run_turn("alice-token", session.session_id, "combined query")
        self.assertEqual(result.result.final_text, "memory-and-knowledge-aware answer")
        self.assertEqual(self.adapter.memory_contexts, [memory])
        self.assertEqual(self.adapter.knowledge_contexts, [knowledge])

    def test_close_is_owner_scoped_and_idempotent(self):
        host = self.make_host()
        session = host.create_session("alice-token")
        with self.assertRaises(SessionNotFoundError):
            host.close_session("bob-token", session.session_id)
        closed = host.close_session("alice-token", session.session_id)
        self.assertTrue(closed.closed)
        self.assertEqual(host.close_session("alice-token", session.session_id), closed)
        with self.assertRaises(SessionClosedError):
            host.run_turn("alice-token", session.session_id, "after close")

    def test_invalid_input_is_rejected_before_memory_callback(self):
        memory_calls = []
        host = self.make_host(
            memory_context_resolver=lambda *args: memory_calls.append(args)
        )
        session = host.create_session("alice-token")
        with self.assertRaises(HostRuntimeError):
            host.run_turn("alice-token", session.session_id, " " * 20)
        with self.assertRaises(HostRuntimeError):
            host.run_turn("alice-token", session.session_id, "x" * 16_001)
        self.assertEqual(memory_calls, [])
        self.assertEqual(self.adapter.calls, [])

    def test_memory_resolver_failure_is_redacted(self):
        def fail(*args):
            raise RuntimeError("private memory provider secret")

        host = self.make_host(memory_context_resolver=fail)
        session = host.create_session("alice-token")
        with self.assertRaises(HostRuntimeError) as caught:
            host.run_turn("alice-token", session.session_id, "hello")
        self.assertNotIn("private memory provider secret", str(caught.exception))
        self.assertEqual(self.adapter.calls, [])

    def test_invalid_credentials_are_rejected_by_trusted_authority(self):
        host = self.make_host()
        with self.assertRaises(HostAuthorityError):
            host.create_session("invalid-token")

    def test_task_worker_requires_explicit_host_configuration(self):
        host = self.make_host()
        with self.assertRaises(HostRuntimeError):
            host.run_task_worker(object())


    def test_task_creation_read_and_cancel_are_bound_to_authenticated_principal(self):
        worker = TaskWorker(TaskEngine(
            self.task_store,
            {},
            "worker",
            principal_handlers={"collect": lambda data, key, principal: {"ok": True}},
        ))
        host = self.make_host(task_worker=worker)
        task = host.create_task(
            "alice-token",
            [{"tool": "collect", "input": {"scope": "private"}}],
            idempotency_key="request-1",
        )
        self.assertEqual(host.get_task("alice-token", task.task_id), task)
        with self.assertRaises(TaskNotFoundError):
            host.get_task("bob-token", task.task_id)
        with self.assertRaises(TaskNotFoundError):
            host.cancel_task("bob-token", task.task_id)
        cancelled = host.cancel_task("alice-token", task.task_id)
        self.assertEqual(cancelled.state, "cancelled")
        self.assertEqual(host.get_task("alice-token", task.task_id), cancelled)
        with self.assertRaises(HostRuntimeError):
            host.create_task(
                "alice-token", [{"tool": "not-registered", "input": {}}]
            )

    def test_host_worker_dispatches_owned_task_only_to_authenticated_principal_handler(self):
        legacy_calls = []
        principal_calls = []
        worker = TaskWorker(TaskEngine(
            self.task_store,
            {
                "collect": lambda arguments, key: (
                    legacy_calls.append((arguments, key)) or {"legacy": True}
                ),
            },
            "host-integration-worker",
            principal_handlers={
                "collect": lambda arguments, key, principal_id: (
                    principal_calls.append((arguments, key, principal_id))
                    or {"owner": principal_id}
                ),
            },
        ))
        host = self.make_host(task_worker=worker)
        task = host.create_task(
            "alice-token",
            [{"tool": "collect", "input": {"scope": "private"}}],
            idempotency_key="host-worker-integration",
        )

        class StopAfterOneTask:
            def __init__(self):
                self.checks = 0

            def is_set(self):
                self.checks += 1
                return self.checks > 1

            def wait(self, timeout):
                return False

        host.run_task_worker(StopAfterOneTask())
        completed = host.get_task("alice-token", task.task_id)
        self.assertEqual(completed.state, "succeeded")
        self.assertEqual(len(principal_calls), 1)
        self.assertEqual(principal_calls[0][0], {"scope": "private"})
        self.assertEqual(principal_calls[0][2], "alice")
        self.assertEqual(legacy_calls, [])

    def test_task_creation_rejects_hostile_plan_containers_before_inspection(self):
        class HostileList(list):
            def __iter__(self):
                raise AssertionError("host must not iterate a custom list")

        class HostileDict(dict):
            def get(self, *args, **kwargs):
                raise AssertionError("host must not inspect a custom dict")

        worker = TaskWorker(TaskEngine(
            self.task_store,
            {},
            "worker",
            principal_handlers={"collect": lambda data, key, principal: {"ok": True}},
        ))
        host = self.make_host(task_worker=worker)

        with self.assertRaises(TaskValidationError):
            host.create_task(
                "alice-token",
                HostileList([{"tool": "collect", "input": {}}]),
            )
        with self.assertRaises(TaskValidationError):
            host.create_task(
                "alice-token",
                [HostileDict(tool="collect", input={})],
            )
        class HostileString(str):
            def __hash__(self):
                raise AssertionError("host must not hash a custom tool string")

        with self.assertRaises(TaskValidationError):
            host.create_task(
                "alice-token",
                [{"tool": HostileString("collect"), "input": {}}],
            )

    def test_principal_task_creation_requires_a_configured_worker_registry(self):
        host = self.make_host()
        with self.assertRaises(HostRuntimeError):
            host.create_task(
                "alice-token", [{"tool": "collect", "input": {}}]
            )

    def test_goal_operations_are_bound_to_authenticated_principal(self):
        goal_store = SQLiteGoalStore(os.path.join(self.temp.name, "goals.sqlite3"))
        worker = TaskWorker(TaskEngine(
            self.task_store, {}, "worker",
            principal_handlers={
                "collect": lambda data, key, principal: {"ok": True},
            },
        ))
        host = self.make_host(task_worker=worker, goal_store=goal_store)
        goal = host.create_goal(
            "alice-token", "Prepare a verified report",
            acceptance_criteria=["Sources cited", "Claims checked"],
            idempotency_key="goal-1",
        )
        self.assertEqual(host.get_goal("alice-token", goal.goal_id), goal)
        with self.assertRaises(GoalNotFoundError):
            host.get_goal("bob-token", goal.goal_id)
        with self.assertRaises(GoalNotFoundError):
            host.transition_goal(
                "bob-token", goal.goal_id, "planning", expected_version=1,
            )
        planned = host.save_goal_plan(
            "alice-token", goal.goal_id,
            GoalPlanProposal(({"tool": "collect", "input": {}},)),
            expected_version=1,
        )
        self.assertEqual(planned.state, "planned")
        self.assertEqual(planned.plan[0]["tool"], "collect")
        with self.assertRaises(GoalValidationError):
            host.save_goal_plan(
                "alice-token", goal.goal_id,
                GoalPlanProposal(({"tool": "admin", "input": {}},)),
                expected_version=2,
            )

    def test_host_coordinates_goal_task_and_reconciles_evidence(self):
        goal_store = SQLiteGoalStore(os.path.join(self.temp.name, "coordinated-goals.sqlite3"))
        worker = TaskWorker(TaskEngine(
            self.task_store, {}, "goal-worker",
            principal_handlers={
                "collect": lambda data, key, principal: {
                    "owner": principal, "collected": True,
                },
            },
        ))
        host = self.make_host(task_worker=worker, goal_store=goal_store)
        goal = host.create_goal(
            "alice-token", "Collect verified information",
            acceptance_criteria=["Evidence is recorded"],
        )
        planned = host.save_goal_plan(
            "alice-token", goal.goal_id,
            GoalPlanProposal(({"tool": "collect", "input": {}},)),
            expected_version=goal.version,
        )
        execution = host.prepare_goal(
            "alice-token", goal.goal_id, expected_version=planned.version,
        )
        self.assertEqual(execution.goal.state, "running")
        self.assertEqual(execution.task.state, "queued")
        self.assertEqual(host.get_goal_events("alice-token", goal.goal_id)[-1]["event_type"], "task_linked")
        self.assertEqual(worker.run_once().state, "succeeded")
        reconciled = host.reconcile_goal("alice-token", goal.goal_id)
        self.assertEqual(reconciled.goal.state, "awaiting_verification")
        self.assertEqual(len(reconciled.goal.evidence), 1)
        with self.assertRaises(HostRuntimeError):
            host.transition_goal(
                "alice-token", goal.goal_id, "succeeded",
                expected_version=reconciled.goal.version,
            )
        accepted = host.verify_goal(
            "alice-token", goal.goal_id, accepted=True,
            evidence_reference="d" * 64,
            expected_version=reconciled.goal.version,
        )
        self.assertEqual(accepted.state, "succeeded")
        self.assertEqual(len(accepted.evidence), 2)
        with self.assertRaises(GoalNotFoundError):
            host.get_goal_events("bob-token", goal.goal_id)

    def test_host_cancellation_uses_coordinator_for_linked_goal(self):
        goal_store = SQLiteGoalStore(os.path.join(self.temp.name, "cancel-goals.sqlite3"))
        worker = TaskWorker(TaskEngine(
            self.task_store, {}, "cancel-worker",
            principal_handlers={"collect": lambda data, key, principal: {"ok": True}},
        ))
        host = self.make_host(task_worker=worker, goal_store=goal_store)
        goal = host.create_goal(
            "alice-token", "Do one safe task", acceptance_criteria=["Done"],
        )
        planned = host.save_goal_plan(
            "alice-token", goal.goal_id,
            GoalPlanProposal(({"tool": "collect", "input": {}},)),
            expected_version=goal.version,
        )
        execution = host.prepare_goal(
            "alice-token", goal.goal_id, expected_version=planned.version,
        )
        with self.assertRaises(HostRuntimeError):
            host.transition_goal(
                "alice-token", goal.goal_id, "cancelled",
                expected_version=execution.goal.version,
            )
        cancelled = host.cancel_goal(
            "alice-token", goal.goal_id, expected_version=execution.goal.version,
        )
        self.assertEqual(cancelled.goal.state, "cancelled")
        self.assertEqual(cancelled.task.state, "cancelled")

    def test_host_wires_one_budget_ledger_across_provider_tools_and_tasks(self):
        budget_store = SQLiteBudgetStore(
            os.path.join(self.temp.name, "host-budgets.sqlite3"),
            BudgetPolicy(
                window_seconds=3600, max_provider_calls=1,
                max_provider_input_bytes=10_000, max_tool_calls=2,
                max_task_steps=3, max_task_input_bytes=10_000,
            ),
        )
        worker = TaskWorker(TaskEngine(
            self.task_store, {}, "budget-worker",
            principal_handlers={"collect": lambda data, key, principal: {"ok": True}},
        ))
        host = self.make_host(task_worker=worker, budget_store=budget_store)
        self.assertIs(host._orchestrator.budget_store, budget_store)
        self.assertIs(host._orchestrator.bridge.executor.budget_store, budget_store)
        self.assertIs(worker.engine.budget_store, budget_store)
        session = host.create_session("alice-token")
        host.run_turn("alice-token", session.session_id, "first call")
        with self.assertRaises(BudgetExceededError):
            host.run_turn("alice-token", session.session_id, "second call")
        self.assertEqual(len(self.adapter.calls), 1)
        usage = host.get_budget_usage("alice-token")
        self.assertEqual(usage.used["provider_calls"], 1)
        with self.assertRaises(BudgetExceededError):
            budget_store.reserve_for_principal(
                "alice", {"provider_calls": 1},
            )
        self.assertEqual(host.get_budget_usage("bob-token").used["provider_calls"], 0)

    def test_goal_api_requires_configured_store_and_authentication(self):
        host = self.make_host()
        with self.assertRaises(HostRuntimeError):
            host.create_goal(
                "alice-token", "outcome", acceptance_criteria=["done"],
            )
        goal_store = SQLiteGoalStore(os.path.join(self.temp.name, "goals-auth.sqlite3"))
        configured = self.make_host(goal_store=goal_store)
        with self.assertRaises(HostAuthorityError):
            configured.create_goal(
                "invalid-token", "outcome", acceptance_criteria=["done"],
            )


    def test_goal_report_is_read_only_owner_scoped_and_redacts_task_results(self):
        goal_store = SQLiteGoalStore(
            os.path.join(self.temp.name, "goal-report.sqlite3")
        )
        engine = TaskEngine(
            self.task_store,
            {},
            "goal-report-worker",
            principal_handlers={
                "collect": lambda arguments, idempotency_key, principal_id: {
                    "message": "private raw result",
                },
            },
        )
        worker = TaskWorker(
            engine, poll_interval_seconds=0.05, heartbeat_interval_seconds=0.1,
        )
        host = self.make_host(task_worker=worker, goal_store=goal_store)
        goal = host.create_goal(
            "alice-token", "Prepare a verified report",
            acceptance_criteria=["Evidence is checked"],
        )
        planned = host.save_goal_plan(
            "alice-token", goal.goal_id,
            GoalPlanProposal(({"tool": "collect", "input": {}},)),
            expected_version=goal.version,
        )
        host.prepare_goal(
            "alice-token", goal.goal_id, expected_version=planned.version,
        )

        events_before = host.get_goal_events("alice-token", goal.goal_id)
        active = host.get_goal_report("alice-token", goal.goal_id)
        self.assertEqual(active.completion_status, "in_progress")
        self.assertEqual(active.steps_completed, 0)
        self.assertEqual(host.get_goal_events("alice-token", goal.goal_id), events_before)
        with self.assertRaises(GoalNotFoundError):
            host.get_goal_report("bob-token", goal.goal_id)

        worker.run_once()
        completed_task = host.get_goal_report("alice-token", goal.goal_id)
        self.assertEqual(completed_task.completion_status, "reconciliation_pending")
        self.assertNotIn("private raw result", str(completed_task.as_dict()))
        self.assertEqual(host.get_goal_events("alice-token", goal.goal_id), events_before)

        host.reconcile_goal("alice-token", goal.goal_id)
        awaiting = host.get_goal_report("alice-token", goal.goal_id)
        self.assertEqual(awaiting.completion_status, "awaiting_owner_verification")
        self.assertEqual(awaiting.owner_acceptance_status, "pending")
        accepted = host.verify_goal(
            "alice-token", goal.goal_id, accepted=True,
            evidence_reference="d" * 64,
            expected_version=awaiting.goal_version,
        )
        self.assertEqual(accepted.state, "succeeded")
        final = host.get_goal_report("alice-token", goal.goal_id)
        self.assertEqual(final.completion_status, "completed")
        self.assertEqual(final.owner_acceptance_status, "accepted")


    def test_trusted_host_composes_execution_evidence_and_signed_strategy_authorities(self):
        principal_id = "p" * 256
        authority = HostAuthorityResolver(
            authenticate=lambda credential: (
                principal_id if credential == "host-token"
                else ("bob" if credential == "bob-token" else None)
            ),
            permissions_for=lambda _principal: (),
        )
        execution_mac = HmacApprovalKeyRing(
            {"execution-v1": b"e" * 32}, active_key_id="execution-v1",
        )
        journal = SQLiteExecutionEvidenceJournal(
            self.task_store,
            execution_mac,
            authenticate_collector=lambda credential: (
                principal_id if credential == "execution-token" else None
            ),
            classify_task=lambda principal, task_id: TaskClassification(
                "research", "bounded-research",
            ),
            resolve_strategy=lambda principal, claim: StrategyBinding(
                "reasoning", "baseline", "1.0",
            ),
            verify_result=lambda principal, claim, result, digest: VerifiedExecutionResult(
                digest, "verified_success", False, 1, 128, 1, 25,
            ),
        )
        engine = TaskEngine(
            self.task_store,
            {},
            "evidence-worker",
            principal_handlers={
                "research": lambda inputs, key, principal: {"status": "verified"},
            },
            execution_evidence_journal=journal,
            execution_evidence_credential=lambda claim: "execution-token",
        )
        worker = TaskWorker(engine)

        manifest_store = SQLiteStrategyEvidenceManifestStore(
            self.task_store,
            authenticate_collector=lambda credential: (
                principal_id if credential == "manifest-token" else None
            ),
            classify_task_family=lambda principal, task_id: "research",
            validate_source_events=lambda principal, strategy_class, observations, families: (
                principal == principal_id and len(observations) == 40
                and all(families[item.task_id] == "research" for item in observations)
            ),
        )
        evidence_authority = HostStrategyEvidenceAuthority(
            HmacApprovalKeyRing(
                {"evidence-v1": b"v" * 32}, active_key_id="evidence-v1",
            ),
            authenticate_collector=lambda credential: (
                principal_id if credential == "manifest-token" else None
            ),
            attest_manifest=manifest_store.attest_manifest,
            verify_manifest=manifest_store.verify_manifest,
        )
        approval_authority = HostStrategyApprovalAuthority(
            HmacApprovalKeyRing(
                {"approval-v1": b"a" * 32}, active_key_id="approval-v1",
            ),
            authenticate_approver=lambda credential: (
                StrategyApprovalIdentity(principal_id, "host-admin")
                if credential == "host-token" else None
            ),
            authorize_approver=lambda identity, request: (
                identity.principal_id == principal_id
                and identity.approver_id == "host-admin"
                and request.principal_id == principal_id
            ),
        )
        class SpoofedBoundVerifier:
            def __init__(self, authority):
                self.__self__ = authority
                self.__func__ = type(authority).verify

            def __call__(self, _payload):
                return True

        untrusted_store = SQLiteStrategyStore(
            self.task_store,
            approval_verifier=SpoofedBoundVerifier(approval_authority),
            evidence_verifier=SpoofedBoundVerifier(evidence_authority),
        )
        with self.assertRaises(HostRuntimeError):
            CapriHostRuntime(
                authority,
                self.store,
                self.orchestrator,
                task_store=self.task_store,
                strategy_store=untrusted_store,
                strategy_approval_authority=approval_authority,
                strategy_evidence_authority=evidence_authority,
            )

        host = CapriHostRuntime(
            authority,
            self.store,
            self.orchestrator,
            task_worker=worker,
            task_store=self.task_store,
            execution_evidence_journal=journal,
            strategy_approval_authority=approval_authority,
            strategy_evidence_authority=evidence_authority,
        )

        task = host.create_task(
            "host-token", [{"tool": "research", "input": {"query": "bounded"}}],
        )
        completed = worker.run_once()
        self.assertEqual(completed.state, "succeeded")
        reference = host.get_execution_evidence_ref(
            "host-token", task.task_id, 0, 1,
        )
        self.assertTrue(reference.startswith("host-execution-event:"))
        self.assertEqual(host.storage_health()["execution_evidence"], "healthy")
        with self.assertRaises(HostRuntimeError):
            host.get_execution_evidence_ref("bob-token", task.task_id, 0, 1)

        observations = []
        for index in range(20):
            task_id = f"task-{index:03d}"
            base = {
                "task_id": task_id,
                "scenario": "research",
                "evidence_ref": f"host-execution-event:baseline:{task_id}",
                "tool_calls": 5,
                "context_tokens": 1000,
                "estimated_cost_units": 100,
                "latency_ms": 2000,
            }
            observations.append(StrategyObservation(
                strategy_id="baseline", strategy_version="1.0",
                outcome="verified_success", **base,
            ))
            candidate = dict(base)
            candidate["evidence_ref"] = f"host-execution-event:candidate:{task_id}"
            candidate["estimated_cost_units"] = 90
            observations.append(StrategyObservation(
                strategy_id="candidate", strategy_version="2.0",
                outcome="verified_success", **candidate,
            ))
        context = manifest_store.register_manifest(
            "manifest-token",
            strategy_class="reasoning",
            baseline_id="baseline",
            candidate_id="candidate",
            observations=tuple(observations),
        )
        attestation = evidence_authority.issue("manifest-token", context)
        verified_context = replace(context, evidence_manifest_ref=attestation)
        self.assertTrue(evidence_authority.verify(verified_context))
        self.assertTrue(host._strategy_store._evidence_verifier(verified_context))
        baseline = host.register_strategy_baseline(
            "host-token", "reasoning", "baseline", "1.0", {"mode": "safe"},
        )
        self.assertEqual(baseline.principal_id, principal_id)
        request = StrategyApprovalRequest(
            principal_id=principal_id,
            strategy_class="reasoning",
            strategy_id="candidate",
            version="2.0",
            evaluation_sha256="b" * 64,
            config_sha256="c" * 64,
            expected_generation=0,
            action="activate",
        )
        grant = host.issue_strategy_activation_grant("host-token", request)
        self.assertTrue(host._strategy_store._approval_verifier(grant))

        with self.assertRaises(HostRuntimeError):
            self.make_host(task_store=self.task_store, task_worker=worker)

    def test_sqlite_worker_reservation_recovers_after_host_runtime_recreation(self):
        registry = SQLiteWorkerRegistry(self.task_store)
        host = self.make_worker_host(
            registry, {"worker-token": "worker-1"}, lambda *args: {"worker-1"},
        )
        host.register_worker(
            "worker-token",
            WorkerDescriptor("worker-1", (1,), ("math.factorial",), max_concurrency=1),
        )
        host.heartbeat_worker("monitor-token", "worker-1")
        task = self.task_store.create_for_principal(
            "alice", [{"tool": "collect", "input": {"scope": "durable"}}],
        )
        pending = host.reserve_worker_candidate(
            "alice-token", task.task_id, "math.factorial", 1,
        )
        self.assertIsNotNone(pending)

        reopened_registry = SQLiteWorkerRegistry(self.task_store)
        reopened_host = self.make_worker_host(
            reopened_registry, {"worker-token": "worker-1"}, lambda *args: {"worker-1"},
        )
        recovered = reopened_host.get_worker_reservation_for_task(
            "alice-token", task.task_id,
        )
        self.assertIsNotNone(recovered)
        self.assertEqual(recovered.reservation.token, pending.reservation.token)
        committed = reopened_host.commit_worker_reservation(
            "alice-token", "monitor-token", recovered,
        )
        self.assertTrue(committed.reservation.committed)
        self.assertTrue(reopened_host.release_worker_reservation(
            "monitor-token", committed,
        ))
        self.assertEqual(reopened_host.storage_health()["worker_registry"], "healthy")

    def test_sqlite_expired_reservation_context_is_pruned_before_next_reserve(self):
        now = {"value": 1_000_000_000}
        registry = SQLiteWorkerRegistry(
            self.task_store,
            heartbeat_ttl_ms=5_000,
            reservation_ttl_ms=1_000,
            clock_ns=lambda: now["value"],
            clock_wall_ns=lambda: now["value"],
        )
        host = self.make_worker_host(
            registry, {"worker-token": "worker-1"}, lambda *args: {"worker-1"},
        )
        host.register_worker(
            "worker-token",
            WorkerDescriptor("worker-1", (1,), ("math.factorial",), max_concurrency=1),
        )
        host.heartbeat_worker("monitor-token", "worker-1")
        first_task = self.task_store.create_for_principal(
            "alice", [{"tool": "collect", "input": {"scope": "first"}}],
        )
        first = host.reserve_worker_candidate(
            "alice-token", first_task.task_id, "math.factorial", 1,
        )
        self.assertIsNotNone(first)
        self.assertIn(first.reservation.token, host._worker_reservation_contexts)

        now["value"] += 2_000_000_000
        second_task = self.task_store.create_for_principal(
            "alice", [{"tool": "collect", "input": {"scope": "second"}}],
        )
        second = host.reserve_worker_candidate(
            "alice-token", second_task.task_id, "math.factorial", 1,
        )
        self.assertIsNotNone(second)
        self.assertNotIn(first.reservation.token, host._worker_reservation_contexts)
        self.assertIn(second.reservation.token, host._worker_reservation_contexts)
        self.assertIsNone(registry.get_reservation(first.reservation.token))
        self.assertTrue(any(
            event.tool_name == "worker.reservation.expired"
            for event in audit._events
        ))
        self.assertEqual(registry.integrity_check(), "ok")
        self.assertTrue(host.release_worker_reservation("monitor-token", second))
        self.assertFalse(audit.worker_lifecycle_reconciliation_required())

    def test_sqlite_worker_registry_must_share_exact_host_task_store(self):
        other_store = SQLiteTaskStore(
            os.path.join(self.temp.name, "other-tasks.sqlite3")
        )
        registry = SQLiteWorkerRegistry(other_store)
        with self.assertRaisesRegex(HostRuntimeError, "exact configured task store"):
            self.make_worker_host(
                registry, {"worker-token": "worker-1"}, lambda *args: {"worker-1"},
            )

if __name__ == "__main__":
    unittest.main()
