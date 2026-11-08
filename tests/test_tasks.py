import os
from dataclasses import replace
import sqlite3
import stat
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Thread
from datetime import datetime, timedelta, timezone

from capri_runtime.tasks import (
    SQLiteTaskStore,
    TaskClaim,
    TaskConflictError,
    TaskEngine,
    TaskIdempotencyConflict,
    TaskNotFoundError,
    TaskValidationError,
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
        owned = self.store.create_for_principal("backup-owner", PLAN, now=NOW)
        owned_backup_path = os.path.join(self.temp.name, "owned-task-backup.sqlite3")
        self.store.backup_to(owned_backup_path)
        restored_owned = SQLiteTaskStore(owned_backup_path)
        self.assertEqual(
            restored_owned.get_for_principal(owned.task_id, "backup-owner"), owned
        )
        with self.assertRaises(TaskNotFoundError):
            restored_owned.get_for_principal(owned.task_id, "other-owner")

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

    def test_principal_task_ownership_and_namespaced_idempotency(self):
        alice = self.store.create_for_principal("alice", PLAN, "same-key", NOW)
        alice_again = self.store.create_for_principal("alice", PLAN, "same-key", NOW)
        bob = self.store.create_for_principal("bob", PLAN, "same-key", NOW)
        self.assertEqual(alice.task_id, alice_again.task_id)
        self.assertNotEqual(alice.task_id, bob.task_id)
        self.assertEqual(self.store.get_for_principal(alice.task_id, "alice"), alice)
        self.assertEqual(self.store.events_for_principal(alice.task_id, "alice")[0]["state"], "queued")
        with self.assertRaises(TaskNotFoundError):
            self.store.get_for_principal(alice.task_id, "bob")
        with self.assertRaises(TaskNotFoundError):
            self.store.request_cancel_for_principal(alice.task_id, "bob")
        with self.assertRaises(TaskNotFoundError):
            self.store.events_for_principal(alice.task_id, "bob")
        with self.assertRaises(TaskIdempotencyConflict):
            self.store.create_for_principal(
                "alice", [{"tool": "different", "input": {}}], "same-key", NOW
            )

    def test_task_owner_rows_are_immutable_and_legacy_tasks_stay_unowned(self):
        owned = self.store.create_for_principal("alice", PLAN, now=NOW)
        legacy = self.store.create(PLAN, now=NOW)
        connection = self.store._connect()
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE task_owners SET principal_id='bob' WHERE task_id=?",
                    (owned.task_id,),
                )
            with self.assertRaises(Exception):
                connection.execute(
                    "DELETE FROM task_owners WHERE task_id=?",
                    (owned.task_id,),
                )
        finally:
            connection.close()
        with self.assertRaises(TaskNotFoundError):
            self.store.get_for_principal(legacy.task_id, "alice")
        self.assertEqual(self.store.get(legacy.task_id), legacy)

    def test_worker_rejects_tampered_claim_identity_and_payload(self):
        calls = []
        engine = TaskEngine(
            self.store,
            {
                "prepare": lambda data, key: calls.append(("legacy", data)) or {"ok": True},
                "admin": lambda data, key: calls.append(("legacy-admin", data)) or {"ok": True},
            },
            "worker",
            principal_handlers={
                "prepare": lambda data, key, principal: (
                    calls.append(("principal", principal, data)) or {"ok": True}
                ),
                "admin": lambda data, key, principal: (
                    calls.append(("principal-admin", principal, data)) or {"ok": True}
                ),
            },
        )
        tamper = (
            lambda claim: replace(claim, principal_id=None),
            lambda claim: replace(claim, principal_id="mallory"),
            lambda claim: replace(claim, tool="admin", input={"elevated": True}),
            lambda claim: replace(claim, input={"value": "tampered"}),
            lambda claim: replace(claim, attempt=claim.attempt + 1),
            lambda claim: replace(claim, idempotency_key="attacker-key"),
            lambda claim: replace(claim, lease_until="2099-01-01T00:00:00+00:00"),
        )
        for attack in tamper:
            with self.subTest(attack=attack):
                self.store.create_for_principal(
                    "alice",
                    [{"tool": "prepare", "input": {"value": "original"}, "max_attempts": 1}],
                    now=NOW,
                )
                claim = self.store.claim_next("worker", now=NOW)
                self.assertIsInstance(claim, TaskClaim)
                with self.assertRaises(TaskConflictError):
                    engine.execute_claim(attack(claim), now=NOW)
                self.assertEqual(calls, [])
                completed = engine.execute_claim(claim, now=NOW)
                self.assertEqual(completed.state, "succeeded")
                self.assertEqual(
                    calls[-1], ("principal", "alice", {"value": "original"})
                )

    def test_claim_input_is_snapshotted_before_validation_and_dispatch(self):
        calls = []
        self.store.create_for_principal(
            "alice",
            [{"tool": "prepare", "input": {"value": "persisted"}, "max_attempts": 1}],
            now=NOW,
        )
        claim = self.store.claim_next("worker", now=NOW)
        engine = TaskEngine(
            self.store,
            {},
            "worker",
            principal_handlers={
                "prepare": lambda data, key, principal: (
                    calls.append((principal, data)) or {"ok": True}
                )
            },
        )
        original_validate = self.store.validate_claim

        def mutate_original_after_validation(candidate, now=None):
            original_validate(candidate, now=now)
            # Simulate a concurrent caller mutating the public claim object
            # after its authoritative validation but before dispatch.
            claim.input["value"] = "mutated-after-validation"

        self.store.validate_claim = mutate_original_after_validation
        result = engine.execute_claim(claim, now=NOW)
        self.assertEqual(result.state, "succeeded")
        self.assertEqual(calls, [("alice", {"value": "persisted"})])

    def test_expired_claim_is_rejected_before_handler_invocation(self):
        calls = []
        self.store.create_for_principal(
            "alice",
            [{"tool": "prepare", "input": {"value": "original"}, "max_attempts": 2}],
            now=NOW,
        )
        claim = self.store.claim_next("worker", lease_seconds=5, now=NOW)
        engine = TaskEngine(
            self.store,
            {},
            "worker",
            principal_handlers={
                "prepare": lambda data, key, principal: (
                    calls.append((principal, data)) or {"ok": True}
                )
            },
        )
        with self.assertRaises(TaskConflictError):
            engine.execute_claim(claim, now=NOW + timedelta(seconds=6))
        self.assertEqual(calls, [])
        self.assertEqual(self.store.get_for_principal(claim.task_id, "alice").state, "running")

    def test_principal_claims_require_principal_aware_handlers(self):
        calls = []
        self.store.create_for_principal(
            "alice", [{"tool": "prepare", "input": {}, "max_attempts": 1}], now=NOW
        )
        generic = TaskEngine(
            self.store,
            {"prepare": lambda data, key: calls.append("generic") or {"ok": True}},
            "worker",
        )
        failed = generic.run_once(now=NOW)
        self.assertEqual(failed.state, "failed")
        self.assertEqual(failed.error_code, "principal_handler_required")
        self.assertEqual(calls, [])

        self.store.create_for_principal(
            "bob", [{"tool": "prepare", "input": {}, "max_attempts": 1}], now=NOW
        )
        scoped = TaskEngine(
            self.store,
            {},
            "scoped-worker",
            principal_handlers={
                "prepare": lambda data, key, principal: (
                    calls.append(principal) or {"principal": principal}
                )
            },
        )
        succeeded = scoped.run_once(now=NOW)
        self.assertEqual(succeeded.state, "succeeded")
        self.assertEqual(calls, ["bob"])
        self.assertEqual(succeeded.result, ({"principal": "bob"},))

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
        first = engine.run_once(now=NOW)
        self.assertEqual(first.state, "queued")
        self.assertEqual(first.current_step, 1)
        second = engine.run_once(now=NOW)
        self.assertEqual(second.state, "succeeded")
        self.assertEqual(second.result, ({"prepared": True}, {"finished": "two"}))
        self.assertEqual(calls[0][1], f"{task.task_id}:0")

    def test_handler_failure_is_suppressed_and_terminal_after_attempt_limit(self):
        def broken(_data, _key):
            raise RuntimeError("must not leak")
        engine = TaskEngine(self.store, {"prepare": broken}, "worker")
        task = self.store.create([{"tool": "prepare", "input": {}, "max_attempts": 1}], now=NOW)
        result = engine.run_once(now=NOW)
        self.assertEqual(result.state, "failed")
        self.assertEqual(result.error_code, "handler_failed")
        self.assertNotIn("must not leak", str(result))

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
                raise RuntimeError("private failure")
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


    def test_all_lease_transitions_reject_tampered_claims_atomically(self):
        engine_methods = ("renew_lease", "finish_step", "fail_step")
        attacks = (
            lambda claim: replace(claim, principal_id=None),
            lambda claim: replace(claim, tool="admin"),
            lambda claim: replace(claim, input={"elevated": True}),
            lambda claim: replace(claim, attempt=claim.attempt + 1),
            lambda claim: replace(claim, idempotency_key="forged-key"),
            lambda claim: replace(claim, lease_until="2099-01-01T00:00:00+00:00"),
        )
        for method_name in engine_methods:
            for attack in attacks:
                with self.subTest(method=method_name, attack=attack):
                    task = self.store.create_for_principal(
                        "alice",
                        [{"tool": "prepare", "input": {"value": "original"}, "max_attempts": 2}],
                        now=NOW,
                    )
                    claim = self.store.claim_next("worker", now=NOW)
                    forged = attack(claim)
                    with self.assertRaises(TaskConflictError):
                        if method_name == "renew_lease":
                            self.store.renew_lease(forged, lease_seconds=60, now=NOW)
                        elif method_name == "finish_step":
                            self.store.finish_step(forged, {"forged": True}, now=NOW)
                        else:
                            self.store.fail_step(forged, now=NOW)
                    self.assertEqual(self.store.get_for_principal(task.task_id, "alice").state, "running")
                    connection = self.store._connect()
                    try:
                        lease = connection.execute(
                            "SELECT lease_until FROM tasks WHERE task_id=?",
                            (task.task_id,),
                        ).fetchone()[0]
                    finally:
                        connection.close()
                    self.assertEqual(lease, claim.lease_until)

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
