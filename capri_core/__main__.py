"""Read-only command-line entry point for ledger verification."""
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Sequence

from .ledger import HashChainLedger, LedgerIntegrityError
from .health import build_health_report


def _workflow_permissions_are_read_only(workflow: str) -> bool:
    """Accept only the explicit, single-scope contents: read permission block."""
    lines = workflow.splitlines()
    matches = [
        index for index, line in enumerate(lines)
        if re.fullmatch(r"permissions:\s*(?:#.*)?", line)
    ]
    if len(matches) != 1:
        return False

    start = matches[0]
    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.strip() and not line.lstrip().startswith("#"):
            if len(line) - len(line.lstrip()) == 0:
                end = index
                break

    scopes: list[str] = []
    for line in lines[start + 1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if len(line) - len(line.lstrip()) != 2:
            return False
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_-]*):\s*([^#]+?)\s*(?:#.*)?", line.strip())
        if not match or match.group(1) != "contents" or match.group(2).strip() != "read":
            return False
        scopes.append(match.group(1))
    return scopes == ["contents"]


def _workflow_event_branches(workflow: str, event: str) -> set[str] | None:
    """Read a simple explicit branch filter under one top-level Actions event.

    This intentionally supports only the mapping and inline/block sequence forms
    used by the repository workflow. Unsupported YAML constructs fail closed
    rather than being mistaken for verified trigger coverage.
    """
    lines = workflow.splitlines()
    on_blocks = [
        index for index, line in enumerate(lines)
        if re.fullmatch(r"on:\s*(?:#.*)?", line)
    ]
    if len(on_blocks) != 1:
        return None
    on_index = on_blocks[0]

    on_end = len(lines)
    for index in range(on_index + 1, len(lines)):
        line = lines[index]
        if line.strip() and not line.lstrip().startswith("#") and len(line) - len(line.lstrip()) == 0:
            on_end = index
            break

    event_level_indent = None
    for index in range(on_index + 1, on_end):
        line = lines[index]
        if line.strip() and not line.lstrip().startswith("#"):
            event_level_indent = len(line) - len(line.lstrip())
            break
    if event_level_indent is None or event_level_indent == 0:
        return None

    event_indices = []
    event_indent = event_level_indent
    for index in range(on_index + 1, on_end):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == event_level_indent and re.fullmatch(rf"{re.escape(event)}:\s*(?:#.*)?", line.strip()):
            event_indices.append(index)
    if len(event_indices) != 1:
        return None
    event_index = event_indices[0]

    event_end = on_end
    for index in range(event_index + 1, on_end):
        line = lines[index]
        if line.strip() and not line.lstrip().startswith("#"):
            indent = len(line) - len(line.lstrip())
            if indent <= event_indent:
                event_end = index
                break

    branch_entries = []
    for index in range(event_index + 1, event_end):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        match = re.fullmatch(r"branches:\s*(.*)", line.strip())
        if match and indent == event_indent + 2:
            branch_entries.append((index, indent, match.group(1).strip()))
    if len(branch_entries) != 1:
        return None

    branch_index, branch_indent, value = branch_entries[0]
    if value:
        if not (value.startswith("[") and value.endswith("]")):
            return None
        raw_values = value[1:-1].split(",")
        branches = set()
        for raw in raw_values:
            item = raw.strip()
            if len(item) >= 2 and item[0] == item[-1] and item[0] in ("'", '"'):
                item = item[1:-1]
            elif "'" in item or '"' in item:
                return None
            if not item:
                return None
            branches.add(item)
        return branches

    branches = set()
    for line in lines[branch_index + 1:event_end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= branch_indent:
            break
        if indent != branch_indent + 2:
            return None
        item_match = re.fullmatch(r"-\s*(.+?)\s*", line.strip())
        if not item_match:
            return None
        item = item_match.group(1).strip()
        if len(item) >= 2 and item[0] == item[-1] and item[0] in ("'", '"'):
            item = item[1:-1]
        elif "'" in item or '"' in item:
            return None
        if not item:
            return None
        branches.add(item)
    return branches or None


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
            checks.append(("CI workflow readable", True, "workflow file is readable"))
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
            least_privilege = _workflow_permissions_are_read_only(workflow)
            checks.append((
                "CI permissions",
                least_privilege,
                "contents: read is explicitly scoped"
                if least_privilege else "expected explicit contents: read permission",
            ))
            required_branches = {"main", "recovery/non-x5-foundation"}
            push_branches = _workflow_event_branches(workflow, "push")
            pull_request_branches = _workflow_event_branches(workflow, "pull_request")
            triggers_verified = (
                push_branches is not None
                and pull_request_branches is not None
                and required_branches.issubset(push_branches)
                and required_branches.issubset(pull_request_branches)
            )
            checks.append((
                "Recovery CI coverage",
                triggers_verified,
                "push and pull_request explicitly include main and the recovery branch"
                if triggers_verified else
                "could not verify required branches under both top-level events; unsupported or missing filters fail closed",
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
    health_report = build_health_report([
        {"id": item["id"], "status": item["status"]}
        for item in report_checks
    ])
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
            "health": health_report,
        }
        print(json.dumps(report, sort_keys=True))
    else:
        for item in report_checks:
            print(f"[{item['status'].upper()}] {item['name']}: {item['detail']}")
        print(f"\nCapri Doctor: {len(report_checks) - failed}/{len(report_checks)} checks passed")
        print(
            f"Operational health: {health_report['status']} "
            f"({health_report['summary']['healthy']}/{health_report['summary']['components']} components healthy)"
        )
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
