"""Contract tests for scripts/check_probe.py (the keep-alive validator).

Drives the script exactly the way the workflow does - body on stdin,
flags for required booleans - so the greps it replaces stay replaced by
something the quality gate can regress-test.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_probe.py"

FULL = (
    '{"ok":true,"under_limit":true,"cron_active":true,'
    '"cron_stale":false,"time":"2026-11-27T21:00:00.000Z"}'
)
V8_STYLE = '{"ok":true,"under_limit":true,"time":"2026-11-27T19:00:00.000Z"}'
FAIL_CLOSED = (
    '{"ok":false,"under_limit":false,"error":"metrics missing or invalid",'
    '"time":"2026-11-27T21:00:00.000Z"}'
)


def run(body: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=body,
        capture_output=True,
        text=True,
        timeout=10,
    )


class CheckProbeTests(unittest.TestCase):
    def test_healthy_full_contract_passes(self) -> None:
        result = run(FULL, "--true", "ok,under_limit,cron_active", "--false", "cron_stale")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_ping_style_ok_only_passes(self) -> None:
        result = run(V8_STYLE, "--true", "ok")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_empty_body_fails(self) -> None:
        result = run("   \n", "--true", "ok")
        self.assertEqual(result.returncode, 1)
        self.assertIn("empty response", result.stderr)

    def test_html_garbage_fails(self) -> None:
        result = run("<html>502 Bad Gateway</html>", "--true", "ok")
        self.assertEqual(result.returncode, 1)
        self.assertIn("not JSON", result.stderr)

    def test_ok_false_fails(self) -> None:
        result = run(FAIL_CLOSED, "--true", "ok,under_limit")
        self.assertEqual(result.returncode, 1)
        self.assertIn("ok", result.stderr)

    def test_string_true_never_passes(self) -> None:
        body = '{"ok":"true","under_limit":true}'
        result = run(body, "--true", "ok")
        self.assertEqual(result.returncode, 1)
        self.assertIn("not boolean true", result.stderr)

    def test_numeric_one_never_passes(self) -> None:
        body = '{"ok":1,"under_limit":true}'
        result = run(body, "--true", "ok")
        self.assertEqual(result.returncode, 1)
        self.assertIn("not boolean true", result.stderr)

    def test_null_value_never_passes(self) -> None:
        body = '{"ok":null,"under_limit":true}'
        result = run(body, "--true", "ok")
        self.assertEqual(result.returncode, 1)
        self.assertIn("not boolean true", result.stderr)

    def test_v8_payload_missing_cron_keys_fails(self) -> None:
        result = run(V8_STYLE, "--true", "ok,cron_active", "--false", "cron_stale")
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing key: cron_active", result.stderr)

    def test_cron_stale_true_fails_the_false_requirement(self) -> None:
        body = '{"ok":true,"under_limit":true,"cron_active":true,"cron_stale":true}'
        result = run(body, "--true", "cron_active", "--false", "cron_stale")
        self.assertEqual(result.returncode, 1)
        self.assertIn("cron_stale", result.stderr)

    def test_json_array_fails(self) -> None:
        result = run("[1, 2, 3]", "--true", "ok")
        self.assertEqual(result.returncode, 1)
        self.assertIn("not an object", result.stderr)

    def test_fail_closed_502_payload_fails(self) -> None:
        result = run(FAIL_CLOSED, "--true", "ok,under_limit")
        self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
