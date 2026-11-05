import json
import tempfile
import unittest
from pathlib import Path

from capri_core import (
    EvaluationRecord, EvidenceStage, EvaluatorType, HashChainLedger,
    LedgerIntegrityError, RecordValidationError, Status, validate_record,
)


def passing(run_id="r1", parent=None):
    return EvaluationRecord(
        run_id=run_id, scenario_id="scenario-a", dimension="Agency",
        status=Status.PASS, evaluator_type=EvaluatorType.SELF,
        evidence_stage=EvidenceStage.SELF_SCORED,
        evidence_ref="evidence://non-x5/example", run_at="2026-11-05T08:00:00Z",
        parent_run_id=parent,
    )


class ValidationTests(unittest.TestCase):
    def test_valid_self_scored_pass(self):
        validate_record(passing())

    def test_pass_without_evidence_is_rejected(self):
        bad = EvaluationRecord(
            run_id="r1", scenario_id="scenario-a", dimension="Agency", status=Status.PASS,
            evaluator_type=EvaluatorType.SELF, evidence_stage=EvidenceStage.SELF_SCORED,
            evidence_ref=None, run_at="2026-11-05T08:00:00Z")
        with self.assertRaises(RecordValidationError):
            validate_record(bad)

    def test_self_cannot_claim_independent_review(self):
        record = EvaluationRecord(
            run_id="r1", scenario_id="scenario-a", dimension="Agency", status=Status.PASS,
            evaluator_type=EvaluatorType.SELF, evidence_stage=EvidenceStage.INDEPENDENTLY_REVIEWED,
            evidence_ref="evidence://example", run_at="2026-11-05T08:00:00Z")
        with self.assertRaises(RecordValidationError):
            validate_record(record)

    def test_timezone_is_required(self):
        record = EvaluationRecord(
            run_id="r1", scenario_id="scenario-a", dimension="Agency", status=Status.NOT_RUN,
            evaluator_type=EvaluatorType.SELF, evidence_stage=EvidenceStage.NOT_RUN,
            run_at="2026-11-05T08:00:00")
        with self.assertRaises(RecordValidationError):
            validate_record(record)


class LedgerTests(unittest.TestCase):
    def test_append_verify_and_retest_lineage(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = HashChainLedger(Path(directory) / "runs.jsonl")
            ledger.append(passing("r1"))
            ledger.append(passing("r2", parent="r1"))
            result = ledger.verify()
            self.assertTrue(result["valid"])
            self.assertEqual(result["records"], 2)
            self.assertEqual(ledger.records()[1].parent_run_id, "r1")

    def test_duplicate_run_id_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = HashChainLedger(Path(directory) / "runs.jsonl")
            ledger.append(passing("r1"))
            with self.assertRaises(LedgerIntegrityError):
                ledger.append(passing("r1"))

    def test_unknown_parent_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = HashChainLedger(Path(directory) / "runs.jsonl")
            with self.assertRaises(LedgerIntegrityError):
                ledger.append(passing("r2", parent="missing"))

    def test_tampering_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.jsonl"
            ledger = HashChainLedger(path)
            ledger.append(passing("r1"))
            entry = json.loads(path.read_text())
            entry["record"]["status"] = "Fail"
            path.write_text(json.dumps(entry) + "\n")
            with self.assertRaises(LedgerIntegrityError):
                ledger.verify()


if __name__ == "__main__":
    unittest.main()
