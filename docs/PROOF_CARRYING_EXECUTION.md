# Proof-Carrying Execution (PCE)

**Status:** Implemented pure contract; host integration is not implemented.

## Purpose

PCE makes consequential actions auditable as explicit state transitions. Each action is represented by a bounded, data-only Action Capsule. The capsule binds the intended operation to a principal, capability, resource scope, policy version, budget, deadline, idempotency key, and input digest. Events record authorization, dispatch, receipt, verification, and final acceptance or failure.

The first implementation is deliberately a pure core contract. It does not execute tools, authenticate worker processes, enforce budgets, persist state, or verify external side effects. The trusted host must provide those controls.

## Lifecycle

DRAFT -> AUTHORIZED -> DISPATCHED -> RECEIVED -> VERIFIED -> ACCEPTED

Failure outcomes are REJECTED, EXPIRED, CANCELLED, and INDETERMINATE.

- Only the host may issue the decision reference used for AUTHORIZED.
- DISPATCHED requires a host-authenticated worker-binding reference.
- RECEIVED requires a result digest.
- VERIFIED requires evidence references and an identified verifier/version.
- ACCEPTED is possible only after VERIFIED.
- EXPIRED is permitted only from AUTHORIZED, before dispatch, once an authorization deadline has elapsed.
- An undispatched DRAFT may still be closed as CANCELLED or REJECTED after its deadline; it never acquired authority or created an external side effect.
- The lifecycle is acyclic and has at most five transition events. History verification enforces that bound before materializing an untrusted iterable.
- A dispatched action that times out or has an ambiguous external effect becomes INDETERMINATE, never simply EXPIRED or CANCELLED. Reconcile the external system before retrying.
- Terminal states cannot be reopened by this state machine.

The transition helper requires the complete prior event history and verifies that it reconstructs the capsule projection before allowing another transition. History verification is bounded to the five possible lifecycle transitions and stops consuming oversized iterables. This prevents a caller from supplying a fabricated AUTHORIZED projection without its authorization event.

## Integrity model

The immutable capsule metadata is fingerprinted using canonical JSON and SHA-256. Each event binds that capsule digest and the previous event hash. History verification checks sequence numbers, allowed transitions, monotonic timestamps, deadline semantics, event hashes, and that the event chain reconstructs the saved capsule projection.

This is tamper-evident integrity checking, not authentication. SHA-256 chaining does not protect against a privileged attacker who can rewrite the entire event history and recompute hashes. A production host must use authenticated host decision records, authenticated worker channels, append-only persistence, and appropriate external signed checkpoints or protected storage.

## Data minimization

Capsules contain digests and opaque references, not prompts, credentials, secrets, raw tool arguments, or full result payloads. The host retains payloads only in their authorized source systems. Resource scopes, budgets, policy versions, decision references, worker bindings, and evidence references are identifiers, not permission grants by themselves.

## Example

The host creates a DRAFT capsule with a trusted timestamp and bounded resource scope. It records Capri's decision in its own authorization service, then transitions to AUTHORIZED with that opaque decision reference. Before dispatch, the host binds the authenticated worker channel. On receipt, the host records a result digest. An independent verifier checks the actual external outcome and supplies evidence references before the capsule can become VERIFIED and then ACCEPTED.

The caller must persist each event append-only and atomically with the updated capsule projection. The module returns the new projection and event but deliberately provides no database adapter.

## Required integration work

1. Add a host authorization adapter that validates principal, capability, scope, policy version, deadline, and the host decision reference.
2. Bind worker references to actual authenticated process/channel identity, not merely a worker-supplied string.
3. Enforce time and budgets in the host at dispatch and at the final commit boundary. Convert the capsule's absolute UTC deadline to a monotonic deadline once at admission; use the host monotonic clock for elapsed-time enforcement and recheck after slow verification immediately before acceptance.
4. Persist events and capsule projection atomically, with idempotency uniqueness enforced by the host store.
5. Add action-specific independent verifiers and readback receipts.
6. Reconcile INDETERMINATE outcomes before retry; use separately authorized compensating actions for rollback.
7. Add crash/restart, concurrency, replay, and provider-side-effect integration tests before enabling any write-capable adapter.

## Safety boundary

This module is not a runtime permission system, policy engine, worker sandbox, or proof that an external action occurred. A valid capsule can still describe a false claim if the host supplies false evidence. No strategy, worker, model output, or retrieved document may create authority or increase the capsule's declared capability or budget.
