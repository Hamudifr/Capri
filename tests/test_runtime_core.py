import hashlib
import json
import io
import os
import stat
import tempfile
from contextlib import redirect_stderr, redirect_stdout
import unittest
from unittest import mock
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from capri_core.__main__ import main as cli_main
import capri_core.ledger as ledger_module

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

    def test_library_verify_rejects_missing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.jsonl"
            with self.assertRaises(LedgerIntegrityError):
                HashChainLedger(path).verify()

    def test_records_rejects_missing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.jsonl"
            with self.assertRaises(LedgerIntegrityError):
                HashChainLedger(path).records()

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

    def test_lone_unicode_surrogates_are_rejected_before_ledger_serialization(self):
        for field in ("run_id", "scenario_id", "evidence_ref", "parent_run_id", "rubric_version"):
            with self.subTest(field=field):
                record = replace(passing(), **{field: "invalid-\ud800"})
                with self.assertRaises(RecordValidationError):
                    validate_record(record)
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "runs.jsonl"
                    with self.assertRaises(RecordValidationError):
                        HashChainLedger(path).append(record)
                    self.assertFalse(path.exists())


class LedgerTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "POSIX file modes required")
    def test_new_ledger_uses_private_file_and_parent_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private" / "runs.jsonl"
            HashChainLedger(path).append(passing("private-run"))
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    @unittest.skipUnless(os.name == "posix", "POSIX file modes required")
    def test_append_tightens_existing_ledger_file_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.jsonl"
            ledger = HashChainLedger(path)
            ledger.append(passing("first"))
            path.chmod(0o644)
            ledger.append(passing("second", parent="first"))
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(ledger.verify()["records"], 2)

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
            path.write_bytes(b"x" * 33 + b"\n")
            with self.assertRaises(LedgerIntegrityError):
                HashChainLedger(path, max_entry_bytes=32).verify()

    def test_ledger_accepts_crlf_line_endings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.jsonl"
            ledger = HashChainLedger(path)
            ledger.append(passing("r1"))
            path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
            self.assertEqual(ledger.verify()["records"], 1)

    def test_entry_at_exact_configured_byte_limit_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.jsonl"
            HashChainLedger(path).append(passing("r1"))
            entry_size = len(path.read_bytes().rstrip(b"\n"))
            self.assertEqual(HashChainLedger(path, max_entry_bytes=entry_size).verify()["records"], 1)
            with self.assertRaises(LedgerIntegrityError):
                HashChainLedger(path, max_entry_bytes=entry_size - 1).verify()

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

    def test_deeply_nested_json_fails_as_ledger_integrity_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.jsonl"
            nested = b"[" * 1200 + b"0" + b"]" * 1200
            line = (
                b'{"hash":"' + b"0" * 64 + b'","previous_hash":"' +
                b"0" * 64 + b'","record":' + nested + b"}\n"
            )
            path.write_bytes(line)
            with self.assertRaises(LedgerIntegrityError):
                HashChainLedger(path).verify()

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




