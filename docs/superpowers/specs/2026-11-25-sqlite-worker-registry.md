# Durable SQLite Worker Registry and Reservation Lifecycle

**Status:** implementation design for PR #237 (test-first draft)  
**Baseline:** `dda020f465b3ed4724683cac46c3d01bf91689bf`  
**Scope:** durable worker state, task-bound reservation lifecycle, and append-only audit in the existing private SQLite task database.

## Problem

The current host runtime exposes principal/task-scoped reserve, commit, recover-by-context, and release operations, but the underlying `InMemoryWorkerRegistry` and the host reservation-context dictionary are process-local. A restart loses worker catalogue state, reservation state, and the task-to-reservation association. Multiple host processes also do not share one atomic capacity decision.

## Goals

1. Persist worker descriptors and health observations across host restarts.
2. Persist pending and committed reservations, including principal/task/capability/protocol context.
3. Make reserve, commit, release, and expiry atomic across processes using SQLite write transactions.
4. Persist lifecycle transitions in an append-only, hash-chained audit log.
5. Recover active reservations by `(principal_id, task_id)` without relying on process-local dictionaries.
6. Include registry state and audit integrity in task-store backup/restore validation.
7. Keep the existing in-memory implementation for tests and explicitly ephemeral development.
8. Preserve fail-closed policy revalidation and worker identity checks in `CapriHostRuntime`.

## Non-goals

- No worker process launch, shell commands, IPC, OS sandboxing, or process isolation.
- No automatic worker dispatch. The host APIs reserve and commit capacity only.
- No KMS/HSM provisioning or production key generation.
- No model-visible reservation tools.
- No automatic strategy routing, canary, or activation.
- No claim that a hash chain is authenticated against an attacker who can rewrite the entire private database. The audit chain is tamper-evident; HMAC signing can be added later when a production MAC provider is configured.

## Architecture

### Registry interface

Define a runtime-checkable `WorkerRegistry` protocol covering the common worker and reservation operations. Both `InMemoryWorkerRegistry` and `SQLiteWorkerRegistry` implement it.

The in-memory implementation remains ephemeral and returns `ephemeral` from its integrity/health check. The SQLite implementation exposes its exact `SQLiteTaskStore` reference and must be constructed with the same task store used by `CapriHostRuntime`.

### Durable tables

Create these tables in the task store's existing private SQLite database:

- `worker_registry_meta`: singleton schema version, last audit sequence, current audit-chain head.
- `worker_registry_state`: current canonical descriptor and health state per worker.
- `worker_registry_reservations`: active reservation identifier, worker, principal, task, capability, protocol, descriptor revision, creation/expiry wall-clock times, committed state and revision.
- `worker_registry_events`: append-only lifecycle events with sequence, event ID, event type, actor, worker, task/principal context, canonical payload, previous hash and event hash.

Use foreign keys, checks, indexes, and update/delete-blocking triggers on the event table. State and active-reservation tables are mutable projections; every mutation must append the corresponding audit event in the same SQLite transaction.

### Reservation identifiers and secrets

A reservation token is a random opaque identifier, not an authorization credential. Persist it only in the private task database so a host can recover a reservation after restart. The audit log stores only its SHA-256 digest. Every host operation still requires supervisor authorization, task ownership checks, and worker identity binding. Never log credentials or raw supervisor/worker secrets.

### Transaction model

Every mutation uses `BEGIN IMMEDIATE` on the shared SQLite database. This serializes competing host processes and keeps state changes plus audit append atomic.

