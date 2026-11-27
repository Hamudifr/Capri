# Permissioned tool execution boundary

## Purpose and current status

`capri_runtime.tools` provides a provider-neutral execution gate between model-proposed tool calls and host-implemented handlers. A model-generated name and argument object are only a request. They are never authority.

This is an internal capability foundation. It does not connect a model provider, discover plugins, execute shell commands, perform network requests, or read/write files. `HostAuthorityResolver` supplies a narrow callback contract for trusted host authentication and policy lookup; it is not an identity provider, credential validator, session manager, or cryptographic trust boundary. The host application remains responsible for those systems and durable audit storage.

## Execution sequence

1. The host authenticates the opaque request credential with its own identity system. It may use `HostAuthorityResolver` to call trusted authentication and permission-policy callbacks, producing an immutable `ExecutionContext`. Never accept a caller- or model-constructed context as proof of identity.
2. The host registers explicit `ToolSpec` objects with injected Python handlers in a `ToolRegistry`.
3. The executor resolves the exact tool name. Unknown tools fail closed.
4. The executor checks the exact permission string in the trusted host context. If the `ToolSpec` defines a trusted `resource_authorizer`, it receives a fresh validated argument object and the trusted `ExecutionContext`; only an exact boolean `True` authorizes the resource. Exceptions and non-boolean results fail closed and are recorded as redacted permission-denied audit events. Resource authorization runs before handler dispatch.
5. Arguments are canonicalized as strict UTF-8 JSON, bounded by bytes, and validated against the tool's deliberately limited schema.
6. A redacted `started` audit event must persist before the handler is invoked. If this write fails, the handler is not called.
7. The injected handler receives a fresh JSON-decoded copy of the validated arguments. Exceptions are suppressed; raw arguments and handler output are never included in audit events.
8. Results must be valid JSON with string object keys, valid Unicode scalar values, and fit within the configured byte limit.
9. A completion/failure audit event is written. If this write fails after the handler has run, the caller receives `AuditError`; the external side effect may already have happened and its outcome is uncertain.

## Schema subset

Supported schema keywords are `type`, `properties`, `required`, `additionalProperties: false`, `items`, `enum`, `minLength`, `maxLength`, `minimum`, `maximum`, `minItems`, and `maxItems`. Supported types are object, array, string, integer, number, boolean, and null. The root argument schema must be an object. Unsupported keywords, undeclared fields, duplicate registration, and invalid definitions are rejected. Nesting is limited to 16 levels and object properties to 128 fields.

## Authority model

- Permission strings and the principal identity come from trusted host callbacks, never from model output or request-supplied permission fields. `HostAuthorityResolver` fails closed on authentication/policy exceptions, invalid principal IDs, and malformed permission collections. The resolver is only as trustworthy as the callbacks installed by the host; callbacks must be fixed during application startup and must not be user-configurable.
- Per the owner's 2026-11-27 directive, Capri is the sole decision authority: no per-action approval gate, approval grant, or human permission checkpoint exists anywhere in the tool boundary. Consequential tools execute under the same trusted permission checks as every other tool, and every execution is recorded in the redacted audit trail.
- Coarse permission checks are not a substitute for per-resource authorization. Use the optional host-supplied `ToolSpec.resource_authorizer` for reusable ownership/tenant checks, and retain handler-level checks for resource state and domain invariants immediately before side effects. Never trust a model-supplied owner or tenant field as authority.
- The executor is not a sandbox. Handlers execute with the Python process's privileges. Register only trusted, reviewed host functions.

## Audit and failure behavior

Audit events contain event ID, UTC timestamp, principal ID, tool name, canonical argument digest, status, and a bounded error code. They deliberately omit raw arguments, prompts, outputs, credentials, and secrets.

