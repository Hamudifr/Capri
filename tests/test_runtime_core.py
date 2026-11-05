import hashlib
import json
import io
import tempfile
from contextlib import redirect_stderr, redirect_stdout
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from capri_core.__main__ import main as cli_main

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


class CLITests(unittest.TestCase):
    def test_verify_cli_reports_metadata_only_and_does_not_modify_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.jsonl"
            ledger = HashChainLedger(path)
            ledger.append(passing("cli-run"))
            before = path.read_bytes()
            output = io.StringIO()
            with redirect_stdout(output):
                code = cli_main(["verify", str(path)])
            self.assertEqual(code, 0)
            self.assertIn('"records": 1', output.getvalue())
            self.assertNotIn("cli-run", output.getvalue())
            self.assertEqual(path.read_bytes(), before)

    def test_verify_cli_rejects_missing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with redirect_stderr(output):
                code = cli_main(["verify", str(Path(directory) / "missing.jsonl")])
            self.assertEqual(code, 2)
            self.assertIn("not an existing regular file", output.getvalue())

    def test_verify_cli_fails_on_corrupted_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.jsonl"
            path.write_text('{"bad":true}\\n', encoding="utf-8")
            output = io.StringIO()
            with redirect_stderr(output):
                code = cli_main(["verify", str(path)])
            self.assertEqual(code, 2)
            self.assertIn("verification failed", output.getvalue())


class ValidationTests(unittest.TestCase):
    def test_valid_self_scored_pass(self):
        validate_record(passing())

    def test_pass_without_evidence_is_rejected(self):
        with self.assertRaises(RecordValidationError):
            validate_record(replace(passing(), evidence_ref=None))

    def test_pass_or_fail_requires_a_scoring_stage(self):
        for status in (Status.PASS, Status.FAIL):
            with self.subTest(status=status):
                record = replace(
                    passing(),
                    status=status,
                    evidence_stage=EvidenceStage.EVIDENCE_CAPTURED,
                )
                with self.assertRaises(RecordValidationError):
                    validate_record(record)

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

    def test_non_string_timestamp_fails_closed(self):
        record = EvaluationRecord(
            run_id="r1", scenario_id="scenario-a", dimension="Agency", status=Status.NOT_RUN,
            evaluator_type=EvaluatorType.SELF, evidence_stage=EvidenceStage.NOT_RUN,
            run_at=123)
        with self.assertRaises(RecordValidationError):
            validate_record(record)

    def test_unknown_enum_fails_closed(self):
        record = EvaluationRecord(
            run_id="r1", scenario_id="scenario-a", dimension="Agency", status="Pass",
            evaluator_type=EvaluatorType.SELF, evidence_stage=EvidenceStage.SELF_SCORED,
            evidence_ref="evidence://example", run_at="2026-11-05T08:00:00Z")
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

    def test_rehashed_invalid_record_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.jsonl"
            ledger = HashChainLedger(path)
            ledger.append(passing("r1"))
            entry = json.loads(path.read_text())
            entry["record"]["run_at"] = 42
            payload = json.dumps(entry["record"], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
            entry["hash"] = hashlib.sha256(bytes.fromhex(entry["previous_hash"]) + payload).hexdigest()
            path.write_text(json.dumps(entry) + "\n")
            with self.assertRaises(LedgerIntegrityError):
                ledger.verify()

    def test_unknown_retest_parent_in_existing_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.jsonl"
            entry_record = passing("r2", parent="missing").to_dict()
            canonical = json.dumps(entry_record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
            previous = "0" * 64
            digest = hashlib.sha256(bytes.fromhex(previous) + canonical).hexdigest()
            path.write_text(json.dumps({"previous_hash": previous, "record": entry_record, "hash": digest}) + "\n")
            with self.assertRaises(LedgerIntegrityError):
                HashChainLedger(path).verify()

    def test_duplicate_json_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.jsonl"
            path.write_text(
                '{"previous_hash":"' + ("0" * 64) + '","record":{},"hash":"' +
                ("0" * 64) + '","hash":"' + ("0" * 64) + '"}\\n',
                encoding="utf-8",
            )
            with self.assertRaises(LedgerIntegrityError):
                HashChainLedger(path).verify()

    def test_malformed_entry_shape_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.jsonl"
            path.write_text(json.dumps({"record": {}, "hash": "0" * 64}) + "\n")
            with self.assertRaises(LedgerIntegrityError):
                HashChainLedger(path).verify()


    def test_append_after_corrupted_tail_fails_without_modifying_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.jsonl"
            ledger = HashChainLedger(path)
            ledger.append(passing("r1"))
            with path.open("ab") as stream:
                stream.write(b'{"partial":')
            before = path.read_bytes()
            with self.assertRaises(LedgerIntegrityError):
                ledger.append(passing("r2"))
            self.assertEqual(path.read_bytes(), before)

    def test_streaming_verify_and_records_agree(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = HashChainLedger(Path(directory) / "runs.jsonl")
            ledger.append(passing("r1"))
            ledger.append(passing("r2", parent="r1"))
            result = ledger.verify()
            self.assertEqual(result["records"], len(ledger.records()))
            self.assertTrue(result["valid"])

    def test_ledger_entry_size_limit_is_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.jsonl"
            path.write_bytes(b"x" * 33 + b"\\n")
            with self.assertRaises(LedgerIntegrityError):
                HashChainLedger(path, max_entry_bytes=32).verify()

    def test_append_rejects_entry_larger_than_configured_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.jsonl"
            ledger = HashChainLedger(path, max_entry_bytes=128)
            with self.assertRaises(LedgerIntegrityError):
                ledger.append(passing("large-record"))
            self.assertFalse(path.exists())

    def test_unterminated_final_line_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.jsonl"
            ledger = HashChainLedger(path)
            ledger.append(passing("r1"))
            path.write_bytes(path.read_bytes().rstrip(b"\n"))
            with self.assertRaises(LedgerIntegrityError):
                ledger.verify()

    def test_entry_size_limit_requires_positive_non_boolean_integer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.jsonl"
            for value in (0, -1, True, 1.5, "1024"):
                with self.subTest(value=value):
                    with self.assertRaises(ValueError):
                        HashChainLedger(path, max_entry_bytes=value)

    def test_threaded_appends_preserve_a_valid_chain(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = HashChainLedger(Path(directory) / "runs.jsonl")
            with ThreadPoolExecutor(max_workers=8) as pool:
                hashes = list(pool.map(lambda i: ledger.append(passing(f"thread-{i}")), range(24)))
            self.assertEqual(len(set(hashes)), 24)
            self.assertEqual(ledger.verify()["records"], 24)


if __name__ == "__main__":
    unittest.main()
