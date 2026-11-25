# Host Approval Lifecycle

## Status

Design contract for the next implementation increment. This document does not claim that an approval UI, identity provider, notification channel, or deployed approval service exists.

## Existing building blocks

Capri already has:

- `ToolCallOutcome(status="approval_required", argument_digest=...)` from the tool bridge.
- `HmacApprovalAuthority` for short-lived, signed grants bound to principal, tool, exact canonical argument digest, expiry, and explicit signing-key ID. `HmacApprovalKeyRing` supports bounded host-managed key rotation.
- `ToolExecutor` strict signed-grant verification.
- `SQLiteSecurityStore` for durable, cross-process one-use grant consumption and redacted audit events.
- `HostAuthorityResolver` and `HostToolGateway` for host-owned authentication and permission resolution.

These pieces do not yet implement a durable pending-approval lifecycle or authenticate the human who confirms a pending operation.

## Required state machine

A challenge has exactly one terminal decision:

```text
PENDING ── authenticated approve ──> APPROVED
   │
   ├──── authenticated reject ─────> REJECTED
   │
   └──── expiry / timeout ─────────> EXPIRED
```

Terminal states are immutable. No transition may return to PENDING. Expiry is checked against an injected timezone-aware UTC clock at the decision transaction, not only when a challenge is displayed.

## Request creation

Only trusted host code may create a challenge, after it receives an `approval_required` outcome from the bridge. It must use the authenticated request principal and the outcome's argument digest. The challenge binds:

