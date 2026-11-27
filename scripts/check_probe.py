#!/usr/bin/env python3
"""Validate a Capri probe response body against the JSON contract.

Used by .github/workflows/keep-alive.yml instead of inline greps so the
checks are unit-tested (tests/test_check_probe.py) and a failure says
exactly which key was missing or wrongly valued. Exit 0 = contract
satisfied; exit 1 = violation (reason on stderr).

Identity matters: only literal JSON true/false pass --true/--false.
Strings ("true"), numbers (1/0), and null never satisfy a requirement -
the same fail-closed rule the edge function applies to budget metrics.
"""

from __future__ import annotations

import argparse
import json
import sys


def validate(body: str, require_true: list[str], require_false: list[str]) -> str | None:
    """Return None when the contract holds, else a human-readable reason."""
    if not body.strip():
        return "empty response (transport failure?)"
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        return f"response is not JSON: {exc}"
    if not isinstance(data, dict):
        return f"JSON is not an object: {type(data).__name__}"
    for key in require_true:
        if key not in data:
            return f"missing key: {key}"
        if data[key] is not True:
            return f"{key}={data[key]!r} is not boolean true"
    for key in require_false:
        if key not in data:
            return f"missing key: {key}"
        if data[key] is not False:
            return f"{key}={data[key]!r} is not boolean false"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--true", default="", help="comma-separated keys that must be boolean true"
    )
    parser.add_argument(
        "--false", default="", help="comma-separated keys that must be boolean false"
    )
    args = parser.parse_args(argv)
    require_true = [key.strip() for key in args.true.split(",") if key.strip()]
    require_false = [key.strip() for key in args.false.split(",") if key.strip()]
    reason = validate(sys.stdin.read(), require_true, require_false)
    if reason is None:
        print("contract satisfied")
        return 0
    print(f"contract violated: {reason}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
