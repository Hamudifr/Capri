import sqlite3
import tempfile
import unittest
from dataclasses import replace

from capri_core.strategy import StrategyObservation
from capri_runtime.strategy_approval import HostStrategyApprovalAuthority, StrategyApprovalIdentity
from capri_runtime.strategy_evidence_store import SQLiteStrategyEvidenceManifestStore
from capri_runtime.strategy_store import SQLiteStrategyStore, StrategyAuthorizationError
from capri_runtime.tasks import SQLiteTaskStore
from capri_runtime.tools import HmacApprovalKeyRing


class SQLiteStrategyEvidenceManifestStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.task_store = SQLiteTaskStore(f"{self.directory.name}/tasks.sqlite3")
        self.source_valid = True
        self.family_override = None
        self.store = SQLiteStrategyEvidenceManifestStore(
            self.task_store,
            authenticate_collector=lambda credential: "alice" if credential == "host-credential" else None,
            classify_task_family=lambda principal, task_id: (
                self.family_override if self.family_override is not None else "research"
            ),
            validate_source_events=lambda principal, category, observations, families: (
                self.source_valid
                and principal == "alice"
                and category == "reasoning"
                and len(observations) == 40
                and all(families[item.task_id] == "research" for item in observations)
            ),
        )
        self.observations = []
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
            self.observations.append(StrategyObservation(
                strategy_id="baseline", strategy_version="1.0",
                outcome="verified_success", **base,
            ))
            candidate = dict(base)
            candidate["estimated_cost_units"] = 90
            self.observations.append(StrategyObservation(
                strategy_id="candidate", strategy_version="2.0",
                outcome="verified_success", **candidate,
            ))
        self.observations = tuple(self.observations)

    def tearDown(self):
        self.directory.cleanup()

    def register(self):
        return self.store.register_manifest(
            "host-credential",
            strategy_class="reasoning",
            baseline_id="baseline",
            candidate_id="candidate",
            observations=self.observations,
        )

    def test_manifest_is_immutable_and_idempotent(self):
        first = self.register()
        second = self.register()
        self.assertEqual(first, second)
        with self.task_store._lock:
            connection = self.task_store._connect()
            try:
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        "UPDATE strategy_evidence_manifests SET task_family='coding' WHERE cohort_sha256=?",
                        (first.cohort_sha256,),
                    )
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        "DELETE FROM strategy_evidence_manifests WHERE cohort_sha256=?",
                        (first.cohort_sha256,),
                    )
            finally:
                connection.close()

    def test_invalid_collector_is_rejected(self):
        with self.assertRaises(StrategyAuthorizationError):
            self.store.register_manifest(
                "wrong", strategy_class="reasoning",
                baseline_id="baseline", candidate_id="candidate",
                observations=self.observations,
            )

    def test_source_validator_must_return_literal_true(self):
        self.source_valid = 1
        with self.assertRaises(StrategyAuthorizationError):
            self.register()

    def test_unknown_task_family_is_rejected(self):
        self.family_override = "untrusted_family"
        with self.assertRaises(StrategyAuthorizationError):
            self.register()

    def test_all_observations_must_share_one_task_family(self):
        self.family_override = "coding"
        with self.assertRaises(StrategyAuthorizationError):
            self.register()

    def test_host_authority_and_store_compose_end_to_end(self):
        context = self.register()
        keyring = HmacApprovalKeyRing({"e1": b"e" * 32}, active_key_id="e1")
        authority = HostStrategyEvidenceAuthority(
            keyring,
            authenticate_collector=lambda credential: "alice" if credential == "host-credential" else None,
            attest_manifest=self.store.attest_manifest,
            verify_manifest=self.store.verify_manifest,
        )
        token = authority.issue("host-credential", context)
        attested_context = replace(context, evidence_manifest_ref=token)
        self.assertTrue(authority.verify(attested_context))
        with tempfile.TemporaryDirectory() as directory:
            task_store = SQLiteTaskStore(f"{directory}/tasks.sqlite3")
            registry = SQLiteStrategyStore(task_store, evidence_verifier=authority.verify)
            registry.register_baseline_for_principal(
                "alice", "reasoning", "baseline", "1.0", {"mode": "standard"},
            )
            evaluation = __import__(
                "capri_core.strategy", fromlist=["evaluate_strategies"]
            ).evaluate_strategies("baseline", "candidate", self.observations)
            candidate = registry.register_candidate_for_principal(
                "alice", "reasoning", "candidate", "2.0",
                {"mode": "efficient"}, evaluation,
                observations=self.observations,
                evidence_manifest_ref=token,
            )
            self.assertEqual(candidate.evaluation_sha256, context.cohort_sha256)

    def test_manifest_revalidation_detects_source_revocation(self):
        context = self.register()
        self.source_valid = False
        digest = context.evidence_manifest_ref.split(":", 1)[1]
        verification_context = replace(context, evidence_manifest_ref=f"sha256:{digest}")
        self.assertFalse(self.store.verify_manifest(verification_context, digest))


if __name__ == "__main__":
    unittest.main()
