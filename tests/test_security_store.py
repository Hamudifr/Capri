import hashlib
import json
import os
import stat
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from capri_runtime import (
    ApprovalGrant,
    ApprovalRequiredError,
    AuditEvent,
    ExecutionContext,
    SQLiteSecurityStore,
    ToolExecutor,
    ToolRegistry,
    ToolSpec,
    ToolValidationError,
)


SCHEMA = {
    "type": "object",
    "properties": {"item": {"type": "string", "minLength": 1, "maxLength": 32}},
    "required": ["item"],
}


def argument_digest(arguments):
    raw = json.dumps(
        arguments, ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class SQLiteSecurityStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "security.sqlite3")
        self.now = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.temp.cleanup()

    def grant(self, grant_id="grant-1"):
        args = {"item": "item-1"}
        return ApprovalGrant(
            grant_id,
            "principal-1",
            "delete_item",
            argument_digest(args),
            (self.now + timedelta(minutes=5)).isoformat(),
        )

    def test_backup_is_consistent_private_and_restores_replay_state(self):
        store = SQLiteSecurityStore(self.path)
        event = AuditEvent(
            "backup-event", self.now.isoformat(), "principal-1", "delete_item",
            "a" * 64, "succeeded", None,
        )
        store.write(event)
        grant = self.grant("backup-grant")
        self.assertTrue(store.consume(grant, self.now))
        backup_path = os.path.join(self.temp.name, "backup.sqlite3")
        self.assertEqual(store.backup_to(backup_path), backup_path)
        self.assertTrue(os.path.isfile(backup_path))
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(os.stat(backup_path).st_mode), 0o600)
        restored = SQLiteSecurityStore(backup_path)
        self.assertEqual(restored.integrity_check(), "ok")
        self.assertIn(event, restored.events())
        self.assertFalse(restored.consume(grant, self.now))

    def test_backup_refuses_existing_symlink_and_live_database_destinations(self):
        store = SQLiteSecurityStore(self.path)
        with self.assertRaises(ToolValidationError):
            store.backup_to(self.path)
        existing = os.path.join(self.temp.name, "existing.sqlite3")
        with open(existing, "wb") as stream:
            stream.write(b"keep")
        with self.assertRaises(ToolValidationError):
            store.backup_to(existing)
        link = os.path.join(self.temp.name, "link.sqlite3")
        os.symlink(existing, link)
        with self.assertRaises(ToolValidationError):
            store.backup_to(link)
        with open(existing, "rb") as stream:
            self.assertEqual(stream.read(), b"keep")

    @unittest.skipUnless(os.name == "posix", "POSIX filesystem permissions are required")
    def test_backup_rejects_non_private_destination_directory(self):
        store = SQLiteSecurityStore(self.path)
        destination_dir = os.path.join(self.temp.name, "public")
        os.mkdir(destination_dir, 0o755)
        with self.assertRaises(ToolValidationError):
            store.backup_to(os.path.join(destination_dir, "backup.sqlite3"))

    def test_database_is_private_and_integrity_check_passes(self):
        store = SQLiteSecurityStore(self.path)
        self.assertEqual(store.integrity_check(), "ok")
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)

    def test_redacted_audit_events_persist_across_store_instances(self):
        event = AuditEvent(
            "event-1", self.now.isoformat(), "principal-1", "search",
            "a" * 64, "succeeded", None,
        )
        SQLiteSecurityStore(self.path).write(event)
        reopened = SQLiteSecurityStore(self.path)
        self.assertEqual(reopened.events(), (event,))
        self.assertFalse(hasattr(reopened.events()[0], "arguments"))
        self.assertFalse(hasattr(reopened.events()[0], "result"))

    def test_approval_replay_protection_persists_across_store_instances(self):
        grant = self.grant()
        first = SQLiteSecurityStore(self.path)
        second = SQLiteSecurityStore(self.path)
        self.assertTrue(first.consume(grant, self.now))
        self.assertFalse(second.consume(grant, self.now))

    def test_concurrent_consumption_has_exactly_one_winner_across_connections(self):
        grant = self.grant()
        stores = [SQLiteSecurityStore(self.path) for _ in range(6)]
        with ThreadPoolExecutor(max_workers=6) as pool:
            outcomes = list(pool.map(lambda store: store.consume(grant, self.now), stores))
        self.assertEqual(sum(outcomes), 1)

    def test_expired_approval_is_not_consumed(self):
        grant = self.grant()
        expired = ApprovalGrant(
            grant.grant_id, grant.principal_id, grant.tool_name, grant.argument_digest,
            (self.now - timedelta(seconds=1)).isoformat(),
        )
        self.assertFalse(SQLiteSecurityStore(self.path).consume(expired, self.now))

    def test_executor_uses_durable_approval_store_across_restarts(self):
        calls = []
        registry = ToolRegistry()
        registry.register(
            ToolSpec("delete_item", "tools:delete", SCHEMA, requires_approval=True),
            lambda args: calls.append(args) or {"deleted": True},
        )
        grant = self.grant()
        context = ExecutionContext("principal-1", frozenset({"tools:delete"}), (grant,))
        first_store = SQLiteSecurityStore(self.path)
        first_executor = ToolExecutor(
            registry, first_store, approval_store=first_store, clock=lambda: self.now
        )
        self.assertEqual(first_executor.execute("delete_item", {"item": "item-1"}, context), {"deleted": True})

        second_store = SQLiteSecurityStore(self.path)
        second_executor = ToolExecutor(
            registry, second_store, approval_store=second_store, clock=lambda: self.now
        )
        with self.assertRaises(ApprovalRequiredError):
            second_executor.execute("delete_item", {"item": "item-1"}, context)
        self.assertEqual(len(calls), 1)
        self.assertEqual([event.status for event in second_store.events()], ["started", "succeeded"])

    @unittest.skipUnless(os.name == "posix", "POSIX filesystem permissions are required")
    def test_insecure_parent_directory_is_rejected(self):
        os.chmod(self.temp.name, 0o755)
        with self.assertRaises(ToolValidationError):
            SQLiteSecurityStore(self.path)

    @unittest.skipUnless(os.name == "posix", "POSIX symlink semantics are required")
    def test_symlink_database_path_is_rejected(self):
        target = os.path.join(self.temp.name, "target.sqlite3")
        with open(target, "wb") as stream:
            stream.write(b"not a database")
        link = os.path.join(self.temp.name, "linked.sqlite3")
        os.symlink(target, link)
        with self.assertRaises(ToolValidationError):
            SQLiteSecurityStore(link)

    @unittest.skipUnless(os.name == "posix", "POSIX filesystem permissions are required")
    def test_parent_directory_privacy_is_rechecked_on_each_connection(self):
        store = SQLiteSecurityStore(self.path)
        os.chmod(self.temp.name, 0o755)
        try:
            with self.assertRaises(ToolValidationError):
                store.integrity_check()
        finally:
            os.chmod(self.temp.name, 0o700)

    @unittest.skipUnless(
        os.name == "posix" and hasattr(os, "link"),
        "POSIX hard-link support is required",
    )
    def test_database_hard_link_alias_is_rejected(self):
        SQLiteSecurityStore(self.path)
        alias = os.path.join(self.temp.name, "alias.sqlite3")
        os.link(self.path, alias)
        with self.assertRaises(ToolValidationError):
            SQLiteSecurityStore(alias)

    @unittest.skipUnless(os.name == "posix", "POSIX symlink semantics are required")
    def test_database_symlink_substitution_is_rejected_on_read(self):
        store = SQLiteSecurityStore(self.path)
        target = os.path.join(self.temp.name, "target.sqlite3")
        with open(target, "wb") as stream:
            stream.write(b"not a database")
        os.unlink(self.path)
        os.symlink(target, self.path)
        with self.assertRaises(ToolValidationError):
            store.integrity_check()

    def test_missing_parent_directory_is_rejected(self):
        missing = os.path.join(self.temp.name, "missing", "security.sqlite3")
        with self.assertRaises(ToolValidationError):
            SQLiteSecurityStore(missing)


if __name__ == "__main__":
    unittest.main()
