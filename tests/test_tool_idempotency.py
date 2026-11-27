"""Tests for tool-call idempotency: at-most-once execution with safe retry."""

import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone

from capri_runtime.idempotency import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
    IdempotencyReplay,
    InMemoryIdempotencyStore,
    SQLiteIdempotencyStore,
)
from capri_runtime.tools import (
    ExecutionContext,
    ToolExecutor,
    ToolRegistry,
    ToolSpec,
    ToolValidationError,
)
from capri_runtime.tool_bridge import (
    ToolBridgeValidationError,
    ToolCallOutcome,
    ToolCallRequest,
    ToolExecutionBridge,
)
from capri_runtime.tools import InMemoryAuditSink


def _ctx(principal="p1", perms=("demo:run",)):
    return ExecutionContext(principal_id=principal, permissions=frozenset(perms))


def _registry_with_counter(counter, fail=False):
    reg = ToolRegistry()
    captured = {}

    def handler(args, cancel=None):
        counter[0] += 1
        captured["args"] = args
        if fail:
            raise RuntimeError("boom")
        return {"echo": args.get("x")}

    reg.register(
        ToolSpec(
            name="echo",
            permission="demo:run",
            argument_schema={
                "type": "object",
                "properties": {"x": {"type": "string"}},
                "required": ["x"],
                "additionalProperties": False,
            },
        ),
        handler,
    )
    return reg, captured


class IdempotencyStoreTests(unittest.TestCase):
    def test_in_memory_reserve_then_complete(self):
        store = InMemoryIdempotencyStore()
        self.assertIsNone(store.check_or_reserve("p", "k", "f1", time.time(), 60))
        store.complete("p", "k", "succeeded", '{"ok":1}', None, time.time())
        rec = store.check_or_reserve("p", "k", "f1", time.time(), 60)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.status, "succeeded")
        self.assertEqual(rec.result_json, '{"ok":1}')

    def test_in_memory_returns_completed_record_for_fingerprint_comparison(self):
        # The store returns the completed record; the executor compares fingerprints
        # and raises IdempotencyConflictError. The store itself is fingerprint-agnostic.
        store = InMemoryIdempotencyStore()
        store.check_or_reserve("p", "k", "f1", time.time(), 60)
        store.complete("p", "k", "succeeded", "{}", None, time.time())
        rec = store.check_or_reserve("p", "k", "f2", time.time(), 60)  # different fingerprint
        self.assertIsNotNone(rec)
        self.assertEqual(rec.status, "succeeded")
        self.assertEqual(rec.fingerprint, "f1")  # original fingerprint preserved

    def test_in_memory_in_progress_blocks(self):
        store = InMemoryIdempotencyStore()
        store.check_or_reserve("p", "k", "f1", time.time(), 60)  # reserved, not completed
        with self.assertRaises(IdempotencyInProgressError):
            store.check_or_reserve("p", "k", "f1", time.time(), 60)

    def test_in_memory_expiry_reclaims_key(self):
        store = InMemoryIdempotencyStore(clock=lambda: 1_000_000.0)
        store.check_or_reserve("p", "k", "f1", 1_000_000.0, 10)
        store.complete("p", "k", "succeeded", "{}", None, 1_000_000.0)
        # far in the future relative to ttl -> expired
        self.assertIsNone(store.check_or_reserve("p", "k", "f1", 1_000_100.0, 10))

    def test_sqlite_persists_across_reopen(self):
        with tempfile.TemporaryDirectory() as d:
            path = f"{d}/idem.sqlite"
            s1 = SQLiteIdempotencyStore(path)
            self.assertIsNone(s1.check_or_reserve("p", "k", "f1", time.time(), 60))
            s1.complete("p", "k", "succeeded", '{"v":9}', None, time.time())
            s2 = SQLiteIdempotencyStore(path)
            rec = s2.check_or_reserve("p", "k", "f1", time.time(), 60)
            self.assertIsNotNone(rec)
            self.assertEqual(rec.result_json, '{"v":9}')

    def test_sqlite_in_progress_blocks_concurrent(self):
        with tempfile.TemporaryDirectory() as d:
            store = SQLiteIdempotencyStore(f"{d}/idem.sqlite")
            store.check_or_reserve("p", "k", "f1", time.time(), 60)
            with self.assertRaises(IdempotencyInProgressError):
                store.check_or_reserve("p", "k", "f1", time.time(), 60)


