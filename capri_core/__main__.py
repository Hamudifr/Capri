"""Read-only command-line entry point for ledger verification."""
import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .ledger import HashChainLedger, LedgerIntegrityError


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m capri_core",
        description="Read-only tools for the Capri non-X5 execution ledger.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify", help="verify an existing ledger without modifying it")
    verify.add_argument("path", type=Path, help="path to an existing JSONL ledger")
    args = parser.parse_args(argv)

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
