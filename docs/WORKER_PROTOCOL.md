# Nexus worker protocol v1

The worker protocol is a bounded JSON message contract. It is not a process launcher, sandbox, identity provider, authorization system, or task scheduler.

## Request envelope

A request contains:
- protocol version and message type;
- a bounded request identifier;
- a lowercase capability identifier;
- a JSON-object input payload;
- a relative deadline budget in milliseconds.

## Response envelope

A response contains:
- protocol version and message type;
- the correlated request identifier;
- the worker identifier;
- a succeeded/failed status;
- worker-reported duration telemetry;
- exactly one result payload or error.

Unknown fields, duplicate JSON keys, non-standard numeric constants, invalid UTF-8, non-object payloads, unsupported values, cycles in in-memory payloads, excessive nesting, and messages over 1 MiB are rejected.

## Deadline rule

The host owns the deadline. It must:
1. Record a monotonic start timestamp immediately before dispatch.
2. Enforce cancellation/termination at the deadline where the execution environment supports it.
3. Measure elapsed time using the host monotonic nanosecond clock when the response is received and again at the final acceptance boundary if verification can take time.
4. Pass host-measured elapsed nanoseconds to `WorkerResponse.validate_for(..., elapsed_ns=...)`.
5. Reject a response when host-measured elapsed time exceeds the request budget.

The worker-reported `duration_ms` is untrusted telemetry. A value above the budget is rejected as an inconsistency, but a value within the budget is never proof that the deadline was met. Only the host's monotonic measurement can establish that. A worker cannot grant itself more time by changing the reported duration.

## Identity and authority

The host must obtain the expected worker identity from its authenticated execution channel, not from the response body. The response identifier is checked against that trusted value.

A capability string is a routing label, not a permission grant. The host must independently resolve the capability against its own allow-list and enforce principal, resource, budget, and policy constraints before dispatch. Worker output is untrusted data and cannot authorize follow-up actions.

## Current scope and non-goals

This package currently validates and serializes messages only. It does not launch or supervise workers, create OS/container isolation, authenticate a process, enforce a wall-clock timeout, retry tasks, persist receipts, or reconcile ambiguous side effects. Those belong to a future host-owned execution adapter and must not be inferred from this protocol library.

## Example

```python
import time

started_ns = time.monotonic_ns()
# Dispatch request through a host-authenticated worker channel.
# Receive and decode response.
elapsed_ns = time.monotonic_ns() - started_ns
response.validate_for(
    request,
    expected_worker_id=authenticated_worker_id,
    elapsed_ns=elapsed_ns,
)
```

If response verification or persistence is a slow step, measure the monotonic deadline again immediately before accepting the result. Do not rely on a worker-provided duration.
