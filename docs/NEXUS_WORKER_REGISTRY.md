# Nexus Worker Registry v1

## Purpose

The first registry is a bounded, thread-safe, in-memory catalogue for a single host process. It tracks host-approved worker descriptors and host-observed health, then returns deterministic candidate metadata to a separate host dispatcher.

It is deliberately not a distributed registry or a worker runtime.

## Trust boundaries

- Registration, descriptor updates, heartbeats, failure reports, quarantine and retirement are host-side operations.
- The authenticated worker ID passed to registration/heartbeat/failure methods must come from a trusted host supervisor or authenticated transport. A worker ID copied from a JSON response is not authentication.
- Capability labels in descriptors are host-approved routing metadata. Worker self-advertisements must never be copied into descriptors without host validation.
- The host authorization layer must independently determine the authorized worker-ID set for the current principal and task. Pass that result to eligible-candidate lookup.
- Registry results are advisory. The dispatcher must re-check principal, capability, resource scope, approvals, budgets, protocol compatibility and worker identity immediately before dispatch and again when accepting a response.
- Registry membership, health, priority and capability metadata do not grant tools, permissions, approvals or execution authority.

## v1 API

- `WorkerDescriptor`: stable worker ID, supported protocol versions, host-approved capability labels, bounded priority/concurrency, enabled flag and compare-and-swap revision.
- `WorkerHealth`: state, host monotonic heartbeat time, consecutive host-observed failures, host-observed in-flight count and revision.
- `InMemoryWorkerRegistry.register`: binds a host-provided descriptor to the identity authenticated by the host transport. New registrations start ineligible.
- `heartbeat`: only a trusted host observation can make a starting/degraded/unavailable worker healthy. Quarantined and retired workers cannot heartbeat themselves back into service.
- `record_failure`: transitions workers through degraded to unavailable at a bounded threshold.
- `quarantine` / `clear_quarantine`: quarantine is sticky until an explicit host-side compare-and-swap recovery, followed by a fresh heartbeat.
- `retire`: permanently disables the worker record in v1.
- `update_descriptor`: host-side compare-and-swap descriptor update.
- `eligible`: advisory filtering by host policy allow-list, capability, protocol version, enabled state, health, heartbeat freshness and remaining capacity. Ranking is deterministic: configured priority descending, combined in-flight/reserved load ascending, worker ID ascending.
- `reserve_eligible`: atomically selects one eligible worker and creates a short-lived pending capacity hold under the registry lock. It returns an opaque `WorkerReservation` or `None` when no worker is eligible.
- `commit_reservation`: atomically converts a live pending hold into a non-expiring committed/in-flight hold before dispatch. It fails closed if the hold expired, was revoked, the descriptor revision changed, worker health is no longer fresh/healthy, or current host-observed in-flight load plus all holds would exceed configured capacity. Repeating the commit with the committed token is idempotent.
- `release_reservation`: releases a pending hold before dispatch, or atomically replaces a committed hold with the host-observed in-flight count after completion/reconciliation. A committed hold cannot be released without a valid non-negative `observed_in_flight` value. Repeated, expired or revoked releases return `False`; an identity mismatch is rejected.
- Pending reservations expire after a bounded TTL (default 10 seconds, configurable from 1–60 seconds); committed reservations do not expire automatically. Both count against capacity and the global 4,096 reservation cap. Worker health/descriptor changes revoke pending holds but preserve committed work until explicit completion/reconciliation release.

## Limits and failure semantics

- Maximum 1,024 records by default; configurable only up to that hard ceiling.
- Maximum 64 capability labels and 16 protocol versions per descriptor.
- Heartbeat TTL is bounded to 1–300 seconds; default 30 seconds.
- Concurrency is bounded to 1–256 per worker.
- Health freshness uses host monotonic time only. Missing, stale or future timestamps fail closed.
- The registry is process-local and non-durable. Restart loses the catalogue and all health state; a host must re-register workers and obtain fresh authenticated heartbeats.
- This module does not persist audit events. The integrating host must send registration, policy, health, quarantine, recovery and retirement transitions to its durable audit sink.
- Reservations prevent concurrent dispatchers using this registry from over-selecting the same advertised capacity. They are process-local coordination tokens, not dispatch authorization or durable leases. The required order is: reserve a pending hold; re-check policy and transport identity; commit the hold before dispatch/acceptance; dispatch; on completion or reconciliation, call `release_reservation` with the host-observed in-flight count. The committed hold and replacement load count are updated under one lock, so there is no interval in which active work is unaccounted. A committed hold never expires automatically; only pending holds expire. A process crash loses all holds and requires supervisor reconciliation before the registry is considered healthy again.
- No process launch, IPC transport, sandboxing, cancellation, retry, side-effect reconciliation or automatic recovery is implemented here.

## Minimal usage

