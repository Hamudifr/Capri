"""Offline, dependency-free performance baseline for Capri runtime hot paths.

Run from the repository root:
    python benchmarks/runtime/run.py --warmup 50 --samples 250

The harness uses private temporary SQLite databases and a fake model adapter.
It never calls a live provider or external service.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import platform
import sqlite3
import statistics
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Any

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

try:
    import resource
except ImportError:  # pragma: no cover - Windows
    resource = None  # type: ignore[assignment]

from capri_runtime import (
    AssistantTurn,
    ExecutionContext,
    InMemoryAuditSink,
    SQLiteGoalStore,
    SQLiteTaskStore,
    ToolExecutionBridge,
    ToolExecutor,
    ToolOrchestrator,
    ToolRegistry,
    ToolSpec,
)

_TASK_PLAN = [{
    "tool": "noop",
    "input": {"value": "baseline"},
    "max_attempts": 1,
}]
_TOOL_SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "string", "maxLength": 32}},
    "required": ["value"],
    "additionalProperties": False,
}


class _OfflineAdapter:
    """Deterministic adapter used to measure orchestration without a provider."""

    def complete_with_tools(self, session_id: str, history: Any, tools: Any) -> AssistantTurn:
        return AssistantTurn(content="offline benchmark response")


def _private_tempdir() -> tempfile.TemporaryDirectory[str]:
    directory = tempfile.TemporaryDirectory(prefix="capri-runtime-bench-")
    if os.name == "posix":
        os.chmod(directory.name, 0o700)
    return directory


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _measure(
    name: str,
    operation: Callable[[], Any],
    *,
    warmup: int,
    samples: int,
) -> dict[str, Any]:
    for _ in range(warmup):
        operation()

    latencies_ns: list[int] = []
    batch_start = time.perf_counter_ns()
    for _ in range(samples):
        start = time.perf_counter_ns()
        operation()
        latencies_ns.append(time.perf_counter_ns() - start)
    elapsed_ns = time.perf_counter_ns() - batch_start
    latency_us = [value / 1_000 for value in latencies_ns]
    elapsed_seconds = elapsed_ns / 1_000_000_000
    return {
        "name": name,
        "unit": "operation",
        "warmup_operations": warmup,
        "sample_count": samples,
        "elapsed_seconds": round(elapsed_seconds, 6),
        "throughput_operations_per_second": round(samples / elapsed_seconds, 2),
        "latency_us": {
            "min": round(min(latency_us), 3),
            "median": round(statistics.median(latency_us), 3),
            "p95": round(_percentile(latency_us, 0.95), 3),
            "p99": round(_percentile(latency_us, 0.99), 3),
            "max": round(max(latency_us), 3),
        },
        "latency_samples_us": [round(value, 3) for value in latency_us],
    }


def _cpu_model() -> str | None:
    processor = (platform.processor() or "").strip()
    if processor:
        return processor
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        try:
            for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.lower().startswith(("model name", "hardware")):
                    return line.split(":", 1)[-1].strip()
        except OSError:
            return None
    return None


def _peak_rss_bytes() -> int | None:
    if resource is None:
        return None
    try:
        peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except (AttributeError, OSError, ValueError):
        return None
    # Linux and most BSDs report KiB; macOS reports bytes.
    return peak if sys.platform == "darwin" else peak * 1024


def run_benchmarks(*, warmup: int = 50, samples: int = 250) -> dict[str, Any]:
    if type(warmup) is not int or not 0 <= warmup <= 10_000:
        raise ValueError("warmup must be an integer between 0 and 10000")
    if type(samples) is not int or not 5 <= samples <= 100_000:
        raise ValueError("samples must be an integer between 5 and 100000")

    measurements: list[dict[str, Any]] = []
    base_time = datetime.now(timezone.utc).replace(microsecond=0)

    with _private_tempdir() as temp:
        root = Path(temp)

        goals = SQLiteGoalStore(str(root / "goals.sqlite3"))
        goal_counter = 0

        def goal_persistence() -> None:
            nonlocal goal_counter
            goal_counter += 1
            key = f"goal-bench-{goal_counter}"
            record = goals.create_for_principal(
                "benchmark-principal",
                "Persist and retrieve a benchmark goal",
                constraints={"source": "offline-benchmark"},
                acceptance_criteria=["goal record is readable"],
                idempotency_key=key,
                now=base_time,
            )
            if goals.get_for_principal(record.goal_id, "benchmark-principal").goal_id != record.goal_id:
                raise RuntimeError("goal persistence benchmark invariant failed")

        measurements.append(_measure(
            "goal_create_and_read", goal_persistence, warmup=warmup, samples=samples,
        ))

        tasks = SQLiteTaskStore(str(root / "tasks.sqlite3"))
        task_counter = 0

        def task_persistence() -> None:
            nonlocal task_counter
            task_counter += 1
            record = tasks.create_for_principal(
                "benchmark-principal",
                _TASK_PLAN,
                idempotency_key=f"task-bench-{task_counter}",
                now=base_time,
            )
            if tasks.get_for_principal(record.task_id, "benchmark-principal").task_id != record.task_id:
                raise RuntimeError("task persistence benchmark invariant failed")

        measurements.append(_measure(
            "task_create_and_read", task_persistence, warmup=warmup, samples=samples,
        ))

        claim_store = SQLiteTaskStore(str(root / "claims.sqlite3"))
        claim_count = warmup + samples
        for index in range(claim_count):
            claim_store.create(
                _TASK_PLAN,
                idempotency_key=f"claim-bench-{index}",
                now=base_time,
            )
        claim_time = base_time + timedelta(seconds=1)

        def task_claim() -> None:
            claim = claim_store.claim_next("benchmark-worker", now=claim_time)
            if claim is None:
                raise RuntimeError("task claim benchmark queue unexpectedly empty")

        measurements.append(_measure(
            "task_claim_throughput", task_claim, warmup=warmup, samples=samples,
        ))

        registry = ToolRegistry()
        registry.register(
            ToolSpec("bench_echo", "tools:bench_echo", _TOOL_SCHEMA),
            lambda arguments: {"echo": arguments["value"]},
        )
        executor = ToolExecutor(registry, InMemoryAuditSink(max_events=2 * (warmup + samples) + 10))
        context = ExecutionContext("benchmark-principal", frozenset({"tools:bench_echo"}))

        def tool_dispatch() -> None:
            result = executor.execute("bench_echo", {"value": "baseline"}, context)
            if result != {"echo": "baseline"}:
                raise RuntimeError("tool dispatch benchmark invariant failed")

        measurements.append(_measure(
            "tool_validation_and_dispatch", tool_dispatch, warmup=warmup, samples=samples,
        ))

        orchestrator = ToolOrchestrator(
            _OfflineAdapter(),
            ToolExecutionBridge(ToolExecutor(ToolRegistry(), InMemoryAuditSink())),
        )

        def orchestration() -> None:
            result = orchestrator.run(
                "benchmark-session",
                "measure local orchestration overhead",
                (),
                ExecutionContext("benchmark-principal", frozenset()),
            )
            if result.final_text != "offline benchmark response":
                raise RuntimeError("orchestration benchmark invariant failed")

        measurements.append(_measure(
            "orchestration_with_fake_adapter", orchestration,
            warmup=warmup, samples=samples,
        ))

    peak_rss = _peak_rss_bytes()
    return {
        "schema_version": 1,
        "benchmark": "capri_runtime_baseline",
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "commit_sha": os.environ.get("GITHUB_SHA"),
        "workflow_run_id": os.environ.get("GITHUB_RUN_ID"),
        "environment": {
            "os": platform.platform(),
            "machine": platform.machine(),
            "cpu_model": _cpu_model(),
            "logical_cpu_count": os.cpu_count(),
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "python_executable": sys.executable,
            "sqlite_version": sqlite3.sqlite_version,
        },
        "configuration": {
            "warmup_operations_per_workload": warmup,
            "measured_samples_per_workload": samples,
            "external_provider_calls": 0,
            "external_network_calls": 0,
        },
        "memory": {
            "process_peak_rss_bytes": peak_rss,
            "scope": "whole benchmark process; not attributable to an individual workload",
        },
        "measurement_notes": [
            "Store initialization and temporary-directory creation are excluded from timed samples.",
            "Each sample times one operation; throughput uses the complete measured batch duration.",
            "SQLite operations use private temporary databases on the runner's local filesystem.",
            "The orchestration workload uses a deterministic fake adapter and makes no provider call.",
            "Results are a baseline for this runner/runtime only, not a universal language ranking.",
        ],
        "results": measurements,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--warmup", type=int, default=50)
    parser.add_argument("--samples", type=int, default=250)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = run_benchmarks(warmup=args.warmup, samples=args.samples)
    except ValueError as error:
        parser.error(str(error))
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
        print(f"Wrote benchmark report to {args.output}")
    else:
        sys.stdout.write(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
