import json
import os
import sqlite3
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from capri_core import learning as learning_module
from capri_core.learning import LearningConsent, LearningDataError, LearningExample, LearningStore


def example(**overrides):
    values = dict(
        example_id="ex-001", task_id="task-001", capability="tool_execution",
        prompt="Use the read-only status tool.", completion="Returned the verified status.",
        outcome="verified_success", evidence_ref="test://evidence/001",
        quality_score=0.98, consent=True, privacy_reviewed=True,
        consent_id="consent-001",
    )
    values.update(overrides)
    return LearningExample(**values)


class LearningStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = LearningStore(self.root / "learning.sqlite3")
        self.store.record_consent(LearningConsent(
            consent_id="consent-001",
            scope="curated_training_examples",
            policy_version="learning-consent-v1",
            evidence_ref="test://consent/001",
            granted_at="2026-11-06T11:00:00+00:00",
        ))

    def tearDown(self):
        self.temp.cleanup()

    def test_migrates_legacy_learning_database_for_consent_provenance(self):
        legacy_path = self.root / "legacy-learning.sqlite3"
        connection = sqlite3.connect(legacy_path)
        try:
            connection.execute(
                """CREATE TABLE learning_examples (
                    example_id TEXT PRIMARY KEY, task_id TEXT NOT NULL,
                    capability TEXT NOT NULL, prompt TEXT NOT NULL,
                    completion TEXT NOT NULL, outcome TEXT NOT NULL,
                    evidence_ref TEXT NOT NULL, quality_score REAL NOT NULL,
                    consent INTEGER NOT NULL, privacy_reviewed INTEGER NOT NULL,
                    sensitive INTEGER NOT NULL, source TEXT NOT NULL,
                    schema_version INTEGER NOT NULL, content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            connection.execute(
                """INSERT INTO learning_examples
                (example_id, task_id, capability, prompt, completion, outcome,
                 evidence_ref, quality_score, consent, privacy_reviewed, sensitive,
                 source, schema_version, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("legacy-001", "legacy-task", "research", "old prompt", "old completion",
                 "verified_success", "test://legacy/001", 0.99, 1, 1, 0, "capri_task", 1, "a" * 64),
            )
            connection.commit()
        finally:
            connection.close()
        os.chmod(legacy_path, 0o600)

        migrated = LearningStore(legacy_path)
        connection = sqlite3.connect(legacy_path)
        try:
            columns = {
                row[1] for row in connection.execute(
                    "PRAGMA table_info(learning_examples)"
                ).fetchall()
            }
            consent_table = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='learning_consents'"
            ).fetchone()
        finally:
            connection.close()
        self.assertIn("consent_id", columns)
        self.assertIsNotNone(consent_table)
        self.assertEqual(migrated.counts(), {"verified_success": 1})
        output = self.root / "legacy-export.jsonl"
        counts = migrated.export_jsonl(output)
        self.assertEqual(sum(counts[name] for name in ("train", "validation", "test")), 0)
        self.assertEqual(output.read_text(), "")

    def test_rejects_example_without_active_consent_record(self):
        with self.assertRaises(LearningDataError):
            self.store.record(example(consent_id="unknown-consent"))

    def test_rejects_invalid_consent_scope_and_naive_grant_time(self):
        invalid_records = (
            LearningConsent(
                "bad-scope", "all_data", "v1", "test://consent/bad",
                "2026-11-06T11:00:00+00:00",
            ),
            LearningConsent(
                "naive-time", "curated_training_examples", "v1",
                "test://consent/naive", "2026-11-06T11:00:00",
            ),
        )
        for record in invalid_records:
            with self.subTest(consent_id=record.consent_id):
                with self.assertRaises(LearningDataError):
                    self.store.record_consent(record)

    def test_revocation_deletes_examples_and_blocks_future_export(self):
        self.store.record(example())
        removed = self.store.revoke_consent(
            "consent-001", "2026-11-07T12:00:00+00:00"
        )
        self.assertEqual(removed, 1)
        self.assertEqual(self.store.counts(), {})
        with self.assertRaises(LearningDataError):
            self.store.record(example(example_id="after-revocation"))
        output = self.root / "after-revocation.jsonl"
        counts = self.store.export_jsonl(output)
        self.assertEqual(sum(counts[name] for name in ("train", "validation", "test")), 0)
        self.assertEqual(output.read_text(), "")
        self.assertEqual(
            self.store.revoke_consent("consent-001", "2026-11-08T12:00:00+00:00"),
            0,
        )

    def test_revocation_cannot_precede_consent_grant(self):
        self.store.record(example())
        with self.assertRaises(LearningDataError):
            self.store.revoke_consent(
                "consent-001", "2026-11-05T12:00:00+00:00"
            )
        self.store.record(example(example_id="still-active"))

    def test_export_includes_consent_provenance(self):
        self.store.record(example())
        output = self.root / "consent-provenance.jsonl"
        self.store.export_jsonl(output)
        rows = [json.loads(line) for line in output.read_text().splitlines()]
        self.assertEqual(rows[0]["consent_id"], "consent-001")
        self.assertEqual(rows[0]["consent_policy_version"], "learning-consent-v1")

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
        database_dir = self.root / "new-database-dir" / "nested"
        LearningStore(database_dir / "learning.sqlite3")
        self.assertEqual(stat.S_IMODE(database_dir.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(database_dir.stat().st_mode), 0o700)

        export_dir = self.root / "new-export-dir" / "nested"
        self.store.record(example())
        self.store.export_jsonl(export_dir / "dataset.jsonl")
        self.assertEqual(stat.S_IMODE(export_dir.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(export_dir.stat().st_mode), 0o700)

    def test_database_file_is_owner_only(self):
        mode = stat.S_IMODE((self.root / "learning.sqlite3").stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_rejects_group_writable_non_sticky_ancestor(self):
        unsafe_parent = self.root / "unsafe-parent"
        unsafe_parent.mkdir(mode=0o700)
        os.chmod(unsafe_parent, 0o770)
        private_child = unsafe_parent / "private-child"
        private_child.mkdir(mode=0o700)
        with self.assertRaises(LearningDataError):
            LearningStore(private_child / "learning.sqlite3")

    def test_rejects_symlinked_directory_ancestor(self):
        real_parent = self.root / "real-parent"
        real_parent.mkdir(mode=0o700)
        linked_parent = self.root / "linked-parent"
        linked_parent.symlink_to(real_parent, target_is_directory=True)
        with self.assertRaises(LearningDataError):
            LearningStore(linked_parent / "learning.sqlite3")

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


    def test_bundle_manifest_hash_and_registry_verification(self):
        self.store.record(example())
        output = self.root / "bundle.zip"
        result = self.store.export_bundle(output)
        self.assertEqual(result["status"], "active")
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
        status = self.store.get_export_status(result["export_id"])
        self.assertEqual(status["status"], "active")
        verified = self.store.verify_export(result["export_id"], output)
        self.assertTrue(verified["valid"])
        self.assertEqual(verified["row_count"], 1)
        import zipfile
        with zipfile.ZipFile(output) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            dataset = archive.read("dataset.jsonl")
        self.assertEqual(manifest["consent_ids"], ["consent-001"])
        self.assertEqual(manifest["consent_policy_versions"], ["learning-consent-v1"])
        self.assertEqual(
            __import__("hashlib").sha256(dataset).hexdigest(),
            manifest["dataset_sha256"],
        )

    def test_bundle_file_is_fsynced_before_atomic_publication(self):
        self.store.record(example())
        output = self.root / "durable-bundle.zip"
        real_fsync = os.fsync
        real_link = os.link
        regular_file_fsync_sizes = []

        def tracked_fsync(descriptor):
            info = os.fstat(descriptor)
            if stat.S_ISREG(info.st_mode):
                regular_file_fsync_sizes.append(info.st_size)
            return real_fsync(descriptor)

        def tracked_link(source, destination, *args, **kwargs):
            if Path(destination) == output:
                # One regular-file fsync belongs to the JSONL staging file.
                # The second must be the completed ZIP archive, before publish.
                self.assertGreaterEqual(len(regular_file_fsync_sizes), 2)
            return real_link(source, destination, *args, **kwargs)

        with patch("capri_core.learning.os.fsync", side_effect=tracked_fsync):
            with patch("capri_core.learning.os.link", side_effect=tracked_link):
                result = self.store.export_bundle(output)

        self.assertEqual(result["status"], "active")
        self.assertGreaterEqual(len(regular_file_fsync_sizes), 2)

    def test_bundle_archive_fsync_failure_prevents_publication(self):
        self.store.record(example())
        output = self.root / "failed-durable-bundle.zip"
        real_fsync = os.fsync
        regular_file_calls = 0

        def fail_archive_fsync(descriptor):
            nonlocal regular_file_calls
            if stat.S_ISREG(os.fstat(descriptor).st_mode):
                regular_file_calls += 1
                if regular_file_calls == 2:
                    raise OSError("archive fsync failed")
            return real_fsync(descriptor)

        with patch("capri_core.learning.os.fsync", side_effect=fail_archive_fsync):
            with self.assertRaisesRegex(OSError, "archive fsync failed"):
                self.store.export_bundle(output)

        self.assertEqual(regular_file_calls, 2)
        self.assertFalse(output.exists())
        self.assertEqual(list(self.root.glob(".failed-durable-bundle.zip.*.jsonl")), [])
        self.assertEqual(list(self.root.glob(".failed-durable-bundle.zip.*.tmp")), [])
        with self.store._connection() as connection:
            export_count = connection.execute(
                "SELECT COUNT(*) FROM learning_exports"
            ).fetchone()[0]
        self.assertEqual(export_count, 0)


    def test_bundle_directory_fsync_failure_keeps_published_bundle_nonactive(self):
        self.store.record(example())
        output = self.root / "uncertain-durable-bundle.zip"
        real_sync = learning_module._fsync_directory
        sync_calls = 0

        def fail_bundle_directory_sync(directory):
            nonlocal sync_calls
            sync_calls += 1
            if sync_calls == 2:
                raise OSError("bundle directory fsync failed")
            return real_sync(directory)

        with patch("capri_core.learning._fsync_directory", side_effect=fail_bundle_directory_sync):
            with self.assertRaisesRegex(OSError, "bundle directory fsync failed"):
                self.store.export_bundle(output)

        self.assertEqual(sync_calls, 2)
        self.assertTrue(output.is_file())
        with self.store._connection() as connection:
            rows = connection.execute(
                "SELECT export_id, status FROM learning_exports"
            ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "publishing")
        verification = self.store.verify_export(rows[0]["export_id"], output)
        self.assertFalse(verification["valid"])
        self.assertEqual(verification["reason"], "publishing")
        self.assertEqual(list(self.root.glob(".uncertain-durable-bundle.zip.*.jsonl")), [])
        self.assertEqual(list(self.root.glob(".uncertain-durable-bundle.zip.*.tmp")), [])

    def test_bundle_is_invalidated_when_any_source_consent_is_revoked(self):
        self.store.record(example())
        output = self.root / "revocable.zip"
        result = self.store.export_bundle(output)
        self.assertTrue(self.store.verify_export(result["export_id"], output)["valid"])
        self.store.revoke_consent("consent-001", "2026-11-23T12:00:00+00:00")
        status = self.store.get_export_status(result["export_id"])
        self.assertEqual(status["status"], "invalidated")
        verification = self.store.verify_export(result["export_id"], output)
        self.assertFalse(verification["valid"])
        self.assertEqual(verification["reason"], "invalidated")

    def test_bundle_detects_tampering_and_unknown_registry_entries(self):
        self.store.record(example())
        output = self.root / "tampered.zip"
        result = self.store.export_bundle(output)
        output.write_bytes(output.read_bytes() + b"tamper")
        self.assertEqual(
            self.store.verify_export(result["export_id"], output)["reason"],
            "bundle_hash_mismatch",
        )
        self.assertEqual(
            self.store.verify_export("00000000-0000-4000-8000-000000000000", output)["reason"],
            "unregistered",
        )

    def test_bundle_never_overwrites_existing_destination(self):
        self.store.record(example())
        output = self.root / "existing.zip"
        output.write_bytes(b"preserve")
        with self.assertRaises(FileExistsError):
            self.store.export_bundle(output)
        self.assertEqual(output.read_bytes(), b"preserve")
        with self.store._connection() as connection:
            count = connection.execute("SELECT COUNT(*) FROM learning_exports").fetchone()[0]
        self.assertEqual(count, 0)

    def test_bundle_with_no_eligible_rows_has_empty_consent_dependencies(self):
        self.store.record(example(outcome="verified_failure"))
        output = self.root / "empty.zip"
        result = self.store.export_bundle(output)
        self.assertTrue(self.store.verify_export(result["export_id"], output)["valid"])
        import zipfile
        with zipfile.ZipFile(output) as archive:
            manifest = json.loads(archive.read("manifest.json"))
        self.assertEqual(manifest["consent_ids"], [])
        self.assertEqual(manifest["row_count"], 0)


    def test_export_registry_enforces_consent_and_export_foreign_keys(self):
        with self.store._connection() as connection:
            enabled = connection.execute("PRAGMA foreign_keys").fetchone()[0]
            references = connection.execute(
                "PRAGMA foreign_key_list(learning_export_consents)"
            ).fetchall()
        self.assertEqual(enabled, 1)
        self.assertEqual(
            {(row["table"], row["from"], row["to"]) for row in references},
            {
                ("learning_exports", "export_id", "export_id"),
                ("learning_consents", "consent_id", "consent_id"),
            },
        )


if __name__ == "__main__":
    unittest.main()