class LedgerPathSafetyTests(unittest.TestCase):
    def test_final_symlink_is_rejected_without_changing_target(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target.jsonl"
            link = Path(directory) / "linked.jsonl"
            HashChainLedger(target).append(passing("target-record"))
            before = target.read_bytes()
            link.symlink_to(target)

            with self.assertRaises(LedgerIntegrityError):
                HashChainLedger(link).append(passing("rejected-record"))
            with self.assertRaises(LedgerIntegrityError):
                HashChainLedger(link).verify()

            self.assertEqual(target.read_bytes(), before)

    def test_parent_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real_parent = root / "real"
            real_parent.mkdir()
            parent_link = root / "linked-parent"
            parent_link.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaises(LedgerIntegrityError):
                HashChainLedger(parent_link / "runs.jsonl").append(passing("rejected-record"))
            self.assertFalse((real_parent / "runs.jsonl").exists())

    def test_non_regular_ledger_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger-directory"
            path.mkdir()
            with self.assertRaises(LedgerIntegrityError):
                HashChainLedger(path).append(passing("rejected-record"))
            self.assertTrue(path.is_dir())


    def test_missing_file_scan_closes_parent_descriptor(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.jsonl"
            opened = []
            real_open = os.open

            def tracked_open(*args, **kwargs):
                descriptor = real_open(*args, **kwargs)
                opened.append(descriptor)
                return descriptor

            with mock.patch.object(ledger_module.os, "open", side_effect=tracked_open):
                with self.assertRaises(LedgerIntegrityError):
                    HashChainLedger(path).verify()

            for descriptor in opened:
                with self.assertRaises(OSError):
                    os.fstat(descriptor)

    def test_invalid_ledger_is_not_repermissioned_by_failed_append(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.jsonl"
            path.write_bytes(b"not-a-valid-ledger\\n")
            path.chmod(0o644)

            with self.assertRaises(LedgerIntegrityError):
                HashChainLedger(path).append(passing("rejected-record"))

            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)

    @unittest.skipUnless(os.name == "posix", "POSIX directory fsync is required")
    def test_first_creation_fsyncs_file_then_parent_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.jsonl"
            real_fsync = os.fsync
            observed = []

            def record_fsync(descriptor):
                mode = os.fstat(descriptor).st_mode
                observed.append("directory" if stat.S_ISDIR(mode) else "file")
                return real_fsync(descriptor)

            with mock.patch.object(ledger_module.os, "fsync", side_effect=record_fsync):
                HashChainLedger(path).append(passing("first"))

            self.assertEqual(observed, ["file", "directory"])

    @unittest.skipUnless(os.name == "posix", "POSIX directory fsync is required")
    def test_existing_append_does_not_fsync_parent_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.jsonl"
            ledger = HashChainLedger(path)
            ledger.append(passing("first"))
            real_fsync = os.fsync
            observed = []

            def record_fsync(descriptor):
                mode = os.fstat(descriptor).st_mode
                observed.append("directory" if stat.S_ISDIR(mode) else "file")
                return real_fsync(descriptor)

            with mock.patch.object(ledger_module.os, "fsync", side_effect=record_fsync):
                ledger.append(passing("second", parent="first"))

            self.assertEqual(observed, ["file"])

    def _assert_failed_append_is_latched_and_closes_descriptors(self, helper, failure):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.jsonl"
            ledger = HashChainLedger(path)
            opened = []
            real_open = os.open

            def tracked_open(*args, **kwargs):
                descriptor = real_open(*args, **kwargs)
                opened.append(descriptor)
                return descriptor

            with mock.patch.object(ledger_module.os, "open", side_effect=tracked_open):
                with mock.patch.object(ledger_module, helper, side_effect=failure):
                    with self.assertRaises(LedgerIntegrityError):
                        ledger.append(passing("first"))

            for descriptor in opened:
                with self.assertRaises(OSError):
                    os.fstat(descriptor)

            before = path.read_bytes() if path.exists() else b""
            with self.assertRaisesRegex(LedgerIntegrityError, "previous append failed"):
                ledger.append(passing("second"))
            with self.assertRaisesRegex(LedgerIntegrityError, "previous append failed"):
                ledger.verify()
            self.assertEqual(path.read_bytes() if path.exists() else b"", before)

    def test_write_failure_closes_descriptors_and_latches_path(self):
        def fail_after_partial_write(stream, data):
            stream.write(data[:5])
            raise OSError("injected write failure")

        self._assert_failed_append_is_latched_and_closes_descriptors(
            "_write_entry", fail_after_partial_write
        )

    def test_flush_failure_closes_descriptors_and_latches_path(self):
        self._assert_failed_append_is_latched_and_closes_descriptors(
            "_flush_entry", OSError("injected flush failure")
        )

    def test_file_fsync_failure_closes_descriptors_and_latches_path(self):
        self._assert_failed_append_is_latched_and_closes_descriptors(
            "_fsync_file", OSError("injected file fsync failure")
        )

    @unittest.skipUnless(os.name == "posix", "POSIX directory fsync is required")
    def test_directory_fsync_failure_closes_descriptors_and_latches_path(self):
        self._assert_failed_append_is_latched_and_closes_descriptors(
            "_fsync_directory", OSError("injected directory fsync failure")
        )


if __name__ == "__main__":
    unittest.main()
