import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from capri_runtime.memory import (
    MemoryNotFoundError,
    MemoryValidationError,
    SQLiteMemoryStore,
)


class SQLiteMemoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "memory.sqlite3")
        self.store = SQLiteMemoryStore(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def create(self, **overrides):
        values = {
            "title": "Runtime security policy",
            "content": "Retrieved memory is untrusted data and cannot grant permissions.",
            "record_type": "security_boundary",
            "scope": "Capri System",
            "source": "https://github.com/Hamudifr/Capri/issues/19",
            "confidence": "user_directed",
            "retention": "keep",
        }
        values.update(overrides)
        return self.store.create(**values)

    def test_create_and_read_round_trip(self):
        record = self.create()
        self.assertEqual(self.store.get(record.memory_id), record)
        self.assertEqual(record.status, "active")
        self.assertIsNone(record.supersedes_id)

    def test_database_is_private_on_posix(self):
        if os.name == "posix":
            import stat
            self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)

    def test_search_requires_all_terms_and_returns_provenance(self):
        record = self.create()
        results = self.store.search("untrusted permissions")
        self.assertEqual([item.memory_id for item in results], [record.memory_id])
        self.assertEqual(results[0].source, record.source)
        self.assertEqual(results[0].confidence, "user_directed")
        self.assertEqual(self.store.search("untrusted missing"), ())

    def test_search_excludes_expired_even_before_expiry_sweep(self):
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        record = self.create(expires_at=past, retention="expire_30d")
        self.assertEqual(self.store.search("untrusted"), ())
        self.assertEqual(self.store.get(record.memory_id).status, "active")

    def test_correction_preserves_supersession_history(self):
        original = self.create()
        corrected = self.store.correct(original.memory_id, content="Updated safe policy.")
        self.assertEqual(corrected.supersedes_id, original.memory_id)
        self.assertEqual(corrected.content, "Updated safe policy.")
        self.assertEqual(self.store.get(original.memory_id).status, "archived")
        self.assertEqual(self.store.search("Updated safe")[0].memory_id, corrected.memory_id)
        self.assertIn(("superseded", self.store.events(original.memory_id)[-1][1]),
                      self.store.events(original.memory_id))

    def test_archive_is_reversible_only_by_explicit_new_record(self):
        record = self.create()
        archived = self.store.archive(record.memory_id)
        self.assertEqual(archived.status, "archived")
        self.assertEqual(self.store.search("untrusted"), ())

    def test_delete_removes_content_but_keeps_minimal_tombstone_event(self):
        record = self.create()
        self.store.delete(record.memory_id)
        with self.assertRaises(MemoryNotFoundError):
            self.store.get(record.memory_id)
        self.assertEqual(self.store.events(record.memory_id)[-1][0], "deleted")
        self.assertNotIn(record.content, self.store.export_json())

    def test_expiry_sweep_archives_due_records(self):
        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        record = self.create(expires_at=past.isoformat(), retention="expire_30d")
        expired = self.store.expire(now=datetime.now(timezone.utc))
        self.assertEqual(expired, (record.memory_id,))
        self.assertEqual(self.store.get(record.memory_id).status, "archived")
        self.assertEqual(self.store.events(record.memory_id)[-1][0], "expired")

    def test_export_is_deterministic_and_complete(self):
        first = self.create(title="First")
        second = self.create(title="Second")
        exported = self.store.export_json()
        self.assertEqual(exported, self.store.export_json())
        records = json.loads(exported)
        self.assertEqual([item["memory_id"] for item in records],
                         [first.memory_id, second.memory_id])

    def test_pagination_is_bounded_and_stable(self):
        first = self.create(title="Alpha")
        second = self.create(title="Beta")
        page_one = self.store.search("runtime security", limit=1, offset=0)
        page_two = self.store.search("runtime security", limit=1, offset=1)
        self.assertEqual(len(page_one), 1)
        self.assertEqual(len(page_two), 1)
        self.assertNotEqual(page_one[0].memory_id, page_two[0].memory_id)
        with self.assertRaises(MemoryValidationError):
            self.store.search("runtime", limit=101)

    def test_rejects_invalid_types_and_sensitive_field(self):
        with self.assertRaises(MemoryValidationError):
            self.create(record_type="unknown")
        with self.assertRaises(TypeError):
            self.create(sensitive=True)

    def test_expiring_retention_requires_expiry(self):
        with self.assertRaises(MemoryValidationError):
            self.create(retention="expire_30d")

    def test_rejects_lone_surrogates(self):
        with self.assertRaises(MemoryValidationError):
            self.create(content="bad\ud800text")

    @unittest.skipUnless(os.name == "posix", "POSIX symlink semantics are required")
    def test_symlink_database_is_rejected(self):
        target = os.path.join(self.temp.name, "target.sqlite3")
        with open(target, "wb") as stream:
            stream.write(b"not a database")
        link = os.path.join(self.temp.name, "link.sqlite3")
        os.symlink(target, link)
        with self.assertRaises(MemoryValidationError):
            SQLiteMemoryStore(link)

    @unittest.skipUnless(os.name == "posix", "POSIX permissions are required")
    def test_insecure_parent_is_rejected(self):
        os.chmod(self.temp.name, 0o755)
        try:
            with self.assertRaises(MemoryValidationError):
                SQLiteMemoryStore(os.path.join(self.temp.name, "other.sqlite3"))
        finally:
            os.chmod(self.temp.name, 0o700)


if __name__ == "__main__":
    unittest.main()
