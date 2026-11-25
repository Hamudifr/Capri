#!/usr/bin/env python3
"""Run Capri's offline repository checks without installing dependencies or using CI."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence


@dataclass
class CheckResult:
    name: str
    command: list[str]
    status: str
    returncode: int | None
    duration_seconds: float
    output: str


def run_check(root: Path, name: str, command: Sequence[str], timeout: float) -> CheckResult:
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            list(command), cwd=root, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=timeout, check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        status = "passed" if completed.returncode == 0 else "failed"
        returncode, output = completed.returncode, completed.stdout
    except subprocess.TimeoutExpired as exc:
        status, returncode = "timed_out", None
        raw = exc.stdout or b""
        output = raw.decode(errors="replace") if isinstance(raw, bytes) else raw
        output += f"\nTimed out after {timeout:g}s"
    except OSError as exc:
        status, returncode, output = "could_not_run", None, f"{type(exc).__name__}: {exc}"
    return CheckResult(name, list(command), status, returncode,
                       round(time.perf_counter() - started, 4), output)


def build_checks(python: str, full: bool) -> list[tuple[str, list[str]]]:
    checks = [
        ("compile", [python, "-m", "compileall", "-q",
                     "capri_core", "capri_runtime", "tests", "benchmarks"]),
    ]
    if full:
        checks.extend([
            ("unit_tests", [python, "-m", "unittest", "discover", "-s", "tests", "-v"]),
            ("capri_doctor", [python, "-m", "capri_core", "doctor"]),
            ("memory_retrieval_regression", [python, "-m", "benchmarks.memory_retrieval.run"]),
            ("skill_validation", [python, "-m", "capri_core", "skills", "validate",
                                  "--root", ".", "--json"]),
        ])
    checks.append(("diff_whitespace", ["git", "diff", "--check", "HEAD"]))
    return checks


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(),
                        help="repository root (default: current directory)")
    parser.add_argument("--python", default=sys.executable,
                        help="Python executable to use")
    parser.add_argument("--timeout", type=float, default=900.0,
                        help="per-check timeout in seconds")
    parser.add_argument("--compile-only", action="store_true",
                        help="run syntax and whitespace checks only")
    parser.add_argument("--json", action="store_true",
                        help="emit machine-readable results")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if not (root / ".git").exists() or not (root / "pyproject.toml").is_file():
        parser.error(f"{root} does not look like a Capri Git checkout "
                     "(.git and pyproject.toml required)")

    results = [run_check(root, name, command, args.timeout)
               for name, command in build_checks(args.python, not args.compile_only)]
    payload = {
        "repository": str(root), "python": args.python,
        "mode": "compile_only" if args.compile_only else "full",
        "checks": [asdict(item) for item in results],
        "passed": all(item.status == "passed" for item in results),
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for item in results:
            print(f"[{item.status.upper():11}] {item.name:30} "
                  f"{item.duration_seconds:8.3f}s")
            if item.status != "passed" and item.output:
                print(item.output.rstrip())
        print(f"\nResult: {'PASS' if payload['passed'] else 'FAIL'}")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
