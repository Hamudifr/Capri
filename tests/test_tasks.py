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

    def test_backup_accepts_valid_running_lease(self):
        task = self.store.create(PLAN, now=NOW)
        claim = self.store.claim_next("backup-worker", now=NOW)
        self.assertEqual(claim.task_id, task.task_id)
        backup_path = os.path.join(self.temp.name, "running-task-backup.sqlite3")
        self.assertEqual(self.store.backup_to(backup_path), backup_path)

    def test_backup_rejects_corrupt_event_attempt_bounds(self):
        cases = (
            ("event_attempt_over_step_limit", 0, 3),
            ("event_step_outside_plan", len(PLAN), 0),
        )
        for suffix, step_index, attempt in cases:
            with self.subTest(case=suffix):
                task = self.store.create(PLAN, now=NOW)
                connection = self.store._connect()
                try:
                    connection.execute(
                        """UPDATE task_events SET step_index=?,attempt=?
                        WHERE task_id=?""",
                        (step_index, attempt, task.task_id),
                    )
                finally:
                    connection.close()
                backup_path = os.path.join(self.temp.name, f"{suffix}.sqlite3")
                with self.assertRaisesRegex(
                    TaskValidationError, "backup contains invalid task event progress"
                ):
                    self.store.backup_to(backup_path)
                self.assertFalse(os.path.exists(backup_path))
                connection = self.store._connect()
                try:
                    connection.execute(
                        "UPDATE task_events SET step_index=0,attempt=0 WHERE task_id=?",
                        (task.task_id,),
                    )
                finally:
                    connection.close()

    def test_backup_rejects_inconsistent_attempt_and_step_lifecycle(self):
        cases = (
            ("queued_nonzero_attempts", "queued", 0, 1),
            ("retry_wait_zero_attempts", "retry_wait", 0, 0),
            ("running_attempts_over_max", "running", 0, 3),
            ("succeeded_before_plan_end", "succeeded", 0, 0),
            ("succeeded_nonzero_attempts", "succeeded", len(PLAN), 1),
            ("failed_zero_attempts", "failed", 0, 0),
            ("cancelled_attempts_over_max", "cancelled", 0, 3),
            ("queued_after_plan_end", "queued", len(PLAN), 0),
        )
        for suffix, state, index, attempts in cases:
            with self.subTest(case=suffix):
                task = self.store.create(PLAN, now=NOW)
                lease_owner = "backup-worker" if state == "running" else None
                lease_until = (
                    (NOW + timedelta(seconds=30)).isoformat()
                    if state == "running" else None
                )
                connection = self.store._connect()
                try:
                    connection.execute(
                        """UPDATE tasks SET state=?,current_step=?,attempts=?,
                        lease_owner=?,lease_until=? WHERE task_id=?""",
                        (state, index, attempts, lease_owner, lease_until, task.task_id),
                    )
                finally:
                    connection.close()
                backup_path = os.path.join(self.temp.name, f"{suffix}.sqlite3")
                with self.assertRaisesRegex(
                    TaskValidationError, "backup contains invalid task lifecycle progress"
                ):
                    self.store.backup_to(backup_path)
                self.assertFalse(os.path.exists(backup_path))
                connection = self.store._connect()
                try:
                    connection.execute(
                        """UPDATE tasks SET state='queued',current_step=0,attempts=0,
                        lease_owner=NULL,lease_until=NULL WHERE task_id=?""",
                        (task.task_id,),
                    )
                finally:
                    connection.close()

    def test_backup_rejects_inconsistent_task_lease_state(self):
        cases = (
            ("running_missing_owner", "running", None, (NOW + timedelta(seconds=30)).isoformat()),
            ("running_missing_expiry", "running", "backup-worker", None),
            ("running_invalid_expiry", "running", "backup-worker", "not-a-timestamp"),
            ("queued_with_lease", "queued", "orphan-worker", (NOW + timedelta(seconds=30)).isoformat()),
        )
        for suffix, state, owner, expiry in cases:
            with self.subTest(case=suffix):
                task = self.store.create(PLAN, now=NOW)
                if state == "running":
                    claim = self.store.claim_next("backup-worker", now=NOW)
                    self.assertEqual(claim.task_id, task.task_id)
                connection = self.store._connect()
                try:
                    connection.execute(
                        "UPDATE tasks SET lease_owner=?,lease_until=? WHERE task_id=?",
                        (owner, expiry, task.task_id),
                    )
                finally:
                    connection.close()
                backup_path = os.path.join(self.temp.name, f"{suffix}.sqlite3")
                with self.assertRaises(TaskValidationError):
                    self.store.backup_to(backup_path)
                self.assertFalse(os.path.exists(backup_path))
                connection = self.store._connect()
                try:
                    connection.execute(
                        "UPDATE tasks SET state='queued',attempts=0,lease_owner=NULL,lease_until=NULL WHERE task_id=?",
                        (task.task_id,),
                    )
                finally:
                    connection.close()

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
            lambda claim: replace(claim, step_index=True),
            lambda claim: replace(claim, attempt=True),
            lambda claim: replace(claim, executor_id="attacker"),
            lambda claim: replace(claim, idempotency_key="attacker-key"),
        )
        for attack in tamper:
            with self.subTest(attack=attack):
                self.store.create_for_principal(
                    "alice",
                    [{"tool": "prepare", "input": {"value": "original"}, "max_attempts": 1}],
                    now=NOW,
                )
                claim = self.store.claim_next("worker", now=NOW, principal_tools=frozenset({"prepare"}))
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
        claim = self.store.claim_next("worker", now=NOW, principal_tools=frozenset({"prepare"}))
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

    def test_handler_mutating_nested_input_does_not_mutate_claim_snapshot(self):
        calls = []

        def mutate_nested(data, key, principal):
            data["nested"]["values"].append(2)
            calls.append((principal, data))
            return {"ok": True}

        self.store.create_for_principal(
            "alice",
            [{"tool": "prepare", "input": {"nested": {"values": [1]}}, "max_attempts": 1}],
            now=NOW,
        )
        engine = TaskEngine(
            self.store,
            {},
            "worker",
            principal_handlers={"prepare": mutate_nested},
        )
        result = engine.run_once(now=NOW)

        self.assertEqual(result.state, "succeeded")
        self.assertEqual(result.current_step, 1)
        self.assertEqual(calls, [("alice", {"nested": {"values": [1, 2]}})])
        self.assertEqual(
            self.store.get_for_principal(result.task_id, "alice").state,
            "succeeded",
        )

    def test_claim_rejects_non_native_json_containers_before_handler_dispatch(self):
        calls = []

        class HostileDict(dict):
            def items(self):
                raise AssertionError("custom dict iteration must not execute")

        class HostileList(list):
            def __iter__(self):
                raise AssertionError("custom list iteration must not execute")

        self.store.create_for_principal(
            "alice",
            [{"tool": "prepare", "input": {"nested": {"value": "persisted"}}, "max_attempts": 1}],
            now=NOW,
        )
        claim = self.store.claim_next("worker", now=NOW, principal_tools=frozenset({"prepare"}))
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
        attacks = [
            {"nested": HostileDict(value="persisted")},
            {"nested": {"value": HostileList([1])}},
        ]
        for hostile_input in attacks:
            with self.subTest(container=type(next(iter(hostile_input.values()))).__name__):
                with self.assertRaises(TaskValidationError):
                    engine.execute_claim(replace(claim, input=hostile_input), now=NOW)

        self.assertEqual(calls, [])
        result = engine.execute_claim(claim, now=NOW)
        self.assertEqual(result.state, "succeeded")
        self.assertEqual(calls, [("alice", {"nested": {"value": "persisted"}})])

    def test_expired_claim_is_rejected_before_handler_invocation(self):
        calls = []
        self.store.create_for_principal(
            "alice",
            [{"tool": "prepare", "input": {"value": "original"}, "max_attempts": 2}],
            now=NOW,
        )
        claim = self.store.claim_next("worker", lease_seconds=5, now=NOW, principal_tools=frozenset({"prepare"}))
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
            engine.execute_claim(
                replace(claim, lease_until="2099-01-01T00:00:00+00:00"),
                now=NOW + timedelta(seconds=6),
            )
        self.assertEqual(calls, [])
        self.assertEqual(self.store.get_for_principal(claim.task_id, "alice").state, "running")

    def test_principal_claims_require_principal_aware_handlers(self):
        calls = []
        alice = self.store.create_for_principal(
            "alice", [{"tool": "prepare", "input": {}, "max_attempts": 1}], now=NOW
        )
        generic = TaskEngine(
            self.store,
            {"prepare": lambda data, key: calls.append("generic") or {"ok": True}},
            "worker",
        )
        self.assertIsNone(generic.run_once(now=NOW))
        self.assertEqual(self.store.get_for_principal(alice.task_id, "alice").state, "queued")
        self.assertEqual(calls, [])

        bob = self.store.create_for_principal(
            "bob",
            [{"tool": "prepare", "input": {}, "max_attempts": 1}],
            now=NOW + timedelta(seconds=1),
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
        succeeded_alice = scoped.run_once(now=NOW + timedelta(seconds=2))
        succeeded_bob = scoped.run_once(now=NOW + timedelta(seconds=3))
        self.assertEqual(succeeded_alice.state, "succeeded")
        self.assertEqual(succeeded_bob.state, "succeeded")
        self.assertEqual(calls, ["alice", "bob"])
        self.assertEqual(succeeded_bob.result, ({"principal": "bob"},))

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

    def test_stale_claim_rejected_when_same_executor_reclaims_lease(self):
        task = self.store.create(PLAN, now=NOW)
        old = self.store.claim_next("worker", lease_seconds=5, now=NOW)
        current = self.store.claim_next(
            "worker", lease_seconds=30, now=NOW + timedelta(seconds=6)
        )
        self.assertEqual(current.task_id, task.task_id)
        self.assertEqual(current.executor_id, old.executor_id)
        self.assertEqual(current.attempt, old.attempt + 1)

        record_before = self.store.get(task.task_id)
        events_before = self.store.events(task.task_id)
        handler_calls = []
        engine = TaskEngine(
            self.store,
            {"prepare": lambda data, key: handler_calls.append((data, key)) or {"ok": True}},
            "worker",
        )
        stale_transitions = (
            lambda: self.store.validate_claim(old, now=NOW + timedelta(seconds=7)),
            lambda: self.store.renew_lease(old, now=NOW + timedelta(seconds=7)),
            lambda: self.store.finish_step(
                old, {"stale": True}, now=NOW + timedelta(seconds=7)
            ),
            lambda: self.store.fail_step(old, now=NOW + timedelta(seconds=7)),
            lambda: engine.execute_claim(old, now=NOW + timedelta(seconds=7)),
        )
        for transition in stale_transitions:
            with self.assertRaises(TaskConflictError):
                transition()
            self.assertEqual(self.store.get(task.task_id), record_before)
            self.assertEqual(self.store.events(task.task_id), events_before)
        self.assertEqual(handler_calls, [])

        finished = self.store.finish_step(
            current, {"current": True}, now=NOW + timedelta(seconds=8)
        )
        self.assertEqual(finished.state, "succeeded")
        self.assertEqual(finished.result, ({"current": True},))

    def test_retry_backoff_and_attempt_limit(self):
        task = self.store.create(PLAN, now=NOW)
        claim = self.store.claim_next("worker", now=NOW, principal_tools=frozenset({"prepare"}))
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
        self.assertIsNone(self.store.claim_next("worker", now=NOW, principal_tools=frozenset({"prepare"})))

    def test_cancel_running_task_finishes_current_step_then_stops(self):
        task = self.store.create(PLAN, now=NOW)
        claim = self.store.claim_next("worker", now=NOW, principal_tools=frozenset({"prepare"}))
        self.store.request_cancel(task.task_id, now=NOW + timedelta(seconds=1))
        result = self.store.finish_step(claim, {"completed": True}, now=NOW + timedelta(seconds=2))
        self.assertEqual(result.state, "cancelled")
        self.assertEqual(result.current_step, 1)
        self.assertEqual(result.result, ({"completed": True},))

    def test_events_are_durable_and_ordered(self):
        task = self.store.create(PLAN, now=NOW)
        self.store.claim_next("worker", now=NOW, principal_tools=frozenset({"prepare"}))
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
        claim = self.store.claim_next("worker", now=NOW, principal_tools=frozenset({"prepare"}))
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


    def test_plan_rejects_scalar_subclasses_before_custom_methods(self):
        class HostileString(str):
            def __iter__(self):
                raise AssertionError("custom string iteration must not execute")

        class HostileInt(int):
            def __repr__(self):
                raise AssertionError("custom integer representation must not execute")

        invalid = [
            [{"tool": HostileString("prepare"), "input": {}}],
            [{"tool": "prepare", "input": {"value": HostileString("payload")}}],
            [{"tool": "prepare", "input": {"value": HostileInt(7)}}],
        ]
        for plan in invalid:
            with self.subTest(value_type=type(plan[0].get("tool"))):
                with self.assertRaises(TaskValidationError):
                    self.store.create(plan, now=NOW)


    def test_live_lease_can_be_renewed_for_long_handler(self):
        self.store.create([{"tool": "prepare", "input": {}, "max_attempts": 2}], now=NOW)
        claim = self.store.claim_next("worker", lease_seconds=5, now=NOW, principal_tools=frozenset({"prepare"}))
        renewed = self.store.renew_lease(
            claim, lease_seconds=60, now=NOW + timedelta(seconds=4)
        )
        self.assertGreater(
            datetime.fromisoformat(renewed.lease_until),
            datetime.fromisoformat(claim.lease_until),
        )
        result = self.store.finish_step(
            renewed, {"completed": True}, now=NOW + timedelta(seconds=20)
        )
        self.assertEqual(result.state, "succeeded")

    def test_expired_lease_cannot_be_renewed(self):
        self.store.create(PLAN, now=NOW)
        claim = self.store.claim_next("worker-a", lease_seconds=5, now=NOW)
        with self.assertRaises(TaskConflictError):
            self.store.renew_lease(
                replace(claim, lease_until="2099-01-01T00:00:00+00:00"),
                lease_seconds=60,
                now=NOW + timedelta(seconds=6),
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
            lambda claim: replace(claim, step_index=claim.step_index + 1),
            lambda claim: replace(claim, step_index=True),
            lambda claim: replace(claim, attempt=True),
            lambda claim: replace(claim, executor_id="attacker"),
            lambda claim: replace(claim, idempotency_key="forged-key"),
        )
        for method_name in engine_methods:
            for attack in attacks:
                with self.subTest(method=method_name, attack=attack):
                    task = self.store.create_for_principal(
                        "alice",
                        [{"tool": "prepare", "input": {"value": "original"}, "max_attempts": 2}],
                        now=NOW,
                    )
                    claim = self.store.claim_next("worker", now=NOW, principal_tools=frozenset({"prepare"}))
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

    def test_claim_text_fields_reject_string_subclasses_before_comparison(self):
        class HostileString(str):
            def __eq__(self, other):
                raise AssertionError("custom claim string comparison must not execute")

            def __ne__(self, other):
                raise AssertionError("custom claim string comparison must not execute")

        task = self.store.create_for_principal(
            "alice",
            [{"tool": "prepare", "input": {"value": "original"}, "max_attempts": 2}],
            now=NOW,
        )
        claim = self.store.claim_next("worker", now=NOW, principal_tools=frozenset({"prepare"}))
        attacks = (
            replace(claim, idempotency_key=HostileString(claim.idempotency_key)),
            replace(claim, tool=HostileString(claim.tool)),
            replace(claim, principal_id=HostileString("alice")),
        )
        for forged in attacks:
            with self.subTest(field="claim text metadata"):
                with self.assertRaises(TaskValidationError):
                    self.store.renew_lease(forged, lease_seconds=60, now=NOW)
                self.assertEqual(
                    self.store.get_for_principal(task.task_id, "alice").state,
                    "running",
                )

    def test_direct_claim_transitions_reject_nested_custom_input_objects(self):
        class HostileDict(dict):
            def __eq__(self, other):
                raise AssertionError("custom nested dictionary comparison must not execute")

        class HostileString(str):
            def __eq__(self, other):
                raise AssertionError("custom nested scalar comparison must not execute")

        attacks = (
            {"nested": HostileDict(value="original")},
            {"nested": {"value": HostileString("original")}},
        )
        for method_name in ("validate_claim", "finish_step", "fail_step"):
            for hostile_input in attacks:
                with self.subTest(method=method_name, hostile_type=type(hostile_input["nested"]).__name__):
                    task = self.store.create_for_principal(
                        "alice",
                        [{"tool": "prepare", "input": {"nested": {"value": "original"}}, "max_attempts": 2}],
                        now=NOW,
                    )
                    claim = self.store.claim_next("worker", now=NOW, principal_tools=frozenset({"prepare"}))
                    forged = replace(claim, input=hostile_input)
                    with self.assertRaises(TaskValidationError):
                        if method_name == "validate_claim":
                            self.store.validate_claim(forged, now=NOW)
                        elif method_name == "finish_step":
                            self.store.finish_step(forged, {"ok": True}, now=NOW)
                        else:
                            self.store.fail_step(forged, now=NOW)
                    self.assertEqual(
                        self.store.get_for_principal(task.task_id, "alice").state,
                        "running",
                    )

    def test_public_claim_apis_reject_taskclaim_subclasses_before_field_access(self):
        claim_fields = {
            "task_id", "executor_id", "step_index", "attempt",
            "idempotency_key", "tool", "input", "lease_until", "principal_id",
        }

        class HostileTaskClaim(TaskClaim):
            __slots__ = ()

            def __getattribute__(self, name):
                if name in claim_fields:
                    raise AssertionError("TaskClaim subclass field access must not execute")
                return super().__getattribute__(name)

        methods = (
            "validate_claim", "renew_lease", "finish_step", "fail_step", "execute_claim"
        )
        handler_calls = []
        engine = TaskEngine(
            self.store,
            {},
            "worker",
            principal_handlers={
                "prepare": lambda data, key, principal: (
                    handler_calls.append((data, key, principal)) or {"ok": True}
                )
            },
        )
        for method_name in methods:
            with self.subTest(method=method_name):
                task = self.store.create_for_principal(
                    "alice",
                    [{"tool": "prepare", "input": {"value": "original"}, "max_attempts": 2}],
                    now=NOW,
                )
                claim = self.store.claim_next("worker", now=NOW, principal_tools=frozenset({"prepare"}))
                hostile = HostileTaskClaim(
                    claim.task_id, claim.executor_id, claim.step_index, claim.attempt,
                    claim.idempotency_key, claim.tool, claim.input, claim.lease_until,
                    claim.principal_id,
                )
                before_record = self.store.get(task.task_id)
                before_events = self.store.events(task.task_id)
                connection = self.store._connect()
                try:
                    before_lease_state = connection.execute(
                        "SELECT state,lease_owner,lease_until,current_step,attempts,"
                        "results_json,error_code FROM tasks WHERE task_id=?",
                        (task.task_id,),
                    ).fetchone()
                finally:
                    connection.close()

                with self.assertRaises(TaskValidationError):
                    if method_name == "validate_claim":
                        self.store.validate_claim(hostile, now=NOW)
                    elif method_name == "renew_lease":
                        self.store.renew_lease(hostile, lease_seconds=60, now=NOW)
                    elif method_name == "finish_step":
                        self.store.finish_step(hostile, {"ok": True}, now=NOW)
                    elif method_name == "fail_step":
                        self.store.fail_step(hostile, now=NOW)
                    else:
                        engine.execute_claim(hostile, now=NOW)

                self.assertEqual(self.store.get(task.task_id), before_record)
                self.assertEqual(self.store.events(task.task_id), before_events)
                self.assertEqual(handler_calls, [])
                connection = self.store._connect()
                try:
                    after_lease_state = connection.execute(
                        "SELECT state,lease_owner,lease_until,current_step,attempts,"
                        "results_json,error_code FROM tasks WHERE task_id=?",
                        (task.task_id,),
                    ).fetchone()
                finally:
                    connection.close()
                self.assertEqual(after_lease_state, before_lease_state)


    def test_execute_claim_rejects_hostile_executor_id_before_comparison(self):
        class HostileString(str):
            def __eq__(self, other):
                raise AssertionError("hostile executor equality must not execute")

            def __ne__(self, other):
                raise AssertionError("hostile executor inequality must not execute")

        task = self.store.create_for_principal(
            "alice",
            [{"tool": "prepare", "input": {"value": "original"}, "max_attempts": 2}],
            now=NOW,
        )
        claim = self.store.claim_next("worker", now=NOW, principal_tools=frozenset({"prepare"}))
        hostile = replace(claim, executor_id=HostileString("worker"))
        handler_calls = []
        engine = TaskEngine(
            self.store,
            {},
            "worker",
            principal_handlers={
                "prepare": lambda data, key, principal: (
                    handler_calls.append((data, key, principal)) or {"ok": True}
                )
            },
        )
        before_record = self.store.get(task.task_id)
        before_events = self.store.events(task.task_id)

        with self.assertRaises(TaskValidationError):
            engine.execute_claim(hostile, now=NOW)

        self.assertEqual(self.store.get(task.task_id), before_record)
        self.assertEqual(self.store.events(task.task_id), before_events)
        self.assertEqual(handler_calls, [])


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


    def test_legacy_worker_leaves_principal_task_for_principal_aware_worker(self):
        created_at = datetime.now(timezone.utc)
        task = self.store.create_for_principal(
            "alice",
            [{"tool": "prepare", "input": {"value": "private"}, "max_attempts": 2}],
            now=created_at,
        )
        legacy_calls = []
        legacy_engine = TaskEngine(
            self.store,
            {"prepare": lambda data, key: legacy_calls.append((data, key)) or {"legacy": True}},
            "legacy-worker",
        )
        before_events = self.store.events(task.task_id)

        self.assertIsNone(TaskWorker(legacy_engine).run_once())
        connection = self.store._connect()
        try:
            state_after_legacy_poll = connection.execute(
                "SELECT state,attempts,lease_owner,lease_until FROM tasks WHERE task_id=?",
                (task.task_id,),
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(state_after_legacy_poll, ("queued", 0, None, None))
        self.assertEqual(self.store.events(task.task_id), before_events)
        self.assertEqual(legacy_calls, [])

        principal_calls = []
        principal_engine = TaskEngine(
            self.store,
            {},
            "principal-worker",
            principal_handlers={
                "prepare": lambda data, key, principal: (
                    principal_calls.append((data, key, principal)) or {"principal": principal}
                )
            },
        )
        result = TaskWorker(principal_engine).run_once()
        self.assertEqual(result.state, "succeeded")
        self.assertEqual([call[2] for call in principal_calls], ["alice"])

    def test_legacy_engine_does_not_reclaim_expired_principal_lease(self):
        task = self.store.create_for_principal(
            "alice",
            [{"tool": "prepare", "input": {"value": "private"}, "max_attempts": 2}],
            now=NOW,
        )
        original = self.store.claim_next(
            "principal-worker",
            lease_seconds=5,
            now=NOW,
            principal_tools=frozenset({"prepare"}),
        )
        self.assertEqual(original.task_id, task.task_id)
        before_events = self.store.events(task.task_id)

        legacy_engine = TaskEngine(
            self.store,
            {"prepare": lambda data, key: {"legacy": True}},
            "legacy-worker",
        )
        self.assertIsNone(legacy_engine.run_once(now=NOW + timedelta(seconds=6)))
        connection = self.store._connect()
        try:
            state_after_legacy_poll = connection.execute(
                "SELECT state,attempts,lease_owner,lease_until FROM tasks WHERE task_id=?",
                (task.task_id,),
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(
            state_after_legacy_poll,
            ("running", 1, "principal-worker", original.lease_until),
        )
        self.assertEqual(self.store.events(task.task_id), before_events)

        principal_engine = TaskEngine(
            self.store,
            {},
            "principal-worker-2",
            principal_handlers={"prepare": lambda data, key, principal: {"principal": principal}},
        )
        result = principal_engine.run_once(now=NOW + timedelta(seconds=6))
        self.assertEqual(result.state, "succeeded")

    def test_unsupported_worker_processes_cancelled_principal_task_without_handler(self):
        task = self.store.create_for_principal(
            "alice",
            [{"tool": "prepare", "input": {"value": "private"}, "max_attempts": 2}],
            now=NOW,
        )
        claim = self.store.claim_next(
            "principal-worker",
            lease_seconds=5,
            now=NOW,
            principal_tools=frozenset({"prepare"}),
        )
        self.assertEqual(claim.task_id, task.task_id)
        self.store.request_cancel(task.task_id, now=NOW + timedelta(seconds=1))

        handler_calls = []
        legacy_engine = TaskEngine(
            self.store,
            {"prepare": lambda data, key: handler_calls.append((data, key)) or {"legacy": True}},
            "legacy-worker",
        )
        self.assertIsNone(legacy_engine.run_once(now=NOW + timedelta(seconds=6)))

        record = self.store.get_for_principal(task.task_id, "alice")
        self.assertEqual(record.state, "cancelled")
        self.assertEqual(record.attempts, 1)
        self.assertEqual(self.store.events(task.task_id)[-1]["state"], "cancelled")
        self.assertEqual(handler_calls, [])

    def test_unsupported_worker_fails_exhausted_principal_lease_without_handler(self):
        task = self.store.create_for_principal(
            "alice",
            [{"tool": "prepare", "input": {"value": "private"}, "max_attempts": 1}],
            now=NOW,
        )
        claim = self.store.claim_next(
            "principal-worker",
            lease_seconds=5,
            now=NOW,
            principal_tools=frozenset({"prepare"}),
        )
        self.assertEqual(claim.task_id, task.task_id)

        handler_calls = []
        legacy_engine = TaskEngine(
            self.store,
            {"prepare": lambda data, key: handler_calls.append((data, key)) or {"legacy": True}},
            "legacy-worker",
        )
        self.assertIsNone(legacy_engine.run_once(now=NOW + timedelta(seconds=6)))

        record = self.store.get_for_principal(task.task_id, "alice")
        self.assertEqual(record.state, "failed")
        self.assertEqual(record.error_code, "lease_expired")
        self.assertEqual(record.attempts, 1)
        self.assertEqual(self.store.events(task.task_id)[-1]["error_code"], "lease_expired")
        self.assertEqual(handler_calls, [])

    def test_legacy_worker_surfaces_corrupt_principal_plan_without_handlers(self):
        task = self.store.create_for_principal(
            "alice",
            [{"tool": "unsupported", "input": {}, "max_attempts": 1}],
            now=NOW,
        )
        before_events = self.store.events(task.task_id)
        connection = self.store._connect()
        try:
            connection.execute(
                "UPDATE tasks SET plan_json=? WHERE task_id=?",
                ("{broken", task.task_id),
            )
        finally:
            connection.close()

        legacy_engine = TaskEngine(self.store, {}, "legacy-worker")
        with self.assertRaisesRegex(TaskValidationError, "persisted task plan is corrupt"):
            legacy_engine.run_once(now=NOW)

        connection = self.store._connect()
        try:
            state = connection.execute(
                "SELECT state,attempts,lease_owner,lease_until FROM tasks WHERE task_id=?",
                (task.task_id,),
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(state, ("queued", 0, None, None))
        self.assertEqual(self.store.events(task.task_id), before_events)

    def test_principal_worker_skips_unsupported_queue_prefix_beyond_claim_batch_limit(self):
        unsupported_tasks = []
        for index in range(40):
            unsupported_tasks.append(
                self.store.create_for_principal(
                    f"owner-{index}",
                    [{"tool": "unsupported", "input": {"index": index}, "max_attempts": 1}],
                    now=NOW + timedelta(seconds=index),
                )
            )
        supported_task = self.store.create_for_principal(
            "alice",
            [{"tool": "prepare", "input": {"value": "supported"}, "max_attempts": 1}],
            now=NOW + timedelta(seconds=40),
        )
        engine = TaskEngine(
            self.store,
            {},
            "capable-worker",
            principal_handlers={"prepare": lambda data, key, principal: {"principal": principal}},
        )

        result = engine.run_once(now=NOW + timedelta(seconds=41))
        self.assertEqual(result.task_id, supported_task.task_id)
        self.assertEqual(result.state, "succeeded")
        for index, task in enumerate(unsupported_tasks):
            with self.subTest(task_id=task.task_id):
                record = self.store.get_for_principal(task.task_id, f"owner-{index}")
                self.assertEqual(record.state, "queued")
                self.assertEqual(record.attempts, 0)


    def test_low_level_claim_requires_explicit_principal_tool_allowlist(self):
        task = self.store.create_for_principal(
            "alice",
            [{"tool": "prepare", "input": {}, "max_attempts": 1}],
            now=NOW,
        )

        self.assertIsNone(self.store.claim_next("legacy-caller", now=NOW))
        self.assertEqual(
            self.store.get_for_principal(task.task_id, "alice").state,
            "queued",
        )

        claim = self.store.claim_next(
            "principal-caller",
            now=NOW,
            principal_tools=frozenset({"prepare"}),
        )
        self.assertEqual(claim.task_id, task.task_id)


    def test_corrupt_running_attempts_rejected_by_every_claim_transition(self):
        handler_calls = []
        engine = TaskEngine(
            self.store,
            {"prepare": lambda data, key: handler_calls.append((data, key)) or {"ok": True}},
            "worker",
        )
        transitions = ("validate", "renew", "finish", "fail", "execute")

        for offset, transition in enumerate(transitions):
            with self.subTest(transition=transition):
                now = NOW + timedelta(minutes=offset)
                task = self.store.create(
                    [{"tool": "prepare", "input": {}, "max_attempts": 2}],
                    now=now,
                )
                claim = self.store.claim_next(
                    "worker", lease_seconds=60, now=now
                )
                self.assertEqual(claim.task_id, task.task_id)

                connection = self.store._connect()
                try:
                    connection.execute(
                        "UPDATE tasks SET attempts=3 WHERE task_id=?",
                        (task.task_id,),
                    )
                finally:
                    connection.close()

                # Match the corrupt row deliberately. The shared validator must
                # reject its lifecycle invariant, not merely detect a stale claim.
                corrupt_claim = replace(claim, attempt=3)
                record_before = self.store.get(task.task_id)
                events_before = self.store.events(task.task_id)
                operations = {
                    "validate": lambda: self.store.validate_claim(
                        corrupt_claim, now=now + timedelta(seconds=1)
                    ),
                    "renew": lambda: self.store.renew_lease(
                        corrupt_claim, now=now + timedelta(seconds=1)
                    ),
                    "finish": lambda: self.store.finish_step(
                        corrupt_claim, {"done": True}, now=now + timedelta(seconds=1)
                    ),
                    "fail": lambda: self.store.fail_step(
                        corrupt_claim, now=now + timedelta(seconds=1)
                    ),
                    "execute": lambda: engine.execute_claim(
                        corrupt_claim, now=now + timedelta(seconds=1)
                    ),
                }
                with self.assertRaisesRegex(
                    TaskValidationError, "persisted task attempts are corrupt"
                ):
                    operations[transition]()

                self.assertEqual(self.store.get(task.task_id), record_before)
                self.assertEqual(self.store.events(task.task_id), events_before)
                self.assertEqual(handler_calls, [])


    def test_corrupt_attempt_metadata_fails_closed_before_capability_filter(self):
        cases = (
            ("queued", -1, 0),
            ("queued", 1, 0),
            ("queued", 0.5, 0),
            ("queued", "not-an-integer", 0),
            ("retry_wait", 0, 0),
            ("retry_wait", 2, 0),
            ("running", 0, 0),
            ("running", 3, 0),
            ("running", 1.5, 0),
            ("queued", 1, 1),
        )
        handler_calls = []
        engine = TaskEngine(
            self.store,
            {},
            "capable-worker",
            principal_handlers={
                "prepare": lambda data, key, principal: handler_calls.append(principal)
                or {"ok": True}
            },
        )

        for offset, (state, attempts, current_step) in enumerate(cases):
            with self.subTest(state=state, attempts=attempts):
                task = self.store.create_for_principal(
                    "alice",
                    [{"tool": "unsupported", "input": {}, "max_attempts": 2}],
                    now=NOW + timedelta(seconds=offset),
                )
                events_before = self.store.events(task.task_id)
                connection = self.store._connect()
                try:
                    lease_owner = "expired-worker" if state == "running" else None
                    lease_until = (
                        (NOW - timedelta(seconds=1)).isoformat()
                        if state == "running"
                        else None
                    )
                    connection.execute(
                        "UPDATE tasks SET state=?,attempts=?,current_step=?,lease_owner=?,lease_until=?,available_at=? WHERE task_id=?",
                        (state, attempts, current_step, lease_owner, lease_until, NOW.isoformat(), task.task_id),
                    )
                finally:
                    connection.close()

                with self.assertRaisesRegex(
                    TaskValidationError, "persisted task attempts are corrupt"
                ):
                    engine.run_once(now=NOW + timedelta(seconds=20))

                connection = self.store._connect()
                try:
                    row = connection.execute(
                        "SELECT state,attempts,lease_owner,lease_until FROM tasks WHERE task_id=?",
                        (task.task_id,),
                    ).fetchone()
                    connection.execute(
                        "UPDATE tasks SET state='queued',attempts=0,current_step=0,lease_owner=NULL,lease_until=NULL WHERE task_id=?",
                        (task.task_id,),
                    )
                finally:
                    connection.close()
                self.assertEqual(row, (state, attempts, lease_owner, lease_until))
                self.assertEqual(self.store.events(task.task_id), events_before)
                self.assertEqual(handler_calls, [])


    def test_corrupt_principal_plan_fails_closed_before_claiming_later_work(self):
        corrupt = self.store.create_for_principal(
            "corrupt-owner",
            [{"tool": "prepare", "input": {}, "max_attempts": 1}],
            now=NOW,
        )
        valid = self.store.create_for_principal(
            "alice",
            [{"tool": "prepare", "input": {}, "max_attempts": 1}],
            now=NOW + timedelta(seconds=1),
        )
        corrupt_events_before = self.store.events(corrupt.task_id)
        valid_events_before = self.store.events(valid.task_id)

        connection = self.store._connect()
        try:
            connection.execute(
                "UPDATE tasks SET plan_json=? WHERE task_id=?",
                ("{broken", corrupt.task_id),
            )
        finally:
            connection.close()

        engine = TaskEngine(
            self.store,
            {},
            "capable-worker",
            principal_handlers={
                "prepare": lambda data, key, principal: {"principal": principal}
            },
        )
        with self.assertRaisesRegex(TaskValidationError, "persisted task plan is corrupt"):
            engine.run_once(now=NOW + timedelta(seconds=2))

        connection = self.store._connect()
        try:
            corrupt_state = connection.execute(
                "SELECT state,attempts,lease_owner,lease_until FROM tasks WHERE task_id=?",
                (corrupt.task_id,),
            ).fetchone()
            valid_state = connection.execute(
                "SELECT state,attempts,lease_owner,lease_until FROM tasks WHERE task_id=?",
                (valid.task_id,),
            ).fetchone()
        finally:
            connection.close()

        self.assertEqual(corrupt_state, ("queued", 0, None, None))
        self.assertEqual(valid_state, ("queued", 0, None, None))
        self.assertEqual(self.store.events(corrupt.task_id), corrupt_events_before)
        self.assertEqual(self.store.events(valid.task_id), valid_events_before)


    def test_valid_json_with_invalid_principal_plan_is_not_hidden_by_capability_filter(self):
        corrupt = self.store.create_for_principal(
            "corrupt-owner",
            [{"tool": "prepare", "input": {}, "max_attempts": 1}],
            now=NOW,
        )
        valid = self.store.create_for_principal(
            "alice",
            [{"tool": "prepare", "input": {}, "max_attempts": 1}],
            now=NOW + timedelta(seconds=1),
        )
        corrupt_events_before = self.store.events(corrupt.task_id)
        valid_events_before = self.store.events(valid.task_id)

        connection = self.store._connect()
        try:
            # Valid JSON, but not a valid normalized task step: max_attempts is absent.
            # Its unsupported tool name would previously be filtered out by SQL,
            # hiding the persisted-plan integrity failure from this capable worker.
            connection.execute(
                "UPDATE tasks SET plan_json=? WHERE task_id=?",
                ('[{"input":{},"tool":"unsupported"}]', corrupt.task_id),
            )
        finally:
            connection.close()

        engine = TaskEngine(
            self.store,
            {},
            "capable-worker",
            principal_handlers={
                "prepare": lambda data, key, principal: {"principal": principal}
            },
        )
        with self.assertRaisesRegex(TaskValidationError, "persisted task plan is corrupt"):
            engine.run_once(now=NOW + timedelta(seconds=2))

        connection = self.store._connect()
        try:
            corrupt_state = connection.execute(
                "SELECT state,attempts,lease_owner,lease_until FROM tasks WHERE task_id=?",
                (corrupt.task_id,),
            ).fetchone()
            valid_state = connection.execute(
                "SELECT state,attempts,lease_owner,lease_until FROM tasks WHERE task_id=?",
                (valid.task_id,),
            ).fetchone()
        finally:
            connection.close()

        self.assertEqual(corrupt_state, ("queued", 0, None, None))
        self.assertEqual(valid_state, ("queued", 0, None, None))
        self.assertEqual(self.store.events(corrupt.task_id), corrupt_events_before)
        self.assertEqual(self.store.events(valid.task_id), valid_events_before)


    def test_post_claim_later_step_corruption_rejected_by_all_claim_paths(self):
        handler_calls = []

        def handler(data, key, principal):
            handler_calls.append((data, key, principal))
            return {"ok": True}

        engine = TaskEngine(
            self.store,
            {},
            "worker",
            principal_handlers={"prepare": handler, "finish": handler},
        )
        corrupt_plan = (
            '[{"input":{"value":"one"},"max_attempts":2,"tool":"prepare"},'
            '{"input":{"value":"two"},"max_attempts":0,"tool":"finish"}]'
        )
        actions = (
            "validate_claim",
            "renew_lease",
            "finish_step",
            "fail_step",
            "execute_claim",
        )

        for offset, action in enumerate(actions):
            with self.subTest(action=action):
                created_at = NOW + timedelta(seconds=offset * 10)
                task = self.store.create_for_principal("alice", PLAN, now=created_at)
                claim = self.store.claim_next(
                    "worker",
                    now=created_at,
                    principal_tools=frozenset({"prepare", "finish"}),
                )
                self.assertEqual(claim.task_id, task.task_id)

                connection = self.store._connect()
                try:
                    connection.execute(
                        "UPDATE tasks SET plan_json=? WHERE task_id=?",
                        (corrupt_plan, task.task_id),
                    )
                    before = connection.execute(
                        """SELECT state,current_step,attempts,lease_owner,lease_until,
                        results_json,error_code,available_at,plan_json
                        FROM tasks WHERE task_id=?""",
                        (task.task_id,),
                    ).fetchone()
                finally:
                    connection.close()
                events_before = self.store.events(task.task_id)
                transition_time = created_at + timedelta(seconds=1)

                with self.assertRaisesRegex(
                    TaskValidationError, "persisted task plan is corrupt"
                ):
                    if action == "validate_claim":
                        self.store.validate_claim(claim, now=transition_time)
                    elif action == "renew_lease":
                        self.store.renew_lease(claim, now=transition_time)
                    elif action == "finish_step":
                        self.store.finish_step(
                            claim, {"completed": True}, now=transition_time
                        )
                    elif action == "fail_step":
                        self.store.fail_step(claim, now=transition_time)
                    else:
                        engine.execute_claim(claim, now=transition_time)

                connection = self.store._connect()
                try:
                    after = connection.execute(
                        """SELECT state,current_step,attempts,lease_owner,lease_until,
                        results_json,error_code,available_at,plan_json
                        FROM tasks WHERE task_id=?""",
                        (task.task_id,),
                    ).fetchone()
                finally:
                    connection.close()

                self.assertEqual(after, before)
                self.assertEqual(self.store.events(task.task_id), events_before)

        self.assertEqual(handler_calls, [])


if __name__ == "__main__":
    unittest.main()
