from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from capri_runtime import (
    AssistantTurn,
    ExecutionContext,
    InMemoryAuditSink,
    ProviderUsage,
    ProviderUsageConflictError,
    ProviderUsageJournalError,
    SQLiteProviderUsageJournal,
    SQLiteTaskStore,
    ToolExecutionBridge,
    ToolExecutor,
    ToolOrchestrator,
    ToolRegistry,
)


class StaticUsageAdapter:
    def __init__(self, usage: ProviderUsage) -> None:
        self.usage = usage

    def complete_with_tools(self, session_id, messages, tools):
        return AssistantTurn(content="Recorded.", provider_usage=self.usage)


class SQLiteProviderUsageJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.task_store = SQLiteTaskStore(str(Path(self.temp.name) / "tasks.sqlite3"))
        self.clock_value = datetime(2026, 11, 25, 17, 0, 0, tzinfo=timezone.utc)
        self.journal = SQLiteProviderUsageJournal(
            self.task_store, clock=lambda: self.clock_value,
        )
        self.usage = ProviderUsage(
            provider="openai",
            model="gpt-6-astra",
            response_id="resp_usage_001",
            input_tokens=120,
            output_tokens=30,
            total_tokens=150,
            cached_input_tokens=20,
            cache_write_tokens=10,
            reasoning_tokens=12,
            provider_latency_ms=45,
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_record_and_read_back_usage_for_session(self):
        self.journal.record_usage("session-1", "principal-1", self.usage)
        records = self.journal.usage_for_session("principal-1", "session-1")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].usage, self.usage)
        self.assertEqual(records[0].recorded_at, "2026-11-25T17:00:00+00:00")
        self.assertRegex(records[0].event_sha256, r"^[0-9a-f]{64}$")

    def test_identical_replay_is_idempotent(self):
        self.journal.record_usage("session-1", "principal-1", self.usage)
        self.clock_value = datetime(2026, 11, 25, 17, 1, 0, tzinfo=timezone.utc)
        self.journal.record_usage("session-1", "principal-1", self.usage)
        self.assertEqual(len(self.journal.usage_for_session("principal-1", "session-1")), 1)

    def test_reused_response_id_with_different_usage_is_rejected(self):
        self.journal.record_usage("session-1", "principal-1", self.usage)
        conflicting = ProviderUsage(
            provider="openai", model="gpt-6-astra", response_id="resp_usage_001",
            input_tokens=121, output_tokens=30, total_tokens=151,
            cached_input_tokens=20, cache_write_tokens=10, reasoning_tokens=12,
            provider_latency_ms=45,
        )
        with self.assertRaises(ProviderUsageConflictError):
            self.journal.record_usage("session-1", "principal-1", conflicting)

    def test_response_id_cannot_be_rebound_to_another_principal(self):
        self.journal.record_usage("session-1", "principal-1", self.usage)
        with self.assertRaises(ProviderUsageConflictError):
            self.journal.record_usage("session-2", "principal-2", self.usage)

    def test_summary_aggregates_tokens_without_inventing_currency(self):
        self.journal.record_usage("session-1", "principal-1", self.usage)
        second = ProviderUsage(
            provider="openai", model="gpt-6-astra", response_id="resp_usage_002",
            input_tokens=80, output_tokens=20, total_tokens=100,
            cached_input_tokens=10, cache_write_tokens=5, reasoning_tokens=8,
            provider_latency_ms=25,
        )
        self.journal.record_usage("session-2", "principal-1", second)
        summaries = self.journal.summary_for_principal("principal-1")
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].requests, 2)
        self.assertEqual(summaries[0].input_tokens, 200)
        self.assertEqual(summaries[0].output_tokens, 50)
        self.assertEqual(summaries[0].total_tokens, 250)
        self.assertEqual(summaries[0].cached_input_tokens, 30)
        self.assertEqual(summaries[0].cache_write_tokens, 15)
        self.assertEqual(summaries[0].reasoning_tokens, 20)
        self.assertEqual(summaries[0].average_latency_ms, 35.0)

    def test_usage_observer_integrates_with_tool_orchestrator(self):
        adapter = StaticUsageAdapter(self.usage)
        bridge = ToolExecutionBridge(ToolExecutor(ToolRegistry(), InMemoryAuditSink()))
        orchestrator = ToolOrchestrator(
            adapter, bridge, usage_observer=self.journal.record_usage,
        )
        result = orchestrator.run(
            "session-1", "Record one usage event.", (),
            ExecutionContext("principal-1", frozenset()),
        )
        self.assertEqual(result.final_text, "Recorded.")
        self.assertEqual(result.provider_usage, (self.usage,))
        self.assertEqual(len(self.journal.usage_for_session("principal-1", "session-1")), 1)

    def test_journal_is_append_only(self):
        self.journal.record_usage("session-1", "principal-1", self.usage)
        connection = self.task_store._connect()
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE provider_usage_events SET input_tokens=121"
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM provider_usage_events")
        finally:
            connection.close()

    def test_task_store_integrity_and_backup_validate_usage_journal(self):
        self.journal.record_usage("session-1", "principal-1", self.usage)
        self.assertEqual(self.task_store.integrity_check(), "ok")
        backup_path = str(Path(self.temp.name) / "usage-backup.sqlite3")
        self.task_store.backup_to(backup_path)
        with open(backup_path, "rb") as backup:
            self.assertTrue(backup.read(16).startswith(b"SQLite format 3"))

    def test_integrity_check_rejects_missing_usage_immutability_trigger(self):
        self.journal.record_usage("session-1", "principal-1", self.usage)
        connection = self.task_store._connect()
        try:
            connection.execute("DROP TRIGGER provider_usage_immutable_delete")
        finally:
            connection.close()
        self.assertEqual(self.task_store.integrity_check(), "task store validation failed")

    def test_integrity_check_rejects_tampered_usage_digest(self):
        self.journal.record_usage("session-1", "principal-1", self.usage)
        connection = self.task_store._connect()
        try:
            connection.execute("DROP TRIGGER provider_usage_immutable_update")
            connection.execute(
                "UPDATE provider_usage_events SET event_sha256=?",
                ("0" * 64,),
            )
            connection.execute(
                """CREATE TRIGGER provider_usage_immutable_update
                BEFORE UPDATE ON provider_usage_events
                BEGIN SELECT RAISE(ABORT, 'provider usage events are append-only'); END"""
            )
        finally:
            connection.close()
        self.assertEqual(self.task_store.integrity_check(), "task store validation failed")

    def test_usage_schema_contains_no_prompt_or_response_content(self):
        connection = self.task_store._connect()
        try:
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(provider_usage_events)")
            }
        finally:
            connection.close()
        self.assertEqual(columns, {
            "provider", "response_id", "principal_id", "session_id", "model",
            "input_tokens", "output_tokens", "total_tokens", "cached_input_tokens",
            "cache_write_tokens", "reasoning_tokens", "provider_latency_ms",
            "recorded_at", "event_sha256",
        })

    def test_missing_latency_remains_unknown_not_zero(self):
        usage = ProviderUsage(
            provider="openai", model="gpt-6-astra", response_id="resp_usage_no_latency",
            input_tokens=10, output_tokens=2, total_tokens=12,
            provider_latency_ms=None,
        )
        self.journal.record_usage("session-1", "principal-1", usage)
        record = self.journal.usage_for_session("principal-1", "session-1")[0]
        self.assertIsNone(record.usage.provider_latency_ms)
        self.assertIsNone(self.journal.summary_for_principal("principal-1")[0].average_latency_ms)


if __name__ == "__main__":
    unittest.main()
