import hashlib
import json
import os
import sqlite3
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

    def test_enriched_audit_metadata_roundtrips_with_digest_binding(self):
        store = SQLiteSecurityStore(self.path)
        metadata = {
            "event_type": "worker.reservation.committed",
            "worker_id": "worker-1",
            "reservation_token_sha256": "a" * 64,
            "observed_in_flight": 1,
        }
        metadata_json = json.dumps(
            metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        )
        digest = hashlib.sha256(metadata_json.encode("utf-8")).hexdigest()
        event = AuditEvent(
            "worker-event-1", self.now.isoformat(), "alice",
            "worker.reservation.committed", digest, "success", None,
            "worker", "worker-1", "task-1", metadata_json,
        )
        store.write(event)
        self.assertEqual(store.events(), (event,))

    def test_enriched_audit_metadata_rejects_digest_mismatch(self):
        store = SQLiteSecurityStore(self.path)
        metadata_json = json.dumps(
            {"event_type": "worker.heartbeat"}, sort_keys=True, separators=(",", ":"),
        )
        event = AuditEvent(
            "worker-event-2", self.now.isoformat(), "host",
            "worker.heartbeat", "0" * 64, "success", None,
            "worker", "worker-1", None, metadata_json,
        )
        with self.assertRaises(ToolValidationError):
            store.write(event)
        self.assertEqual(store.events(), ())

    def test_audit_events_are_append_only(self):
        store = SQLiteSecurityStore(self.path)
        event = AuditEvent(
            "audit-immutable", self.now.isoformat(), "principal-1",
            "search", argument_digest({"item": "item-1"}), "succeeded",
        )
        store.write(event)
        for statement in (
            "UPDATE audit_events SET status='tampered' WHERE event_id='audit-immutable'",
            "DELETE FROM audit_events WHERE event_id='audit-immutable'",
        ):
            connection = sqlite3.connect(self.path)
            try:
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(statement)
            finally:
                connection.close()
        self.assertEqual(store.events(), (event,))

    def test_legacy_audit_schema_is_migrated_with_resource_columns(self):
        connection = sqlite3.connect(self.path)
        try:
            connection.execute(
                """CREATE TABLE audit_events (
                    event_id TEXT PRIMARY KEY, timestamp TEXT NOT NULL,
                    principal_id TEXT NOT NULL, tool_name TEXT NOT NULL,
                    argument_digest TEXT NOT NULL, status TEXT NOT NULL,
                    error_code TEXT
                )"""
            )
            connection.commit()
        finally:
            connection.close()
        store = SQLiteSecurityStore(self.path)
        connection = sqlite3.connect(self.path)
        try:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(audit_events)")}
        finally:
            connection.close()
        self.assertTrue({"resource_type", "resource_id", "task_id", "metadata_json"}.issubset(columns))
        self.assertEqual(store.events(), ())

    def grant(self, grant_id="grant-1"):
        args = {"item": "item-1"}
        return ApprovalGrant(
            grant_id,
            "principal-1",
            "delete_item",
            argument_digest(args),
            (self.now + timedelta(minutes=5)).isoformat(),
        )

    def _store_with_approval_challenge(
        self, *, status="approved", operation_id="session-1:call-1",
        grant_operation_id="session-1:call-1", created_at=None, expires_at=None,
        grant_json=None,
    ):
        store = SQLiteSecurityStore(self.path)
        created_at = created_at or self.now.isoformat()
        expires_at = expires_at or (self.now + timedelta(minutes=5)).isoformat()
        connection = sqlite3.connect(self.path)
        try:
            connection.execute(
                """CREATE TABLE approval_challenges (
                    challenge_id TEXT PRIMARY KEY,
                    operation_id TEXT NOT NULL UNIQUE,
                    principal_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    argument_digest TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected','expired')),
                    approver_id TEXT,
                    grant_json TEXT,
                    CHECK(
                        (status='approved' AND approver_id IS NOT NULL AND grant_json IS NOT NULL)
                        OR (status!='approved' AND grant_json IS NULL)
                    )
                )"""
            )
            if grant_json is None and status == "approved":
                grant = {
                    "grant_id": "challenge-grant-1",
                    "principal_id": "principal-1",
                    "tool_name": "delete_item",
                    "argument_digest": "a" * 64,
                    "expires_at": expires_at,
                    "signature": "b" * 64,
                    "key_id": "active",
                }
                if grant_operation_id is not None:
                    grant["operation_id"] = grant_operation_id
                grant_json = json.dumps(grant, sort_keys=True, separators=(",", ":"))
            connection.execute(
                """INSERT INTO approval_challenges
                (challenge_id, operation_id, principal_id, tool_name, argument_digest,
                 created_at, expires_at, status, approver_id, grant_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "challenge-1", operation_id, "principal-1", "delete_item",
                    "a" * 64, created_at, expires_at, status,
                    "reviewer-1" if status == "approved" else None, grant_json,
                ),
            )
            connection.commit()
        finally:
            connection.close()
        return store

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

    def test_audit_write_rejects_surrogate_metadata(self):
        store = SQLiteSecurityStore(self.path)
        event = AuditEvent(
            "bad" + chr(0xD800), self.now.isoformat(), "principal-1",
            "search", "a" * 64, "succeeded", None,
        )
        with self.assertRaises(ToolValidationError):
            store.write(event)

    def test_approval_consumption_rejects_surrogate_identifiers(self):
        store = SQLiteSecurityStore(self.path)
        grant = ApprovalGrant(
            "grant-" + chr(0xD800), "principal-1", "delete_item",
            argument_digest({"item": "item-1"}),
            (self.now + timedelta(minutes=5)).isoformat(),
        )
        self.assertFalse(store.consume(grant, self.now))

    def test_executor_uses_durable_approval_store_across_restarts(self):
        calls = []
        registry = ToolRegistry()
        registry.register(
            ToolSpec("delete_item", "tools:delete", SCHEMA, requires_approval=True),
            lambda args: calls.append(args) or {"deleted": True},
        )
        grant = ApprovalGrant(
            "grant-1", "principal-1", "delete_item", argument_digest({"item": "item-1"}),
            (self.now + timedelta(minutes=5)).isoformat(),
            operation_id="session-1:durable-delete",
        )
        context = ExecutionContext(
            "principal-1", frozenset({"tools:delete"}), (grant,),
            operation_id="session-1:durable-delete",
        )
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

    @unittest.skipUnless(os.name == "posix", "POSIX hard-link semantics are required")
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


    def test_backup_rejects_semantically_invalid_audit_rows(self):
        store = SQLiteSecurityStore(self.path)
        store.write(AuditEvent(
            "corrupt-audit", self.now.isoformat(), "principal-1", "search",
            "a" * 64, "succeeded", None,
        ))
        connection = sqlite3.connect(self.path)
        try:
            connection.execute("DROP TRIGGER audit_events_immutable_update")
            connection.execute(
                "UPDATE audit_events SET argument_digest = ? WHERE event_id = ?",
                ("not-a-sha256-digest", "corrupt-audit"),
            )
            connection.commit()
        finally:
            connection.close()

        destination = os.path.join(self.temp.name, "invalid-audit-backup.sqlite3")
        with self.assertRaises(ToolValidationError):
            store.backup_to(destination)
        self.assertFalse(os.path.lexists(destination))

    def test_backup_rejects_semantically_invalid_approval_replay_rows(self):
        store = SQLiteSecurityStore(self.path)
        grant = self.grant("corrupt-approval")
        self.assertTrue(store.consume(grant, self.now))
        connection = sqlite3.connect(self.path)
        try:
            connection.execute(
                "UPDATE consumed_approvals SET tool_name = ? WHERE grant_id = ?",
                ("Invalid Tool Name", "corrupt-approval"),
            )
            connection.commit()
        finally:
            connection.close()

        destination = os.path.join(self.temp.name, "invalid-approval-backup.sqlite3")
        with self.assertRaises(ToolValidationError):
            store.backup_to(destination)
        self.assertFalse(os.path.lexists(destination))

    def test_backup_preserves_valid_operation_bound_approval_challenge(self):
        store = self._store_with_approval_challenge()
        destination = os.path.join(self.temp.name, "valid-challenge-backup.sqlite3")
        store.backup_to(destination)
        connection = sqlite3.connect(destination)
        try:
            row = connection.execute(
                "SELECT operation_id, status, grant_json FROM approval_challenges"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(row[0], "session-1:call-1")
        self.assertEqual(row[1], "approved")
        self.assertEqual(json.loads(row[2])["operation_id"], "session-1:call-1")

    def test_backup_rejects_approval_challenge_grant_for_another_operation(self):
        store = self._store_with_approval_challenge(
            grant_operation_id="session-1:call-2"
        )
        destination = os.path.join(self.temp.name, "wrong-operation-challenge.sqlite3")
        with self.assertRaises(ToolValidationError):
            store.backup_to(destination)
        self.assertFalse(os.path.lexists(destination))

    def test_backup_rejects_approval_challenge_expiry_before_creation(self):
        store = self._store_with_approval_challenge(
            status="pending",
            expires_at=(self.now - timedelta(seconds=1)).isoformat(),
        )
        destination = os.path.join(self.temp.name, "invalid-challenge-time.sqlite3")
        with self.assertRaises(ToolValidationError):
            store.backup_to(destination)
        self.assertFalse(os.path.lexists(destination))

    def test_backup_rejects_malformed_approval_challenge_grant_json(self):
        store = self._store_with_approval_challenge(grant_json="{not-json")
        destination = os.path.join(self.temp.name, "invalid-challenge-json.sqlite3")
        with self.assertRaises(ToolValidationError):
            store.backup_to(destination)
        self.assertFalse(os.path.lexists(destination))

    def test_backup_preserves_legacy_challenge_grant_for_migration(self):
        store = self._store_with_approval_challenge(grant_operation_id=None)
        destination = os.path.join(self.temp.name, "legacy-challenge-backup.sqlite3")
        store.backup_to(destination)
        connection = sqlite3.connect(destination)
        try:
            row = connection.execute(
                "SELECT grant_json FROM approval_challenges WHERE challenge_id='challenge-1'"
            ).fetchone()
        finally:
            connection.close()
        self.assertNotIn("operation_id", json.loads(row[0]))

    def test_backup_rejects_approval_expiry_before_consumption(self):
        store = SQLiteSecurityStore(self.path)
        grant = self.grant("expired-order")
        self.assertTrue(store.consume(grant, self.now))
        connection = sqlite3.connect(self.path)
        try:
            connection.execute(
                "UPDATE consumed_approvals SET expires_at = ? WHERE grant_id = ?",
                ((self.now - timedelta(seconds=1)).isoformat(), "expired-order"),
            )
            connection.commit()
        finally:
            connection.close()

        destination = os.path.join(self.temp.name, "invalid-expiry-backup.sqlite3")
        with self.assertRaises(ToolValidationError):
            store.backup_to(destination)
        self.assertFalse(os.path.lexists(destination))


if __name__ == "__main__":
    unittest.main()
