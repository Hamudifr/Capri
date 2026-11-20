# Durable task execution and recovery

## Status and purpose

`capri_runtime.tasks` adds a provider-neutral durable task queue and a synchronous worker primitive. It stores a bounded ordered plan, claims work through SQLite leases, checkpoints each completed step, retries failed steps with bounded exponential backoff, supports cancellation between steps, and recovers abandoned work after a lease expires.

It includes an explicit `TaskWorker` polling loop with graceful stop-event support and a concurrent lease-heartbeat thread while a handler runs. Constructing a worker starts no thread; the host must call `run_once()` or `run_forever(stop_event)` and owns process lifecycle, authenticated principal context, scheduling, and handler registration. Principal-owned tasks carry the owner ID from the immutable task-owner table into the claim; they execute only through a separately configured `principal_handlers` allowlist. Legacy unowned tasks continue to use the original two-argument `handlers` mapping. The stop event is checked between tasks and does not forcibly interrupt an active handler; process supervisors must account for the current handler's completion time. It does not call a model provider, create plans from natural language, or grant tool permissions.

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

## Principal-scoped task ownership

`create_for_principal(principal_id, plan, idempotency_key=...)` atomically creates the task and an immutable owner row in the same SQLite transaction. `get_for_principal()`, `request_cancel_for_principal()`, and `events_for_principal()` hide foreign and legacy-unowned tasks as `TaskNotFoundError`. Existing tasks created with `create()` remain unowned and are not silently assigned to a principal. Principal-scoped idempotency keys are stored as one-way principal-namespaced digests, so different principals can reuse the same client key without colliding or revealing one another's task.

The worker claim includes the owner ID from the trusted database row. A principal-owned claim never falls back to a generic legacy handler: it requires a matching trusted `principal_handlers` callback with signature `(input_dict, stable_idempotency_key, principal_id)`. That callback must enforce current resource-level authorization for every external resource it touches. The principal ID is provenance from the local ownership record, not a replacement for a live authentication provider or resource ACL check. Legacy unowned tasks continue to use `handlers` with signature `(input_dict, stable_idempotency_key)`.

A `TaskClaim` is a transport value, not an authority source. Before dispatch, `TaskEngine` validates the claim against the authoritative SQLite task row and persisted plan: principal owner, executor, active lease and expiry, step index, attempt, idempotency key, tool name, and exact input must all match. The database's current lease and expiry are authoritative; the claim's lease timestamp is only a snapshot because a host heartbeat may extend the persisted lease while a handler is running. The store repeats full claim validation inside the same write transaction for lease renewal, successful completion, and failure transitions, preventing a forged claim from changing task state or extending a lease between a separate validation and write. A forged, stale, expired, or altered claim is rejected before the requested transition. This prevents callers from changing a principal-owned claim into a legacy claim or substituting a different registered tool/input. It does not make trusted in-process handler code a sandbox; handlers still require resource-level authorization and idempotent side effects.



## Persisted-plan integrity failure

A malformed persisted plan is a store-integrity error, not a retryable step failure. This includes invalid JSON, a non-canonical stored representation, or a JSON value that no longer satisfies the normalized task-plan schema. `SQLiteTaskStore.claim_next()` raises `TaskValidationError` and aborts the current claim transaction; it does not mark the row failed or silently skip it. The principal-worker capability filter deliberately includes malformed plans so a structurally invalid plan cannot disappear merely because its current tool name is unsupported. Later candidates in that poll are not claimed. A corrupt row can therefore block later work in queue order. This is an intentional fail-closed tradeoff: preserve task-store integrity rather than execute later work from a queue containing an unreadable or malformed record.

The host should stop the worker, preserve the original database and backups, inspect a copy or restore from a verified backup, and restart only after the integrity fault is resolved. Do not edit the live database or bypass the corrupt row.

## State machine

- `queued`: eligible for a worker claim.
- `running`: held by one executor until its lease expires.
- `retry_wait`: failed step is eligible after its backoff deadline.
- `succeeded`: every planned step completed.
- `failed`: a step exhausted its attempts or its lease expired after the attempt budget was exhausted.
- `cancelled`: cancellation was requested and the task stopped at a safe step boundary.

Claims and state transitions use `BEGIN IMMEDIATE`, so concurrent workers cannot both own the same current lease. Every state transition is recorded in a bounded metadata event log. A worker that loses its lease cannot commit a stale result.

## Delivery and idempotency semantics

Execution is **bounded and may be repeated; it is not exactly once**. A process can crash after claiming a step but before invoking its handler, or after a side effect but before persisting the result. Depending on the crash point and remaining attempt budget, a handler may run zero, one, or multiple times. After lease expiry, another worker may retry the same step. Each step therefore receives the stable idempotency key `<task_id>:<step_index>`; handlers that perform side effects must enforce that key at the side-effect boundary. Do not blindly retry a non-idempotent handler.

Leases are bounded to 5–3600 seconds. The store exposes `renew_lease()` so a host-managed heartbeat can extend a live claim. Renewal must occur before expiry and fails closed after expiry or ownership change. The lower-level `TaskEngine.run_once()` helper does not start a heartbeat thread; hosts using it directly must arrange renewal themselves. `TaskWorker` handles heartbeats while its handler is running. Neither API can forcibly interrupt a running handler. If a handler outlives its lease without renewal, a second worker may reclaim it; stable idempotency is mandatory.

## Retry and cancellation

Each step may set `max_attempts` from 1 to 10 (default 3). Retry delay uses bounded exponential backoff, capped at one hour. Error details are deliberately suppressed; only a short error code is stored.

Cancellation is cooperative. Queued/retry-wait tasks cancel immediately. A running handler is not killed; its current step may finish and be checkpointed, then the task becomes cancelled without starting another step. Hosts should expose this behavior honestly in UI.

## Security and privacy boundary

- Plans contain only 1–32 ordered steps, each with a bounded JSON object input; handler results are bounded JSON.
- The database stores task inputs and results in plaintext SQLite. Do not put credentials, secrets, or sensitive personal data in task plans/results. Encryption and key management are not implemented.
- Handler names must exist in the host's injected allowlist. This module never imports code dynamically or runs shell/network/filesystem commands.
- Injected handlers are trusted host code and run with the process's privileges; this module is not a sandbox.
- Model-proposed actions must still pass through `ToolExecutor`, host authentication/authorization, and any required user approval. Do not register a raw unrestricted handler merely because a task plan names it.
- Immutable task ownership protects task lookup and cancellation through the scoped APIs, but it does not by itself establish resource-level authorization or complete tenant isolation. Principal handlers must perform resource ACL checks.
- The store protects local file paths and permissions, but does not provide remote multi-tenant isolation, encrypted storage, backup/restore automation, retention/compaction, or authenticated event signatures.

## Validation

`tests/test_tasks.py` covers persistent state, idempotent creation, principal-scoped task isolation, immutable owner rows, principal-aware worker dispatch, backup/restore of ownership, plan validation, concurrent claims, lease recovery, stale-worker rejection, tampered-claim rejection across renewal/completion/failure transitions, bounded retries, step checkpointing, handler failure suppression, cancellation, event persistence, symlink rejection, and directory privacy. The repository quality workflow runs the full suite on Python 3.11, 3.12, and 3.13.
