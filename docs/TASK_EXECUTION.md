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

## SQLite backup publication portability

SQLite backup APIs create and validate a standalone temporary snapshot before publication. Publication must be atomic and must never replace an existing destination. Capri uses a hard-link-plus-unlink operation when Python exposes `os.link`. On Linux hosts where that API is absent, it uses libc `renameat2` with `RENAME_NOREPLACE`, which atomically moves the temporary file and rejects destination collisions. If neither primitive is available, backup publication fails closed with an unsupported-operation error. Do not replace this with `os.rename` or another operation that can overwrite a destination. The Linux fallback is covered by collision-preservation tests; platform support still depends on the host libc and filesystem implementing `renameat2(RENAME_NOREPLACE)`.

## Principal-scoped task ownership

`create_for_principal(principal_id, plan, idempotency_key=...)` atomically creates the task and an immutable owner row in the same SQLite transaction. `get_for_principal()`, `request_cancel_for_principal()`, and `events_for_principal()` hide foreign and legacy-unowned tasks as `TaskNotFoundError`. Existing tasks created with `create()` remain unowned and are not silently assigned to a principal. Principal-scoped idempotency keys are stored as one-way principal-namespaced digests, so different principals can reuse the same client key without colliding or revealing one another's task.

The worker claim includes the owner ID from the trusted database row. A principal-owned claim never falls back to a generic legacy handler: it requires a matching trusted `principal_handlers` callback with signature `(input_dict, stable_idempotency_key, principal_id)`. That callback must enforce current resource-level authorization for every external resource it touches. The principal ID is provenance from the local ownership record, not a replacement for a live authentication provider or resource ACL check. Legacy unowned tasks continue to use `handlers` with signature `(input_dict, stable_idempotency_key)`.

The worker capability allowlist controls handler dispatch, not store-maintenance transitions. Any worker may process an eligible cancel-requested task as `cancelled`, mark an expired running task `failed` when its attempt budget is exhausted, or finalize a completed plan; these transitions do not invoke a handler. Before recording a cancellation event, the store still validates the active step index and state-specific attempt count, so cancellation cannot turn corrupt progress metadata into a terminal record. Ordinary principal-owned work with an unsupported tool, and expired leases that still have attempts remaining, remain untouched for a compatible principal-aware worker. Malformed persisted plans are surfaced as integrity errors rather than hidden by the capability filter.

A `TaskClaim` is a transport value, not an authority source. Before dispatch, `TaskEngine` validates the claim against the authoritative SQLite task row and persisted plan: principal owner, executor, active lease and expiry, step index, attempt, idempotency key, tool name, and exact input must all match. The database's current lease and expiry are authoritative; the claim's lease timestamp is only a snapshot because a host heartbeat may extend the persisted lease while a handler is running. The store repeats full claim validation inside the same write transaction for lease renewal, successful completion, and failure transitions, preventing a forged claim from changing task state or extending a lease between a separate validation and write. A forged, stale, expired, or altered claim is rejected before the requested transition. This prevents callers from changing a principal-owned claim into a legacy claim or substituting a different registered tool/input. It does not make trusted in-process handler code a sandbox; handlers still require resource-level authorization and idempotent side effects.



## Persisted-plan integrity failure

A malformed persisted plan is a store-integrity error, not a retryable step failure. This includes invalid JSON, a non-canonical stored representation, or a JSON value that no longer satisfies the normalized task-plan schema. `SQLiteTaskStore.claim_next()` raises `TaskValidationError` and aborts the current claim transaction; it does not mark the row failed or silently skip it. The principal-worker capability filter deliberately includes malformed plans so a structurally invalid plan cannot disappear merely because its current tool name is unsupported. Later candidates in that poll are not claimed. A corrupt row can therefore block later work in queue order. This is an intentional fail-closed tradeoff: preserve task-store integrity rather than execute later work from a queue containing an unreadable or malformed record.

The host should stop the worker, preserve the original database and backups, inspect a copy or restore from a verified backup, and restart only after the integrity fault is resolved. Do not edit the live database or bypass the corrupt row.

## State machine

