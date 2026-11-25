from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / "scripts" / "verify_local.py"
SPEC = importlib.util.spec_from_file_location("verify_local", SCRIPT)
verify_local = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = verify_local
SPEC.loader.exec_module(verify_local)


class VerifyLocalTests(unittest.TestCase):
    def test_full_check_set_matches_repository_quality_workflow(self):
        names = [name for name, _ in verify_local.build_checks("python", full=True)]
        self.assertEqual(names, [
            "compile", "unit_tests", "capri_doctor",
            "memory_retrieval_regression", "skill_validation", "diff_whitespace",
        ])

    def test_compile_only_skips_expensive_checks(self):
        checks = verify_local.build_checks("python", full=False)
        self.assertEqual([name for name, _ in checks], ["compile", "diff_whitespace"])
        self.assertTrue(all("unittest" not in command for _, command in checks))

    def test_runner_captures_nonzero_exit(self):
        with patch.object(verify_local.subprocess, "run") as run:
            run.return_value.returncode = 2
            run.return_value.stdout = "failure details"
            result = verify_local.run_check(Path.cwd(), "example", ["false"], 1)
        self.assertEqual((result.status, result.returncode, result.output),
                         ("failed", 2, "failure details"))

    def test_runner_reports_timeout(self):
        with patch.object(verify_local.subprocess, "run",
                          side_effect=subprocess.TimeoutExpired(["slow"], 1)):
            result = verify_local.run_check(Path.cwd(), "slow", ["slow"], 1)
        self.assertEqual(result.status, "timed_out")
        self.assertIsNone(result.returncode)

    def test_checkout_guard_rejects_non_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                verify_local.main(["--root", tmp])


if __name__ == "__main__":
    unittest.main()
