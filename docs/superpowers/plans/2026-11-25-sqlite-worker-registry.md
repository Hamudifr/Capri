# Implementation Plan: Durable SQLite Worker Registry

**Design:** `docs/superpowers/specs/2026-11-25-sqlite-worker-registry.md`  
**Baseline:** `dda020f465b3ed4724683cac46c3d01bf91689bf`  
**Execution:** isolated GitHub branch; Notion CAP-210 is the progress ledger.

## Task 1 — Lock the interface and capacity contract

Files:
- `capri_runtime/worker_registry.py`
- `tests/test_worker_registry.py`

Steps:
1. Add a runtime-checkable `WorkerRegistry` protocol covering registration, descriptor/health lifecycle, eligibility, reservations, recovery lookup, expiry and integrity.
2. Extend `WorkerReservation` with optional principal/task/capability/protocol context; validate all-or-none metadata.
3. Extend `InMemoryWorkerRegistry.reserve_eligible` to accept task context, enforce one active reservation per principal/task, expose `get_reservation_for_task` and `expire_reservations`.
4. Add `integrity_check() == "ephemeral"` to the in-memory implementation.
5. Rename the host-load handoff parameter to `observed_unreserved_in_flight` and document that `WorkerHealth.in_flight` excludes reservation-managed tasks.
6. Add tests first for task binding, duplicate task reservation rejection, expiry reporting, and unreserved-load accounting.

## Task 2 — Implement SQLite persistence and audit

Files:
- `capri_runtime/sqlite_worker_registry.py` (new)
- `tests/test_sqlite_worker_registry.py` (new)

Steps:
1. Add schema initialization for meta, worker state, active reservations and append-only events.
2. Implement canonical serialization/deserialization and wall-clock-to-monotonic freshness conversion.
3. Implement all WorkerRegistry operations with `BEGIN IMMEDIATE`; keep state changes and event append in one transaction.
4. Persist task-bound reservation context and provide recovery by principal/task.
5. Implement pending expiry, committed non-expiry, capacity revalidation and atomic release handoff.
6. Implement hash-chain validation, append-only triggers, event listing, and `integrity_check()`.
7. Add tests for restart persistence, cross-instance concurrency, task uniqueness, capacity revalidation, expiry, committed release, tamper detection and append-only triggers.

## Task 3 — Integrate host runtime and backup validation

Files:
- `capri_runtime/host_runtime.py`
- `capri_runtime/tasks.py`
- `capri_runtime/__init__.py`
- `tests/test_host_gateway.py`
- `tests/test_tasks.py` or the existing task-store backup test module

Steps:
1. Change HostRuntime to accept the WorkerRegistry protocol and require exact task-store identity for SQLiteWorkerRegistry.
2. Remove process-local reservation context/lock; validate wrappers against durable registry records.
3. Add recovery lookup by authenticated principal/task.
4. Rename the host load callback to `worker_unreserved_in_flight_resolver`; preserve fail-closed validation.
5. Add worker-registry integrity to host storage health.
6. Extend task-store backup validation through a local import of `validate_worker_registry_snapshot`; verify schema, state, reservation constraints and audit chain.
7. Test host integration, foreign-task-store rejection, restart recovery, backup/restore and tampered backup rejection.

## Task 4 — Documentation and final verification

Files:
- `docs/NEXUS_WORKER_REGISTRY.md`
- `docs/CAPABILITY_ROADMAP.md`
- `capri_runtime/__init__.py`

Steps:
1. Document SQLite durability, hash-chained audit, unreserved-load semantics, restart recovery and the opaque-token boundary.
2. State clearly that registry persistence does not enable worker dispatch, IPC, process launch or OS isolation.
3. Update the roadmap to distinguish durable reservation state from the earlier process-local primitive.
4. Run targeted tests, full test suite, formatting/lint/type checks, Capri Doctor, operational health and repository skill validation.
5. Review the final diff for secrets, raw tokens in audit, schema migration hazards, process-local fallback, and any accidental dispatch surface.
6. Update the CAP-210 Notion ledger with exact commit IDs, test results, remaining risks and next step.

## Commit sequence

1. `test: specify task-bound worker registry persistence`
2. `feat: persist worker registry and reservation lifecycle in SQLite`
3. `feat: integrate durable worker registry with host runtime`
4. `docs: define durable registry and audit guarantees`

## Stop conditions

- Any schema ambiguity that would rewrite existing task/provider/evidence records.
- Any need to generate or store production credentials.
- Any requirement to launch a worker process or expose model-visible dispatch.
- Any backup validation that cannot preserve existing task-store guarantees.

In those cases, stop the affected change, record the exact blocker in CAP-210, and keep the branch isolated.