- `queued`: eligible for a worker claim.
- `running`: held by one executor until its lease expires.
- `reconciliation_required`: quarantined after an uncertain outcome; never claimable until an authorized reconciliation decision is recorded.
- `retry_wait`: failed step is eligible after its backoff deadline.
- `succeeded`: every planned step completed.
- `failed`: a step exhausted its attempts or its lease expired after the attempt budget was exhausted.
- `cancelled`: cancellation was requested and the task stopped at a safe step boundary.

Claims and state transitions use `BEGIN IMMEDIATE`, so concurrent workers cannot both own the same current lease. Every state transition is recorded in a bounded metadata event log. A worker that loses its lease cannot commit a stale result.

## Delivery and idempotency semantics

Execution is bounded and does not guarantee exactly-once external effects. A process can crash before invoking a handler, or after an external side effect but before persisting the result. An explicitly safe pre-side-effect failure may be retried; an expired running lease or uncertain handler outcome is quarantined in `reconciliation_required` rather than automatically replayed. Each step receives the stable idempotency key `<task_id>:<step_index>`; handlers that perform side effects should still enforce that key at the side-effect boundary.

The engine distinguishes known pre-effect failures from uncertain outcomes. A trusted handler may raise the public `RetryableTaskError` only when it can guarantee that no external side effect occurred; this opts the step into the existing bounded retry/backoff policy. Any other handler exception, and any invalid/oversized/non-JSON result returned after handler invocation, enters non-claimable `reconciliation_required` with the distinct redacted `handler_outcome_uncertain` code. It is deliberately not retried automatically because the external action may already have happened. Hosts must surface the quarantined task for inspection and use the stable idempotency key when deciding whether a separately authorized recovery is safe.

Leases are bounded to 5–3600 seconds. The store exposes `renew_lease()` so a host-managed heartbeat can extend a live claim. Renewal must occur before expiry and fails closed after expiry or ownership change. The lower-level `TaskEngine.run_once()` helper does not start a heartbeat thread; hosts using it directly must arrange renewal themselves. `TaskWorker` handles heartbeats while its handler is running. Neither API can forcibly interrupt a running handler. If a handler outlives its lease, the next claim attempt moves it to `reconciliation_required`; it is never automatically reclaimed because the external side-effect outcome is unknown. This is deliberately at-most-once recovery, not exactly-once execution.

## Uncertain outcomes and reconciliation

A `running` task whose lease expires is transitioned to `reconciliation_required`, regardless of remaining retry attempts. The expired lease is not a retry signal: the worker may have completed an external action before crashing or losing its lease. This state is excluded from all claim queries. A handler exception after dispatch and an invalid handler result also enter this state. `ToolCancelledError(outcome_uncertain=False)` is handled as a known pre-handler cancellation; `ToolCancelledError(outcome_uncertain=True)` enters quarantine. Only `RetryableTaskError`, explicitly guaranteed by trusted handler code to occur before every external side effect, may use automatic retry.

For principal-owned tasks, the owner may call `reconcile_for_principal(task_id, principal_id, decision_id, outcome, evidence_ref, result=None)`. Outcomes are `succeeded`, `failed`, and `unresolved`. A successful decision checkpoints the supplied result and advances to the next step (or succeeds); a failed decision ends the task without retry; unresolved preserves quarantine. Decision IDs are unique per task and content-bound, so exact replays are safe and conflicting replays fail. The evidence reference is recorded as provenance, not treated as proof by itself. Task backups validate reconciliation records and preserve them across restore. The preferred host entry point is `CapriHostRuntime.reconcile_task()`: it derives the actor only from `HostAuthorityResolver.resolve(credential)`, requires the explicit `task.reconcile.owned` permission, and requires a trusted host evidence-verifier callback to approve the exact actor/task/decision/outcome/result payload before persistence. The callback must be read-only/idempotent and independently validate evidence and current resource authorization; it may be invoked again for an exact replay. The store atomically enforces quarantine state and decision idempotency. A caller-supplied evidence reference is never proof. Direct store-level reconciliation is a lower-level primitive and must not be exposed directly to untrusted clients.

Cancellation does not erase uncertainty. A cancellation request against a quarantined task sets `cancel_requested` but leaves the task quarantined until reconciliation determines what happened.

## Retry and cancellation

