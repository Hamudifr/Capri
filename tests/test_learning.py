import json
import os
import sqlite3
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from capri_core.learning import LearningDataError, LearningExample, LearningStore


def example(**overrides):
    values = dict(
        example_id="ex-001", task_id="task-001", capability="tool_execution",
        prompt="Use the read-only status tool.", completion="Returned the verified status.",
        outcome="verified_success", evidence_ref="test://evidence/001",
        quality_score=0.98, consent=True, privacy_reviewed=True,
    )
    values.update(overrides)
    return LearningExample(**values)


class LearningStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = LearningStore(self.root / "learning.sqlite3")

    def tearDown(self):
        self.temp.cleanup()

    def test_rejects_missing_consent(self):
        with self.assertRaises(LearningDataError):
            self.store.record(example(consent=False))

    def test_rejects_missing_privacy_review(self):
        for value in (False, "yes", 1):
            with self.subTest(value=value):
                with self.assertRaises(LearningDataError):
                    self.store.record(example(privacy_reviewed=value))

    def test_rejects_non_boolean_consent(self):
        with self.assertRaises(LearningDataError):
            self.store.record(example(consent="yes"))

    def test_rejects_unclassified_sensitive_flag(self):
        with self.assertRaises(LearningDataError):
            self.store.record(example(sensitive=None))

    def test_rejects_sensitive_content(self):
        with self.assertRaises(LearningDataError):
            self.store.record(example(sensitive=True))

    def test_rejects_invalid_quality(self):
        for value in (1.1, -0.1, float("nan"), float("inf"), float("-inf"), "0.9", True):
            with self.subTest(value=value):
                with self.assertRaises(LearningDataError):
                    self.store.record(example(quality_score=value))

    def test_rejects_duplicate_identifier(self):
        self.store.record(example())
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.record(example())

    def test_only_verified_success_is_exported(self):
        self.store.record(example())
        self.store.record(example(
            example_id="ex-002", task_id="task-002",
            outcome="verified_failure", prompt="bad", completion="bad",
        ))
        self.store.record(example(
            example_id="ex-003", task_id="task-003",
            outcome="unverified", prompt="unknown", completion="unknown",
        ))
        output = self.root / "dataset.jsonl"
        counts = self.store.export_jsonl(output)
        rows = [json.loads(line) for line in output.read_text().splitlines()]
        self.assertEqual(sum(counts[s] for s in ("train", "validation", "test")), 1)
        self.assertEqual([row["example_id"] for row in rows], ["ex-001"])

    def test_quality_threshold_excludes_low_quality(self):
        self.store.record(example(quality_score=0.89))
        counts = self.store.export_jsonl(self.root / "out.jsonl")
        self.assertEqual(sum(counts[s] for s in ("train", "validation", "test")), 0)

    def test_duplicate_content_is_exported_once(self):
        self.store.record(example())
        self.store.record(example(
            example_id="ex-002", task_id="task-002",
            evidence_ref="test://evidence/002",
        ))
        counts = self.store.export_jsonl(self.root / "out.jsonl")
        self.assertEqual(counts["excluded_duplicate"], 1)
        self.assertEqual(sum(counts[s] for s in ("train", "validation", "test")), 1)

    def test_splits_are_deterministic(self):
        self.store.record(example())
        first = self.root / "first.jsonl"
        second = self.root / "second.jsonl"
        self.store.export_jsonl(first)
        self.store.export_jsonl(second)
        self.assertEqual(first.read_text(), second.read_text())
        rows = [json.loads(line) for line in first.read_text().splitlines()]
        self.assertIn(rows[0]["split"], {"train", "validation", "test"})

    def test_rejects_non_integer_schema_version(self):
        for value in (1.0, True, "1"):
            with self.subTest(value=value):
                with self.assertRaises(LearningDataError):
                    self.store.record(example(schema_version=value))

    def test_rejects_oversized_integer_quality_score(self):
        with self.assertRaises(LearningDataError):
            self.store.record(example(quality_score=10**10000))

    def test_rejects_invalid_export_threshold(self):
        for value in (-0.1, 1.1, float("nan"), float("inf"), float("-inf"), "0.9", True):
            with self.subTest(value=value):
                with self.assertRaises(LearningDataError):
                    self.store.export_jsonl(self.root / "bad.jsonl", minimum_quality=value)

    def test_examples_from_same_task_share_a_split(self):
        self.store.record(example())
        self.store.record(example(
            example_id="ex-002", prompt="A different prompt",
            completion="A different completion",
        ))
        output = self.root / "grouped.jsonl"
        self.store.export_jsonl(output)
        rows = [json.loads(line) for line in output.read_text().splitlines()]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["split"], rows[1]["split"])

    def test_rejects_oversized_integer_export_threshold(self):
        with self.assertRaises(LearningDataError):
            self.store.export_jsonl(
                self.root / "bad-large-threshold.jsonl",
                minimum_quality=10**10000,
            )


    def test_creates_private_storage_directories(self):
        database_dir = self.root / "new-database-dir"
        LearningStore(database_dir / "learning.sqlite3")
        self.assertEqual(stat.S_IMODE(database_dir.stat().st_mode), 0o700)

        export_dir = self.root / "new-export-dir"
        self.store.record(example())
        self.store.export_jsonl(export_dir / "dataset.jsonl")
        self.assertEqual(stat.S_IMODE(export_dir.stat().st_mode), 0o700)

    def test_database_file_is_owner_only(self):
        mode = stat.S_IMODE((self.root / "learning.sqlite3").stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_rejects_non_private_database_directory(self):
        public_dir = self.root / "public-db"
        public_dir.mkdir(mode=0o755)
        os.chmod(public_dir, 0o755)
        with self.assertRaises(LearningDataError):
            LearningStore(public_dir / "learning.sqlite3")

    def test_rejects_existing_non_private_database_file(self):
        database = self.root / "public.sqlite3"
        database.write_bytes(b"not a database")
        os.chmod(database, 0o644)
        with self.assertRaises(LearningDataError):
            LearningStore(database)

    def test_rejects_database_symlink(self):
        target = self.root / "target.sqlite3"
        target.write_bytes(b"do not follow")
        link = self.root / "linked.sqlite3"
        link.symlink_to(target)
        with self.assertRaises(LearningDataError):
            LearningStore(link)

    def test_export_is_private_and_never_overwrites(self):
        self.store.record(example())
        output = self.root / "dataset.jsonl"
        self.store.export_jsonl(output)
        original = output.read_bytes()
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
        with self.assertRaises(FileExistsError):
            self.store.export_jsonl(output)
        self.assertEqual(output.read_bytes(), original)

    def test_export_rejects_non_private_directory(self):
        public_dir = self.root / "public-export"
        public_dir.mkdir(mode=0o755)
        os.chmod(public_dir, 0o755)
        with self.assertRaises(LearningDataError):
            self.store.export_jsonl(public_dir / "dataset.jsonl")

    def test_failed_atomic_publication_leaves_no_partial_export(self):
        self.store.record(example())
        output = self.root / "dataset.jsonl"
        with patch("capri_core.learning.os.link", side_effect=OSError("link unavailable")):
            with self.assertRaises(OSError):
                self.store.export_jsonl(output)
        self.assertFalse(output.exists())
        self.assertEqual(list(self.root.glob(".dataset.jsonl.*.tmp")), [])

    def test_export_refuses_symlink_destination(self):
        self.store.record(example())
        existing = self.root / "existing.jsonl"
        existing.write_text("preserve me")
        link = self.root / "dataset.jsonl"
        link.symlink_to(existing)
        with self.assertRaises(FileExistsError):
            self.store.export_jsonl(link)
        self.assertTrue(link.is_symlink())
        self.assertEqual(existing.read_text(), "preserve me")

    def test_export_surfaces_post_publish_directory_fsync_uncertainty(self):
        self.store.record(example())
        output = self.root / "dataset.jsonl"
        with patch("capri_core.learning._fsync_directory", side_effect=OSError("fsync failed")):
            with self.assertRaisesRegex(OSError, "published at"):
                self.store.export_jsonl(output)
        rows = [json.loads(line) for line in output.read_text().splitlines()]
        self.assertEqual([row["example_id"] for row in rows], ["ex-001"])

    def test_capability_allowlist(self):
        self.store.record(example(capability="research"))
        counts = self.store.export_jsonl(
            self.root / "out.jsonl", allowed_capabilities={"tool_execution"}
        )
        self.assertEqual(sum(counts[s] for s in ("train", "validation", "test")), 0)


if __name__ == "__main__":
    unittest.main()
