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
from capri_runtime.tasks import SQLiteTaskStore, TaskEngine
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

    def test_signed_execution_event_requires_persisted_task_completion(self):
        reference = self.journal.record_execution(
            "host-credential", self.claim, self.result,
        )
        observation = self.observation(reference)
        self.assertFalse(self.journal.validate_source_events(
            "alice", "reasoning", (observation,),
            {self.claim.task_id: "research"},
        ))
        # A pending but correctly signed event is structurally sound. It is
        # simply not eligible for strategy evidence until task completion.
        self.assertEqual(self.journal.integrity_check(), "ok")
        self.assertIsNone(self.journal.get_completed_event_ref(
            "alice", self.claim.task_id, self.claim.step_index, self.claim.attempt,
        ))
        self.tasks.finish_step(self.claim, self.result)
        self.assertEqual(
            self.journal.get_completed_event_ref(
                "alice", self.claim.task_id, self.claim.step_index, self.claim.attempt,
            ),
            reference,
        )
        self.assertTrue(self.journal.validate_source_events(
            "alice", "reasoning", (observation,),
            {self.claim.task_id: "research"},
        ))
        self.assertEqual(self.tasks.integrity_check(), "ok")

    def test_event_is_not_admitted_when_persisted_result_digest_differs(self):
        reference = self.journal.record_execution(
            "host-credential", self.claim, self.result,
        )
        self.tasks.finish_step(self.claim, {"status": "different persisted result"})
        self.assertFalse(self.journal.validate_source_events(
            "alice", "reasoning", (self.observation(reference),),
            {self.claim.task_id: "research"},
        ))

    def test_task_engine_atomically_records_evidence_and_finishes_claim(self):
        engine = TaskEngine(
            self.tasks,
            {},
            "worker-1",
            principal_handlers={"research": lambda inputs, key, principal: self.result},
            execution_evidence_journal=self.journal,
            execution_evidence_credential=lambda claim: "host-credential",
        )
        completed = engine.execute_claim(self.claim)
        self.assertEqual(completed.state, "succeeded")
        self.assertEqual(completed.result[-1], self.result)
        with self.tasks._lock:
            connection = self.tasks._connect()
            try:
                count = connection.execute(
                    "SELECT COUNT(*) FROM execution_evidence_events WHERE task_id=?",
                    (self.claim.task_id,),
                ).fetchone()[0]
            finally:
                connection.close()
        self.assertEqual(count, 1)
        reference = self.journal.get_completed_event_ref(
            "alice", self.claim.task_id, self.claim.step_index, self.claim.attempt,
        )
        self.assertIsNotNone(reference)
        self.assertTrue(self.journal.validate_source_events(
            "alice", "reasoning",
            (self.observation(reference),),
            {self.claim.task_id: "research"},
        ))

    def test_result_verifier_cannot_mutate_task_engine_persisted_snapshot(self):
        def mutate_verifier(principal, claim, result, digest):
            result["status"] = "mutated by verifier"
            return VerifiedExecutionResult(
                digest, "verified_success", False, 2, 300, 10, 125,
            )

        journal = self.make_journal(verifier=mutate_verifier)
        engine = TaskEngine(
            self.tasks,
            {},
            "worker-1",
            principal_handlers={"research": lambda inputs, key, principal: self.result},
            execution_evidence_journal=journal,
            execution_evidence_credential=lambda claim: "host-credential",
        )
        completed = engine.execute_claim(self.claim)
        self.assertEqual(completed.state, "succeeded")
        self.assertEqual(completed.result[-1], self.result)

    def test_task_engine_rolls_back_evidence_if_task_completion_fails(self):
        def fail_completion(connection, claim, result, stamp):
            raise RuntimeError("forced task completion failure")

        self.tasks._finish_step_in_transaction = fail_completion
        engine = TaskEngine(
            self.tasks,
            {},
            "worker-1",
            principal_handlers={"research": lambda inputs, key, principal: self.result},
            execution_evidence_journal=self.journal,
            execution_evidence_credential=lambda claim: "host-credential",
        )
        record = engine.execute_claim(self.claim)
        self.assertEqual(record.state, "reconciliation_required")
        with self.tasks._lock:
            connection = self.tasks._connect()
            try:
                count = connection.execute(
                    "SELECT COUNT(*) FROM execution_evidence_events WHERE task_id=?",
                    (self.claim.task_id,),
                ).fetchone()[0]
            finally:
                connection.close()
        self.assertEqual(count, 0)

    def test_task_engine_quarantines_result_when_evidence_cannot_be_recorded(self):
        journal = self.make_journal(verifier=lambda *args: False)
        engine = TaskEngine(
            self.tasks,
            {},
            "worker-1",
            principal_handlers={"research": lambda inputs, key, principal: self.result},
            execution_evidence_journal=journal,
            execution_evidence_credential=lambda claim: "host-credential",
        )
        record = engine.execute_claim(self.claim)
        self.assertEqual(record.state, "reconciliation_required")
        self.assertEqual(record.error_code, "execution_evidence_unavailable")

    def test_evidence_and_task_result_roll_back_atomically_on_finish_failure(self):
        original_finish = self.tasks._finish_step_in_transaction

        def fail_after_evidence_insert(connection, claim, result, stamp):
            raise RuntimeError("injected task completion failure")

        self.tasks._finish_step_in_transaction = fail_after_evidence_insert
        try:
            engine = TaskEngine(
                self.tasks,
                {},
                "worker-1",
                principal_handlers={"research": lambda inputs, key, principal: self.result},
                execution_evidence_journal=self.journal,
                execution_evidence_credential=lambda claim: "host-credential",
            )
            record = engine.execute_claim(self.claim)
        finally:
            self.tasks._finish_step_in_transaction = original_finish

        self.assertEqual(record.state, "reconciliation_required")
        self.assertEqual(record.error_code, "execution_evidence_unavailable")
        with self.tasks._lock:
            connection = self.tasks._connect()
            try:
                event_count = connection.execute(
                    "SELECT COUNT(*) FROM execution_evidence_events WHERE task_id=?",
                    (self.claim.task_id,),
                ).fetchone()[0]
            finally:
                connection.close()
        self.assertEqual(event_count, 0)
        self.assertEqual(record.result, ())

    def test_execution_record_is_idempotent_for_same_claim_and_result(self):
        first = self.journal.record_execution("host-credential", self.claim, self.result)
        second = self.journal.record_execution("host-credential", self.claim, self.result)
        self.assertEqual(first, second)

    def test_idempotent_replay_rejects_strategy_version_drift(self):
        first = self.journal.record_execution(
            "host-credential", self.claim, self.result,
        )
        changed = self.make_journal(
            resolver=lambda principal, claim: StrategyBinding(
                "reasoning", "baseline", "2.0",
            ),
        )
        with self.assertRaisesRegex(Exception, "conflicting execution evidence"):
            changed.record_execution("host-credential", self.claim, self.result)

    def test_idempotent_replay_rejects_strategy_id_drift(self):
        self.journal.record_execution("host-credential", self.claim, self.result)
        changed = self.make_journal(
            resolver=lambda principal, claim: StrategyBinding(
                "reasoning", "candidate", "1.0",
            ),
        )
        with self.assertRaisesRegex(Exception, "conflicting execution evidence"):
            changed.record_execution("host-credential", self.claim, self.result)

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

    def test_claim_is_revalidated_inside_evidence_write_transaction(self):
        def complete_during_classification(principal, task_id):
            # Use a second store instance with an independent process-local lock
            # to simulate a competing host writer after initial validation.
            competing_store = SQLiteTaskStore(self.tasks.path)
            competing_store.finish_step(
                self.claim, {"status": "concurrent completion"},
            )
            return self.classification

        journal = self.make_journal(classifier=complete_during_classification)
        with self.assertRaisesRegex(Exception, "task claim does not match"):
            journal.record_execution("host-credential", self.claim, self.result)
        with self.tasks._lock:
            connection = self.tasks._connect()
            try:
                count = connection.execute(
                    "SELECT COUNT(*) FROM execution_evidence_events WHERE task_id=?",
                    (self.claim.task_id,),
                ).fetchone()[0]
            finally:
                connection.close()
        self.assertEqual(count, 0)

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
        self.assertEqual(self.tasks.integrity_check(), "task store validation failed")

    def test_observation_cannot_be_rebound_to_another_strategy(self):
        reference = self.journal.record_execution("host-credential", self.claim, self.result)
        forged = replace(self.observation(reference), strategy_id="candidate")
        self.assertFalse(self.journal.validate_source_events(
            "alice", "reasoning", (forged,), {self.claim.task_id: "research"},
        ))


    def test_256_character_principal_identity_is_supported_by_evidence_journal(self):
        principal_id = "p" * 256
        store = SQLiteTaskStore(f"{self.directory.name}/long-principal.sqlite3")
        task = store.create_for_principal(
            principal_id, [{"tool": "research", "input": {"query": "bounded"}}],
        )
        claim = store.claim_next(
            "worker-256", principal_tools=frozenset({"research"}),
        )
        self.assertIsNotNone(claim)
        keyring = HmacApprovalKeyRing({"e1": b"e" * 32}, active_key_id="e1")
        result = {"status": "verified"}

        def verify(principal, live_claim, value, digest):
            self.assertEqual(principal, principal_id)
            return VerifiedExecutionResult(
                digest, "verified_success", False, 1, 128, 1, 25,
            )

        journal = SQLiteExecutionEvidenceJournal(
            store,
            keyring,
            authenticate_collector=lambda credential: (
                principal_id if credential == "host-credential" else None
            ),
            classify_task=lambda principal, task_id: TaskClassification(
                "research", "long-principal-scenario",
            ),
            resolve_strategy=lambda principal, live_claim: StrategyBinding(
                "reasoning", "baseline", "1.0",
            ),
            verify_result=verify,
        )
        reference = journal.record_execution_and_finish(
            "host-credential", claim, result,
        )
        observation = StrategyObservation(
            task_id=task.task_id,
            scenario="long-principal-scenario",
            strategy_id="baseline",
            strategy_version="1.0",
            outcome="verified_success",
            evidence_ref=reference,
            safety_violation=False,
            tool_calls=1,
            context_tokens=128,
            estimated_cost_units=1,
            latency_ms=25,
        )
        self.assertTrue(journal.validate_source_events(
            principal_id, "reasoning", (observation,),
            {task.task_id: "research"},
        ))
        self.assertEqual(journal.integrity_check(), "ok")
        self.assertEqual(store.integrity_check(), "ok")

if __name__ == "__main__":
    unittest.main()
