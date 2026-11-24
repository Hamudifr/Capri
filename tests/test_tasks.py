import os
import stat
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Thread
from datetime import datetime, timedelta, timezone

from capri_runtime.tasks import (
    SQLiteTaskStore,
    TaskConflictError,
    TaskEngine,
    TaskIdempotencyConflict,
    TaskValidationError,
    RetryableTaskError,
    TaskWorker,
)

NOW = datetime(2026, 11, 6, 21, 0, tzinfo=timezone.utc)
PLAN = [
    {"tool": "prepare", "input": {"value": "one"}, "max_attempts": 2},
    {"tool": "finish", "input": {"value": "two"}, "max_attempts": 1},
]


class SQLiteTaskStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        if os.name == "posix":
            os.chmod(self.temp.name, 0o700)
        self.path = os.path.join(self.temp.name, "tasks.sqlite3")
        self.store = SQLiteTaskStore(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_create_persists_and_reopens(self):
        task = self.store.create(PLAN, now=NOW)
        reopened = SQLiteTaskStore(self.path).get(task.task_id)
        self.assertEqual(reopened.state, "queued")
        self.assertEqual(reopened.current_step, 0)
        self.assertEqual(self.store.integrity_check(), "ok")

    def test_backup_is_private_consistent_and_restores_task_events(self):
        task = self.store.create(PLAN, "backup-task", NOW)
        claim = self.store.claim_next("backup-worker", now=NOW)
        finished = self.store.finish_step(
            claim, {"prepared": True}, now=NOW + timedelta(seconds=1)
        )
        backup_path = os.path.join(self.temp.name, "task-backup.sqlite3")
        self.assertEqual(self.store.backup_to(backup_path), backup_path)
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(os.stat(backup_path).st_mode), 0o600)
        restored = SQLiteTaskStore(backup_path)
        self.assertEqual(restored.integrity_check(), "ok")
        self.assertEqual(restored.get(task.task_id), finished)
        self.assertEqual(restored.events(task.task_id), self.store.events(task.task_id))

    def test_backup_refuses_existing_symlink_and_public_directory(self):
        existing = os.path.join(self.temp.name, "existing.sqlite3")
        with open(existing, "wb") as stream:
            stream.write(b"preserve")
        with self.assertRaises(TaskValidationError):
            self.store.backup_to(existing)
        link = os.path.join(self.temp.name, "link.sqlite3")
        os.symlink(existing, link)
        with self.assertRaises(TaskValidationError):
            self.store.backup_to(link)
        with open(existing, "rb") as stream:
            self.assertEqual(stream.read(), b"preserve")
        if os.name == "posix":
            public_dir = os.path.join(self.temp.name, "public")
            os.mkdir(public_dir, 0o755)
            with self.assertRaises(TaskValidationError):
                self.store.backup_to(os.path.join(public_dir, "backup.sqlite3"))

    def test_idempotency_key_returns_same_task_for_same_plan(self):
        first = self.store.create(PLAN, "request-1", NOW)
        second = self.store.create(PLAN, "request-1", NOW)
        self.assertEqual(first.task_id, second.task_id)

    def test_idempotency_key_rejects_different_plan(self):
        self.store.create(PLAN, "request-1", NOW)
        with self.assertRaises(TaskIdempotencyConflict):
            self.store.create([{"tool": "other", "input": {}}], "request-1", NOW)

    def test_plan_validation_is_strict_and_bounded(self):
        invalid = (
            [],
            [{"tool": "x", "input": [], "max_attempts": 1}],
            [{"tool": "x", "input": {}, "max_attempts": 0}],
            [{"tool": "x", "input": {}, "unexpected": True}],
            [{"tool": "x", "input": {"bad": float("nan")}}],
            [{"tool": "x", "input": {}}] * 33,
        )
        for plan in invalid:
            with self.subTest(plan=plan):
                with self.assertRaises(TaskValidationError):
                    self.store.create(plan, now=NOW)

    def test_two_workers_cannot_claim_same_task(self):
        task = self.store.create(PLAN, now=NOW)
        stores = [SQLiteTaskStore(self.path) for _ in range(4)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            claims = list(pool.map(
                lambda pair: pair[1].claim_next(pair[0], now=NOW),
                [(f"worker-{i}", store) for i, store in enumerate(stores)],
            ))
        winners = [claim for claim in claims if claim is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(winners[0].task_id, task.task_id)

    def test_expired_lease_is_quarantined_instead_of_replayed(self):
        task = self.store.create(PLAN, now=NOW)
        first = self.store.claim_next("worker-a", lease_seconds=5, now=NOW)
        self.assertEqual(first.idempotency_key, f"{task.task_id}:0")
        self.assertIsNone(self.store.claim_next(
            "worker-b", lease_seconds=5, now=NOW + timedelta(seconds=6)
        ))
        record = self.store.get(task.task_id)
        self.assertEqual(record.state, "reconciliation_required")
        self.assertEqual(record.error_code, "lease_expired_outcome_uncertain")

    def test_expired_lease_with_cancel_request_remains_uncertain(self):
        task = self.store.create(PLAN, now=NOW)
        self.store.claim_next("worker-a", lease_seconds=5, now=NOW)
        self.store.request_cancel(task.task_id, now=NOW + timedelta(seconds=1))
        self.assertIsNone(self.store.claim_next(
            "worker-b", lease_seconds=5, now=NOW + timedelta(seconds=6)
        ))
        record = self.store.get(task.task_id)
        self.assertEqual(record.state, "reconciliation_required")
        self.assertTrue(record.cancel_requested)

    def test_stale_worker_cannot_commit_after_lease_expiry_quarantine(self):
        task = self.store.create(PLAN, now=NOW)
        old = self.store.claim_next("worker-a", lease_seconds=5, now=NOW)
        self.assertIsNone(self.store.claim_next("worker-b", lease_seconds=5, now=NOW + timedelta(seconds=6)))
        with self.assertRaises(TaskConflictError):
            self.store.finish_step(old, {"ok": True}, now=NOW + timedelta(seconds=7))
        self.assertEqual(self.store.get(task.task_id).state, "reconciliation_required")

    def test_retry_backoff_and_attempt_limit(self):
        task = self.store.create(PLAN, now=NOW)
        claim = self.store.claim_next("worker", now=NOW)
        waiting = self.store.fail_step(claim, now=NOW)
        self.assertEqual(waiting.state, "retry_wait")
        self.assertIsNone(self.store.claim_next("worker", now=NOW + timedelta(seconds=4)))
        retry = self.store.claim_next("worker", now=NOW + timedelta(seconds=5))
        self.assertEqual(retry.attempt, 2)
        failed = self.store.fail_step(retry, now=NOW + timedelta(seconds=5))
        self.assertEqual(failed.state, "failed")
        self.assertEqual(failed.error_code, "handler_failed")

    def test_engine_runs_steps_and_persists_results(self):
        calls = []
        engine = TaskEngine(
            self.store,
            {
                "prepare": lambda data, key: calls.append((data, key)) or {"prepared": True},
                "finish": lambda data, key: {"finished": data["value"]},
            },
            "worker",
        )
        task = self.store.create(PLAN, now=NOW)
        first = engine.run_once(now=NOW)
        self.assertEqual(first.state, "queued")
        self.assertEqual(first.current_step, 1)
        second = engine.run_once(now=NOW)
        self.assertEqual(second.state, "succeeded")
        self.assertEqual(second.result, ({"prepared": True}, {"finished": "two"}))
        self.assertEqual(calls[0][1], f"{task.task_id}:0")

    def test_uncertain_handler_exception_is_quarantined_and_never_replayed(self):
        calls = []
        def broken(_data, _key):
            calls.append("side_effect")
            raise RuntimeError("must not leak")
        engine = TaskEngine(self.store, {"prepare": broken}, "worker")
        task = self.store.create([{"tool": "prepare", "input": {}, "max_attempts": 3}], now=NOW)
        result = engine.run_once(now=NOW)
        self.assertEqual(result.state, "reconciliation_required")
        self.assertEqual(result.error_code, "handler_outcome_uncertain")
        self.assertNotIn("must not leak", str(result))
        self.assertEqual(calls, ["side_effect"])
        self.assertIsNone(engine.run_once(now=NOW + timedelta(hours=1)))
        self.assertEqual(calls, ["side_effect"])

    def test_invalid_handler_result_is_quarantined_after_side_effect(self):
        calls = []
        engine = TaskEngine(
            self.store,
            {"prepare": lambda data, key: calls.append("side_effect") or object()},
            "worker",
        )
        task = self.store.create([{"tool": "prepare", "input": {}, "max_attempts": 3}], now=NOW)
        result = engine.run_once(now=NOW)
        self.assertEqual(result.state, "reconciliation_required")
        self.assertEqual(result.error_code, "handler_result_invalid")
        self.assertEqual(calls, ["side_effect"])
        self.assertIsNone(engine.run_once(now=NOW + timedelta(hours=1)))

    def test_explicit_retryable_error_retries_only_declared_pre_side_effect_failure(self):
        calls = []
        def handler(_data, _key):
            calls.append("attempt")
            if len(calls) == 1:
                raise RetryableTaskError("safe pre-side-effect failure")
            return {"ok": True}
        engine = TaskEngine(self.store, {"prepare": handler}, "worker")
        task = self.store.create([{"tool": "prepare", "input": {}, "max_attempts": 2}], now=NOW)
        first = engine.run_once(now=NOW)
        self.assertEqual(first.state, "retry_wait")
        second = engine.run_once(now=NOW + timedelta(seconds=5))
        self.assertEqual(second.state, "succeeded")
        self.assertEqual(calls, ["attempt", "attempt"])

    def test_uncertain_cancellation_requires_reconciliation(self):
        from capri_runtime.tools import ToolCancelledError
        engine = TaskEngine(
            self.store,
            {"prepare": lambda data, key: (_ for _ in ()).throw(ToolCancelledError(outcome_uncertain=True))},
            "worker",
        )
        self.store.create([{"tool": "prepare", "input": {}, "max_attempts": 3}], now=NOW)
        result = engine.run_once(now=NOW)
        self.assertEqual(result.state, "reconciliation_required")
        self.assertEqual(result.error_code, "handler_outcome_uncertain")

    def test_cancellation_before_handler_start_is_not_quarantined(self):
        from capri_runtime.tools import ToolCancelledError
        engine = TaskEngine(
            self.store,
            {"prepare": lambda data, key: (_ for _ in ()).throw(ToolCancelledError(outcome_uncertain=False))},
            "worker",
        )
        self.store.create([{"tool": "prepare", "input": {}, "max_attempts": 3}], now=NOW)
        result = engine.run_once(now=NOW)
        self.assertEqual(result.state, "failed")
        self.assertEqual(result.error_code, "handler_cancelled_before_start")

    def test_cancel_request_preserves_uncertain_state(self):
        engine = TaskEngine(
            self.store,
            {"prepare": lambda data, key: (_ for _ in ()).throw(RuntimeError("uncertain"))},
            "worker",
        )
        task = self.store.create([{"tool": "prepare", "input": {}, "max_attempts": 3}], now=NOW)
        result = engine.run_once(now=NOW)
        self.assertEqual(result.state, "reconciliation_required")
        cancelled = self.store.request_cancel(task.task_id, now=NOW + timedelta(seconds=1))
        self.assertEqual(cancelled.state, "reconciliation_required")
        self.assertTrue(cancelled.cancel_requested)

    def test_reconciliation_state_is_valid_in_private_backup(self):
        engine = TaskEngine(
            self.store,
            {"prepare": lambda data, key: (_ for _ in ()).throw(RuntimeError("uncertain"))},
            "worker",
        )
        self.store.create([{"tool": "prepare", "input": {}, "max_attempts": 3}], now=NOW)
        result = engine.run_once(now=NOW)
        self.assertEqual(result.state, "reconciliation_required")
        backup = os.path.join(self.temp.name, "quarantine-backup.sqlite3")
        self.store.backup_to(backup)
        self.assertTrue(os.path.exists(backup))

    def test_missing_handler_fails_without_retry(self):
        engine = TaskEngine(self.store, {}, "worker")
        self.store.create([{"tool": "missing", "input": {}, "max_attempts": 5}], now=NOW)
        result = engine.run_once(now=NOW)
        self.assertEqual(result.state, "failed")
        self.assertEqual(result.error_code, "unknown_handler")

    def test_cancel_queued_task(self):
        task = self.store.create(PLAN, now=NOW)
        cancelled = self.store.request_cancel(task.task_id, now=NOW)
        self.assertEqual(cancelled.state, "cancelled")
        self.assertIsNone(self.store.claim_next("worker", now=NOW))

    def test_cancel_running_task_finishes_current_step_then_stops(self):
        task = self.store.create(PLAN, now=NOW)
        claim = self.store.claim_next("worker", now=NOW)
        self.store.request_cancel(task.task_id, now=NOW + timedelta(seconds=1))
        result = self.store.finish_step(claim, {"completed": True}, now=NOW + timedelta(seconds=2))
        self.assertEqual(result.state, "cancelled")
        self.assertEqual(result.current_step, 1)
        self.assertEqual(result.result, ({"completed": True},))

    def test_events_are_durable_and_ordered(self):
        task = self.store.create(PLAN, now=NOW)
        self.store.claim_next("worker", now=NOW)
        events = SQLiteTaskStore(self.path).events(task.task_id)
        self.assertEqual([event["state"] for event in events], ["queued", "running"])

    def test_database_rejects_symlink_path(self):
        if os.name != "posix":
            self.skipTest("POSIX symlink semantics required")
        target = os.path.join(self.temp.name, "target.db")
        with open(target, "w", encoding="utf-8") as stream:
            stream.write("not a database")
        link = os.path.join(self.temp.name, "link.db")
        os.symlink(target, link)
        with self.assertRaises(TaskValidationError):
            SQLiteTaskStore(link)

    def test_database_rechecks_directory_privacy(self):
        if os.name != "posix":
            self.skipTest("POSIX permissions required")
        os.chmod(self.temp.name, 0o755)
        try:
            with self.assertRaises(TaskValidationError):
                self.store.integrity_check()
        finally:
            os.chmod(self.temp.name, 0o700)


    def test_success_after_retry_clears_previous_error_code(self):
        attempts = {"count": 0}
        def sometimes_fails(_data, _key):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RetryableTaskError("safe pre-side-effect failure")
            return {"ok": True}
        engine = TaskEngine(self.store, {"prepare": sometimes_fails}, "worker")
        self.store.create([{"tool": "prepare", "input": {}, "max_attempts": 2}], now=NOW)
        first = engine.run_once(now=NOW)
        self.assertEqual(first.state, "retry_wait")
        second = engine.run_once(now=NOW + timedelta(seconds=5))
        self.assertEqual(second.state, "succeeded")
        self.assertIsNone(second.error_code)

    def test_cancellation_during_failed_step_does_not_schedule_retry(self):
        self.store.create([{"tool": "prepare", "input": {}, "max_attempts": 5}], now=NOW)
        claim = self.store.claim_next("worker", now=NOW)
        self.store.request_cancel(claim.task_id, now=NOW + timedelta(seconds=1))
        result = self.store.fail_step(claim, now=NOW + timedelta(seconds=2))
        self.assertEqual(result.state, "cancelled")
        self.assertIsNone(self.store.claim_next("worker", now=NOW + timedelta(seconds=3)))


    def test_plan_rejects_non_string_keys_and_non_json_values(self):
        invalid = [
            [{"tool": "prepare", "input": {1: "value"}}],
            [{"tool": "prepare", "input": {"nested": (1, 2)}}],
            [{"tool": "prepare", "input": {"nested": [[[[[[[[[[[[[[[[[0]]]]]]]]]]]]]]]]]}}],
        ]
        for plan in invalid:
            with self.subTest(plan=plan):
                with self.assertRaises(TaskValidationError):
                    self.store.create(plan, now=NOW)


    def test_live_lease_can_be_renewed_for_long_handler(self):
        self.store.create([{"tool": "prepare", "input": {}, "max_attempts": 2}], now=NOW)
        claim = self.store.claim_next("worker", lease_seconds=5, now=NOW)
        renewed = self.store.renew_lease(
            claim, lease_seconds=60, now=NOW + timedelta(seconds=4)
        )
        self.assertGreater(
            datetime.fromisoformat(renewed.lease_until),
            datetime.fromisoformat(claim.lease_until),
        )
        result = self.store.finish_step(
            claim, {"completed": True}, now=NOW + timedelta(seconds=20)
        )
        self.assertEqual(result.state, "succeeded")

    def test_expired_lease_cannot_be_renewed(self):
        self.store.create(PLAN, now=NOW)
        claim = self.store.claim_next("worker-a", lease_seconds=5, now=NOW)
        with self.assertRaises(TaskConflictError):
            self.store.renew_lease(
                claim, lease_seconds=60, now=NOW + timedelta(seconds=6)
            )

    def test_stolen_lease_cannot_be_renewed_by_old_worker(self):
        self.store.create(PLAN, now=NOW)
        old = self.store.claim_next("worker-a", lease_seconds=5, now=NOW)
        self.store.claim_next(
            "worker-b", lease_seconds=30, now=NOW + timedelta(seconds=6)
        )
        with self.assertRaises(TaskConflictError):
            self.store.renew_lease(
                old, lease_seconds=60, now=NOW + timedelta(seconds=7)
            )


    def test_managed_worker_renews_lease_during_long_handler(self):
        started = Event()
        release = Event()
        outcomes = []

        def slow_handler(_data, _key):
            started.set()
            release.wait(timeout=8)
            return {"completed": True}

        self.store.create(
            [{"tool": "slow", "input": {}, "max_attempts": 2}],
            now=datetime.now(timezone.utc),
        )
        engine = TaskEngine(
            self.store, {"slow": slow_handler}, "worker-a", lease_seconds=5
        )
        worker = TaskWorker(
            engine, poll_interval_seconds=0.05, heartbeat_interval_seconds=0.1
        )
        thread = Thread(target=lambda: outcomes.append(worker.run_once()))
        thread.start()
        self.assertTrue(started.wait(timeout=2))
        time.sleep(5.2)
        competing = self.store.claim_next(
            "worker-b", lease_seconds=5, now=datetime.now(timezone.utc)
        )
        self.assertIsNone(competing)
        release.set()
        thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcomes[0].state, "succeeded")

    def test_managed_worker_stops_polling_when_stop_event_is_set(self):
        worker = TaskWorker(
            TaskEngine(self.store, {}, "worker"),
            poll_interval_seconds=0.05,
            heartbeat_interval_seconds=0.1,
        )
        stop = Event()
        thread = Thread(target=lambda: worker.run_forever(stop))
        thread.start()
        time.sleep(0.1)
        stop.set()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())

    def test_managed_worker_rejects_heartbeat_interval_not_shorter_than_lease(self):
        engine = TaskEngine(self.store, {}, "worker", lease_seconds=5)
        with self.assertRaises(TaskValidationError):
            TaskWorker(engine, heartbeat_interval_seconds=5)


if __name__ == "__main__":
    unittest.main()
