"""Run fixed, named Capri regression suites for the Termux bridge.

The bridge manifest chooses only a suite name from its fixed TASKS allowlist.
No manifest-controlled paths, module names, or commands are accepted here.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

SUITES = {
    "security_store": (
        "test_security_store.py",
    ),
    "approval_binding": (
        "test_signed_approvals.py",
        "test_approval_lifecycle.py",
        "test_host_authority.py",
        "test_host_gateway.py",
        "test_tools.py",
        "test_tool_bridge.py",
        "test_resource_authorization.py",
    ),
    "x7_runtime": (
        "test_tasks.py",
        "test_host_runtime.py",
        "test_runtime_core.py",
    ),
}


def load_suite(name: str) -> unittest.TestSuite:
    if not isinstance(name, str) or name not in SUITES:
        raise ValueError("unknown fixed focused-test suite")
    sys.path.insert(0, str(ROOT))
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for pattern in SUITES[name]:
        suite.addTests(
            loader.discover(
                start_dir=str(TESTS),
                pattern=pattern,
                top_level_dir=str(TESTS),
            )
        )
    return suite


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 1 or arguments[0] not in SUITES:
        print("usage: python tools/focused_tests.py <security_store|approval_binding|x7_runtime>")
        return 2
    result = unittest.TextTestRunner(verbosity=2).run(load_suite(arguments[0]))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
