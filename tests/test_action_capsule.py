import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from capri_core.action_capsule import (
    ActionCapsuleError,
    CapsuleIntegrityError,
    CapsuleState,
    create_action_capsule,
    transition_action_capsule,
    verify_action_capsule_history,
)


class ActionCapsuleTests(unittest.TestCase):
    def setUp(self):
        self.created = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
        self.deadline = self.created + timedelta(minutes=5)
        self.capsule = create_action_capsule(
            capsule_id="capsule-001",
            intent_digest="a" * 64,
            principal_id="principal-1",
            capability="repository.create_branch",
            resource_scope=("repo:Hamudifr/Capri",),
            policy_version="policy-v1",
            budgets={"max_calls": 3, "max_runtime_ms": 30_000},
            deadline_at=self.deadline.isoformat(),
            idempotency_key="task-001:branch-create",
            input_digest="b" * 64,
            created_at=self.created.isoformat(),
        )

    def step(self, capsule, target, seconds, *, history=(), **kwargs):
        return transition_action_capsule(
            capsule,
            target,
            history=history,
            occurred_at=(self.created + timedelta(seconds=seconds)).isoformat(),
            actor="host-1",
            **kwargs,
        )

    def full_history(self):
        capsule = self.capsule
        events = []
        for target, seconds, extra in (
            (CapsuleState.AUTHORIZED, 1, {"approval_ref": "approval-1"}),
            (CapsuleState.DISPATCHED, 2, {"worker_binding": "worker-channel-1"}),
            (CapsuleState.RECEIVED, 3, {"result_digest": "c" * 64}),
            (CapsuleState.VERIFIED, 4, {
                "evidence_refs": ("receipt:provider-1", "readback:resource-1"),
                "verifier_id": "verifier-host-1",
                "verifier_version": "verify-v1",
            }),
            (CapsuleState.ACCEPTED, 5, {}),
        ):
            capsule, event = self.step(capsule, target, seconds, history=events, **extra)
            events.append(event)
        return capsule, tuple(events)

    def test_full_lifecycle_and_hash_chain_verify(self):
        capsule, events = self.full_history()
        self.assertEqual(capsule.state, CapsuleState.ACCEPTED)
        self.assertEqual(capsule.event_sequence, 5)
        verify_action_capsule_history(capsule, events)

    def test_capsule_normalizes_scope_budgets_and_timestamps(self):
        capsule = create_action_capsule(
            capsule_id="capsule-2", intent_digest="a" * 64,
            principal_id="principal-1", capability="file.read",
            resource_scope=("z", "a", "a"), policy_version="policy-v1",
            budgets={"max_bytes": 20, "max_calls": 2},
            deadline_at=self.deadline.isoformat(), idempotency_key="idem-2",
            input_digest="b" * 64, created_at=self.created.isoformat(),
        )
        self.assertEqual(capsule.resource_scope, ("a", "z"))
        self.assertEqual(capsule.budgets, (("max_bytes", 20), ("max_calls", 2)))

    def test_invalid_directly_constructed_capsule_fails_closed(self):
        forged = replace(self.capsule, policy_version="policy-v2")
        with self.assertRaises(CapsuleIntegrityError):
            transition_action_capsule(
                forged, CapsuleState.AUTHORIZED,
                occurred_at=(self.created + timedelta(seconds=1)).isoformat(),
                actor="host-1", approval_ref="approval-1",
            )

    def test_authorization_and_dispatch_require_host_references(self):
        with self.assertRaises(ActionCapsuleError):
            self.step(self.capsule, CapsuleState.AUTHORIZED, 1)
        authorized, auth_event = self.step(
            self.capsule, CapsuleState.AUTHORIZED, 1, approval_ref="approval-1"
        )
        with self.assertRaises(ActionCapsuleError):
            self.step(authorized, CapsuleState.DISPATCHED, 2, history=(auth_event,))

    def test_request_cannot_skip_authorization_or_dispatch(self):
        with self.assertRaises(ActionCapsuleError):
            self.step(self.capsule, CapsuleState.DISPATCHED, 1, worker_binding="worker-1")
        authorized, _ = self.step(
            self.capsule, CapsuleState.AUTHORIZED, 1, approval_ref="approval-1"
        )
        with self.assertRaises(ActionCapsuleError):
            self.step(authorized, CapsuleState.ACCEPTED, 2)

    def test_receipt_requires_result_digest_and_verification_requires_evidence(self):
        authorized, auth_event = self.step(
            self.capsule, CapsuleState.AUTHORIZED, 1, approval_ref="approval-1"
        )
        dispatched, dispatch_event = self.step(
            authorized, CapsuleState.DISPATCHED, 2,
            history=(auth_event,), worker_binding="worker-1"
        )
        with self.assertRaises(ActionCapsuleError):
            self.step(dispatched, CapsuleState.RECEIVED, 3)
        received, received_event = self.step(
            dispatched, CapsuleState.RECEIVED, 3,
            history=(auth_event, dispatch_event), result_digest="c" * 64
        )
        with self.assertRaises(ActionCapsuleError):
            self.step(received, CapsuleState.VERIFIED, 4,
                      history=(auth_event, dispatch_event, received_event))

    def test_dispatched_deadline_becomes_indeterminate_not_expired(self):
        authorized, auth_event = self.step(
            self.capsule, CapsuleState.AUTHORIZED, 1, approval_ref="approval-1"
        )
        dispatched, dispatch_event = self.step(
            authorized, CapsuleState.DISPATCHED, 2,
            history=(auth_event,), worker_binding="worker-1"
        )
        late = self.deadline + timedelta(seconds=1)
        with self.assertRaises(ActionCapsuleError):
            transition_action_capsule(
                dispatched, CapsuleState.RECEIVED, history=(auth_event, dispatch_event),
                occurred_at=late.isoformat(), actor="host-1",
                result_digest="c" * 64,
            )
        indeterminate, event = transition_action_capsule(
            dispatched, CapsuleState.INDETERMINATE, history=(auth_event, dispatch_event),
            occurred_at=late.isoformat(), actor="host-1",
            reason_code="worker_timeout",
        )
        verify_action_capsule_history(indeterminate, (auth_event, dispatch_event, event))

    def test_expired_undispatched_draft_can_be_closed_without_authority(self):
        late = self.deadline + timedelta(seconds=1)
        cancelled, event = transition_action_capsule(
            self.capsule,
            CapsuleState.CANCELLED,
            occurred_at=late.isoformat(),
            actor="host-1",
        )
        self.assertEqual(cancelled.state, CapsuleState.CANCELLED)
        verify_action_capsule_history(cancelled, (event,))

    def test_history_verification_has_a_hard_event_bound(self):
        def unbounded_events():
            while True:
                yield object()

        with self.assertRaises(CapsuleIntegrityError):
            verify_action_capsule_history(self.capsule, unbounded_events())

        with self.assertRaises(ActionCapsuleError):
            replace(self.capsule, event_sequence=6)

    def test_authorized_capsule_expires_only_at_or_after_deadline(self):
        authorized, auth_event = self.step(
            self.capsule, CapsuleState.AUTHORIZED, 1, approval_ref="approval-1"
        )
        with self.assertRaises(ActionCapsuleError):
            transition_action_capsule(
                authorized, CapsuleState.EXPIRED, history=(auth_event,),
                occurred_at=(self.deadline - timedelta(seconds=1)).isoformat(),
                actor="host-1",
            )
        expired, event = transition_action_capsule(
            authorized, CapsuleState.EXPIRED, history=(auth_event,),
            occurred_at=self.deadline.isoformat(), actor="host-1",
        )
        verify_action_capsule_history(expired, (auth_event, event))

    def test_state_projection_cannot_skip_its_event_history(self):
        authorized = replace(
            self.capsule,
            state=CapsuleState.AUTHORIZED,
            approval_ref="fabricated-approval",
            event_sequence=1,
            updated_at=(self.created + timedelta(seconds=1)).isoformat(),
            last_event_hash="c" * 64,
        )
        with self.assertRaises(CapsuleIntegrityError):
            transition_action_capsule(
                authorized, CapsuleState.DISPATCHED,
                occurred_at=(self.created + timedelta(seconds=2)).isoformat(),
                actor="host-1", worker_binding="worker-1",
            )

    def test_event_tampering_is_detected(self):
        capsule, events = self.full_history()
        tampered = (events[0], replace(events[1], actor="attacker")) + events[2:]
        with self.assertRaises(CapsuleIntegrityError):
            verify_action_capsule_history(capsule, tampered)

    def test_projection_tampering_is_detected(self):
        capsule, events = self.full_history()
        forged = replace(capsule, result_digest="d" * 64)
        with self.assertRaises(CapsuleIntegrityError):
            verify_action_capsule_history(forged, events)

    def test_missing_or_reordered_history_is_detected(self):
        capsule, events = self.full_history()
        with self.assertRaises(CapsuleIntegrityError):
            verify_action_capsule_history(capsule, events[:-1])
        with self.assertRaises(CapsuleIntegrityError):
            verify_action_capsule_history(capsule, tuple(reversed(events)))

    def test_timestamps_are_monotonic_and_deadline_is_enforced(self):
        authorized, auth_event = self.step(
            self.capsule, CapsuleState.AUTHORIZED, 1, approval_ref="approval-1"
        )
        with self.assertRaises(ActionCapsuleError):
            self.step(authorized, CapsuleState.DISPATCHED, 0,
                      history=(auth_event,), worker_binding="worker-1")
        with self.assertRaises(ActionCapsuleError):
            create_action_capsule(
                capsule_id="late", intent_digest="a" * 64,
                principal_id="principal-1", capability="file.read",
                resource_scope=("file-1",), policy_version="policy-v1",
                budgets={"max_calls": 1}, deadline_at=self.created.isoformat(),
                idempotency_key="idem", input_digest="b" * 64,
                created_at=self.created.isoformat(),
            )

    def test_non_iterable_evidence_rejected_with_domain_error(self):
        authorized, auth_event = self.step(
            self.capsule, CapsuleState.AUTHORIZED, 1, approval_ref="approval-1"
        )
        dispatched, dispatch_event = self.step(
            authorized, CapsuleState.DISPATCHED, 2,
            history=(auth_event,), worker_binding="worker-1"
        )
        received, received_event = self.step(
            dispatched, CapsuleState.RECEIVED, 3,
            history=(auth_event, dispatch_event), result_digest="c" * 64
        )
        with self.assertRaises(ActionCapsuleError):
            transition_action_capsule(
                received, CapsuleState.VERIFIED,
                history=(auth_event, dispatch_event, received_event),
                occurred_at=(self.created + timedelta(seconds=4)).isoformat(),
                actor="host-1", evidence_refs=None,
                verifier_id="verifier-1", verifier_version="v1",
            )

    def test_invalid_budget_types_and_duplicate_scope_are_normalized_or_rejected(self):
        with self.assertRaises(ActionCapsuleError):
            create_action_capsule(
                capsule_id="bad", intent_digest="a" * 64,
                principal_id="principal-1", capability="file.read",
                resource_scope=("file-1",), policy_version="policy-v1",
                budgets={"max_calls": True}, deadline_at=self.deadline.isoformat(),
                idempotency_key="idem", input_digest="b" * 64,
                created_at=self.created.isoformat(),
            )


if __name__ == "__main__":
    unittest.main()
