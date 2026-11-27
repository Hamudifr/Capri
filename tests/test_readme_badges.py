"""Integrity gate for README workflow badges.

README badges are the landing-page visibility for CI gates; several
(keep-alive, workflow-lint) are ops-critical. A badge points at a workflow
file by name, and nothing previously prevented that target from drifting:
renaming or deleting a workflow file silently breaks the badge with no
test failure. This gate locks every badge target to an existing
.github/workflows/ file, mirroring the drift-gate philosophy of
test_migration_mirror.py.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
WORKFLOWS = ROOT / ".github" / "workflows"

BADGE_RE = re.compile(r"actions/workflows/([\w-]+\.yml)/badge\.svg")


class ReadmeBadgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = README.read_text(encoding="utf-8")
        self.badges = BADGE_RE.findall(self.text)

    def test_readme_declares_at_least_one_workflow_badge(self) -> None:
        self.assertGreaterEqual(
            len(self.badges), 1, "README has no actions/workflows badges"
        )

    def test_badge_targets_are_unique(self) -> None:
        self.assertEqual(
            len(self.badges),
            len(set(self.badges)),
            "duplicate badge targets: " + ", ".join(sorted(self.badges)),
        )

    def test_every_badge_target_is_an_existing_workflow_file(self) -> None:
        for target in self.badges:
            self.assertTrue(
                (WORKFLOWS / target).is_file(),
                f"badge points at missing workflow file: {target}",
            )

    def test_badges_cover_the_ops_critical_workflows(self) -> None:
        required = {"keep-alive.yml"}
        missing = required - set(self.badges)
        self.assertFalse(missing, f"ops-critical workflows lack badges: {sorted(missing)}")
