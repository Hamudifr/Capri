import os
import sqlite3
import stat
import tempfile
import unittest
from datetime import datetime, timezone

from capri_runtime import (
    OutcomeConflictError,
    OutcomeIdempotencyConflict,
    OutcomeNotFoundError,
    OutcomeValidationError,
    SQLiteOutcomeStore,
)


class SQLiteOutcomeStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        if os.name == "posix":
            os.chmod(self.temp.name, 0o700)
        self.path = os.path.join(self.temp.name, "outcomes.sqlite3")
        self.store = SQLiteOutcomeStore(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def append(self, **overrides):
        values = {
            "subject_type": "goal",
            "subject_id": "goal-123",
            "outcome_type": "execution",
            "status": "succeeded",
            "summary": "The goal completed and the owner verified the result.",
            "source_type": "verification",
            "source_reference": "sha256:" + "a" * 64,
            "confidence": "high",
        }
        values.update(overrides)
        return self.store.append_for_principal("alice", **values)

    def test_append_and_owner_scoped_read_round_trip(self):
        record = self.append()
        self.assertEqual(self.store.get_for_principal(record.outcome_id, "alice"), record)
        self.assertEqual(self.store.list_for_principal("alice"), (record,))
        with self.assertRaises(OutcomeNotFoundError):
            self.store.get_for_principal(record.outcome_id, "bob")
        self.assertEqual(self.store.list_for_principal("bob"), ())

    def test_correction_appends_and_preserves_original_history(self):
        original = self.append()
        corrected = self.store.correct_for_principal(
            "alice", original.outcome_id,
            status="partial",
            summary="The task completed, but owner verification is still pending.",
            reason="The original entry overstated acceptance.",
            source_reference="sha256:" + "b" * 64,
            confidence="medium",
        )
        self.assertEqual(corrected.supersedes_id, original.outcome_id)
        self.assertEqual(corrected.source_type, "user_correction")
        self.assertEqual(self.store.get_for_principal(original.outcome_id, "alice"), original)
        self.assertEqual(
            self.store.list_for_principal("alice", subject_type="goal", subject_id="goal-123"),
            (corrected,),
        )
        history = self.store.list_for_principal(
            "alice", subject_type="goal", subject_id="goal-123", include_superseded=True,
        )
        self.assertEqual({item.outcome_id for item in history},
                         {original.outcome_id, corrected.outcome_id})
        self.assertEqual(self.store.integrity_check(), "ok")

    def test_correction_can_be_corrected_without_rewriting_earlier_rows(self):
        first = self.append()
        second = self.store.correct_for_principal(
            "alice", first.outcome_id, status="partial",
            summary="Partial outcome.", reason="Evidence was incomplete.",
        )
        third = self.store.correct_for_principal(
            "alice", second.outcome_id, status="succeeded",
            summary="The complete result was independently verified.",
            reason="The missing evidence was subsequently supplied.",
        )
        self.assertEqual(third.supersedes_id, second.outcome_id)
        self.assertEqual(self.store.get_for_principal(first.outcome_id, "alice"), first)
        self.assertEqual(self.store.get_for_principal(second.outcome_id, "alice"), second)
        self.assertEqual(self.store.list_for_principal("alice"), (third,))
        with self.assertRaises(OutcomeConflictError):
            self.store.correct_for_principal(
                "alice", first.outcome_id, status="failed",
                summary="Conflicting correction.", reason="Already superseded.",
            )

    def test_append_idempotency_returns_original_and_rejects_payload_reuse(self):
        first = self.append(idempotency_key="capture-001")
        replay = self.append(idempotency_key="capture-001")
        self.assertEqual(replay, first)
        with self.assertRaises(OutcomeIdempotencyConflict):
            self.append(idempotency_key="capture-001", status="failed")

    def test_correction_idempotency_returns_original_correction(self):
        first = self.append()
        kwargs = {
            "status": "partial",
            "summary": "One verification remains.",
            "reason": "The first report omitted a pending check.",
            "idempotency_key": "correction-001",
        }
        corrected = self.store.correct_for_principal("alice", first.outcome_id, **kwargs)
        replay = self.store.correct_for_principal("alice", first.outcome_id, **kwargs)
        self.assertEqual(replay, corrected)
        with self.assertRaises(OutcomeIdempotencyConflict):
            self.store.correct_for_principal(
                "alice", first.outcome_id, status="failed",
                summary="Different correction.", reason="Different evidence.",
                idempotency_key="correction-001",
            )

    def test_concurrent_corrections_cannot_create_competing_successors(self):
        from concurrent.futures import ThreadPoolExecutor

        original = self.append()
        second_store = SQLiteOutcomeStore(self.path)

        def correct(store, suffix):
            try:
                return store.correct_for_principal(
                    "alice", original.outcome_id, status="partial",
                    summary="A competing correction " + suffix,
                    reason="Concurrent correction race.",
                )
            except OutcomeConflictError:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = tuple(pool.map(
                lambda pair: correct(*pair),
                ((self.store, "one"), (second_store, "two")),
            ))
        self.assertEqual(sum(item is not None for item in results), 1)
        self.assertEqual(len(self.store.list_for_principal("alice")), 1)
        self.assertEqual(self.store.integrity_check(), "ok")

    def test_cannot_correct_another_principals_record(self):
        first = self.append()
        with self.assertRaises(OutcomeNotFoundError):
            self.store.correct_for_principal(
                "bob", first.outcome_id, status="failed",
                summary="Attempted cross-owner correction.", reason="Not authorized.",
            )

    def test_records_are_append_only_at_sqlite_boundary(self):
        first = self.append()
        connection = sqlite3.connect(self.path)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE outcomes SET summary='rewritten' WHERE outcome_id=?",
                    (first.outcome_id,),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "DELETE FROM outcomes WHERE outcome_id=?",
                    (first.outcome_id,),
                )
        finally:
            connection.close()

    def test_integrity_check_detects_missing_append_only_triggers(self):
        self.append()
        connection = sqlite3.connect(self.path)
        try:
            connection.execute("DROP TRIGGER outcomes_immutable_delete")
            connection.commit()
        finally:
            connection.close()
        self.assertEqual(self.store.integrity_check(), "outcome journal validation failed")

    def test_integrity_check_detects_semantically_invalid_persisted_rows(self):
        self.append()
        connection = sqlite3.connect(self.path)
        try:
            connection.execute("DROP TRIGGER outcomes_immutable_update")
            connection.execute("UPDATE outcomes SET status='impossible'")
            connection.commit()
        finally:
            connection.close()
        self.assertEqual(self.store.integrity_check(), "outcome journal validation failed")

    def test_backup_is_private_consistent_and_restores_correction_history(self):
        first = self.append()
        corrected = self.store.correct_for_principal(
            "alice", first.outcome_id, status="partial",
            summary="A correction with preserved history.", reason="New evidence.",
        )
        backup_path = os.path.join(self.temp.name, "outcomes-backup.sqlite3")
        self.assertEqual(self.store.backup_to(backup_path), backup_path)
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(os.stat(backup_path).st_mode), 0o600)
        restored = SQLiteOutcomeStore(backup_path)
        self.assertEqual(
            restored.list_for_principal("alice", include_superseded=True),
            self.store.list_for_principal("alice", include_superseded=True),
        )
        self.assertEqual(restored.list_for_principal("alice"), (corrected,))
        with self.assertRaises(OutcomeValidationError):
            self.store.backup_to(backup_path)

    def test_validation_rejects_bad_types_and_untrusted_unicode(self):
        for override in (
            {"subject_type": []},
            {"outcome_type": "unknown"},
            {"status": "maybe"},
            {"source_type": "model_instruction"},
            {"confidence": "certain"},
            {"summary": "bad\ud800text"},
            {"source_reference": 42},
        ):
            with self.subTest(override=override):
                with self.assertRaises(OutcomeValidationError):
                    self.append(**override)
        with self.assertRaises(OutcomeValidationError):
            self.append(now=datetime(2026, 11, 25))

    def test_listing_is_bounded_and_subject_scoped(self):
        self.append(subject_id="goal-a")
        self.append(subject_id="goal-b")
        self.assertEqual(
            len(self.store.list_for_principal("alice", subject_type="goal", subject_id="goal-a")),
            1,
        )
        with self.assertRaises(OutcomeValidationError):
            self.store.list_for_principal("alice", limit=101)
        with self.assertRaises(OutcomeValidationError):
            self.store.list_for_principal("alice", subject_type=[])


if __name__ == "__main__":
    unittest.main()
