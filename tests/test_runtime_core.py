import hashlib
import json
import io
import os
import stat
import tempfile
from contextlib import redirect_stderr, redirect_stdout
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import capri_core.ledger as ledger_module
from unittest import mock

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


    def test_doctor_rejects_job_level_permissions_as_workflow_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._make_repository(root)
            workflow = root / ".github/workflows/quality.yml"
            content = workflow.read_text(encoding="utf-8")
            content = content.replace("permissions:\n  contents: read\n", "")
            content = content.replace(
                "  test:\n    steps:\n",
                "  test:\n    permissions:\n      contents: read\n    steps:\n",
            )
            workflow.write_text(content, encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = cli_main(["doctor", "--root", str(root)])
            self.assertEqual(code, 1)
            self.assertIn("[FAIL] CI permissions", output.getvalue())

    def test_doctor_rejects_quoted_and_inline_job_level_permission_overrides(self):
        overrides = (
            "    permissions:\n      contents: write\n",
            "    permissions: { contents: write }\n",
            '    "permissions":\n      contents: write\n',
            "    'permissions': { contents: write }\n",
        )
        for override in overrides:
            with self.subTest(override=override), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self._make_repository(root)
                workflow = root / ".github/workflows/quality.yml"
                content = workflow.read_text(encoding="utf-8")
                content = content.replace(
                    "  test:\n    steps:\n",
                    "  test:\n" + override + "    steps:\n",
                )
                workflow.write_text(content, encoding="utf-8")
                output = io.StringIO()
                with redirect_stdout(output):
                    code = cli_main(["doctor", "--root", str(root)])
                self.assertEqual(code, 1, output.getvalue())
                self.assertIn("[FAIL] CI permissions", output.getvalue())

    def test_doctor_rejects_column_zero_flow_mapping_permission_continuations(self):
        overrides = (
            "permissions: {contents: write},\n",
            '"permissions": {contents: write},\n',
            "permissions:\n      {contents: write},\n",
            '"permissions":\n      {contents: write},\n',
            "'permissions':\n      {contents: write},\n",
        )
        for override in overrides:
            with self.subTest(override=override), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self._make_repository(root)
                workflow = root / ".github/workflows/quality.yml"
                content = workflow.read_text(encoding="utf-8").replace(
                    "  test:\n    steps:\n      - uses: actions/checkout@"
                    + "a" * 40
                    + "\n",
                    "  test: {runs-on: ubuntu-latest,\n"
                    + override
                    + '    steps: [{run: "echo hi"}]}\n',
                )
                workflow.write_text(content, encoding="utf-8")
                output = io.StringIO()
                with redirect_stdout(output):
                    code = cli_main(["doctor", "--root", str(root)])
                self.assertEqual(code, 1, output.getvalue())
                self.assertIn("[FAIL] CI permissions", output.getvalue())

    def test_doctor_rejects_inline_job_mapping_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._make_repository(root)
            workflow = root / ".github/workflows/quality.yml"
            content = workflow.read_text(encoding="utf-8").replace(
                "  test:\n    steps:\n",
                '  test: {runs-on: ubuntu-latest, "permissions": {contents: write}, steps: [{run: "echo hi"}]}\n',
            )
            workflow.write_text(content, encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = cli_main(["doctor", "--root", str(root)])
            self.assertEqual(code, 1, output.getvalue())
            self.assertIn("[FAIL] CI permissions", output.getvalue())

    def test_doctor_fails_closed_on_escaped_quoted_mapping_keys(self):
        overrides = (
            '    "\\u0070ermissions": {contents: write}\n',
            '  test: {runs-on: ubuntu-latest, "\\u0070ermissions": {contents: write}, steps: [{run: "echo hi"}]}\n',
        )
        for override in overrides:
            with self.subTest(override=override), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self._make_repository(root)
                workflow = root / ".github/workflows/quality.yml"
                content = workflow.read_text(encoding="utf-8")
                if override.startswith("  test:"):
                    content = content.replace("  test:\n    steps:\n", override)
                else:
                    content = content.replace("  test:\n    steps:\n", "  test:\n" + override + "    steps:\n")
                workflow.write_text(content, encoding="utf-8")
                output = io.StringIO()
                with redirect_stdout(output):
                    code = cli_main(["doctor", "--root", str(root)])
                self.assertEqual(code, 1, output.getvalue())
                self.assertIn("[FAIL] CI permissions", output.getvalue())

    def test_doctor_rejects_explicit_job_permission_keys(self):
        overrides = (
            '    ? "permissions"\n    : {contents: write}\n',
            '  test: {? "permissions": {contents: write}, runs-on: ubuntu-latest, steps: [{run: "echo hi"}]}\n',
            '    ? "\\u0070ermissions"\n    : {contents: write}\n',
            '  test: {? "\\u0070ermissions": {contents: write}, runs-on: ubuntu-latest, steps: [{run: "echo hi"}]}\n',
            '    name: &perm permissions\n    ? *perm\n    : {contents: write}\n',
            '  test: {name: &perm permissions, ? *perm: {contents: write}, runs-on: ubuntu-latest, steps: [{run: "echo hi"}]}\n',
            '    &perm permissions: {contents: write}\n',
            '  test: {&perm permissions: {contents: write}, runs-on: ubuntu-latest}\n',
            '    !!str permissions: {contents: write}\n',
            '  test: {!!str permissions: {contents: write}, runs-on: ubuntu-latest}\n',
            '    ? >-\n      permissions\n    : {contents: write}\n',
        )
        for override in overrides:
            with self.subTest(override=override), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self._make_repository(root)
                workflow = root / ".github/workflows/quality.yml"
                content = workflow.read_text(encoding="utf-8")
                if override.startswith("  test:"):
                    content = content.replace("  test:\n    steps:\n", override)
                else:
                    content = content.replace("  test:\n    steps:\n", "  test:\n" + override + "    steps:\n")
                workflow.write_text(content, encoding="utf-8")
                output = io.StringIO()
                with redirect_stdout(output):
                    code = cli_main(["doctor", "--root", str(root)])
                self.assertEqual(code, 1, output.getvalue())
                self.assertIn("[FAIL] CI permissions", output.getvalue())


    def test_doctor_accepts_escaped_quotes_in_plain_run_command(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._make_repository(root)
            workflow = root / ".github/workflows/quality.yml"
            content = workflow.read_text(encoding="utf-8")
            content += '      - run: echo "say \\"hello\\":world"\n'
            workflow.write_text(content, encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = cli_main(["doctor", "--root", str(root)])
            self.assertEqual(code, 0, output.getvalue())
            self.assertIn("[PASS] CI permissions", output.getvalue())

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


    @unittest.skipUnless(os.name == "posix", "POSIX directory fsync is required")
    def test_nested_new_parent_directories_are_synced_before_file_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "first" / "second" / "runs.jsonl"
            real_fsync = os.fsync
            observed = []

            def record_fsync(descriptor):
                mode = os.fstat(descriptor).st_mode
                observed.append("directory" if stat.S_ISDIR(mode) else "file")
                return real_fsync(descriptor)

            with mock.patch.object(ledger_module.os, "fsync", side_effect=record_fsync):
                HashChainLedger(path).append(passing("nested-first"))

            self.assertEqual(
                observed,
                ["directory", "directory", "directory", "directory", "file", "directory"],
            )
            self.assertEqual(HashChainLedger(path).verify()["records"], 1)


    @unittest.skipUnless(os.name == "posix", "POSIX hard links are required")
    def test_z_hard_link_alias_is_latched_after_uncertain_append(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original_path = root / "runs.jsonl"
            alias_path = root / "alias.jsonl"
            original = HashChainLedger(original_path)

            with mock.patch.object(
                ledger_module, "_fsync_file", side_effect=OSError("injected file fsync failure")
            ):
                with self.assertRaises(LedgerIntegrityError):
                    original.append(passing("uncertain"))

            alias_path.hardlink_to(original_path)
            before = original_path.read_bytes()
            self.assertEqual(alias_path.read_bytes(), before)
            alias = HashChainLedger(alias_path)

            with self.assertRaisesRegex(LedgerIntegrityError, "previous append failed"):
                alias.verify()
            with self.assertRaisesRegex(LedgerIntegrityError, "previous append failed"):
                alias.records()
            with self.assertRaisesRegex(LedgerIntegrityError, "previous append failed"):
                alias.append(passing("blocked"))
            with self.assertRaisesRegex(LedgerIntegrityError, "previous append failed"):
                original.verify()
            with self.assertRaisesRegex(LedgerIntegrityError, "previous append failed"):
                original.records()
            with self.assertRaisesRegex(LedgerIntegrityError, "previous append failed"):
                original.append(passing("blocked-original"))

            descriptor = os.open(alias_path, os.O_RDONLY)
            try:
                with self.assertRaisesRegex(LedgerIntegrityError, "previous append failed"):
                    alias._scan(descriptor=descriptor)
            finally:
                os.close(descriptor)

            self.assertEqual(original_path.read_bytes(), before)
            self.assertEqual(alias_path.read_bytes(), before)

            independent_path = root / "independent.jsonl"
            independent = HashChainLedger(independent_path)
            independent.append(passing("independent"))
            self.assertTrue(independent.verify()["valid"])


    @unittest.skipUnless(os.name == "posix", "POSIX descriptor semantics are required")
    def test_uncertain_inode_guard_cap_fails_closed_globally(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            uncertain = HashChainLedger(root / "uncertain.jsonl")
            unrelated = HashChainLedger(root / "unrelated.jsonl")

            # A zero-cap fixture exercises the same fail-closed branch as a full
            # 128-descriptor guard table without opening 128 real descriptors.
            with (
                mock.patch.object(ledger_module, "_UNCERTAIN_ALL", False),
                mock.patch.object(ledger_module, "_UNCERTAIN_PATHS", set()),
                mock.patch.object(ledger_module, "_UNCERTAIN_INODES", set()),
                mock.patch.object(ledger_module, "_UNCERTAIN_INODE_FDS", {}),
                mock.patch.object(ledger_module, "_MAX_UNCERTAIN_INODE_GUARDS", 0),
                mock.patch.object(
                    ledger_module,
                    "_fsync_file",
                    side_effect=OSError("injected file fsync failure"),
                ),
            ):
                with self.assertRaises(LedgerIntegrityError):
                    uncertain.append(passing("guard-cap"))

                self.assertTrue(ledger_module._UNCERTAIN_ALL)
                with self.assertRaisesRegex(LedgerIntegrityError, "previous append failed"):
                    unrelated.verify()
                with self.assertRaisesRegex(LedgerIntegrityError, "previous append failed"):
                    unrelated.append(passing("must-fail-closed"))

if __name__ == "__main__":
    unittest.main()
