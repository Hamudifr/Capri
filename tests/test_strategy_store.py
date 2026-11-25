import os
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from capri_core.strategy import StrategyObservation, evaluate_strategies
from capri_runtime.tasks import SQLiteTaskStore
from capri_runtime.strategy_store import (
    SQLiteStrategyStore,
    StrategyActivationGrant,
    StrategyAuthorizationError,
    StrategyConflictError,
    StrategyIntegrityError,
    StrategyNotFoundError,
    StrategyStoreError,
)


def make_observations(count=20):
    records = []
    for index in range(count):
        task_id = f"task-{index:03d}"
        common = {
            "task_id": task_id,
            "scenario": "research",
            "evidence_ref": f"test://evidence/{task_id}",
            "strategy_version": "1.0",
            "tool_calls": 5,
            "context_tokens": 1000,
            "estimated_cost_units": 100,
            "latency_ms": 2000,
        }
        records.append(StrategyObservation(
            strategy_id="baseline", outcome="verified_success", **common,
        ))
        records.append(StrategyObservation(
            strategy_id="candidate", outcome="verified_success",
            estimated_cost_units=90, **{k: v for k, v in common.items() if k != "estimated_cost_units"},
        ))
    return tuple(records)


class SQLiteStrategyStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        if os.name == "posix":
            os.chmod(self.temp.name, 0o700)
        self.task_store = SQLiteTaskStore(os.path.join(self.temp.name, "tasks.sqlite3"))
        self.store = SQLiteStrategyStore(
            self.task_store,
            approval_verifier=lambda grant: grant.signature == "valid",
            evidence_verifier=lambda context: True,
        )
        self.observations = make_observations()
        self.evaluation = evaluate_strategies("baseline", "candidate", self.observations)
        self.baseline = self.store.register_baseline_for_principal(
            "alice", "reasoning", "baseline", "1.0", {"mode": "standard"},
        )
        self.candidate = self.store.register_candidate_for_principal(
            "alice", "reasoning", "candidate", "1.0",
            {"mode": "efficient", "temperature": 0.1},
            self.evaluation,
            observations=self.observations,
            evidence_manifest_ref="test://manifests/cohort-001",
        )

    def tearDown(self):
        self.temp.cleanup()

    def grant(
        self, *, principal="alice", strategy_id="baseline", version="1.0",
        evaluation_sha256=None, config_sha256=None, generation=0,
        action="activate", signature="valid", grant_id=None, now=None,
    ):
        now = now or datetime.now(timezone.utc)
        record = self.baseline if strategy_id == "baseline" else self.candidate
        return StrategyActivationGrant(
            grant_id=grant_id or uuid4().hex,
            principal_id=principal,
            strategy_class="reasoning",
            strategy_id=strategy_id,
            version=version,
            evaluation_sha256=evaluation_sha256,
            config_sha256=config_sha256 or record.config_sha256,
            expected_generation=generation,
            action=action,
            issued_at=(now - timedelta(seconds=1)).isoformat(),
            expires_at=(now + timedelta(minutes=5)).isoformat(),
            approver_id="owner",
            signature=signature,
        )

    def activate_baseline(self):
        return self.store.activate_for_principal(
            "alice", self.grant(),
        )

    def test_candidate_registration_is_not_activation_and_activation_is_reversible(self):
        self.assertIsNone(self.store.get_active_for_principal("alice", "reasoning"))
        baseline = self.activate_baseline()
        self.assertEqual((baseline.strategy_id, baseline.generation), ("baseline", 1))

        candidate = self.store.activate_for_principal(
            "alice",
            self.grant(
                strategy_id="candidate",
                evaluation_sha256=self.evaluation.cohort_sha256,
                generation=1,
            ),
        )
        self.assertEqual((candidate.strategy_id, candidate.generation), ("candidate", 2))
        self.assertEqual(candidate.config, {"mode": "efficient", "temperature": 0.1})

        rollback = self.store.rollback_for_principal(
            "alice", self.grant(strategy_id="baseline", generation=2, action="rollback"),
        )
        self.assertEqual((rollback.strategy_id, rollback.generation), ("baseline", 3))
        events = self.store.events_for_principal("alice", "reasoning")
        self.assertEqual([event.action for event in events], ["activate", "activate", "rollback"])
        self.assertEqual([event.generation for event in events], [1, 2, 3])
        self.assertEqual(events[0].previous_hash, "")
        self.assertEqual(events[1].previous_hash, events[0].event_hash)
        self.assertEqual(events[2].previous_hash, events[1].event_hash)

    def test_default_missing_verifier_denies_activation(self):
        store = SQLiteStrategyStore(self.task_store)
        grant = self.grant()
        with self.assertRaises(StrategyAuthorizationError):
            store.activate_for_principal("alice", grant)

    def test_false_or_failing_verifier_denies_activation(self):
        for verifier in (lambda grant: False, lambda grant: (_ for _ in ()).throw(RuntimeError())):
            store = SQLiteStrategyStore(self.task_store, approval_verifier=verifier)
            with self.subTest(verifier=verifier), self.assertRaises(StrategyAuthorizationError):
                store.activate_for_principal("alice", self.grant())

    def test_grant_expiring_before_event_publication_never_commits(self):
        now = datetime.now(timezone.utc)
        clock_values = [now, now, now + timedelta(seconds=2)]

        def clock():
            return clock_values.pop(0)

        store = SQLiteStrategyStore(
            self.task_store,
            approval_verifier=lambda grant: True,
            clock=clock,
        )
        grant = replace(
            self.grant(now=now),
            expires_at=(now + timedelta(seconds=1)).isoformat(),
        )
        with self.assertRaises(StrategyAuthorizationError):
            store.activate_for_principal("alice", grant)
        self.assertIsNone(store.get_active_for_principal("alice", "reasoning"))
        self.assertEqual(store.events_for_principal("alice", "reasoning"), ())

    def test_expired_and_future_approval_grants_are_rejected(self):
        now = datetime.now(timezone.utc)
        expired = replace(
            self.grant(now=now - timedelta(hours=1)),
            issued_at=(now - timedelta(hours=2)).isoformat(),
            expires_at=(now - timedelta(hours=1)).isoformat(),
        )
        future = replace(
            self.grant(now=now + timedelta(hours=1)),
            issued_at=(now + timedelta(hours=1)).isoformat(),
            expires_at=(now + timedelta(hours=2)).isoformat(),
        )
        for grant in (expired, future):
            with self.subTest(grant=grant), self.assertRaises(StrategyAuthorizationError):
                self.store.activate_for_principal("alice", grant)

    def test_approval_expiring_during_host_verification_is_rejected(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        clock_state = {"now": now}

        def verifier(grant):
            clock_state["now"] = now + timedelta(minutes=6)
            return True

        store = SQLiteStrategyStore(
            self.task_store,
            approval_verifier=verifier,
            clock=lambda: clock_state["now"],
        )
        grant = self.grant(now=now)
        with self.assertRaisesRegex(
            StrategyAuthorizationError, "expired before the transition"
        ):
            store.activate_for_principal("alice", grant)
        self.assertEqual(store.events_for_principal("alice", "reasoning"), ())

    def test_wrong_principal_action_or_signature_is_rejected(self):
        cases = (
            (self.grant(principal="bob"), "alice", "principal"),
            (self.grant(action="rollback"), "alice", "action"),
            (self.grant(signature="forged"), "alice", "signature"),
        )
        for grant, principal, label in cases:
            with self.subTest(label=label), self.assertRaises(StrategyAuthorizationError):
                self.store.activate_for_principal(principal, grant)

    def test_config_and_evaluation_fingerprints_are_bound_to_approval(self):
        wrong_config = self.grant(config_sha256="0" * 64)
        wrong_evaluation = self.grant(
            strategy_id="candidate",
            evaluation_sha256="0" * 64,
            generation=0,
        )
        for grant in (wrong_config, wrong_evaluation):
            with self.subTest(grant=grant), self.assertRaises(StrategyAuthorizationError):
                self.store.activate_for_principal("alice", grant)

    def test_stale_generation_and_replayed_grant_are_rejected(self):
        grant = self.grant()
        self.store.activate_for_principal("alice", grant)
        with self.assertRaises(StrategyConflictError):
            self.store.activate_for_principal("alice", grant)

        replay = self.grant(
            strategy_id="candidate",
            evaluation_sha256=self.evaluation.cohort_sha256,
            generation=1,
            grant_id=grant.grant_id,
        )
        with self.assertRaises(StrategyConflictError):
            self.store.activate_for_principal("alice", replay)

    def test_rollback_target_must_have_been_active_before(self):
        self.activate_baseline()
        grant = self.grant(
            strategy_id="candidate",
            evaluation_sha256=self.evaluation.cohort_sha256,
            generation=1,
            action="rollback",
        )
        with self.assertRaises(StrategyConflictError):
            self.store.rollback_for_principal("alice", grant)

    def test_registry_rejects_candidate_version_not_used_in_evaluation(self):
        observations = make_observations()
        changed = tuple(
            replace(record, strategy_version="2.0")
            if record.strategy_id == "candidate" else record
            for record in observations
        )
        evaluation = evaluate_strategies("baseline", "candidate", changed)
        with self.assertRaises(StrategyStoreError):
            self.store.register_candidate_for_principal(
                "alice", "reasoning", "candidate", "1.0", {"mode": "other"},
                evaluation, observations=changed,
                evidence_manifest_ref="test://manifests/wrong-version",
            )

    def test_candidate_evaluation_is_recomputed_from_exact_observations(self):
        forged = replace(self.evaluation, eligible_for_manual_review=False)
        with self.assertRaises(StrategyStoreError):
            self.store.register_candidate_for_principal(
                "alice", "reasoning", "candidate", "2.0", {"mode": "bad"},
                forged, observations=self.observations,
                evidence_manifest_ref="test://manifests/forged",
            )
        changed = list(self.observations)
        changed[0] = replace(changed[0], evidence_ref="test://different")
        with self.assertRaises(StrategyStoreError):
            self.store.register_candidate_for_principal(
                "alice", "reasoning", "candidate", "2.0", {"mode": "bad"},
                self.evaluation, observations=tuple(changed),
                evidence_manifest_ref="test://manifests/changed",
            )

    def test_baseline_must_be_registered_before_candidate(self):
        store = SQLiteStrategyStore(
            self.task_store,
            approval_verifier=lambda grant: True,
            evidence_verifier=lambda context: True,
        )
        with self.assertRaises(StrategyNotFoundError):
            store.register_candidate_for_principal(
                "bob", "reasoning", "candidate", "1.0", {},
                self.evaluation, observations=self.observations,
                evidence_manifest_ref="test://manifest",
            )

    def test_principals_are_isolated(self):
        self.activate_baseline()
        self.assertIsNone(self.store.get_active_for_principal("bob", "reasoning"))
        with self.assertRaises(StrategyAuthorizationError):
            self.store.activate_for_principal("bob", self.grant(principal="alice", generation=1))
        self.assertEqual(
            len(self.store.events_for_principal("bob", "reasoning")), 0,
        )

    def test_data_only_config_rejects_authority_secrets_code_and_bad_values(self):
        invalid = (
            {"permissions": ["admin"]},
            {"nested": {"allowed_tools": ["shell"]}},
            {"api_key": "secret"},
            {"script": "print(1)"},
            {"value": float("nan")},
            {"value": object()},
            {"nested": {"a": {"b": {"c": {"d": {"e": 1}}}}}},
        )
        for config in invalid:
            with self.subTest(config=repr(config)), self.assertRaises(StrategyStoreError):
                self.store.register_baseline_for_principal(
                    "bob", "reasoning", "baseline", "1.0", config,
                )

    def test_strategy_versions_and_evaluations_are_append_only(self):
        connection = self.task_store._connect()
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE strategy_versions SET config_json='{}' "
                    "WHERE principal_id='alice' AND strategy_id='baseline'"
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE strategy_evaluations SET summary_json='{}' "
                    "WHERE principal_id='alice'"
                )
        finally:
            connection.close()

    def test_approval_grant_lifetime_cannot_exceed_fifteen_minutes(self):
        now = datetime.now(timezone.utc)
        grant = replace(
            self.grant(now=now),
            issued_at=(now - timedelta(seconds=1)).isoformat(),
            expires_at=(now + timedelta(minutes=16)).isoformat(),
        )
        with self.assertRaises(StrategyAuthorizationError):
            self.store.activate_for_principal("alice", grant)

    def test_registry_rejects_unversioned_and_unmatched_baseline_versions(self):
        with self.assertRaises(StrategyStoreError):
            self.store.register_baseline_for_principal(
                "bob", "reasoning", "baseline", "unversioned", {},
            )
        self.store.register_baseline_for_principal(
            "bob", "reasoning", "baseline", "2.0", {},
        )
        with self.assertRaises(StrategyNotFoundError):
            self.store.register_candidate_for_principal(
                "bob", "reasoning", "candidate", "1.0", {"mode": "candidate"},
                self.evaluation, observations=self.observations,
                evidence_manifest_ref="test://manifests/wrong-baseline-version",
            )

    def test_baseline_version_is_immutable(self):
        with self.assertRaises(StrategyConflictError):
            self.store.register_baseline_for_principal(
                "alice", "reasoning", "baseline", "1.0", {"mode": "changed"},
            )

    def test_event_rows_are_append_only_and_projection_tampering_is_detected(self):
        self.activate_baseline()
        connection = self.task_store._connect()
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE strategy_events SET approver_id='forged' WHERE generation=1"
                )
            connection.execute(
                "UPDATE strategy_active SET strategy_id='candidate',version='1.0' "
                "WHERE principal_id='alice' AND strategy_class='reasoning'"
            )
        finally:
            connection.close()
        with self.assertRaises(StrategyIntegrityError):
            self.store.get_active_for_principal("alice", "reasoning")

    def test_store_requires_the_exact_task_store_type(self):
        with self.assertRaises(StrategyStoreError):
            SQLiteStrategyStore(object())


    def test_candidate_admission_requires_a_trusted_evidence_verifier(self):
        store = SQLiteStrategyStore(self.task_store)
        store.register_baseline_for_principal(
            "carol", "reasoning", "baseline", "1.0", {"mode": "standard"},
        )
        with self.assertRaisesRegex(StrategyAuthorizationError, "evidence verifier"):
            store.register_candidate_for_principal(
                "carol", "reasoning", "candidate", "1.0", {"mode": "candidate"},
                self.evaluation, observations=self.observations,
                evidence_manifest_ref="test://manifests/cohort-002",
            )
        connection = self.task_store._connect()
        try:
            count = connection.execute(
                "SELECT COUNT(*) FROM strategy_evaluations WHERE principal_id='carol'"
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(count, 0)

    def test_candidate_evidence_verifier_fails_closed(self):
        verifiers = (
            lambda context: False,
            lambda context: 1,
            lambda context: None,
            lambda context: (_ for _ in ()).throw(RuntimeError("unavailable")),
        )
        for index, verifier in enumerate(verifiers):
            principal = f"carol{index}"
            store = SQLiteStrategyStore(self.task_store, evidence_verifier=verifier)
            store.register_baseline_for_principal(
                principal, "reasoning", "baseline", "1.0", {"mode": "standard"},
            )
            with self.subTest(verifier=index), self.assertRaises(StrategyAuthorizationError):
                store.register_candidate_for_principal(
                    principal, "reasoning", "candidate", "1.0", {"mode": "candidate"},
                    self.evaluation, observations=self.observations,
                    evidence_manifest_ref=f"test://manifests/{principal}",
                )
            connection = self.task_store._connect()
            try:
                count = connection.execute(
                    "SELECT COUNT(*) FROM strategy_evaluations WHERE principal_id=?",
                    (principal,),
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(count, 0)

    def test_candidate_evidence_verifier_receives_exact_immutable_binding(self):
        captured = []
        store = SQLiteStrategyStore(
            self.task_store,
            evidence_verifier=lambda context: captured.append(context) is None,
        )
        store.register_baseline_for_principal(
            "dana", "reasoning", "baseline", "1.0", {"mode": "standard"},
        )
        store.register_candidate_for_principal(
            "dana", "reasoning", "candidate", "1.0", {"mode": "candidate"},
            self.evaluation, observations=self.observations,
            evidence_manifest_ref="test://manifests/dana-cohort",
        )
        self.assertEqual(len(captured), 1)
        context = captured[0]
        self.assertEqual(context.principal_id, "dana")
        self.assertEqual(context.strategy_class, "reasoning")
        self.assertEqual(context.baseline_id, "baseline")
        self.assertEqual(context.baseline_version, "1.0")
        self.assertEqual(context.candidate_id, "candidate")
        self.assertEqual(context.candidate_version, "1.0")
        self.assertEqual(context.cohort_sha256, self.evaluation.cohort_sha256)
        self.assertEqual(context.cohort_schema, self.evaluation.cohort_schema)
        self.assertEqual(context.evidence_manifest_ref, "test://manifests/dana-cohort")
        self.assertEqual(context.matched_pairs, self.evaluation.matched_pairs)
        with self.assertRaises((AttributeError, TypeError)):
            context.cohort_sha256 = "0" * 64


if __name__ == "__main__":
    unittest.main()
