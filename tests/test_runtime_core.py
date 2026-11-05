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
            path.write_text('{"bad":true}\n', encoding="utf-8")
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
                ("0" * 64) + '","hash":"' + ("0" * 64) + '"}\n',
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


class DoctorTests(unittest.TestCase):
    def _make_repository(self, root):
        required = (
            "README.md",
            "capri_core/__main__.py",
            "capri_core/ledger.py",
            "capri_runtime/runtime.py",
            "tests/test_runtime_core.py",
            "tests/test_runtime.py",
        )
        for name in required:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# fixture\n", encoding="utf-8")
        workflow = root / ".github/workflows/quality.yml"
        workflow.parent.mkdir(parents=True, exist_ok=True)
        workflow.write_text(
            "on:\n"
            "  push:\n"
            '    branches: ["main", "recovery/non-x5-foundation"]\n'
            "  pull_request:\n"
            '    branches: ["main", "recovery/non-x5-foundation"]\n'
            "permissions:\n"
            "  contents: read\n"
            "jobs:\n"
            "  test:\n"
            "    steps:\n"
            "      - uses: actions/checkout@"
            + "a" * 40
            + "\n",
            encoding="utf-8",
        )

    def test_doctor_passes_on_healthy_repository_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._make_repository(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = cli_main(["doctor", "--root", str(root)])
            self.assertEqual(code, 0, output.getvalue())
            self.assertIn("Capri Doctor:", output.getvalue())
            self.assertIn("Recovery CI coverage: push and pull_request", output.getvalue())

    def test_doctor_json_report_has_stable_schema_and_exit_code(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._make_repository(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = cli_main(["doctor", "--root", str(root), "--json"])
            report = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(report["schema_version"], 1)
            self.assertEqual(report["tool"], "capri-doctor")
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["summary"], {"passed": 6, "failed": 0, "total": 6})
            self.assertEqual(
                [item["id"] for item in report["checks"]],
                [
                    "python_version",
                    "repository_structure",
                    "ci_workflow_readable",
                    "ci_actions_pinned",
                    "ci_permissions",
                    "recovery_ci_coverage",
                ],
            )
            self.assertTrue(all(item["status"] == "pass" for item in report["checks"]))

    def test_doctor_json_report_is_machine_readable_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with redirect_stdout(output):
                code = cli_main(["doctor", "--root", directory, "--json"])
            report = json.loads(output.getvalue())
            self.assertEqual(code, 1)
            self.assertEqual(report["status"], "fail")
            self.assertGreater(report["summary"]["failed"], 0)
            self.assertEqual(
                report["summary"]["passed"] + report["summary"]["failed"],
                report["summary"]["total"],
            )

    def test_doctor_fails_closed_on_missing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with redirect_stdout(output):
                code = cli_main(["doctor", "--root", directory])
            self.assertEqual(code, 1)
            self.assertIn("[FAIL] Repository structure", output.getvalue())

    def test_doctor_detects_unpinned_external_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._make_repository(root)
            workflow = root / ".github/workflows/quality.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace("@" + "a" * 40, "@v6"),
                encoding="utf-8",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                code = cli_main(["doctor", "--root", str(root)])
            self.assertEqual(code, 1)
            self.assertIn("[FAIL] CI actions pinned", output.getvalue())


    def test_doctor_ignores_unrelated_branch_lists_in_job_matrix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._make_repository(root)
            workflow = root / ".github/workflows/quality.yml"
            content = workflow.read_text(encoding="utf-8").replace(
                'branches: ["main", "recovery/non-x5-foundation"]',
                'branches: ["main"]',
            )
            content += (
                "    strategy:\n"
                "      matrix:\n"
                "        include:\n"
                '          - branches: ["main", "recovery/non-x5-foundation"]\n'
                '          - branches: ["main", "recovery/non-x5-foundation"]\n'
            )
            workflow.write_text(content, encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = cli_main(["doctor", "--root", str(root)])
            self.assertEqual(code, 1)
            self.assertIn("[FAIL] Recovery CI coverage", output.getvalue())

    def test_doctor_accepts_block_style_event_branch_lists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._make_repository(root)
            workflow = root / ".github/workflows/quality.yml"
            content = workflow.read_text(encoding="utf-8").replace(
                'branches: ["main", "recovery/non-x5-foundation"]',
                'branches:\n'
                '      - "main"\n'
                '      - "recovery/non-x5-foundation"',
            )
            workflow.write_text(content, encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = cli_main(["doctor", "--root", str(root)])
            self.assertEqual(code, 0, output.getvalue())
            self.assertIn("[PASS] Recovery CI coverage", output.getvalue())


    def test_doctor_ignores_nested_event_names_and_branch_lists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._make_repository(root)
            workflow = root / ".github/workflows/quality.yml"
            content = workflow.read_text(encoding="utf-8")
            start = content.index("on:\n")
            end = content.index("permissions:\n", start)
            nested = (
                "on:\n"
                "  workflow_dispatch:\n"
                "    inputs:\n"
                '      push:\n'
                '        branches: ["main", "recovery/non-x5-foundation"]\n'
                '      pull_request:\n'
                '        branches: ["main", "recovery/non-x5-foundation"]\n'
            )
            workflow.write_text(content[:start] + nested + content[end:], encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = cli_main(["doctor", "--root", str(root)])
            self.assertEqual(code, 1)
            self.assertIn("[FAIL] Recovery CI coverage", output.getvalue())


    def test_doctor_rejects_additional_workflow_write_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._make_repository(root)
            workflow = root / ".github/workflows/quality.yml"
            content = workflow.read_text(encoding="utf-8").replace(
                "  contents: read\n",
                "  contents: read\n  issues: write\n",
            )
            workflow.write_text(content, encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = cli_main(["doctor", "--root", str(root)])
            self.assertEqual(code, 1)
            self.assertIn("[FAIL] CI permissions", output.getvalue())

    def test_doctor_rejects_nested_branch_list_lookalikes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._make_repository(root)
            workflow = root / ".github/workflows/quality.yml"
            content = workflow.read_text(encoding="utf-8").replace(
                'branches: ["main", "recovery/non-x5-foundation"]',
                "branches:\n"
                "      - include:\n"
                "          - main\n"
                "          - recovery/non-x5-foundation",
            )
            workflow.write_text(content, encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = cli_main(["doctor", "--root", str(root)])
            self.assertEqual(code, 1)
            self.assertIn("[FAIL] Recovery CI coverage", output.getvalue())


    def test_doctor_rejects_duplicate_top_level_on_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._make_repository(root)
            workflow = root / ".github/workflows/quality.yml"
            content = workflow.read_text(encoding="utf-8")
            start = content.index("on:\n")
            end = content.index("permissions:\n", start)
            first = content[start:end]
            workflow.write_text(content + first, encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = cli_main(["doctor", "--root", str(root)])
            self.assertEqual(code, 1)
            self.assertIn("[FAIL] Recovery CI coverage", output.getvalue())

    def test_doctor_rejects_duplicate_push_event_mappings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._make_repository(root)
            workflow = root / ".github/workflows/quality.yml"
            content = workflow.read_text(encoding="utf-8")
            duplicate = (
                "  push:\n"
                '    branches: ["main", "recovery/non-x5-foundation"]\n'
            )
            workflow.write_text(content.replace("  pull_request:\n", duplicate + "  pull_request:\n"), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = cli_main(["doctor", "--root", str(root)])
            self.assertEqual(code, 1)
            self.assertIn("[FAIL] Recovery CI coverage", output.getvalue())


if __name__ == "__main__":
    unittest.main()