```python
from capri_runtime import InMemoryWorkerRegistry, WorkerDescriptor

registry = InMemoryWorkerRegistry()
registry.register(
    WorkerDescriptor(
        worker_id="local-python-1",
        protocol_versions=(1,),
        capabilities=("math.factorial",),
        max_concurrency=2,
    ),
    authenticated_worker_id="local-python-1",  # supplied by trusted host transport
)
registry.heartbeat(
    "local-python-1",
    authenticated_worker_id="local-python-1",
    in_flight=0,  # host-observed, not worker-asserted
)

# This allow-list must come from the separate host authorization policy.
reservation = registry.reserve_eligible(
    "math.factorial",
    protocol_version=1,
    authorized_worker_ids={"local-python-1"},
)
if reservation is not None:
    authenticated_worker_id = authenticated_transport.worker_id
    # Re-check policy and authenticated transport immediately before dispatch.
    committed = registry.commit_reservation(
        reservation, authenticated_worker_id=authenticated_worker_id,
    )
    if committed is not None:
        try:
            # The trusted host dispatcher starts work here.
            pass
        finally:
            # Atomically replace the committed hold with host-observed load.
            registry.release_reservation(
                committed,
                authenticated_worker_id=authenticated_worker_id,
                observed_in_flight=host_monitor.in_flight_count(authenticated_worker_id),
            )
```

## Next integration boundary

Before connecting this catalogue to a dispatcher, integrate a trusted host supervisor that supplies authenticated transport identity, re-checks principal/task/capability/resource/approval/budget policy at dispatch and response acceptance, updates host-observed in-flight counts, and records lifecycle events in a durable audit sink. Keep process launch, cancellation, OS isolation and restart policy separate from this registry.

## Trusted host runtime gateway

`CapriHostRuntime` can optionally expose the registry through five injected host callbacks:

- `worker_identity_resolver(credential)`: authenticates a worker transport and returns the worker ID bound to that authenticated channel. Used for registration; it must not read an ID from an unauthenticated payload.
- `worker_descriptor_resolver(worker_id, proposed_descriptor)`: returns the exact host-approved `WorkerDescriptor` for that identity. It must derive protocol versions, capabilities, priority and concurrency from host configuration/policy rather than blindly trusting worker self-advertisements.
- `worker_observer_authorizer(credential, worker_id)`: authenticates a separate host supervisor/monitor credential and authorizes it to report health for that worker. Worker transport credentials must be rejected.
- `worker_in_flight_resolver(worker_id)`: returns the in-flight count measured by the trusted host supervisor. The heartbeat API accepts no caller-supplied load count; worker payloads cannot claim zero load or otherwise alter capacity.
- `worker_policy_resolver(principal_id, task_id, capability)`: returns a set/frozenset of worker IDs authorized by the host for this exact principal, task and capability. The embedding host must include all applicable resource, approval, budget and task-state checks; the registry does not infer them.
- `worker_registry`: the process-local catalogue instance.

The runtime gateway exposes registration, supervisor-observed heartbeat/failure recording, advisory candidate lookup, and a principal/task-scoped reservation lifecycle:

- `reserve_worker_candidate(credential, task_id, capability, protocol_version)` authenticates the principal, verifies task ownership, obtains the host policy allow-list, and atomically reserves one eligible worker. It returns a `HostWorkerReservation` wrapper or `None`.
- `commit_worker_reservation(credential, observer_credential, reservation)` rechecks principal ownership and current task policy, authenticates the separate supervisor/monitor credential, refreshes host-observed load, and commits the pending hold. The registry's committed hold does not expire automatically.
- `mark_worker_reservation_started(observer_credential, reservation)` requires supervisor authorization and is called after the worker accepts the task. It obtains the total host-observed in-flight count and atomically replaces that committed hold with `WorkerHealth.in_flight`.
- `release_worker_reservation(observer_credential, reservation)` releases a pending or committed hold only when dispatch did not start or was rejected. It does not update host load.
- `HostWorkerReservation` binds the opaque registry token to the authenticated principal, task, capability and protocol version in process-local host context. The runtime rejects context rebinding and purges expired pending contexts. Do not expose this wrapper or the lifecycle methods as model-visible tools.

Registration binds the worker ID to the authenticated worker transport and passes the proposed descriptor through the host descriptor-approval resolver. Heartbeat and failure observations require the separate supervisor/monitor credential. Heartbeat load is derived from the host monitor, never from a worker-provided field. Candidate lookup and reservation both verify task ownership and apply the separate host policy resolver; the policy callback must include resource, approval, budget and task-state checks.

The gateway can reserve and account for capacity, but it does not dispatch, launch a process, implement IPC, accept a worker response, or provide OS isolation. A dispatcher must re-evaluate policy and transport identity immediately before dispatch and response acceptance. Callback exceptions, worker credentials presented as supervisor credentials, invalid policy/load results, stale tokens and cross-task reservation reuse fail closed and are surfaced as redacted host errors. The registry and reservation context are process-local; the integrating host must send lifecycle transitions to a durable audit sink and reconcile after restart.

Example composition:

```python
host = CapriHostRuntime(
    authority,
    session_store,
    orchestrator,
    task_store=task_store,
    worker_registry=registry,
    worker_identity_resolver=authenticate_worker_transport,
    worker_descriptor_resolver=approve_worker_descriptor_from_host_config,
    worker_observer_authorizer=authenticate_supervisor_for_worker,
    worker_in_flight_resolver=host_observed_in_flight_count,
    worker_policy_resolver=authorized_workers_for_task,
)
```
