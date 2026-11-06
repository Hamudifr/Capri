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
    """Accept only top-level contents: read; reject nested permission overrides."""
    lines = workflow.splitlines()
    if any(
        re.search(
            r"(?:^[ \t]+(?:permissions|[\"']permissions[\"'])\s*:|"
            r"[{,]\s*(?:permissions|[\"']permissions[\"'])\s*:|"
            r"^[ \t]+\?\s*(?:permissions|[\"']permissions[\"'])\s*$|"
            r"[{,]\s*\?\s*(?:permissions|[\"']permissions[\"'])\s*(?=:|$))",
            line,
        )
        # Column-zero quoted keys (value may live on a later line). The
        # legitimate top-level block is the unquoted form "permissions:" and
        # is validated separately below; only quoted forms are treated as
        # overrides here. This closes the multiline flow-mapping bypass.
        or re.search(r"""^[\"']permissions[\"']\s*:""", line)
        # GitHub Actions accepts YAML anchors/aliases, and YAML double-quoted
        # keys can use escapes (for example, "\\u0070ermissions"). Without
        # parsing YAML, fail closed on alias, anchor, tag, explicit, and escaped keys.
        or re.search(r'^[ \t]*(?:\?\s*)?"(?:[^"\\]|\\.)*\\(?:[^"\\]|\\.)*"\s*(?::|$)', line)
        or re.search(r'[{,]\s*(?:\?\s*)?"(?:[^"\\]|\\.)*\\(?:[^"\\]|\\.)*"\s*(?=:|,|})', line)
        or re.search(r'^[ \t]*(?:\?\s*)?\*[^\s,:{}\[\]]+\s*(?::|$)', line)
        or re.search(r'[{,]\s*(?:\?\s*)?\*[^\s,:{}\[\]]+\s*(?=:|,|})', line)
        or re.search(r'^[ \t]*\?\s+', line)
        or re.search(r'[{,]\s*\?\s+', line)
        or re.search(r'^[ \t]*&[^\s,:{}\[\]]+\s+', line)
        or re.search(r'[{,]\s*&[^\s,:{}\[\]]+\s+', line)
        or re.search(r'^[ \t]*!(?:<[^>]+>|[^\s,:{}\[\]]+)\s+', line)
        or re.search(r'[{,]\s*!(?:<[^>]+>|[^\s,:{}\[\]]+)\s+', line)
        for line in lines
        if not line.lstrip().startswith("#")
    ):
        return False
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