class ExecutorIdempotencyTests(unittest.TestCase):
    def _exec(self, store):
        counter = [0]
        reg, _ = _registry_with_counter(counter)
        ex = ToolExecutor(reg, InMemoryAuditSink(), idempotency_store=store)
        return ex, counter

    def test_repeat_key_same_args_invokes_handler_once(self):
        store = InMemoryIdempotencyStore()
        ex, counter = self._exec(store)
        ctx = _ctx()
        r1 = ex.execute("echo", {"x": "a"}, ctx, idempotency_key="k1")
        # A replay raises IdempotencyReplay carrying the memoized result; the
        # handler must NOT run again.
        with self.assertRaises(IdempotencyReplay) as cm:
            ex.execute("echo", {"x": "a"}, ctx, idempotency_key="k1")
        self.assertEqual(counter[0], 1)  # handler ran exactly once
        self.assertEqual(cm.exception.result, r1)
        self.assertEqual(cm.exception.status, "succeeded")
        self.assertEqual(r1, {"echo": "a"})

    def test_replay_is_byte_identical(self):
        store = InMemoryIdempotencyStore()
        ex, _ = self._exec(store)
        ctx = _ctx()
        first = ex.execute("echo", {"x": "nested-value"}, ctx, idempotency_key="k")
        with self.assertRaises(IdempotencyReplay) as cm:
            ex.execute("echo", {"x": "nested-value"}, ctx, idempotency_key="k")
        self.assertEqual(first, cm.exception.result)

    def test_conflicting_key_raises(self):
        store = InMemoryIdempotencyStore()
        ex, _ = self._exec(store)
        ctx = _ctx()
        ex.execute("echo", {"x": "a"}, ctx, idempotency_key="k")
        with self.assertRaises(IdempotencyConflictError):
            ex.execute("echo", {"x": "DIFFERENT"}, ctx, idempotency_key="k")

    def test_failed_call_is_memoized_and_replays_failure(self):
        store = InMemoryIdempotencyStore()
        counter = [0]
        reg, _ = _registry_with_counter(counter, fail=True)
        ex = ToolExecutor(reg, InMemoryAuditSink(), idempotency_store=store)
        ctx = _ctx()
        with self.assertRaises(Exception):
            ex.execute("echo", {"x": "a"}, ctx, idempotency_key="k")
        self.assertEqual(counter[0], 1)
        # Replay reproduces the failure without re-invoking the handler.
        with self.assertRaises(Exception):
            ex.execute("echo", {"x": "a"}, ctx, idempotency_key="k")
        self.assertEqual(counter[0], 1)

    def test_no_key_disables_idempotency(self):
        store = InMemoryIdempotencyStore()
        ex, counter = self._exec(store)
        ctx = _ctx()
        ex.execute("echo", {"x": "a"}, ctx)  # no key
        ex.execute("echo", {"x": "a"}, ctx)  # no key
        self.assertEqual(counter[0], 2)

    def test_principal_isolation(self):
        store = InMemoryIdempotencyStore()
        ex, counter = self._exec(store)
        ex.execute("echo", {"x": "a"}, _ctx("p1"), idempotency_key="k")
        ex.execute("echo", {"x": "a"}, _ctx("p2"), idempotency_key="k")
        self.assertEqual(counter[0], 2)

    def test_expired_key_reused(self):
        # The executor passes real time as now_epoch, so expire the stored record
        # directly to simulate the 24h TTL elapsing, then confirm the handler
        # runs again (the key is reclaimed rather than replayed).
        import dataclasses
        import datetime

        store = InMemoryIdempotencyStore()
        ex, counter = self._exec(store)
        ctx = _ctx()
        ex.execute("echo", {"x": "a"}, ctx, idempotency_key="k")
        self.assertEqual(counter[0], 1)
        past = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=25)
        rec = store._rows[("p1", "k")]  # noqa: SLF001 - white-box expiry setup
        store._rows[("p1", "k")] = dataclasses.replace(rec, expires_at=past.isoformat())  # noqa: SLF001
        ex.execute("echo", {"x": "a"}, ctx, idempotency_key="k")
        self.assertEqual(counter[0], 2)


class BridgeIdempotencyTests(unittest.TestCase):
    def _bridge(self, store):
        counter = [0]
        reg, _ = _registry_with_counter(counter)
        ex = ToolExecutor(reg, InMemoryAuditSink(), idempotency_store=store)
        return ToolExecutionBridge(ex), counter

    def test_replay_marks_outcome_replayed(self):
        store = InMemoryIdempotencyStore()
        bridge, counter = self._bridge(store)
        ctx = _ctx()
        req = ToolCallRequest("c1", "echo", {"x": "a"}, idempotency_key="k")
        o1 = bridge.execute_batch([req], ctx)
        o2 = bridge.execute_batch([req], ctx)
        self.assertEqual(counter[0], 1)
        self.assertEqual(o1[0].status, "succeeded")
        self.assertEqual(o2[0].status, "succeeded")
        self.assertTrue(o2[0].replayed)

    def test_conflict_outcome(self):
        store = InMemoryIdempotencyStore()
        bridge, _ = self._bridge(store)
        ctx = _ctx()
        bridge.execute_batch([ToolCallRequest("c1", "echo", {"x": "a"}, idempotency_key="k")], ctx)
        out = bridge.execute_batch(
            [ToolCallRequest("c2", "echo", {"x": "other"}, idempotency_key="k")], ctx
        )
        self.assertEqual(out[0].status, "idempotency_conflict")
        self.assertEqual(out[0].error_code, "idempotency_key_reused")

    def test_empty_idempotency_key_rejected_by_bridge(self):
        store = InMemoryIdempotencyStore()
        bridge, _ = self._bridge(store)
        with self.assertRaises(ToolBridgeValidationError):
            bridge.execute_batch(
                [ToolCallRequest("c1", "echo", {"x": "a"}, idempotency_key="")], _ctx()
            )


class ConcurrentIdempotencyTests(unittest.TestCase):
    def test_concurrent_same_key_one_wins(self):
        store = InMemoryIdempotencyStore()
        counter = [0]
        reg, _ = _registry_with_counter(counter)
        ex = ToolExecutor(reg, InMemoryAuditSink(), idempotency_store=store)
        ctx = _ctx()
        results = []
        errors = []

        def work():
            try:
                results.append(
                    ex.execute("echo", {"x": "a"}, ctx, idempotency_key="same")
                )
            except IdempotencyInProgressError:
                errors.append("in_progress")
            except IdempotencyReplay as exc:
                results.append(exc.result)

        threads = [threading.Thread(target=work) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # Exactly one real handler execution.
        self.assertEqual(counter[0], 1)
        # Everyone got the same successful outcome.
        self.assertEqual(len(results), 8)
        self.assertTrue(all(r == {"echo": "a"} for r in results))


if __name__ == "__main__":
    unittest.main()
