import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from capri_runtime.tasks import (
    SQLiteTaskStore,
    TaskConflictError,
    TaskEngine,
    TaskIdempotencyConflict,
    TaskValidationError,
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

    def test_expired_lease_recovers_with_stable_idempotency_key(self):
        task = self.store.create(PLAN, now=NOW)
        first = self.store.claim_next("worker-a", lease_seconds=5, now=NOW)
        self.assertEqual(first.idempotency_key, f"{task.task_id}:0")
        second = self.store.claim_next(
            "worker-b", lease_seconds=5, now=NOW + timedelta(seconds=6)
        )
        self.assertEqual(second.idempotency_key, first.idempotency_key)
        self.assertEqual(second.attempt, 2)

    def test_stale_worker_cannot_commit_after_lease_reclaimed(self):
        self.store.create(PLAN, now=NOW)
        old = self.store.claim_next("worker-a", lease_seconds=5, now=NOW)
        self.store.claim_next("worker-b", lease_seconds=5, now=NOW + timedelta(seconds=6))
        with self.assertRaises(TaskConflictError):
            self.store.finish_step(old, {"ok": True}, now=NOW + timedelta(seconds=7))

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
        first = engine.run_once()
        self.assertEqual(first.state, "queued")
        self.assertEqual(first.current_step, 1)
        second = engine.run_once()
        self.assertEqual(second.state, "succeeded")
        self.assertEqual(second.result, ({"prepared": True}, {"finished": "two"}))
        self.assertEqual(calls[0][1], f"{task.task_id}:0")

    def test_handler_failure_is_suppressed_and_retried(self):
        def broken(_data, _key):
            raise RuntimeError("must not leak")
        engine = TaskEngine(self.store, {"prepare": broken}, "worker")
        task = self.store.create([{"tool": "prepare", "input": {}, "max_attempts": 1}], now=NOW)
        result = engine.run_once()
        self.assertEqual(result.state, "failed")
        self.assertEqual(result.error_code, "handler_failed")
        self.assertNotIn("must not leak", str(result))

    def test_missing_handler_fails_without_retry(self):
        engine = TaskEngine(self.store, {}, "worker")
        self.store.create([{"tool": "missing", "input": {}, "max_attempts": 5}], now=NOW)
        result = engine.run_once()
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


if __name__ == "__main__":
    unittest.main()
