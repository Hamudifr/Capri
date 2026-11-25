import sqlite3
import tempfile
import unittest
from dataclasses import replace

from capri_core.strategy import StrategyObservation
from capri_runtime import SQLiteExecutionEvidenceJournal as ExportedExecutionEvidenceJournal
from capri_runtime.execution_evidence import (
    SQLiteExecutionEvidenceJournal,
    StrategyBinding,
    TaskClassification,
    VerifiedExecutionResult,
)
from capri_runtime.tasks import SQLiteTaskStore
from capri_runtime.tools import HmacApprovalKeyRing


class SQLiteExecutionEvidenceJournalTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.tasks = SQLiteTaskStore(f"{self.directory.name}/tasks.sqlite3")
        self.task = self.tasks.create_for_principal(
            "alice", [{"tool": "research", "input": {"query": "safe test"}}],
        )
        self.claim = self.tasks.claim_next(
            "worker-1", principal_tools=frozenset({"research"}),
        )
        self.assertIsNotNone(self.claim)
        self.classification = TaskClassification("research", "scenario-a")
        self.binding = StrategyBinding("reasoning", "baseline", "1.0")
        self.result = {"status": "verified", "private_marker": "not-persisted"}
        self.keyring = HmacApprovalKeyRing({"e1": b"e" * 32}, active_key_id="e1")
        self.journal = self.make_journal()

    def tearDown(self):
        self.directory.cleanup()

    def make_journal(self, *, verifier=None, classifier=None, resolver=None, authenticator=None):
        def verify(principal, claim, result, digest):
            if verifier is not None:
                return verifier(principal, claim, result, digest)
            return VerifiedExecutionResult(
                digest, "verified_success", False, 2, 300, 10, 125,
            )

        return SQLiteExecutionEvidenceJournal(
            self.tasks,
            self.keyring,
            authenticate_collector=authenticator or (
                lambda credential: "alice" if credential == "host-credential" else None
            ),
            classify_task=classifier or (lambda principal, task_id: self.classification),
            resolve_strategy=resolver or (lambda principal, claim: self.binding),
            verify_result=verify,
        )

    def observation(self, reference):
        return StrategyObservation(
            task_id=self.claim.task_id,
            scenario="scenario-a",
            strategy_id="baseline",
            strategy_version="1.0",
            outcome="verified_success",
            evidence_ref=reference,
            safety_violation=False,
            tool_calls=2,
            context_tokens=300,
            estimated_cost_units=10,
            latency_ms=125,
        )

    def test_journal_is_a_public_package_export(self):
        self.assertIs(ExportedExecutionEvidenceJournal, SQLiteExecutionEvidenceJournal)

    def test_signed_execution_event_validates_strategy_observation(self):
        reference = self.journal.record_execution(
            "host-credential", self.claim, self.result,
        )
        self.assertTrue(self.journal.validate_source_events(
            "alice", "reasoning", (self.observation(reference),),
            {self.claim.task_id: "research"},
        ))
        self.assertEqual(self.journal.integrity_check(), "ok")

    def test_execution_record_is_idempotent_for_same_claim_and_result(self):
        first = self.journal.record_execution("host-credential", self.claim, self.result)
        second = self.journal.record_execution("host-credential", self.claim, self.result)
        self.assertEqual(first, second)

    def test_raw_result_is_not_persisted(self):
        self.journal.record_execution("host-credential", self.claim, self.result)
        with self.tasks._lock:
            connection = self.tasks._connect()
            try:
                payload = connection.execute(
                    "SELECT payload_json FROM execution_evidence_events"
                ).fetchone()[0]
            finally:
                connection.close()
        self.assertNotIn("not-persisted", payload)
        self.assertNotIn('"query"', payload)

    def test_wrong_principal_cannot_record_execution(self):
        with self.assertRaises(Exception):
            self.journal.record_execution("wrong", self.claim, self.result)

    def test_unverified_result_is_rejected(self):
        journal = self.make_journal(verifier=lambda *args: False)
        with self.assertRaises(Exception):
            journal.record_execution("host-credential", self.claim, self.result)

    def test_raising_result_verifier_fails_closed(self):
        def fail(*args):
            raise RuntimeError("private verifier detail")
        journal = self.make_journal(verifier=fail)
        with self.assertRaisesRegex(Exception, "verification failed"):
            journal.record_execution("host-credential", self.claim, self.result)

    def test_unknown_task_family_is_rejected(self):
        journal = self.make_journal(
            classifier=lambda principal, task_id: TaskClassification("untrusted", "scenario-a"),
        )
        with self.assertRaises(Exception):
            journal.record_execution("host-credential", self.claim, self.result)

    def test_stale_claim_is_rejected(self):
        self.tasks.finish_step(self.claim, {"status": "done"})
        with self.assertRaises(Exception):
            self.journal.record_execution("host-credential", self.claim, self.result)

    def test_tampered_signed_payload_is_not_admitted(self):
        reference = self.journal.record_execution("host-credential", self.claim, self.result)
        event_id = reference.split(":", 1)[1]
        with self.tasks._lock:
            connection = self.tasks._connect()
            try:
                connection.execute("DROP TRIGGER execution_evidence_immutable_update")
                connection.execute(
                    "UPDATE execution_evidence_events SET payload_json=? WHERE event_id=?",
                    ('{"event_id":"tampered"}', event_id),
                )
            finally:
                connection.close()
        self.assertFalse(self.journal.validate_source_events(
            "alice", "reasoning", (self.observation(reference),),
            {self.claim.task_id: "research"},
        ))
        self.assertNotEqual(self.journal.integrity_check(), "ok")

    def test_observation_cannot_be_rebound_to_another_strategy(self):
        reference = self.journal.record_execution("host-credential", self.claim, self.result)
        forged = replace(self.observation(reference), strategy_id="candidate")
        self.assertFalse(self.journal.validate_source_events(
            "alice", "reasoning", (forged,), {self.claim.task_id: "research"},
        ))


if __name__ == "__main__":
    unittest.main()
