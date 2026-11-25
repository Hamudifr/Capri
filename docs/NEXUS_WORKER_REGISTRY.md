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
- `eligible`: filters by the host policy allow-list, capability, protocol version, enabled state, health, heartbeat freshness and available concurrency. Ranking is deterministic: configured priority descending, in-flight load ascending, worker ID ascending.

## Limits and failure semantics

- Maximum 1,024 records by default; configurable only up to that hard ceiling.
- Maximum 64 capability labels and 16 protocol versions per descriptor.
- Heartbeat TTL is bounded to 1–300 seconds; default 30 seconds.
- Concurrency is bounded to 1–256 per worker.
- Health freshness uses host monotonic time only. Missing, stale or future timestamps fail closed.
- The registry is process-local and non-durable. Restart loses the catalogue and all health state; a host must re-register workers and obtain fresh authenticated heartbeats.
- This module does not persist audit events. The integrating host must send registration, policy, health, quarantine, recovery and retirement transitions to its durable audit sink.
- There is no atomic dispatch reservation in v1. Candidate selection is advisory and can become stale immediately; a future dispatcher must own race-safe capacity reservation and revalidate policy at dispatch time.
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
candidates = registry.eligible(
    "math.factorial",
    protocol_version=1,
    authorized_worker_ids={"local-python-1"},
)
```

## Next integration boundary

Before connecting this catalogue to a dispatcher, implement host-authenticated transport/supervisor identity, durable audit integration, and an atomic host-owned capacity reservation. Keep dispatch policy and worker execution separate from this registry.
