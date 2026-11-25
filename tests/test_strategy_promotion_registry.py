import os
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone

from capri_core.strategy import StrategyObservation, evaluate_strategies
from capri_core.strategy_promotion import PromotionCohort
from capri_runtime.strategy_approval import (
    HostStrategyApprovalAuthority,
    StrategyApprovalIdentity,
    StrategyApprovalRequest,
)
from capri_runtime.strategy_store import (
    SQLiteStrategyStore,
    StrategyAuthorizationError,
    StrategyNotFoundError,
)
from capri_runtime.tasks import SQLiteTaskStore
from capri_runtime.tools import HmacApprovalKeyRing


_SCENARIOS = ("coding", "logic", "research", "planning", "synthesis")


def make_promotion_cohort(
    cohort_id: str,
    *,
    baseline_successes: int = 15,
    candidate_successes: int = 20,
) -> PromotionCohort:
    observations = []
    for scenario in _SCENARIOS:
        for index in range(20):
            task_id = f"{cohort_id}-{scenario}-{index:02d}"
            baseline_outcome = (
                "verified_success" if index < baseline_successes else "verified_failure"
            )
            candidate_outcome = (
                "verified_success" if index < candidate_successes else "verified_failure"
            )
            observations.append(StrategyObservation(
                task_id=task_id,
                scenario=scenario,
                strategy_id="baseline",
                outcome=baseline_outcome,
                evidence_ref=f"evidence://{cohort_id}/{task_id}/baseline",
                tool_calls=5,
                context_tokens=1000,
                estimated_cost_units=100,
                latency_ms=2000,
                strategy_version="1.0",
            ))
            observations.append(StrategyObservation(
                task_id=task_id,
                scenario=scenario,
                strategy_id="candidate",
                outcome=candidate_outcome,
                evidence_ref=f"evidence://{cohort_id}/{task_id}/candidate",
                tool_calls=4,
                context_tokens=900,
                estimated_cost_units=90,
                latency_ms=1800,
                strategy_version="1.1",
            ))
    return PromotionCohort(cohort_id=cohort_id, observations=tuple(observations))


class StrategyPromotionRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        if os.name == "posix":
            os.chmod(self.temp.name, 0o700)
        self.now = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
        self.task_store = SQLiteTaskStore(os.path.join(self.temp.name, "tasks.sqlite3"))
        self.evidence_contexts = []
        self.keyring = HmacApprovalKeyRing(
            {"promotion-key": b"p" * 32}, active_key_id="promotion-key",
        )
        self.identity = StrategyApprovalIdentity("alice", "reviewer-1")
        self.authority = HostStrategyApprovalAuthority(
            self.keyring,
            authenticate_approver=lambda credential: (
                self.identity if credential == "valid" else None
            ),
            authorize_approver=lambda identity, request: (
                identity.approver_id == "reviewer-1"
                and request.promotion_assessment_sha256 is not None
            ),
            clock=lambda: self.now,
            max_ttl_seconds=300,
        )
        self.store = SQLiteStrategyStore(
            self.task_store,
            approval_verifier=self.authority.verify,
            evidence_verifier=self.verify_evidence,
            clock=lambda: self.now,
        )
        self.cohort_a = make_promotion_cohort("cohort-a")
        self.cohort_b = make_promotion_cohort("cohort-b")
        self.observations = self.cohort_a.observations
        self.evaluation = evaluate_strategies(
            "baseline", "candidate", self.observations, min_pairs=20,
        )
        self.baseline = self.store.register_baseline_for_principal(
            "alice", "reasoning", "baseline", "1.0", {"mode": "standard"},
        )
        self.candidate = self.store.register_candidate_for_principal(
            "alice", "reasoning", "candidate", "1.1",
            {"mode": "efficient", "temperature": 0.1},
            self.evaluation,
            observations=self.observations,
            evidence_manifest_ref="manifest://cohort-a",
        )

    def tearDown(self):
        self.temp.cleanup()

    def verify_evidence(self, context):
        self.evidence_contexts.append(context)
        return (
            context.principal_id == "alice"
            and bool(context.cohort_sha256)
            and context.evidence_manifest_ref.startswith("manifest://")
        )

    def register_assessment(self):
        return self.store.register_promotion_assessment_for_principal(
            principal_id="alice",
            strategy_class="reasoning",
            task_family="reasoning",
            baseline_id="baseline",
            candidate_id="candidate",
            primary_metric="verified_success_rate",
            cohorts=(self.cohort_a, self.cohort_b),
            evidence_manifest_refs={
                "cohort-a": "manifest://cohort-a",
                "cohort-b": "manifest://cohort-b",
            },
        )

    def approval_request(self, assessment_hash, *, generation=0):
        return StrategyApprovalRequest(
            principal_id="alice",
            strategy_class="reasoning",
            strategy_id="candidate",
            version="1.1",
            evaluation_sha256=self.evaluation.cohort_sha256,
            config_sha256=self.candidate.config_sha256,
            expected_generation=generation,
            action="activate",
            promotion_assessment_sha256=assessment_hash,
        )

    def test_promotion_assessment_is_recomputed_persisted_and_bound_to_activation(self):
        record = self.register_assessment()
        self.assertTrue(record.summary["eligible_for_canary"])
        self.assertEqual(record.policy_version, record.summary["policy_version"])
        self.assertEqual(len(record.evidence_manifest_refs), 2)
        self.assertEqual(len(record.cohort_sha256s), 2)
        self.assertEqual(
            {context.cohort_id for context in self.evidence_contexts[-2:]},
            {"cohort-a", "cohort-b"},
        )
        self.assertEqual(
            {context.task_family for context in self.evidence_contexts[-2:]},
            {"reasoning"},
        )

        recovered = self.store.get_promotion_assessment_for_principal(
            "alice", "reasoning", "candidate", "1.1", record.assessment_sha256,
        )
        self.assertEqual(recovered, record)
        repeated = self.register_assessment()
        self.assertEqual(repeated.assessment_id, record.assessment_id)

        request = self.approval_request(record.assessment_sha256)
        grant = self.authority.issue_grant("valid", request)
        self.assertTrue(self.authority.verify(grant))
        tampered = replace(grant, promotion_assessment_sha256="f" * 64)
        self.assertFalse(self.authority.verify(tampered))
        with self.assertRaises(StrategyAuthorizationError):
            self.store.activate_for_principal("alice", tampered)

        active = self.store.activate_for_principal("alice", grant)
        self.assertEqual(active.strategy_id, "candidate")
        self.assertEqual(active.promotion_assessment_sha256, record.assessment_sha256)
        events = self.store.events_for_principal("alice", "reasoning")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].promotion_assessment_sha256, record.assessment_sha256)
        self.assertEqual(
            self.store.get_active_for_principal("alice", "reasoning").promotion_assessment_sha256,
            record.assessment_sha256,
        )

    def test_signed_but_unregistered_assessment_fingerprint_cannot_activate(self):
        fake_hash = "f" * 64
        grant = self.authority.issue_grant("valid", self.approval_request(fake_hash))
        self.assertTrue(self.authority.verify(grant))
        with self.assertRaises(StrategyAuthorizationError):
            self.store.activate_for_principal("alice", grant)
        self.assertIsNone(self.store.get_active_for_principal("alice", "reasoning"))
        self.assertEqual(self.store.events_for_principal("alice", "reasoning"), ())

    def test_every_cohort_must_pass_host_evidence_verification(self):
        record_store = SQLiteStrategyStore(
            self.task_store,
            approval_verifier=self.authority.verify,
            evidence_verifier=lambda context: context.cohort_id != "cohort-b",
            clock=lambda: self.now,
        )
        with self.assertRaises(StrategyAuthorizationError):
            record_store.register_promotion_assessment_for_principal(
                "alice", "reasoning", "reasoning", "baseline", "candidate",
                "verified_success_rate", (self.cohort_a, self.cohort_b),
                {"cohort-a": "manifest://cohort-a", "cohort-b": "manifest://cohort-b"},
            )
        with self.assertRaises(StrategyNotFoundError):
            self.store.get_promotion_assessment_for_principal(
                "alice", "reasoning", "candidate", "1.1", "f" * 64,
            )

    def test_blocked_or_unbound_cohort_sets_cannot_be_registered(self):
        regressing = make_promotion_cohort(
            "cohort-regressing", baseline_successes=15, candidate_successes=14,
        )
        with self.assertRaises(StrategyAuthorizationError):
            self.store.register_promotion_assessment_for_principal(
                "alice", "reasoning", "reasoning", "baseline", "candidate",
                "verified_success_rate", (self.cohort_a, regressing),
                {
                    "cohort-a": "manifest://cohort-a",
                    "cohort-regressing": "manifest://cohort-regressing",
                },
            )
        cohort_c = make_promotion_cohort("cohort-c")
        with self.assertRaises(StrategyAuthorizationError):
            self.store.register_promotion_assessment_for_principal(
                "alice", "reasoning", "reasoning", "baseline", "candidate",
                "verified_success_rate", (self.cohort_b, cohort_c),
                {
                    "cohort-b": "manifest://cohort-b",
                    "cohort-c": "manifest://cohort-c",
                },
            )

    def test_promotion_assessment_records_are_append_only(self):
        record = self.register_assessment()
        connection = self.store._connect()
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE strategy_promotion_assessments SET task_family='coding' WHERE assessment_id=?",
                    (record.assessment_id,),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "DELETE FROM strategy_promotion_assessments WHERE assessment_id=?",
                    (record.assessment_id,),
                )
        finally:
            connection.close()
        self.assertEqual(
            self.store.get_promotion_assessment_for_principal(
                "alice", "reasoning", "candidate", "1.1", record.assessment_sha256,
            ),
            record,
        )


if __name__ == "__main__":
    unittest.main()
