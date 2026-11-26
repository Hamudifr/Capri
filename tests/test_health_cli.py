"""Integration tests for the Doctor operational health report."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from capri_core.__main__ import main


class DoctorHealthIntegrationTests(unittest.TestCase):
    def test_json_output_contains_evidence_backed_health_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (
                "README.md",
                "capri_core/__main__.py",
                "capri_core/ledger.py",
                "capri_runtime/runtime.py",
                "tests/test_runtime_core.py",
                "tests/test_runtime.py",
            ):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture\n", encoding="utf-8")
            workflow = root / ".github/workflows/quality.yml"
            workflow.parent.mkdir(parents=True, exist_ok=True)
            workflow.write_text(
                'on:\n  push:\n    branches: ["main"]\n'
                '  pull_request:\n    branches: ["main"]\n'
                'permissions:\n  contents: read\n'
                'jobs:\n  test:\n    steps:\n'
                '      - uses: actions/checkout@' + "a" * 40 + "\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["doctor", "--root", directory, "--json"])
            report = json.loads(output.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(report["health"]["scope"], "local_static_repository_checks")
            self.assertEqual(report["health"]["status"], "healthy", str(report["health"]))
            self.assertEqual(report["health"]["summary"]["components"], 8)
            self.assertEqual(report["health"]["summary"]["healthy"], 8)
            self.assertTrue(all(item["evidence"] is not None for item in report["health"]["components"][:-1]))
            self.assertIsNone(report["health"]["components"][-1]["evidence"])
            self.assertTrue(report["health"]["components"][0]["observed_at"].endswith("+00:00") or report["health"]["components"][0]["observed_at"].endswith("Z"))


if __name__ == "__main__":
    unittest.main()