The supplied `InMemoryAuditSink` is a process-local, non-durable development implementation. `SQLiteSecurityStore` is available as a standard-library durable `AuditSink`. It requires an existing private directory, rejects symlink/non-regular database paths, enforces POSIX directory ownership/private mode and database mode 0600, uses SQLite WAL with full synchronous commits, and appends audit events atomically with `BEGIN IMMEDIATE` under append-only triggers. Its audit table stores only redacted metadata. `SQLiteSecurityStore.backup_to(path)` creates a consistent standalone SQLite snapshot with SQLite's online backup API, checks its integrity, publishes it without overwriting an existing path, and enforces a private destination directory/file. It preserves committed audit state, including data committed through WAL. Backups are still plaintext and must be protected, rotated, retained, and restore-tested by the host. Hosts still own retention, access control, integrity monitoring, and key/host security. Audit persistence is fail-closed before handler invocation. A completion-audit failure after a handler returns is inherently an uncertain-outcome case; callers must not blindly retry non-idempotent actions.

## Explicit non-goals and next hardening

Not implemented: a concrete identity provider/session validator, handler sandboxing, handler timeouts, per-tool rate limits, per-principal quotas, tenant identity provider, tool discovery, model-provider integration, or automatic retries. HMAC MAC signing for evidence and audit attestation is provided by `ApprovalMacProvider`/`HmacApprovalKeyRing`, but production key custody and host identity wiring remain host responsibilities. Cooperative cancellation plumbing exists for opted-in handlers, but handlers must implement and poll it. Durable local audit metadata is implemented by `SQLiteSecurityStore`; encryption, backup/restore automation, retention/compaction, and monitoring are not.

Before exposing consequential handlers to an actual model, connect a real host identity provider to the resolver, protect MAC key custody for evidence attestation, add rate/resource budgets, enforce handler timeout/process isolation where needed, audit-store backup/restore and retention controls, and adversarial integration tests. Keep dangerous capabilities absent by default.

## Durable store verification

`SQLiteSecurityStore` is covered by `tests/test_security_store.py`: database permissions, integrity check, audit readback across instances, append-only chain enforcement, symlink rejection, and unsafe/missing parent directories. The SQLite store does not encrypt data; its database contains only redacted operational metadata. The host must keep the parent directory private and provide backups/retention controls.


## Model-to-tool bridge

`capri_runtime.tool_bridge.ToolExecutionBridge` accepts bounded batches of structured `ToolCallRequest` values and routes every call through the existing `ToolExecutor`. It validates the entire batch envelope (call IDs, duplicate IDs, object arguments, call count, and total bytes) before the first handler can run. Each call then receives the executor's existing schema, trusted permission, audit, and result checks.

The host supplies the `ExecutionContext`; the bridge never creates or modifies identity or permissions from model data. Tool specs may explicitly opt into cooperative cancellation with `cooperative_cancellation=True`; such handlers receive the host-owned cancellation event as a second argument and should poll it at safe checkpoints. If a handler raises `ToolCancelledError` after it has started, the executor records an `outcome_uncertain` audit event and the bridge reports an uncertain outcome because partial side effects may already have occurred. A cancellation signaled before handler invocation is reported as `cancelled` without running the handler. Existing one-argument handlers remain unchanged by default. `available_tools(context)` returns only schemas whose permission is already present in that trusted context.

Outcomes are returned per call in request order. Audit failures are reported as `outcome_uncertain`, because the executor cannot always distinguish a failed pre-handler audit write from a failed completion write after a side effect. The bridge never retries an uncertain call. A `ToolExecutionError` becomes a generic handler-failed outcome; raw exception details are not returned.

This is a provider-neutral execution bridge, not a model-provider adapter, conversation loop, authenticated identity system, sandbox, or resource-level authorization layer. The host must authenticate the principal, build the context, and enforce per-resource ownership in handlers. Do not blindly retry uncertain side effects.


## Bounded model/tool orchestration

`capri_runtime.orchestration.ToolOrchestrator` implements a provider-neutral loop around a host-supplied `ToolModelAdapter`. Each adapter response is a typed `AssistantTurn` containing final text or a tuple of structured `ToolCallRequest` objects. The orchestrator passes only permission-filtered `ToolDefinition` schemas to the adapter and sends every proposed batch through `ToolExecutionBridge`; it has no direct handler access and cannot construct identity or permissions.

