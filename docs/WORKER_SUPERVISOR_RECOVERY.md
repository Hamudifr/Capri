# Nexus worker supervisor recovery contract

**Status:** operational contract draft; not production authorization  
**Scope:** restart and reconciliation of the durable SQLite worker registry and task-bound reservations  
**Related:** GitHub issue #246, PR #242, PR #250, `docs/superpowers/specs/2026-11-25-sqlite-worker-registry.md`

This runbook describes the host/supervisor boundary. It does not launch workers, dispatch tasks, authenticate a transport, or provide process isolation. A recovered SQLite row is state to reconcile, not permission to resume work.

## Safety invariants

1. **Quiesce before acknowledgement.** No old host or supervisor may still mutate the registry while reconciliation is being acknowledged. Use an external single-supervisor lease or equivalent host-level exclusion. SQLite serializes individual write transactions; it does not elect the one supervisor responsible for a multi-step recovery.
2. **Re-authenticate workers.** Never trust a persisted worker ID, descriptor, heartbeat, or reservation as proof that the same process is alive. Re-establish identity through the trusted host transport and compare it with the persisted identity before marking a worker healthy or making it eligible.
3. **Separate reserved from unreserved load.** The supervisor's load observation must count only work not represented by an active registry reservation. Pending and committed reservations are counted by the registry. Counting them again in `in_flight` double-counts capacity; omitting unreserved work can overbook a worker.
4. **Do not infer completion.** A committed reservation means capacity was committed, not that an external task completed. An uncertain task outcome remains uncertain until the external system is queried or reconciled.
5. **Never auto-replay.** Do not recreate, re-dispatch, or release a committed reservation merely because the host restarted or its TTL elapsed. Only pending reservations expire automatically.
6. **Fail closed on incomplete audit.** A pending lifecycle-operation marker or failed integrity check blocks runtime construction until an authorized reconciliation is completed against the same durable security store.

## Required restart sequence

### 1. Fence and preserve

- Stop new work admission and prevent new reservations.
- Acquire the host's external single-supervisor lease.
- Quiesce the old host and all registry writers. Confirm no old process can resume writes.
- Preserve the task/security database and take a consistent private backup using the store's supported backup method. Verify the backup before any recovery mutation.
- Record the database identity, backup location, timestamp, software version, and operator/supervisor identity in the host's protected operational record. Do not copy secrets or raw reservation tokens into the record.

If writer quiescence or exclusive supervisor ownership cannot be established, stop. Do not acknowledge reconciliation.

### 2. Inspect durable state

- Open the exact existing `SQLiteTaskStore` and `SQLiteSecurityStore` instances that the replacement host will use.
- Run the supported SQLite integrity, foreign-key, worker-registry projection, and audit-chain checks.
- Inspect `worker_lifecycle_reconciliation_required()`. A pending operation or outstanding reservation is a reconciliation condition, not a clean startup.
- Enumerate active reservations through the registry's supported API. Record only token digests and the task/principal/worker identifiers required for reconciliation.
- Compare each persisted worker with a newly authenticated transport identity. A matching string alone is insufficient if the transport has not authenticated the current process.

Any malformed schema, projection mismatch, audit-chain failure, unknown worker identity, or unexplained reservation is a stop condition. Preserve evidence and escalate to the host operator; do not edit SQLite rows directly.

### 3. Reconcile each worker and task

For every persisted worker:

- Confirm whether the authenticated worker process is the expected instance.
- Obtain a fresh host-side health observation.
- Obtain the current count of **unreserved** in-flight work from the trusted supervisor.
- Treat a missing, stale, unauthenticated, or identity-mismatched worker as unavailable. Do not make it eligible based on its last persisted heartbeat.
- Reconcile each reservation against the external task system. Distinguish pending (not committed) from committed (capacity was committed) reservations.
- For a pending reservation whose TTL elapsed, allow the registry's normal expiry path to record expiry. Do not manually delete it.
- For a committed reservation, determine whether the external operation is still running, completed, failed, or indeterminate. Preserve an indeterminate outcome; do not retry automatically.
- If the worker disappeared while work may be in flight, quarantine or mark it unavailable through supported host APIs and retain the task's uncertain state until external reconciliation establishes the outcome.

The supervisor must not treat a worker's self-reported load as authoritative. The host-observed unreserved load resolver is the source for that component of capacity accounting.

### 4. Acknowledge and reopen

Only after all relevant workers and reservations have been inspected:

