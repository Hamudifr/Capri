"""Read-only command-line entry point for ledger verification."""
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Sequence

from .ledger import HashChainLedger, LedgerIntegrityError


def run_doctor(root: Path, json_output: bool = False) -> int:
    """Run bounded, read-only checks against known Capri project files."""
    root = root.resolve()
    checks: list[tuple[str, bool, str]] = []

    checks.append((
        "Python version",
        sys.version_info >= (3, 11),
        "Python 3.11 or newer is required",
    ))

    required = (
        "README.md",
        "capri_core/__main__.py",
        "capri_core/ledger.py",
        "capri_runtime/runtime.py",
        "tests/test_runtime_core.py",
        "tests/test_runtime.py",
        ".github/workflows/quality.yml",
    )
    missing = [name for name in required if not (root / name).is_file()]
    checks.append((
        "Repository structure",
        not missing,
        "required files present" if not missing else "missing: " + ", ".join(missing),
    ))

    workflow_path = root / ".github/workflows/quality.yml"
    if workflow_path.is_file():
        try:
            workflow = workflow_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            checks.append(("CI workflow readable", False, type(exc).__name__))
        else:
            uses_lines = [
                line for line in workflow.splitlines()
                if re.match(r"^\s*(?:-\s*)?uses\s*:", line)
            ]
            unpinned = [
                line.strip() for line in uses_lines
                if not re.search(r"@[0-9a-fA-F]{40}(?:\s|$)", line)
                and not re.search(r"uses\s*:\s*\./", line)
            ]
            checks.append((
                "CI actions pinned",
                bool(uses_lines) and not unpinned,
                "all external actions use full commit SHAs"
                if uses_lines and not unpinned
                else "unpinned action references: " + "; ".join(unpinned or ["no action references found"]),
            ))
            least_privilege = bool(re.search(
                r"(?m)^permissions:\s*\n\s+contents:\s*read\s*$",
                workflow,
            ))
            checks.append((
                "CI permissions",
                least_privilege,
                "contents: read is explicitly scoped"
                if least_privilege else "expected explicit contents: read permission",
            ))
            recovery_triggers = workflow.count('branches: ["main", "recovery/non-x5-foundation"]')
            checks.append((
                "Recovery CI coverage",
                recovery_triggers >= 2,
                "push and pull_request include the recovery branch"
                if recovery_triggers >= 2 else "recovery branch trigger missing from push or pull_request",
            ))
    else:
        checks.append(("CI workflow readable", False, "workflow file is missing"))

    check_ids = {
        "Python version": "python_version",
        "Repository structure": "repository_structure",
        "CI workflow readable": "ci_workflow_readable",
        "CI actions pinned": "ci_actions_pinned",
        "CI permissions": "ci_permissions",
        "Recovery CI coverage": "recovery_ci_coverage",
    }
    report_checks = [
        {
            "id": check_ids[name],
            "name": name,
            "status": "pass" if passed else "fail",
            "detail": detail,
        }
        for name, passed, detail in checks
    ]
    failed = sum(item["status"] == "fail" for item in report_checks)
    if json_output:
        report = {
            "schema_version": 1,
            "tool": "capri-doctor",
            "status": "fail" if failed else "pass",
            "summary": {
                "passed": len(report_checks) - failed,
                "failed": failed,
                "total": len(report_checks),
            },
            "checks": report_checks,
        }
        print(json.dumps(report, sort_keys=True))
    else:
        for item in report_checks:
            print(f"[{item['status'].upper()}] {item['name']}: {item['detail']}")
        print(f"\nCapri Doctor: {len(report_checks) - failed}/{len(report_checks)} checks passed")
    return 0 if failed == 0 else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m capri_core",
        description="Read-only tools for the Capri non-X5 execution ledger.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    doctor_parser = commands.add_parser("doctor", help="run read-only repository health checks")
    doctor_parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root (default: current directory)")
    doctor_parser.add_argument("--json", action="store_true", help="emit a versioned machine-readable JSON report")
    verify = commands.add_parser("verify", help="verify an existing ledger without modifying it")
    verify.add_argument("path", type=Path, help="path to an existing JSONL ledger")
    args = parser.parse_args(argv)

    if args.command == "doctor":
        return run_doctor(args.root, json_output=args.json)

    if args.command == "verify":
        if not args.path.exists() or not args.path.is_file():
            print(f"verification failed: not an existing regular file: {args.path}", file=sys.stderr)
            return 2
        try:
            result = HashChainLedger(args.path).verify()
        except (LedgerIntegrityError, OSError, UnicodeError) as exc:
            print(f"verification failed: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(result, sort_keys=True))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