The loop is bounded by a configurable maximum number of tool rounds, call-batch size, per-message bytes, aggregate UTF-8 transcript bytes (including framing overhead), and history-message count. Before executing a tool batch, it reserves the maximum configured result envelope for every call against the remaining transcript budget; this conservative preflight prevents a side effect from succeeding when its result cannot fit into the returned transcript. Hosts can tune `max_history_bytes` and `max_tool_message_bytes` together for their provider context window. Call IDs must remain unique across the turn. A repeated ID is returned to the model as an invalid request and is not executed again. A malformed batch fails before its handlers are invoked. Denied, failed, and uncertain outcomes are returned as structured tool messages so the adapter can decide how to continue. Uncertain outcomes are never retried by the orchestrator.

The adapter is injected by trusted host code and is responsible for translating provider-specific messages and tool schemas. `ToolOrchestrator.run()` accepts an optional host-owned cancellation event and checks it before each model round and before tool execution. The bridge checks the same event between individual handlers; calls not yet started receive a `cancelled` outcome. This is cooperative cancellation only: a handler already running cannot be forcibly interrupted, and a side effect already performed cannot be recalled. Its history argument contains the prior conversation plus the current user message exactly once, followed by intermediate assistant-call and tool-result messages as the loop progresses. No separate repeated user-text field is passed to subsequent rounds. No provider SDK, credentials, network client, or automatic plugin discovery is included. `ToolOrchestrator.run()` is stateless with respect to persistence: it returns the full provider-neutral transcript, and the host decides how to store it. The host must serialize concurrent turns for the same session before calling `run()`; otherwise two turns could execute side effects before one loses a later optimistic session commit. The host also owns identity authentication, per-resource authorization, process isolation, timeouts, cancellation, and transcript retention.


## Durable conversation sessions

`capri_runtime.sqlite_sessions.SQLiteSessionStore` is a drop-in `SessionStore` subclass accepted by `Runtime`. It persists session metadata, transcript messages, closed state, and optimistic version numbers in SQLite. Each turn commit and close operation uses `BEGIN IMMEDIATE` and updates transactionally; stale versions fail with `SessionConflictError`, including across independent store instances/processes. Reopening the store recovers the transcript and version.

The database path must be in an existing directory owned by the current user and private (0700 or stricter on POSIX). The database file is regular, non-symlink, single-link, and forced to mode 0600; directory and file properties are rechecked on every connection. SQLite uses WAL and full synchronous commits.

**Data handling:** transcript messages are stored as plaintext JSON. This is not encryption at rest. The host must protect the device, parent directory, WAL files, backups, and retention lifecycle. Do not store credentials, secrets, or sensitive personal data unless a separate encryption and data-governance layer is provided.


## Persisting tool-enabled turns

Both `SessionStore` and `SQLiteSessionStore` expose `commit_turn_messages(session_id, expected_version, turn_messages)`. It atomically appends one complete turn beginning with one user message and ending with an assistant message; intermediate assistant tool-call messages and tool-result messages are preserved in order. The session version advances once per user turn. Invalid role sequences, incomplete turns, oversized messages, stale versions, and closed sessions fail without committing.

A host can persist a completed `ToolOrchestrator` result by loading the session snapshot, running the orchestrator with that snapshot as history, extracting the appended turn from `result.messages[len(session.messages):]`, then passing that tuple and the original `session.version` to `commit_turn_messages`. The host must serialize turns per session **before** calling the orchestrator: optimistic commit detects a stale result after generation, but it cannot undo tool side effects already performed by a concurrent turn. The SQLite implementation protects the final transcript commit across processes; it does not itself provide a pre-execution session lease.


## Same-session turn coordination

`SessionTurnCoordinator.run_and_commit(orchestrator, store, session_id, user_text, context)` provides a bounded-memory, fixed-stripe lock coordinator for one host process. It holds the session lock across snapshot retrieval, model/tool orchestration, and the atomic `commit_turn_messages` call. This prevents two requests routed through the same coordinator instance from executing tools concurrently against the same session. Hash collisions can serialize unrelated sessions but cannot weaken same-session exclusion.

