"""Integrity gate for the docs/db/migrations/ audit mirror.

The mirror is exported verbatim from supabase_migrations.schema_migrations;
CI cannot reach the platform, so this gate checks the invariants that have
actually drifted before: README count vs file count, filename/version
consistency, and basic file hygiene. Byte-fidelity to the platform is
verified at export time with md5(statements[1]) (see README).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

MIRROR = Path(__file__).resolve().parent.parent / "docs" / "db" / "migrations"
VERSION_RE = re.compile(r"^(\d{14})_.+\.sql$")
README_COUNT_RE = re.compile(r"(\d+) migrations")


class MigrationMirrorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sql_files = sorted(MIRROR.glob("*.sql"))

    def test_mirror_is_non_empty(self) -> None:
        self.assertGreaterEqual(len(self.sql_files), 1, "mirror has no .sql files")

    def test_filenames_are_versioned_and_unique(self) -> None:
        versions: list[str] = []
        for path in self.sql_files:
            match = VERSION_RE.match(path.name)
            self.assertIsNotNone(match, f"bad mirror filename: {path.name}")
            versions.append(match.group(1))  # type: ignore[union-attr]
        self.assertEqual(len(versions), len(set(versions)), "duplicate version prefixes")
        self.assertEqual(versions, sorted(versions), "files not sorted by version")

    def test_files_are_non_empty_utf8(self) -> None:
        for path in self.sql_files:
            data = path.read_bytes()
            self.assertGreater(len(data), 0, f"empty file: {path.name}")
            self.assertFalse(data.startswith(b"\xef\xbb\xbf"), f"BOM in {path.name}")
            try:
                data.decode("utf-8")
            except UnicodeDecodeError as exc:  # pragma: no cover - failure path
                self.fail(f"not UTF-8: {path.name}: {exc}")

    def test_readme_count_matches_file_count(self) -> None:
        readme = (MIRROR / "README.md").read_text(encoding="utf-8")
        match = README_COUNT_RE.search(readme)
        self.assertIsNotNone(match, "README does not state a migration count")
        declared = int(match.group(1))
        self.assertEqual(
            declared,
            len(self.sql_files),
            "README count out of sync with mirror contents "
            f"(README says {declared}, found {len(self.sql_files)})",
        )

    def test_readme_states_verification_method(self) -> None:
        readme = (MIRROR / "README.md").read_text(encoding="utf-8")
        self.assertIn(
            "md5",
            readme.lower(),
            "README must record the md5 export-verification method",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