Each step may set `max_attempts` from 1 to 10 (default 3). Retry delay uses bounded exponential backoff, capped at one hour. Only an explicit `RetryableTaskError` from trusted handler code opts into automatic retry, and only when no external side effect occurred. Other exceptions and invalid handler results move the task to `reconciliation_required` with `handler_outcome_uncertain`. The task is non-claimable until an owner-scoped reconciliation decision records `succeeded`, `failed`, or `unresolved`. Reconciliation requires `create_for_principal()` ownership, a unique decision ID, and an evidence reference. Replaying the same decision ID with identical content is idempotent; reusing it with different content is rejected. `unresolved` keeps the task quarantined; a later decision must use a new ID. `evidence_ref` is provenance, not proof by itself. Legacy unowned tasks can be quarantined but cannot use the principal-scoped reconciliation API and require trusted host-level recovery outside this API. Error details are deliberately suppressed; only a short error code is stored.

Cancellation is cooperative. Queued/retry-wait tasks cancel immediately. A running handler is not killed; its current step may finish and be checkpointed, then the task becomes cancelled without starting another step. Hosts should expose this behavior honestly in UI.

## Security and privacy boundary

- Plans contain only 1–32 ordered steps, each with a bounded JSON object input; handler results are bounded JSON.
- The database stores task inputs and results in plaintext SQLite. Do not put credentials, secrets, or sensitive personal data in task plans/results. Encryption and key management are not implemented.
- Handler names must exist in the host's injected allowlist. This module never imports code dynamically or runs shell/network/filesystem commands.
- Injected handlers are trusted host code and run with the process's privileges; this module is not a sandbox.
- Model-proposed actions must still pass through `ToolExecutor`, host authentication/authorization, and any required user approval. Do not register a raw unrestricted handler merely because a task plan names it.
- Immutable task ownership protects task lookup and cancellation through the scoped APIs, but it does not by itself establish resource-level authorization or complete tenant isolation. Principal handlers must perform resource ACL checks.
- The store protects local file paths and permissions, but does not provide remote multi-tenant isolation, encrypted storage, backup/restore automation, retention/compaction, or authenticated event signatures.

## Backup snapshot integrity

Before producing a SQLite backup, the task store validates the snapshot's task records and ownership metadata, including the same canonical persisted-plan format required by normal recovery and consistency between task state and cancellation metadata. Lease state must agree with task state: a `running` task must have a non-empty executor owner and a valid timezone-aware lease expiry; every non-running task must have both lease fields set to NULL. A snapshot that violates these invariants is rejected rather than copied as a backup. An expired but structurally valid running lease may still be backed up; normal lease recovery can reclaim it after restore.

This validation checks the task-store snapshot's semantic consistency. It is not a substitute for protecting backup files, retaining independent copies, or testing restore procedures.

## Validation

`tests/test_tasks.py` covers persistent state, idempotent creation, principal-scoped task isolation, immutable owner rows, principal-aware worker dispatch, backup/restore of ownership, plan and persisted attempt-count validation, concurrent claims, lease recovery, stale-worker rejection, tampered-claim rejection across renewal/completion/failure transitions, explicit pre-effect retry opt-in, terminal handling of uncertain handler exceptions and invalid results, side-effect non-replay, cancellation, event persistence, symlink rejection, and directory privacy. The repository quality workflow runs the full suite on Python 3.11, 3.12, and 3.13.


## Persisted attempt-count integrity

The attempt counter is scoped to the current step. A queued task must have zero attempts; a retry-wait task must have at least one attempt but remain below that step's maximum; running and reconciliation-required tasks retain an attempt between one and the maximum. A task whose plan is complete must have a zero current-step attempt count. Any other persisted value is treated as corruption and fails closed before a handler is dispatched. Expired running tasks transition to `reconciliation_required` regardless of remaining attempt budget. The shared authoritative claim validator enforces the running-attempt invariant for claim validation, lease renewal, step completion, step failure and engine dispatch. Backup validation checks state-specific step and attempt bounds before publishing a snapshot, validates owner-scoped reconciliation decision records, and preserves them across restore. Historical event step indices and attempt counts are checked against the corresponding plan step, including required nonzero attempts for running, retry-wait, reconciliation-required, failed and succeeded events. The completed-results list must align exactly with the current-step checkpoint. Corrupt snapshots are rejected before a backup file is published.