The coordinator also passes the store's message-count limit into the orchestrator. Before model invocation, it verifies that the store's assistant-output limit covers both final assistant output and assistant tool-call envelopes, that the tool-result limit covers the orchestrator's tool-message byte cap, and that the current user message fits the store input limit. The orchestrator reserves room for the current tool-call messages, all corresponding tool results, and a final assistant message before executing a batch. These preflights prevent successful side effects from being followed by predictable persistence failures caused by undersized session limits.

**Store/orchestrator limit alignment:** the default orchestrator tool-message byte cap is 131,072, while the default session assistant-output cap is 64,000 characters. Assistant tool-call envelopes are persisted as assistant messages, so a default tool-enabled coordinator must be paired with `max_output_chars=131_072` (and `max_tool_chars=131_072`) or with deliberately reduced, mutually compatible orchestrator limits. The coordinator checks these limits before model invocation or tool side effects. Example: `SQLiteSessionStore(path, max_output_chars=131_072, max_tool_chars=131_072)`.

**Multi-process limitation:** in-memory session stores provide process-local locks only. When paired with SQLiteSessionStore, the coordinator uses a durable renewable lease with owner-token commit fencing. Lease expiry still cannot forcibly stop a paused handler or undo an external side effect already in progress; handlers require idempotency and resource-level authorization.


Session stores enforce a separate `max_tool_chars` budget (default 131,072 characters) for tool-result messages; assistant text remains governed by `max_output_chars`. This keeps the persisted tool-result allowance aligned with the orchestrator's default tool-message budget instead of incorrectly applying the smaller assistant-output limit to tool payloads.


## Cross-process session-turn leases

`SQLiteSessionStore` adds durable `claim_turn_lease`, `renew_turn_lease`, and `release_turn_lease` operations. A lease is acquired transactionally for one session and one random owner token; another worker cannot claim it while unexpired. The coordinator renews the lease on a heartbeat thread while the model and tools run, checks lease health before commit, and supplies the owner token to the transcript commit. The commit rechecks owner and expiry inside the same SQLite write transaction. Any existing lease row, including an expired row, requires a still-live matching owner token; a stale owner cannot commit without a token or delete an expired lease. A new worker must reclaim the expired row with a fresh token before committing.

`SessionTurnCoordinator` automatically uses this durable lease contract when the store exposes it. With the in-memory `SessionStore`, it uses only process-local lock stripes. Durable lease expiry is a crash-recovery mechanism, not a sandbox or a hard cancellation mechanism: a process paused beyond lease expiry may still have an active handler. The old owner cannot renew or commit after takeover, but external side effects already in progress cannot be recalled. Tool handlers still need stable idempotency keys and resource-level authorization. Hosts must monitor heartbeat failures and must not blindly retry uncertain side effects.


## Host invocation facade

`capri_runtime.host.HostToolGateway` is the credential-only request boundary for hosts that want to avoid passing `ExecutionContext` through untrusted request plumbing. The host constructs the gateway at startup with a fixed `HostAuthorityResolver` and a fixed `ToolExecutionBridge`. Request handlers call `available_tools(credential)` or `execute_batch(credential, requests)`; the gateway resolves a fresh context internally for each call and never accepts a caller-supplied context parameter. Invalid credentials or resolver failures stop before tool discovery/execution. The gateway does not itself validate credentials: its resolver callbacks must delegate to the host's real identity provider and authoritative policy service. Keep the gateway, resolver callbacks, bridge, registry, and handler references inside trusted application code; do not let clients choose or replace them. Direct use of lower-level `ToolExecutor`, `ToolExecutionBridge`, or construction of `ExecutionContext` remains possible to trusted Python code, so the application must expose only the gateway through its external request boundary.


