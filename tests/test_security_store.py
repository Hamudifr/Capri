import hashlib
import json
import os
import sqlite3
import stat
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from capri_runtime import (
    AuditEvent,
    SQLiteSecurityStore,
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

    def test_worker_lifecycle_operation_markers_and_reconciliation_ack(self):
        store = SQLiteSecurityStore(self.path)
        self.assertFalse(store.worker_lifecycle_reconciliation_required())
        with self.assertRaises(ToolValidationError):
            store.finish_worker_lifecycle_operation()

        store.begin_worker_lifecycle_operation()
        store.begin_worker_lifecycle_operation()
        self.assertTrue(store.worker_lifecycle_reconciliation_required())
        self.assertTrue(
            store.acknowledge_worker_lifecycle_reconciliation(
                "Supervisor reconciled worker registry and host-observed load after restart",
            )
        )
        self.assertFalse(store.worker_lifecycle_reconciliation_required())
        event = store.events()[-1]
        self.assertEqual(event.tool_name, "worker.reconciliation.acknowledged")
        self.assertEqual(event.resource_type, "worker_registry")
        self.assertEqual(event.resource_id, "registry")
        self.assertEqual(
            json.loads(event.metadata_json)["pending_operations"], 2,
        )
        self.assertFalse(
            store.acknowledge_worker_lifecycle_reconciliation(
                "No pending operation remains",
            )
        )

    def test_expired_worker_reservation_closes_durable_reconciliation_state(self):
        store = SQLiteSecurityStore(self.path)
        token_hash = "b" * 64
        for event_type in (
            "worker.reservation.created",
            "worker.reservation.expired",
        ):
            metadata_json = json.dumps(
                {
                    "event_type": event_type,
                    "worker_id": "worker-1",
                    "reservation_token_sha256": token_hash,
                },
                sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            )
            event = AuditEvent(
                f"worker-{event_type.rsplit('.', 1)[-1]}",
                self.now.isoformat(),
                "alice",
                event_type,
                hashlib.sha256(metadata_json.encode("utf-8")).hexdigest(),
                "success",
                None,
                "worker",
                "worker-1",
                "task-1",
                metadata_json,
            )
            store.write(event)
            if event_type.endswith(".created"):
                self.assertTrue(store.worker_lifecycle_reconciliation_required())
        self.assertFalse(store.worker_lifecycle_reconciliation_required())

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

    def test_legacy_audit_rows_migrate_under_existing_immutable_trigger(self):
        connection = sqlite3.connect(self.path)
        try:
            connection.execute(
                """CREATE TABLE audit_events (
                    event_id TEXT PRIMARY KEY, timestamp TEXT NOT NULL,
                    principal_id TEXT NOT NULL, tool_name TEXT NOT NULL,
                    argument_digest TEXT NOT NULL, status TEXT NOT NULL,
                    error_code TEXT, resource_type TEXT, resource_id TEXT,
                    task_id TEXT, metadata_json TEXT
                )"""
            )
            event = AuditEvent(
                "legacy-chain-event", self.now.isoformat(), "principal-1", "search",
                argument_digest({"item": "legacy"}), "succeeded", None,
            )
            connection.execute(
                """INSERT INTO audit_events
                (event_id, timestamp, principal_id, tool_name, argument_digest,
                 status, error_code, resource_type, resource_id, task_id, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.event_id, event.timestamp, event.principal_id, event.tool_name,
                    event.argument_digest, event.status, event.error_code,
                    event.resource_type, event.resource_id, event.task_id, event.metadata_json,
                ),
            )
            connection.execute(
                """CREATE TRIGGER audit_events_immutable_update
                BEFORE UPDATE ON audit_events
                BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END"""
            )
            connection.execute(
                """CREATE TRIGGER audit_events_immutable_delete
                BEFORE DELETE ON audit_events
                BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END"""
            )
            connection.commit()
        finally:
            connection.close()

        store = SQLiteSecurityStore(self.path)
        self.assertEqual(store.events(), (event,))
        self.assertEqual(store.integrity_check(), "ok")
        connection = sqlite3.connect(self.path)
        try:
            row = connection.execute(
                "SELECT sequence, previous_hash, event_hash FROM audit_events WHERE event_id=?",
                (event.event_id,),
            ).fetchone()
            triggers = {
                item[0] for item in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='trigger'"
                )
            }
        finally:
            connection.close()
        self.assertEqual(row[0], 1)
        self.assertEqual(row[1], "0" * 64)
        self.assertIn("audit_events_immutable_update", triggers)
        self.assertIn("audit_events_immutable_delete", triggers)

    def test_lifecycle_audit_chain_is_monotonic_and_detects_event_tampering(self):
        store = SQLiteSecurityStore(self.path)
        first = AuditEvent(
            "chain-event-1", self.now.isoformat(), "principal-1", "search",
            argument_digest({"item": "one"}), "succeeded", None,
        )
        second = AuditEvent(
            "chain-event-2", self.now.isoformat(), "principal-2", "search",
            argument_digest({"item": "two"}), "succeeded", None,
        )
        store.write(first)
        store.write(second)
        connection = sqlite3.connect(self.path)
        try:
            rows = connection.execute(
                "SELECT sequence, previous_hash, event_hash FROM audit_events ORDER BY sequence"
            ).fetchall()
            state = connection.execute(
                "SELECT last_sequence, head_hash FROM audit_chain_state WHERE singleton_id=1"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual([row[0] for row in rows], [1, 2])
        self.assertEqual(rows[1][1], rows[0][2])
        self.assertEqual(state, (2, rows[1][2]))
        self.assertEqual(store.integrity_check(), "ok")

        connection = sqlite3.connect(self.path)
        try:
            connection.execute("DROP TRIGGER audit_events_immutable_update")
            connection.execute(
                "UPDATE audit_events SET status='tampered' WHERE event_id='chain-event-1'"
            )
            connection.execute(
                """CREATE TRIGGER audit_events_immutable_update
                BEFORE UPDATE ON audit_events
                BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END"""
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaisesRegex(ToolValidationError, "chain digest mismatch"):
            store.integrity_check()
        destination = os.path.join(self.temp.name, "tampered-chain-backup.sqlite3")
        with self.assertRaisesRegex(ToolValidationError, "chain digest mismatch"):
            store.backup_to(destination)
        self.assertFalse(os.path.lexists(destination))

    def test_lifecycle_audit_chain_rejects_replaced_noop_immutable_trigger(self):
        store = SQLiteSecurityStore(self.path)
        connection = sqlite3.connect(self.path)
        try:
            connection.execute("DROP TRIGGER audit_events_immutable_update")
            connection.execute(
                """CREATE TRIGGER audit_events_immutable_update
                BEFORE UPDATE ON audit_events BEGIN SELECT 1; END"""
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaisesRegex(ToolValidationError, "trigger definition is invalid"):
            store.integrity_check()

    def test_lifecycle_audit_chain_rejects_non_unique_sequence_index(self):
        store = SQLiteSecurityStore(self.path)
        connection = sqlite3.connect(self.path)
        try:
            connection.execute("DROP INDEX audit_events_sequence_unique")
            connection.execute(
                "CREATE INDEX audit_events_sequence_unique ON audit_events(event_id)"
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaisesRegex(ToolValidationError, "sequence index is not unique"):
            store.integrity_check()

    def test_lifecycle_audit_chain_append_is_atomic_with_event_insert(self):
        store = SQLiteSecurityStore(self.path)
        connection = sqlite3.connect(self.path)
        try:
            connection.execute(
                """CREATE TRIGGER reject_audit_chain_head
                BEFORE UPDATE ON audit_chain_state
                BEGIN SELECT RAISE(ABORT, 'injected chain head failure'); END"""
            )
            connection.commit()
        finally:
            connection.close()
        event = AuditEvent(
            "chain-atomic-failure", self.now.isoformat(), "principal-1", "search",
            argument_digest({"item": "atomic"}), "succeeded", None,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            store.write(event)
        connection = sqlite3.connect(self.path)
        try:
            count = connection.execute(
                "SELECT COUNT(*) FROM audit_events WHERE event_id='chain-atomic-failure'"
            ).fetchone()[0]
            state = connection.execute(
                "SELECT last_sequence, head_hash FROM audit_chain_state WHERE singleton_id=1"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(count, 0)
        self.assertEqual(state, (0, "0" * 64))
        connection = sqlite3.connect(self.path)
        try:
            connection.execute("DROP TRIGGER reject_audit_chain_head")
            connection.commit()
        finally:
            connection.close()
        self.assertEqual(store.integrity_check(), "ok")

    def test_lifecycle_audit_chain_serializes_writers_across_store_instances(self):
        stores = [SQLiteSecurityStore(self.path) for _ in range(4)]

        def append(index):
            event = AuditEvent(
                f"parallel-chain-{index}", self.now.isoformat(), "principal-1", "search",
                argument_digest({"item": str(index)}), "succeeded", None,
            )
            stores[index % len(stores)].write(event)

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(append, range(24)))
        store = SQLiteSecurityStore(self.path)
        self.assertEqual(len(store.events()), 24)
        self.assertEqual(store.integrity_check(), "ok")
        connection = sqlite3.connect(self.path)
        try:
            state = connection.execute(
                "SELECT last_sequence FROM audit_chain_state WHERE singleton_id=1"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(state[0], 24)

    def test_reconciliation_acknowledgement_is_in_lifecycle_audit_chain(self):
        store = SQLiteSecurityStore(self.path)
        store.begin_worker_lifecycle_operation()
        self.assertTrue(store.acknowledge_worker_lifecycle_reconciliation(
            "Supervisor completed durable lifecycle reconciliation",
        ))
        self.assertEqual(store.integrity_check(), "ok")
        connection = sqlite3.connect(self.path)
        try:
            sequence, event_type = connection.execute(
                "SELECT sequence, tool_name FROM audit_events ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(sequence, 1)
        self.assertEqual(event_type, "worker.reconciliation.acknowledged")

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
        self.assertTrue({
            "resource_type", "resource_id", "task_id", "metadata_json",
            "sequence", "previous_hash", "event_hash",
        }.issubset(columns))
        self.assertEqual(store.events(), ())
        self.assertEqual(store.integrity_check(), "ok")

    def test_backup_is_consistent_private_and_restores_state(self):
        store = SQLiteSecurityStore(self.path)
        event = AuditEvent(
            "backup-event", self.now.isoformat(), "principal-1", "delete_item",
            "a" * 64, "succeeded", None,
        )
        store.write(event)
        backup_path = os.path.join(self.temp.name, "backup.sqlite3")
        self.assertEqual(store.backup_to(backup_path), backup_path)
        self.assertTrue(os.path.isfile(backup_path))
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(os.stat(backup_path).st_mode), 0o600)
        restored = SQLiteSecurityStore(backup_path)
        self.assertEqual(restored.integrity_check(), "ok")
        self.assertIn(event, restored.events())

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

    def test_audit_write_rejects_surrogate_metadata(self):
        store = SQLiteSecurityStore(self.path)
        event = AuditEvent(
            "bad" + chr(0xD800), self.now.isoformat(), "principal-1",
            "search", "a" * 64, "succeeded", None,
        )
        with self.assertRaises(ToolValidationError):
            store.write(event)

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

if __name__ == "__main__":
    unittest.main()