- random challenge ID;
- original principal ID;
- exact tool name;
- SHA-256 digest of canonical validated arguments;
- originating call/operation ID (stable and unique within the host's idempotency domain);
- creation and expiry timestamps;
- pending/terminal status.

Do not persist raw arguments, prompts, credentials, tool results, or secrets in the approval record. The human-facing approval view may display a separately generated, redacted operation summary, but the summary is informational and never the authorization binding.

Challenge creation must be idempotent for a stable operation ID: repeating the same operation returns the existing challenge; reusing the ID with different principal/tool/digest is rejected. A challenge ID alone must not be treated as proof of identity.

## Decision and grant issuance

The public decision entry point accepts an opaque host credential and a challenge ID, not an approver ID, grant, signature, principal, tool, or argument digest from the client.

1. The host authentication callback resolves the credential to an authenticated approver principal.
2. A host-owned authorization policy checks that this approver may decide this challenge. The callback must return the exact boolean `True`; exceptions and all other values deny.
3. The store begins a write transaction and re-reads the challenge.
4. It rejects unknown, expired, already rejected, or mismatched challenges. An already approved challenge may return the same previously issued grant only to an authorized approver and only while the grant remains valid; it must never mint a second grant.
5. For a first approval, the trusted host signer issues a short-lived grant using the challenge's stored principal, tool, and digest. The store atomically records the approver, decision, and complete signed grant before returning it.
6. The grant is delivered only to trusted host code, then supplied through the host's normal authority-resolution path. The model and untrusted client never receive the signing key or signer.

Signing and state transition must be serialized by the same database transaction/lock. If the transaction fails, no grant is returned. If the response is lost after commit, an authorized retry reads the same grant rather than issuing another one.

Rejection is also authenticated, authorized, atomic, immutable, and audited. Missing or expired decisions fail closed. No timeout, model instruction, tool output, or notification callback may approve a challenge.

## Storage and concurrency requirements

Use the existing private SQLite security database and its filesystem checks; do not create a second weaker database. Add a dedicated challenge table with constraints and indexes:

- primary key on challenge ID;
- unique key on stable operation ID;
- bounded principal/tool/digest/timestamp/status fields;
- optional approver ID and signed-grant fields, present only for APPROVED;
- check constraints for legal statuses and consistent terminal fields.

Use `BEGIN IMMEDIATE` for challenge creation and decisions. Enforce idempotency and one terminal decision in SQL, not only in Python locks. The existing `consumed_approvals` primary key remains the final one-use replay barrier across executor instances and processes. Approval challenge state and grant consumption are separate facts: APPROVED does not mean EXECUTED.

Do not delete consumed grant IDs merely because the grant expires; retention/compaction requires a documented replay horizon and must not re-enable an unexpired grant. Keep audit records redacted. Database contents are not encrypted; retain existing private-directory, file-mode, backup, and host-access requirements.

## Trust boundaries

- The model may propose an operation; it cannot authenticate, approve, sign, or decide policy.
- The client may submit an opaque credential and challenge ID; it cannot choose authority fields.
- The host authentication provider establishes approver identity.
- Host policy decides whether that identity may approve the requested principal/tool. Self-approval policy must be explicit; default to disallowing self-approval for consequential operations unless the deployment deliberately configures otherwise.
- The HMAC signer proves grant integrity/origin, not human intent. The authenticated decision event is the evidence of intent.
- The executor remains the enforcement point: strict signature verification, exact principal/tool/digest matching, expiry, durable one-use consumption, and audit-before-handler.
- Tool handlers still need resource-level authorization and stable idempotency keys. Approval does not make a non-idempotent external side effect safe to retry.

## Required adversarial tests before release

1. Unauthenticated and unauthorized credentials cannot approve or reject.
2. Client-supplied principal, approver, tool, digest, signature, or grant fields are ignored/rejected.
3. Challenge expiry, malformed timestamps, clock errors, and boundary-time equality fail closed.
4. Different principal/tool/digest cannot reuse a challenge or grant.
5. Concurrent approve/approve, approve/reject, and duplicate create calls have one deterministic winner.
6. Repeated authorized approval after a lost response returns the same grant ID/signature, not a new grant.
7. A rejected or expired challenge can never issue a grant.
8. Process restart preserves pending/terminal state and grant material.
9. Executor replay protection still permits at most one handler invocation across independent stores/processes.
10. Store failure before commit returns no grant; response loss after commit is safely recoverable.
11. Audit records contain no credentials, raw arguments, prompts, results, or signing key.
12. Tests verify that approval is not execution and that an approved-but-unconsumed grant remains subject to expiry and exact-match checks.

## Deployment gate

Do not expose consequential tools to an external model until the host has a real identity provider, protected signing-key custody, authenticated approval UX, durable SQLite replay/challenge storage, handler idempotency, resource authorization, and operational backup/retention controls. This library is a framework component, not a deployed production approval service.


## Implemented library API (PR #50)

The following host-side library components now implement the core lifecycle:

- `SQLiteApprovalChallengeStore(SQLiteSecurityStore)` creates the challenge table in the existing hardened security database. It does not open a second database.
- `HostApprovalService` accepts a trusted store, host-held `HmacApprovalAuthority`, an approver-authentication callback, and an approver-authorization callback.
- `create_challenge(context, outcome, operation_id)` accepts only an `ExecutionContext` and a `ToolCallOutcome` whose status is `approval_required`. The host must call this after the bridge returns that outcome and provide an operation ID stable in its own idempotency domain.
- `approve(opaque_credential, challenge_id)` and `reject(opaque_credential, challenge_id)` authenticate and authorize the approver. Callback exceptions and non-exact-True authorization results deny.
- Self-approval is denied by default. A host may deliberately opt in with `allow_self_approval=True`; consequential tools should retain the default.
- Grant creation occurs inside the same SQLite `BEGIN IMMEDIATE` transaction as the state transition. The signed grant is persisted before it is returned. Authorized repeated approval returns the same persisted grant rather than minting another.
- Challenge creation, approval, rejection, and expiry emit redacted audit events. The challenge row stores approver identity and signed grant material; it never stores raw tool arguments, credentials, prompts, or results.

The service is a trusted host API, not a model-facing endpoint. The application must keep it and the signer private, authenticate users with a real identity provider, implement its own approval UI and policy, and pass the resulting grant only through the host's normal authority-resolution path. The existing executor still performs signature verification and durable one-use consumption before a handler runs.

The store currently uses the existing SQLiteSecurityStore's internal connection and lock hooks so it shares its filesystem protections and transaction database. Keep these classes in the same trusted package boundary; do not hand the store, signer, or service object to model-generated code or untrusted clients. SQLite database contents are not encrypted at rest.


## Gateway integration (PR #51)

`HostToolGateway` can now optionally integrate the approval service. Enable it only when all three trusted host dependencies are configured:

- `approval_service`: the host-owned `HostApprovalService`;
- `operation_id_resolver(credential, execution_context, request)`: derives a stable operation ID from authenticated host session state and the specific request;
- `on_approval_challenge(challenge)`: delivers the durable challenge to the host's authenticated approval UX/notification path.

The gateway invokes this only for bridge outcomes with status `approval_required`. It returns the original `ToolCallOutcome` to the model unchanged; challenge objects are sent only to the host callback. The model does not receive the challenge ID or signer. If notification fails after challenge persistence, the gateway reports a host error; retrying the same operation ID recovers the existing challenge, so the notification callback should be idempotent by challenge ID.

The operation-ID resolver is the critical integration boundary. It must use host-authenticated session identity plus stable request identity and must not trust an operation ID supplied by the client/model. The current request call ID alone is not globally unique; a host should namespace it with a trusted session identifier and reject reuse with a different digest. A new intentional attempt should receive a new operation ID, while a retry of the same logical attempt must reuse its original ID.

After a challenge is approved, the host's authority resolver must supply the persisted grant to the original principal's next execution context. The gateway does not inject grants or bypass the normal executor checks. The executor still verifies the signature and consumes the grant once. No approval integration is enabled by default, preserving existing gateway behavior.


## Non-exportable MAC provider boundary — 2026-11-06

The core now defines an ApprovalMacProvider protocol for host integrations with KMS/HSM-backed HMAC operations. It exposes only the active immutable key ID, sign(key_id, payload), and verify(key_id, payload, signature); raw key bytes are not part of the interface. The provider must operate on the exact requested key version, return a 32-byte HMAC-SHA256 tag from signing, return an actual boolean from verification, and fail closed on errors. No vendor adapter or cloud connection is included.


## Durable domain-action approval bridge — 2026-11-25

The host approval service now supports a generic host-owned action challenge in addition to the tool-outcome adapter:

- `create_action_challenge(principal_id, action_name, argument_digest, operation_id)` is a trusted host API. It is not model-facing.
- `get_challenge_by_operation_id()` recovers the durable record for a stable operation ID.
- `verify_grant()` verifies the HMAC and that the exact grant is stored on the matching approved challenge.
- SQLite triggers make challenge identity immutable, permit only one transition from PENDING to a terminal state, prevent terminal-row updates, and prohibit challenge deletion.
- New approval grants include the authenticated approver ID and actual grant-issuance timestamp inside the HMAC payload. Legacy grants without these optional fields remain verifiable by the generic service for compatibility; the strategy bridge requires both.

The strategy-specific adapter is `StrategyApprovalBridge` in `capri_runtime.strategy_approvals`. It binds principal, strategy class/ID/version, evaluation fingerprint, config fingerprint, expected generation, action, stable operation ID, challenge creation time, approver identity and HMAC grant. The strategy grant lifetime must not exceed 15 minutes; the challenge lifetime is separately governed by the host approval policy. Use the same trusted UTC clock for HostApprovalService and its HMAC signer. Pass `bridge.verify` as the `SQLiteStrategyStore` approval verifier. The bridge is host-only and must not be exposed to model input.

This is an authenticated approval bridge, not a deployed approval UI or identity provider. It does not authenticate evidence manifests, bind the multi-cohort StrategyPromotionAssessment record, route canaries, or activate strategies automatically. The host still owns user-facing disclosure, identity, authorization policy, evidence provenance, task-family classification and the explicit call to activate/rollback. The current strategy store's evaluation fingerprint is a single StrategyEvaluation cohort hash; binding the full promotion assessment is a separate required gate before automatic staged promotion.
