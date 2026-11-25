"""Persistence-focused profiling for Capri's SQLite-backed stores.

Offline only. Uses private temporary databases and no providers/network.
Run: python benchmarks/persistence/run.py --samples 100 --workers 4 --queue-size 100
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import os
import platform
import sqlite3
import statistics
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(_ROOT))

from capri_runtime import SQLiteGoalStore, SQLiteTaskStore

_PLAN = [{"tool": "noop", "input": {"value": "persistence-profile"}, "max_attempts": 1}]
_PRINCIPAL = "persistence-benchmark-principal"


def _private_tempdir() -> tempfile.TemporaryDirectory[str]:
    directory = tempfile.TemporaryDirectory(prefix="capri-persistence-")
    if os.name == "posix":
        os.chmod(directory.name, 0o700)
    return directory


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def _summary(
    name: str, values_ns: list[int], *, wall_elapsed_ns: int | None = None,
    unit: str = "operation"
) -> dict[str, Any]:
    values_us = [value / 1_000 for value in values_ns]
    aggregate_operation_s = sum(values_ns) / 1_000_000_000
    wall_elapsed_s = (
        wall_elapsed_ns / 1_000_000_000 if wall_elapsed_ns is not None else None
    )
    return {
        "name": name,
        "unit": unit,
        "sample_count": len(values_ns),
        "elapsed_seconds": wall_elapsed_s,
        "aggregate_operation_seconds": round(aggregate_operation_s, 6),
        "throughput_per_second": (
            round(len(values_ns) / wall_elapsed_s, 2)
            if wall_elapsed_s is not None and wall_elapsed_s > 0 else None
        ),
        "latency_us": {
            "min": round(min(values_us), 3),
            "median": round(statistics.median(values_us), 3),
            "p95": round(_percentile(values_us, 0.95), 3),
            "p99": round(_percentile(values_us, 0.99), 3),
            "max": round(max(values_us), 3),
        },
        "latency_samples_us": [round(value, 3) for value in values_us],
    }


def _measure(name: str, operation: Callable[[], Any], warmup: int, samples: int) -> dict[str, Any]:
    for _ in range(warmup):
        operation()
    values: list[int] = []
    batch_started = time.perf_counter_ns()
    for _ in range(samples):
        started = time.perf_counter_ns()
        operation()
        values.append(time.perf_counter_ns() - started)
    wall_elapsed_ns = time.perf_counter_ns() - batch_started
    return _summary(name, values, wall_elapsed_ns=wall_elapsed_ns)


def _transaction_phases(path: Path, warmup: int, samples: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """Separate statement execution from COMMIT on a controlled SQLite workload."""
    connection = sqlite3.connect(path, timeout=10, isolation_level=None)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("CREATE TABLE phase_probe (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
        execute_ns: list[int] = []
        commit_ns: list[int] = []
        for index in range(warmup + samples):
            connection.execute("BEGIN IMMEDIATE")
            started = time.perf_counter_ns()
            connection.execute("INSERT INTO phase_probe(payload) VALUES(?)", (f"row-{index}",))
            executed = time.perf_counter_ns()
            connection.execute("COMMIT")
            committed = time.perf_counter_ns()
            if index >= warmup:
                execute_ns.append(executed - started)
                commit_ns.append(committed - executed)
        return (
            _summary("sqlite_insert_statement_only", execute_ns),
            _summary("sqlite_commit_only_after_insert", commit_ns),
        )
    finally:
        connection.close()


def _concurrent_claims(database: str, workers: int, queue_size: int, now: datetime) -> dict[str, Any]:
    """Competing store instances claim an unowned queue; every task must be claimed once."""
    seed = SQLiteTaskStore(database)
    for index in range(queue_size):
        seed.create(_PLAN, idempotency_key=f"concurrent-claim-{index}", now=now)
    stores = [SQLiteTaskStore(database) for _ in range(workers)]
    start = threading.Barrier(workers)

    def drain(store: SQLiteTaskStore, worker_number: int) -> list[str]:
        claimed: list[str] = []
        start.wait()
        while True:
            claim = store.claim_next(
                f"profile-worker-{worker_number}",
                now=now + timedelta(seconds=1),
            )
            if claim is None:
                return claimed
            claimed.append(claim.task_id)

    began = time.perf_counter_ns()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(drain, store, index) for index, store in enumerate(stores)]
        batches = [future.result() for future in futures]
    elapsed = time.perf_counter_ns() - began
    claimed = [task_id for batch in batches for task_id in batch]
    unique = len(set(claimed))
    if len(claimed) != queue_size or unique != queue_size:
        raise RuntimeError(
            f"concurrent claim invariant failed: claimed={len(claimed)}, unique={unique}, expected={queue_size}"
        )
    seconds = elapsed / 1_000_000_000
    return {
        "name": "concurrent_task_claim",
        "workers": workers,
        "queue_size": queue_size,
        "claimed_count": len(claimed),
        "unique_claim_count": unique,
        "duplicate_claims": len(claimed) - unique,
        "elapsed_seconds": round(seconds, 6),
        "throughput_claims_per_second": round(len(claimed) / seconds, 2) if seconds else None,
        "correctness": "passed",
        "note": "One SQLiteTaskStore instance per worker thread; shared WAL database; in-process contention only.",
    }


def run(*, warmup: int = 10, samples: int = 50, workers: int = 4, queue_size: int = 100) -> dict[str, Any]:
    if type(warmup) is not int or not 0 <= warmup <= 10_000:
        raise ValueError("warmup must be between 0 and 10000")
    if type(samples) is not int or not 5 <= samples <= 10_000:
        raise ValueError("samples must be between 5 and 10000")
    if type(workers) is not int or not 2 <= workers <= 32:
        raise ValueError("workers must be between 2 and 32")
    if type(queue_size) is not int or not workers <= queue_size <= 100_000:
        raise ValueError("queue_size must be at least workers and at most 100000")

    results: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).replace(microsecond=0)
    with _private_tempdir() as directory:
        root = Path(directory)
        goals = SQLiteGoalStore(str(root / "goals.sqlite3"))
        goal_ids: list[str] = []
        counter = 0

        def create_goal() -> None:
            nonlocal counter
            counter += 1
            record = goals.create_for_principal(
                _PRINCIPAL, "Profile goal persistence",
                constraints={"profile": True},
                acceptance_criteria=["goal is persisted"],
                idempotency_key=f"goal-{counter}", now=now,
            )
            goal_ids.append(record.goal_id)

        results.append(_measure("goal_create_api_including_readback", create_goal, warmup, samples))
        results.append(_measure(
            "goal_get_for_principal",
            lambda: goals.get_for_principal(goal_ids[-1], _PRINCIPAL),
            warmup, samples,
        ))

        tasks = SQLiteTaskStore(str(root / "tasks.sqlite3"))
        task_ids: list[str] = []
        task_counter = 0

        def create_task() -> None:
            nonlocal task_counter
            task_counter += 1
            record = tasks.create(_PLAN, idempotency_key=f"task-{task_counter}", now=now)
            task_ids.append(record.task_id)

        results.append(_measure("task_create_api", create_task, warmup, samples))
        results.append(_measure("task_get_api", lambda: tasks.get(task_ids[-1]), warmup, samples))

        serialized = json.dumps(_PLAN, separators=(",", ":"), sort_keys=True)
        results.append(_measure("plan_json_encode", lambda: json.dumps(_PLAN, separators=(",", ":"), sort_keys=True), warmup, samples))
        results.append(_measure("plan_json_decode", lambda: json.loads(serialized), warmup, samples))

        insert_phase, commit_phase = _transaction_phases(root / "phases.sqlite3", warmup, samples)
        results.extend([insert_phase, commit_phase])

        concurrent = _concurrent_claims(str(root / "claims.sqlite3"), workers, queue_size, now)

    return {
        "schema_version": 1,
        "benchmark": "capri_sqlite_persistence_profile",
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "commit_sha": os.environ.get("CAPRI_BENCHMARK_HEAD_SHA") or os.environ.get("GITHUB_SHA"),
        "environment": {
            "os": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "sqlite": sqlite3.sqlite_version,
            "logical_cpus": os.cpu_count(),
        },
        "configuration": {
            "warmup": warmup,
            "samples": samples,
            "workers": workers,
            "concurrent_queue_size": queue_size,
            "external_network_calls": 0,
            "external_provider_calls": 0,
        },
        "results": results,
        "concurrency": concurrent,
        "interpretation_limits": [
            "API timings include Capri validation, connection setup, SQLite work, and record materialization; they are not pure SQL timings.",
            "The controlled insert/commit probe separates statement and commit wall time but is not a substitute for instrumenting production transactions.",
            "The concurrency probe uses multiple store instances and threads in one process, not independent processes or machines.",
            "No durability PRAGMA is weakened; the controlled probe uses WAL and synchronous=FULL.",
            "Results must be repeated on the same hardware/runtime before comparing changes.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--samples", type=int, default=50)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--queue-size", type=int, default=100)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = run(warmup=args.warmup, samples=args.samples, workers=args.workers, queue_size=args.queue_size)
    except ValueError as error:
        parser.error(str(error))
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
        print(f"Wrote persistence profile to {args.output}")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
