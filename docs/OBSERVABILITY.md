# Runtime observability

## Status and purpose

`capri_runtime.observability` adds bounded, fail-closed observability primitives for the non-X5 runtime: an in-memory ring event log, a private durable SQLite event log with explicit retention, and a bounded metric registry of counters and gauges.

It is provider-neutral and standard-library only. It is not a network metrics exporter, a profiler, a structured logging framework, or a tracing system. Hosts own delivery to external systems and any authentication for it. This module performs no network, subprocess, or filesystem access beyond the single explicit database path.

## Basic use

```python
from capri_runtime.observability import InMemoryEventLog, MetricRegistry, SQLiteEventLog

events = SQLiteEventLog("/private/capri/events.sqlite3", max_events=10_000)
events.record("task.completed", 1, {"task_id": "t-1"})

registry = MetricRegistry()
registry.counter("tasks.completed")
registry.gauge("queue.depth", 7)
print(registry.export_json())
```

The database parent must already exist and be private (0700 or stricter on POSIX). The database is created with private permissions, rejects symlink/hard-link aliases, rechecks path safety on each connection, and uses SQLite WAL with full synchronous commits.

## Event model

- `record(name, value, attributes, now)` appends one event; `name` is a bounded identifier (1-64 characters, `[A-Za-z0-9_.-]`), `value` is a finite bounded number, and `attributes` is a JSON object of at most 4096 UTF-8 bytes with at most 16 nesting levels. Non-scalar Unicode (lone surrogates) is rejected.
- `query(name, since, until, limit)` returns events in append order with an inclusive timestamp window; the limit is bounded to 1-1000.
- `export_json(...)` is deterministic: sorted keys, compact separators, stable field order.
- `count(name)` returns bounded counts for inspection and tests.

## Retention

`SQLiteEventLog` keeps only the newest `max_events` events automatically. Hosts can apply explicit retention:

- `prune_before(now)` deletes events strictly older than a timestamp and returns the number deleted.
- `keep_last(count)` deletes everything except the newest `count` events and returns the number deleted.

`InMemoryEventLog` evicts oldest events via ring retention; it never grows beyond its configured bound.

## Metric registry

`MetricRegistry` keeps bounded aggregates only: `counter(name, delta)` with a bounded delta and total, and `gauge(name, value)` with finite bounded values. Name cardinality is bounded (default 256 names) and fails closed. `snapshot()` and `export_json()` are deterministic.

## Security and privacy boundary

- Attributes are persisted as plaintext bounded JSON. Do not put credentials, secrets, or sensitive personal data in event attributes or metric names.
- Event names and attributes are data, never instructions; no consumer of these events should parse attribute text as commands.
- The database path is protected like the task store: private directory, regular non-symlink file, single link count, and re-verification on each connection. Untrusted attribute content is never executed, imported, or interpreted.
- This module is not a sandbox and performs no authorization; hosts decide which subsystemqs may record events and who may read the database.
- No aggregation across processes, authenticated event signatures, or remote delivery is implemented; hosts requiring tamper evidence should wrap the durable log with their own signing at the host boundary.

## Validation

`tests/test_observability.py` covers record/query/export determinism, ring and durable retention pruning, timestamp windows and limits, name/value/attribute validation (including lone surrogates and oversized payloads), metric registry aggregates and cardinality bounds, symlink rejection, directory-privacy rechecks, corrupt-row fail-closed reads, and concurrent recording. The repository quality workflow runs the full suite on Python 3.11, 3.12, and 3.13.