**Remote MAC provider integration:** the core package defines the ApprovalMacProvider contract (used for strategy-evidence attestation and future audit checkpoint signing) but ships no cloud-specific adapter. A host adapter should use non-exportable MAC operations, map provider version identifiers to key IDs, return the raw 32-byte HMAC-SHA256 result from sign, and return an exact boolean from verify. Do not use a mutable alias as the persisted key ID; resolve and persist the immutable key/version identifier used for signing. Provider errors must fail closed. See the official [AWS KMS HMAC key documentation](https://docs.aws.amazon.com/kms/latest/developerguide/hmac.html), [Google Cloud KMS MAC signatures](https://docs.cloud.google.com/kms/docs/mac-signatures), and [HashiCorp Vault Transit API](https://developer.hashicorp.com/vault/api-docs/secret/transit).

## Isolated untrusted memory context

The tool orchestrator can optionally receive an immutable `UntrustedMemoryContext`. When present, it requires the adapter's explicit `complete_with_tools_and_memory` method and passes memory as a separate typed argument, never as transcript history. The normal `ExecutionContext` remains a separate trusted host input to tool discovery and execution. Adapters must treat every memory field as untrusted data and place it only in a provider-supported untrusted-data channel; they must not promote retrieved text into system/developer instructions. If an adapter cannot preserve this distinction, it must not accept memory context. This separation prevents memory records from directly mutating host permissions, but it is not a guarantee against model-level prompt injection.


## Post-handler result rejection is an uncertain outcome

The executor distinguishes argument validation failures (which occur before a
handler runs) from result validation failures (which occur after the handler may
have performed a side effect). A handler result that is non-JSON, malformed, or
over the configured result byte limit raises `ToolResultValidationError`, a
backward-compatible subclass of `ToolValidationError`. The bridge maps this
specific post-handler failure to `outcome_uncertain` with
`handler_result_rejected`, preserving the argument digest. It must never be
reported as `invalid_arguments` or blindly retried: the handler may already
have changed an external resource. The audit trail records `result_rejected`.


## Tool-call idempotency (at-most-once with safe retry)

`capri_runtime.idempotency` provides optional, opt-in tool-call idempotency so
a retried call (network retransmission, provider replay of the same function
call, host crash recovery) cannot duplicate a side effect.

**Contract.** The host passes an `idempotency_key` to
`ToolExecutor.execute(...)` (or sets it on `ToolCallRequest`; the OpenAI
adapter reuses the provider `call_id` automatically). Keys are scoped per
principal: the same key under two principals are independent records. A
completed record is keyed by `(principal_id, key)` and carries a fingerprint of
`tool_name:sha256(canonical_arguments)`.

**Semantics, evaluated before any side effect** (before budget reservation,
resource authorization, and handler dispatch):

- First use with a given fingerprint: the key is reserved, the handler runs,
  and the outcome (succeeded, handler-failed, or result-rejected) is memoized.
- Retry with the same key and same fingerprint: the handler does not run
  again; `IdempotencyReplay` returns the byte-identical memoized result
  (failures replay as failures too). The bridge reports `replayed=True`.
- Same key, different tool or arguments: `IdempotencyConflictError`, mapped by
  the bridge to `idempotency_conflict`/`idempotency_key_reused`.
- Key still in flight in another thread: `IdempotencyInProgressError`, mapped
  to `in_progress`/`idempotency_in_progress`.
- Pre-handler denials (permission, budget, invalid arguments) are not
  memoized: they have no side effect, so a retry re-derives them idempotently.
- Records expire after a TTL (default 24h) and are then reclaimed for reuse.

**Stores.** `InMemoryIdempotencyStore` (process-local, development) and
`SQLiteIdempotencyStore` (durable, WAL, `BEGIN IMMEDIATE`, atomic
reserve-then-complete) both satisfy the `IdempotencyStore` protocol. The store
is independent of the audit store; hosts choose persistence explicitly by
passing `idempotency_store=` to the executor. Without a store, behavior is
unchanged and keys are ignored.

**Guarantee.** At most one handler execution per `(principal, key, fingerprint)`
under concurrency; a completed outcome replays byte-identically. This is not a
substitute for host-side authorization or resource-level fencing, and an
`outcome_uncertain` result after a crash must still not be blindly retried by
the model loop—the bridge and orchestrator never auto-retry uncertain calls.