- **Register/update/heartbeat/failure/quarantine/retire/recover:** update the state projection and append a lifecycle event in one transaction.
- **Reserve:** purge expired pending holds, enforce the global reservation cap and one-active-reservation-per-task constraint, select an eligible worker, insert the pending reservation, and append `reservation_created` atomically.
- **Commit:** reload the reservation and worker inside the transaction; verify token/context, authenticated worker identity, descriptor revision, freshness, health, capability/protocol, and `unreserved_in_flight + active_reservations <= max_concurrency`; mark committed and append `reservation_committed`.
- **Release:** for pending holds, remove the hold and append release. For committed holds, atomically replace the reservation with the supplied host-observed *unreserved* in-flight count, remove the hold, update health revision, and append `reservation_released`.
- **Expiry:** only pending reservations expire. Committed holds never expire automatically. Expiry removes the pending row and appends `reservation_expired` in the same transaction.
- **Recovery:** `get_reservation_for_task(principal_id, task_id)` returns the durable active reservation so the host can reconstruct its wrapper after restart.

A partial unique index enforces one active reservation per `(principal_id, task_id)`. The registry rejects incomplete task context: principal and task are either both present or both absent. Host APIs always provide both.

### Time model

Do not persist monotonic timestamps. Persist trusted wall-clock nanoseconds for heartbeat and reservation expiry. On read, derive a current-process monotonic timestamp from the wall-clock age. If the wall clock is in the future, moves backwards, or produces an invalid age, fail stale/expired. This is conservative and safe across restarts.

### Capacity semantics

`WorkerHealth.in_flight` and the host resolver represent host-observed **unreserved** work only. The registry separately counts every pending and committed reservation. Do not report reservation-managed tasks in the unreserved count, or they will be double-counted. The host callback should be named `worker_unreserved_in_flight_resolver`; the release argument should be `observed_unreserved_in_flight`.

### Host runtime

- Accept the `WorkerRegistry` protocol rather than requiring `InMemoryWorkerRegistry`.
- Require the exact same `SQLiteTaskStore` instance when a SQLite registry is supplied.
- Remove the process-local reservation-context dictionary and lock; the registry is the durable source of truth.
- Include worker-registry integrity in `storage_health()`.
- Add recovery lookup by authenticated principal and task ID.
- Recheck task ownership, supervisor authorization, and worker policy immediately before commit.
- Keep reservation operations host-only; do not expose them as model tools.

### Audit chain

The global event chain uses monotonically increasing sequence numbers. Each event payload includes the previous event hash; the event hash is SHA-256 over canonical JSON. The meta head and sequence must match the final event. The event table blocks UPDATE and DELETE. Audit events cover worker registration, descriptor updates, meaningful health transitions, failures, quarantine/retirement/recovery, reservation creation/commit/release/expiry/revocation. Do not write every unchanged heartbeat; persist the latest health timestamp in the state projection and audit only meaningful transitions to bound event growth.

### Backup and integrity

Extend `SQLiteTaskStore._validate_backup_snapshot` to validate registry schema, all-or-none table presence, canonical state rows, active reservation constraints, audit sequence/hash chain, meta head, and append-only triggers. The standalone registry integrity check also runs SQLite integrity and foreign-key checks. A backup with partial registry tables or a broken audit chain must fail closed.

## Compatibility and migration

This is a new schema version. Existing task databases with no registry tables remain valid until a `SQLiteWorkerRegistry` is constructed. Initialization creates all registry tables atomically. Partial table sets, unknown schema versions, or invalid existing registry data must raise a clear integrity error rather than silently repair or discard history. No existing task/session/provider-usage rows are rewritten.

## Acceptance criteria

- Registry and reservations survive constructing a new registry/runtime over the same task database.
- Two independent registry instances sharing one database cannot overbook the same worker or reserve one task twice.
- Commit revalidates capacity and descriptor revision under the SQLite transaction.
- Committed release atomically hands off to unreserved host load; pending release and expiry are safe.
- Restart recovery returns the active reservation by principal/task.
- Every lifecycle mutation and audit event commit atomically.
- Audit UPDATE/DELETE attempts fail; tampering or chain truncation is detected by integrity and backup validation.
- Task-store backup/restore preserves worker state, reservations and audit chain.
- HostRuntime accepts the SQLite implementation, rejects a registry backed by a different task store, and reports durable health.
- Full repository CI passes; no dispatch or process execution is enabled.
