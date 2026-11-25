import tempfile
import unittest
from dataclasses import replace
from hashlib import sha256

from capri_core.strategy import StrategyObservation, evaluate_strategies
from capri_runtime.strategy_evidence import HostStrategyEvidenceAuthority
from capri_runtime.strategy_store import (
    SQLiteStrategyStore,
    StrategyAuthorizationError,
    StrategyEvidenceContext,
)
from capri_runtime.tasks import SQLiteTaskStore
from capri_runtime.tools import HmacApprovalKeyRing


class HostStrategyEvidenceAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.keyring = HmacApprovalKeyRing(
            {"e1": b"e" * 32, "e2": b"f" * 32}, active_key_id="e1",
        )
        self.manifest_digest = sha256(b"immutable manifest fixture").hexdigest()
        self.original = StrategyEvidenceContext(
            principal_id="alice",
            strategy_class="reasoning",
            baseline_id="baseline",
            baseline_version="1.0",
            candidate_id="candidate",
            candidate_version="2.0",
            cohort_sha256="a" * 64,
            cohort_schema="capri.strategy-cohort.v2",
            evidence_manifest_ref="manifest-store://cohort-001",
            matched_pairs=20,
        )
        self.authority = HostStrategyEvidenceAuthority(
            self.keyring,
            authenticate_collector=lambda credential: "alice" if credential == "host-credential" else None,
            attest_manifest=lambda context: self.manifest_digest,
            verify_manifest=lambda context, digest: (
                digest == self.manifest_digest
                and context.evidence_manifest_ref == f"sha256:{self.manifest_digest}"
            ),
        )

    def test_issue_and_verify_host_attestation(self):
        token = self.authority.issue("host-credential", self.original)
        attested = replace(self.original, evidence_manifest_ref=token)
        self.assertTrue(self.authority.verify(attested))
        self.assertTrue(token.startswith("capri-strategy-evidence:v1:e1:"))

    def test_context_tampering_is_rejected(self):
        token = self.authority.issue("host-credential", self.original)
        attested = replace(self.original, evidence_manifest_ref=token)
        self.assertFalse(self.authority.verify(replace(attested, candidate_version="3.0")))
        self.assertFalse(self.authority.verify(replace(attested, matched_pairs=21)))
        self.assertFalse(self.authority.verify(replace(attested, cohort_sha256="b" * 64)))

    def test_invalid_collector_and_cross_principal_fail_closed(self):
        with self.assertRaises(StrategyAuthorizationError):
            self.authority.issue("wrong", self.original)
        with self.assertRaises(StrategyAuthorizationError):
            self.authority.issue(
                "host-credential", replace(self.original, principal_id="bob"),
            )

    def test_attestor_must_return_a_manifest_digest(self):
        authority = HostStrategyEvidenceAuthority(
            self.keyring,
            authenticate_collector=lambda credential: "alice",
            attest_manifest=lambda context: True,
            verify_manifest=lambda context, digest: True,
        )
        with self.assertRaises(StrategyAuthorizationError):
            authority.issue("host-credential", self.original)

    def test_manifest_is_rechecked_during_verification(self):
        authority = HostStrategyEvidenceAuthority(
            self.keyring,
            authenticate_collector=lambda credential: "alice",
            attest_manifest=lambda context: self.manifest_digest,
            verify_manifest=lambda context, digest: False,
        )
        token = authority.issue("host-credential", self.original)
        self.assertFalse(authority.verify(replace(self.original, evidence_manifest_ref=token)))

    def test_key_rotation_retains_old_attestations(self):
        token = self.authority.issue("host-credential", self.original)
        rotated = HostStrategyEvidenceAuthority(
            HmacApprovalKeyRing(
                {"e1": b"e" * 32, "e2": b"f" * 32}, active_key_id="e2",
            ),
            authenticate_collector=lambda credential: "alice",
            attest_manifest=lambda context: self.manifest_digest,
            verify_manifest=lambda context, digest: digest == self.manifest_digest,
        )
        self.assertTrue(rotated.verify(replace(self.original, evidence_manifest_ref=token)))
        self.assertTrue(rotated.issue("host-credential", self.original).startswith(
            "capri-strategy-evidence:v1:e2:"
        ))

    def test_attestation_is_accepted_by_strategy_store(self):
        observations = []
        for index in range(20):
            task_id = f"task-{index:03d}"
            base = {
                "task_id": task_id,
                "scenario": "research",
                "evidence_ref": f"host-event:{task_id}",
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
            candidate["estimated_cost_units"] = 90
            observations.append(StrategyObservation(
                strategy_id="candidate", strategy_version="2.0",
                outcome="verified_success", **candidate,
            ))
        cohort = tuple(observations)
        evaluation = evaluate_strategies("baseline", "candidate", cohort)
        context = replace(
            self.original,
            cohort_sha256=evaluation.cohort_sha256,
            cohort_schema=evaluation.cohort_schema,
            matched_pairs=evaluation.matched_pairs,
        )
        token = self.authority.issue("host-credential", context)
        with tempfile.TemporaryDirectory() as directory:
            task_store = SQLiteTaskStore(f"{directory}/tasks.sqlite3")
            store = SQLiteStrategyStore(
                task_store, evidence_verifier=self.authority.verify,
            )
            store.register_baseline_for_principal(
                "alice", "reasoning", "baseline", "1.0", {"mode": "standard"},
            )
            candidate = store.register_candidate_for_principal(
                "alice", "reasoning", "candidate", "2.0",
                {"mode": "efficient"}, evaluation,
                observations=cohort,
                evidence_manifest_ref=token,
            )
            self.assertEqual(candidate.evaluation_sha256, evaluation.cohort_sha256)


if __name__ == "__main__":
    unittest.main()
