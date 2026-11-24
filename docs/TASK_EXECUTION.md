# Durable task execution and recovery

## Status and purpose

`capri_runtime.tasks` adds a provider-neutral durable task queue and a synchronous worker primitive. It stores a bounded ordered plan, claims work through SQLite leases, checkpoints each completed step, retries failed steps with bounded exponential backoff, supports cancellation between steps, and recovers abandoned work after a lease expires.

It includes an explicit `TaskWorker` polling loop with graceful stop-event support and a concurrent lease-heartbeat thread while a handler runs. Constructing a worker starts no thread; the host must call `run_once()` or `run_forever(stop_event)` and owns process lifecycle, authenticated principal context, scheduling, and handler registration. The stop event is checked between tasks and does not forcibly interrupt an active handler; process supervisors must account for the current handler's completion time. It does not call a model provider, create plans from natural language, or grant tool permissions.

## Basic use

```python
from capri_runtime import SQLiteTaskStore, TaskEngine

store = SQLiteTaskStore("/private/capri/tasks.sqlite3")
task = store.create(
    [
        {"tool": "collect_status", "input": {"scope": "project"}},
        {"tool": "write_report", "input": {"format": "markdown"}},
    ],
    idempotency_key="daily-status-2026-11-06",
)

engine = TaskEngine(
    store,
    handlers={
        "collect_status": trusted_collect_status,
        "write_report": trusted_write_report,
    },
    executor_id="worker-1",
)
engine.run_once()
```

The parent directory must already exist and be private (0700 or stricter on POSIX). The database is created with private permissions, rejects symlink/hard-link aliases, rechecks path safety on each connection, and uses SQLite WAL with full synchronous commits.

## State machine

- `queued`: eligible for a worker claim.
- `running`: held by one executor until its lease expires.
- `retry_wait`: a handler explicitly declared a pre-side-effect failure and the step is eligible after its backoff deadline.
- `reconciliation_required`: a handler may have performed a side effect but its outcome cannot be proven; the task is excluded from automatic claims.
- `succeeded`: every planned step completed.
- `failed`: a step exhausted its attempts or its lease expired after the attempt budget was exhausted.
- `cancelled`: cancellation was requested and the task stopped at a safe step boundary.

Claims and state transitions use `BEGIN IMMEDIATE`, so concurrent workers cannot both own the same current lease. Every state transition is recorded in a bounded metadata event log. A worker that loses its lease cannot commit a stale result.

## Delivery and idempotency semantics

Execution is **not exactly once**. A process can crash after claiming a step but before invoking its handler, or after a side effect but before persisting the result. An expired running lease is now quarantined as `reconciliation_required`; a second worker does not automatically reclaim it. Unknown handler exceptions and invalid/oversized results are also quarantined because a side effect may already have occurred. Only a trusted handler that can prove it failed before any external side effect may raise `RetryableTaskError` to request a bounded retry. Each step receives the stable idempotency key `<task_id>:<step_index>`; handlers that perform side effects must enforce that key at the side-effect boundary.

Leases are bounded to 5–3600 seconds. The store exposes `renew_lease()` so a host-managed heartbeat can extend a live claim. Renewal must occur before expiry and fails closed after expiry or ownership change. The lower-level `TaskEngine.run_once()` helper does not start a heartbeat thread; hosts using it directly must arrange renewal themselves. `TaskWorker` handles heartbeats while its handler is running. Neither API can forcibly interrupt a running handler. If a handler outlives its lease without renewal, the expired running task is quarantined as `reconciliation_required`; another worker must not automatically reclaim or replay it. Establish the external outcome through reconciliation before any manual replay. Stable idempotency keys remain mandatory at side-effect boundaries.

## Retry and cancellation

Each step may set `max_attempts` from 1 to 10 (default 3). Retry delay uses bounded exponential backoff, capped at one hour. Error details are deliberately suppressed; only a short error code is stored.

Cancellation is cooperative. Queued/retry-wait tasks cancel immediately. A running handler is not killed; its current step may finish and be checkpointed, then the task becomes cancelled without starting another step. Hosts should expose this behavior honestly in UI.

## Security and privacy boundary

- Plans contain only 1–32 ordered steps, each with a bounded JSON object input; handler results are bounded JSON.
- The database stores task inputs and results in plaintext SQLite. Do not put credentials, secrets, or sensitive personal data in task plans/results. Encryption and key management are not implemented.
- Handler names must exist in the host's injected allowlist. This module never imports code dynamically or runs shell/network/filesystem commands.
- Injected handlers are trusted host code and run with the process's privileges; this module is not a sandbox.
- Model-proposed actions must still pass through `ToolExecutor`, host authentication/authorization, and any required user approval. Do not register a raw unrestricted handler merely because a task plan names it.
- The store protects local file paths and permissions, but does not provide remote multi-tenant isolation, encrypted storage, backup/restore automation, retention/compaction, or authenticated event signatures.

## Validation

`tests/test_tasks.py` covers persistent state, idempotent creation, plan validation, concurrent claims, lease recovery, stale-worker rejection, bounded retries, step checkpointing, handler failure suppression, missing handlers, cancellation, event persistence, symlink rejection, and directory privacy. The repository quality workflow runs the full suite on Python 3.11, 3.12, and 3.13.


## Uncertain handler outcomes and reconciliation quarantine

A task handler may perform an external side effect and then raise, return an
invalid/oversized result, or lose its worker process before the result is
checkpointed. These cases are not safe automatic retries. The engine now moves
such tasks to `reconciliation_required`, clears the lease, records an event,
and excludes the task from future claims. An expired running lease is treated
the same way because the store cannot prove whether the handler ran.

Only trusted handlers may raise `RetryableTaskError`, and only when they can
guarantee failure occurred before any external side effect. That explicit signal
retains bounded retry behavior. A `ToolCancelledError` marked
`outcome_uncertain=False` is terminal without quarantine; uncertain
cancellation is quarantined.

The current release adds the durable quarantine state but does not yet provide
an owner-facing reconciliation decision API. Hosts must inspect and resolve
quarantined tasks out of band; never reset them to queued/retry_wait or replay
them without independently establishing the external outcome. Cancellation
requests preserve the quarantine state and only set the cancellation flag.