- Reconfirm the old writer is fenced and the current supervisor still holds the external lease.
- Re-run integrity and projection checks.
- **Do not acknowledge while active reservations remain.** `worker_lifecycle_reconciliation_required()` returns true for either pending operation markers or outstanding reservations. `acknowledge_worker_lifecycle_reconciliation(note)` records an audit boundary and clears the pending-operation count, but it does not remove reservations; therefore the startup gate remains closed while any reservation remains.
- Resolve every active reservation against the external task system. A committed reservation may be released only after the external outcome and current unreserved load are established. An unknown outcome remains a hard stop.
- **Current implementation blocker:** `CapriHostRuntime` checks `worker_lifecycle_reconciliation_required()` during construction and rejects outstanding reservations, but the repository does not yet expose a separate host-audited supervisor API that can resolve/release those reservations before constructing the replacement runtime. The normal host release API requires a constructed runtime, creating a recovery deadlock for this case.
- Do not work around this gap with direct SQL, a fresh in-memory audit sink, or an un-audited direct registry mutation. Keep admission stopped until a dedicated supervisor reconciliation API is implemented and tested.
- Once that API has resolved all reservations and persisted the corresponding registry and host lifecycle events, call `acknowledge_worker_lifecycle_reconciliation(note)` on the **same durable security store** used by the prior runtime. The note should identify the recovery record and summarize the reconciliation outcome without containing secrets.
- Read back the lifecycle state and verify that no pending operation or outstanding reservation remains. Then construct the replacement `CapriHostRuntime` over the same task and security stores, re-authenticate workers, re-check policy and capacity, and resume admission only while the external supervisor lease remains held.

If acknowledgement or runtime construction fails, keep admission stopped. Do not switch to a fresh in-memory audit store to bypass the durable gate.

## Failure handling

| Condition | Required behavior |
|---|---|
| Old supervisor may still be writing | Stop; retain the fence and do not acknowledge |
| Worker cannot be re-authenticated | Keep it unavailable; preserve reservations and reconcile task outcomes |
| Worker reports stale heartbeat | Treat as stale until fresh authenticated heartbeat is observed |
| Unreserved load cannot be measured | Do not mark the worker eligible; fail closed for capacity decisions |
| Pending reservation expired | Let the registry's transactional expiry path record it |
| Committed reservation exists after restart | Reconcile the external task; never expire or replay it automatically |
| Task outcome is unknown | Keep it quarantined/uncertain; require external evidence before retry |
| Audit marker or chain is invalid | Preserve database and backup; stop writes and investigate |
| Supervisor acknowledgement is interrupted | Reopen under the same durable store; inspect pending state and repeat reconciliation, not direct SQL repair |
| Two supervisors contend | External lease must select one; SQLite transaction locking is not a substitute |

## Current implementation blocker

The current startup gate and acknowledgement API do not yet provide a complete restart path when outstanding reservations exist. The gate rejects outstanding reservations, while the acknowledgement method clears only pending-operation markers and deliberately leaves reservation rows intact. Because the normal host release path is unavailable until a runtime has been constructed, there is no verified out-of-band route to complete this reconciliation cycle. This is a concrete implementation gap, not an operator procedure that can safely be completed manually. Issue #246 must add a narrowly scoped, authenticated, host-audited supervisor reconciliation API before this runbook can be treated as executable.

## Adversarial validation still required

The following tests are release gates, not claims that this document alone proves the behavior:

1. **Repeated restart:** restart twice with pending and committed reservations; no reservation is silently lost, duplicated, or auto-replayed.
2. **Concurrent supervisors:** two supervisors race for the external lease; exactly one may acknowledge. A stale supervisor cannot acknowledge after losing the lease.
3. **Worker loss during reconciliation:** a worker disappears after identity validation but before acknowledgement; the reconciliation must be invalidated or restarted, and the worker must not become eligible.
4. **Interrupted acknowledgement:** inject failure before, during, and after the acknowledgement transaction; restart must distinguish committed acknowledgement from an incomplete operation without clearing unrelated state.
5. **Load accounting:** verify reserved work is excluded from the unreserved count and that capacity cannot be overbooked.
6. **Task uncertainty:** a committed reservation with an unknown external outcome remains quarantined and is never automatically replayed.

## Audit authenticity limitation

The worker registry currently uses a canonical SHA-256 hash chain, projection validation, and SQLite append-only triggers. These detect many accidental or partial modifications, but they do **not** authenticate history against an attacker able to rewrite the complete SQLite database and recompute the chain. The checkpoint/signature trust boundary tracked separately in issue #246 remains unimplemented. Do not describe the current chain as independently protected or cryptographically authenticated.

A future checkpoint implementation must use a host-supplied key provider and a separately protected monotonic checkpoint store. Key material must not be stored in this repository or the SQLite database. It must define key IDs, rotation and retirement, backup/restore behavior, compromise recovery, and explicit behavior when the external checkpoint service is unavailable. Restoring a database older than the latest external checkpoint must fail closed; an older signed checkpoint must not be accepted as the latest merely because its signature is valid.

## Release boundary

This runbook is a draft contract and a test plan. It does not satisfy issue #246's supervisor acceptance criteria until the adversarial lifecycle tests and exact-head CI pass. It does not authorize worker process launch, arbitrary command execution, authenticated IPC, OS isolation, production dispatch, or production cutover.
