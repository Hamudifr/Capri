# Non-X5 runtime security review

**Status: DESIGN REVIEW / PARTIALLY IMPLEMENTED CONTROLS / NOT A SECURITY CERTIFICATION**

This document records the current trust boundaries, verified controls, and unresolved risks for the non-X5 runtime foundation. It does not define protected evaluation behavior.

## Scope and assets

The current runtime is a synchronous Python library with durable SQLite sessions, owner-scoped task state, host-injected model adapters, optional local/Notion memory, optional read-only Notion knowledge-graph retrieval, and a permissioned tool-execution gate integrated through `ToolOrchestrator`. `CapriHostRuntime` maps opaque credentials through a trusted `HostAuthorityResolver` and enforces principal ownership for session and task operations. The embedding host still owns its identity provider, permission source, resource-level authorization, secrets, process supervision, and deployment. Capri is not a sandbox or a production-ready multi-tenant service.

Assets requiring protection as the runtime grows:
- session transcripts and user-provided content;
- session identifiers and tenant ownership mappings supplied by the host;
- model-provider credentials held by host adapters;
- provider outputs and operational metadata;
- repository credentials and CI supply-chain integrity.

## Trust boundaries

1. **Host application → runtime:** `HostAuthorityResolver` maps an opaque credential to a principal using host-supplied authentication and permission callbacks. The host still owns the identity provider and resource-level ACLs; a session/task UUID is never an authorization token.
2. **Runtime → model adapter:** adapter code is host-supplied and may call an external provider. The runtime treats adapter exceptions and outputs as untrusted; provider budgets and credential custody remain host responsibilities.
3. **Model output → downstream application:** output is plain text and must not be treated as safe HTML, SQL, shell input, policy, or authorization evidence.
4. **Retrieved memory/graph → model:** retrieved records are explicitly untrusted context. They cannot grant identity, policy, permission, approval, or tool authority; host resolvers must enforce principal-specific scope.
5. **Runtime → trusted handlers:** registered handlers execute with process privileges. They must re-check current resource authorization and idempotency at the external side-effect boundary; Capri is not a sandbox.
6. **Repository → CI actions:** workflow dependencies execute code in the CI environment and must be pinned and granted minimum permissions.

## Controls verified in the current foundation

- Input, output, and session-history character/message bounds.
- User input, adapter output, and direct session-store commits reject lone Unicode surrogate code points before transcript storage.
- Evaluation metadata rejects lone Unicode surrogate code points before UTF-8 ledger serialization.
- Input and output character limits are enforced before model invocation and again at the direct `SessionStore.commit_turn` boundary.
- Session-history limit is enforced both before model invocation and atomically inside `SessionStore.commit_turn`.
- An injected store must use the same input, output, and history limits as its `Runtime`.
- Immutable session/message snapshots and optimistic version checks.
- A session closed while a model call is in progress cannot accept the late response.
- Adapter exception details are suppressed from the public runtime exception.
- Tool execution uses an explicit allowlist, immutable tool contracts, strict bounded JSON schema validation, and exact host permission checks.
- Consequential tool specs require a one-use approval bound to principal, tool, canonical argument digest, and expiry.
- Tool arguments/results are byte-bounded and checked for strict JSON/Unicode; handler exception details are suppressed.
- Redacted audit-start persistence must succeed before a handler is invoked; a post-handler audit failure is surfaced as an uncertain outcome.
- `SQLiteSecurityStore` persists redacted audit events and consumed approval IDs using SQLite transactions, a unique grant-ID constraint, and `BEGIN IMMEDIATE` for atomic cross-executor/process replay prevention.
- On POSIX, the SQLite store requires a current-user-owned private parent directory, rejects symlink/non-regular and hard-linked database paths, and enforces database mode 0600; it rechecks parent/file permissions before each connection.
- SQLite backup publication uses an atomic no-replace primitive: Python hard-link publication where supported, with Linux `renameat2(RENAME_NOREPLACE)` fallback when the filesystem or platform does not support hard links. Unsupported hosts fail closed rather than risk overwriting an existing backup destination.
- The runtime does not log transcript content or provider credentials.
- CI declares `contents: read` and pins checkout/setup-python actions to immutable commit SHAs.

These controls reduce accidental resource abuse and concurrency defects; they do not make the runtime a multi-tenant security boundary.

## Unresolved risks — do not silently choose policy

| Risk | Current state | Required decision or implementation |
|---|---|---|
| Authentication and session ownership | Host credential mapping and owner-scoped session/task APIs implemented; identity provider remains host-owned | Integrate a real identity provider and test current resource-level permissions inside handlers |
| Cross-tenant isolation | Application-level session/task ownership exists; complete tenant isolation is not implemented | Add resource ACL, memory/graph scope, per-principal budgets, and end-to-end negative isolation tests |
| Session count growth | Store has no max-session or expiry policy | Approve quotas, retention, deletion, and expiry before eviction |
| Transcript persistence | Not implemented | Approve storage, encryption, backups, access, export, deletion |
| Adapter timeout/cancellation | No runtime timeout | Define adapter cancellation contract and provider-specific timeout behavior |
| Token/cost budget | Character limits only | Define provider-aware token, spend, and request budgets |
| Rate limiting | Not implemented | Define per-user/tenant/IP quotas at host boundary |
| Tool execution | Permissioned gate is integrated through the orchestrator; SQLite audit/approval persistence exists; handlers remain trusted and unsandboxed | Add per-resource authorization inside handlers, timeouts/isolation, budgets, backup/retention, and stronger same-host tamper controls |
| Retrieval/prompt injection | Optional memory and read-only graph retrieval are implemented as untrusted context; no provider-enforced isolation | Test direct and indirect injection at every action boundary and enforce scope in host resolvers |
| Observability | Minimal | Define redacted structured metadata, retention, alerting, and incident response |

## Current implementation update — 2026-11-25

The following controls are now present in the mainline runtime and should be used instead of older checkpoint descriptions below:

- `CapriHostRuntime` authenticates opaque credentials through host callbacks and enforces principal ownership for durable SQLite sessions and tasks. This is application-level ownership, not a substitute for resource ACLs or complete tenant isolation.
- The OpenAI Responses adapter is integrated through the orchestration/tool-execution path. Provider credentials, budgets, timeouts, and lifecycle remain host-owned.
- Optional memory and read-only Notion knowledge-graph resolvers run only after session ownership checks. Retrieved memory and graph records remain untrusted; graph retrieval is bounded, lexical, and uses a short process-local cache.
- Principal-owned task handlers are isolated from the legacy handler registry. Unknown handler failures, invalid results, uncertain cancellation, and expired running leases enter `reconciliation_required`; only an explicit trusted `RetryableTaskError` permits a bounded retry.
- Private SQLite backup publication uses atomic no-replace semantics, including fallback when hard-link publication is unsupported. Backups remain plaintext and require host-managed protected storage and restore drills.

The current task quarantine state intentionally has no automatic reconciliation/replay API. Operators must establish the external outcome independently before any manual replay. See `docs/TASK_EXECUTION.md` and `docs/KNOWLEDGE_GRAPH_RUNTIME.md` for current contracts.

## Required abuse-case tests before enabling real-world model-driven actions

Use harmless fixtures and instrumented fake adapters/tools. Do not use real destructive actions or protected evaluation material.

- Session ID guessing/reuse cannot cross user or tenant boundaries.
- User-supplied or retrieved instructions cannot change tool authorization.
- Untrusted content cannot trigger an unauthorized tool call.
- Tool arguments are validated against strict schemas and caller permissions. Covered in `tests/test_tools.py`; add integration tests when a real host/model adapter is connected.
- Consumed approval IDs persist across executor/store instances and concurrent consumers have one winner. Covered in `tests/test_security_store.py`.
- Memory poisoning and cross-session transcript leakage are rejected.
- Model output cannot reach HTML, SQL, shell, or filesystem sinks without destination-specific validation.
- Repeated retries, recursive tool calls, and expensive outputs hit bounded budgets.
- High-impact actions pause for action-specific approval and cannot self-approve. The current gate tests exact argument binding, expiry, principal binding, and single-use behavior within one executor process.
- Logs and errors do not disclose prompts, transcripts, credentials, or personal data.

## CI supply-chain posture

The quality workflow uses minimal `contents: read` permissions and immutable action commit references. The current references were verified against the official `actions/checkout` v6 and `actions/setup-python` v7 Git tags; their action metadata declares the Node.js 24 runtime. Review action updates as code changes and keep references immutable.

## Release position

The runtime is not approved for public or multi-tenant deployment. The tool executor is not a sandbox. The in-memory audit sink/default approval store are development foundations; `SQLiteSecurityStore` supplies durable local audit/replay metadata but is not encrypted and still requires host-managed backup, retention, monitoring, and private filesystem ownership. Public or multi-tenant deployment requires host-level identity and authorization, tenant isolation, explicit retention/deletion behavior, operational budgets, provider integration, audit-store backup/retention/restore, cryptographically authenticated approval issuance, handler isolation/timeouts, end-to-end/adversarial tests, observability, backup and rollback capability, and a documented Capri internal release review. External independent review is not a prerequisite for ordinary internal engineering; retain it only when a specific contract, regulation, customer commitment, or protected evaluation explicitly requires it. This document is Capri's internal review, not a security certification.

No X5 instructions, rubrics, expected answers, hidden criteria, scoring keys, or evidence are part of this document or the implementation.


## Historical verification notes

The dated entries below are preserved as historical checkpoints. Their implementation/status descriptions may be superseded by the current sections above; do not treat them as the live release state.

## Tool-boundary internal self-review — 2026-11-06

Capri reviewed the implemented tool gate and its negative tests before integration. Verified properties include explicit registration, strict argument schemas, exact host permissions, principal/tool/argument-digest/expiry-bound approvals, durable SQLite single-use replay protection across executor/process instances (with an in-memory fallback), bounded strict JSON, redacted audit events, audit-start fail-closed behavior, suppressed handler exceptions, and explicit uncertain-outcome behavior when completion auditing fails after handler invocation.

Residual risks are material and intentionally visible: trusted host code can construct execution contexts and approval objects; the grant object is not a cryptographic signature; replay prevention is not durable across process restarts or multiple executors; the included audit sink is in-memory; handlers are not sandboxed and run with process privileges; and the gate is not connected to a model provider. Do not register untrusted handlers or expose consequential tools to model-driven calls until durable replay/audit controls, host identity/authorization, idempotency, budgets, and handler isolation are implemented.

This is Capri's internal security review, not a security certification. External independent review is not a prerequisite for ordinary internal engineering or merging.


## Durable tool-security store self-review — 2026-11-06

Capri reviewed the SQLite implementation and added tests for database mode 0600, private parent-directory ownership/mode, permission revalidation on each connection, symlink and hard-link rejection, audit readback across reopened instances, durable grant replay prevention, expiry, and concurrent single-winner consumption. SQLite uses WAL and FULL synchronous commits. The stored data is restricted to redacted audit metadata and consumed grant identifiers.

Residual risks: the database is not encrypted; SQLite durability is limited by the host filesystem and hardware; backups, retention/compaction, monitoring, and restore drills are host responsibilities; and a malicious process running as the same OS user remains within the host trust boundary. This does not sandbox handlers or replace host authentication/authorization.


## Durable security-store verification — 2026-11-06

PR #18 integrated `SQLiteSecurityStore`. Exact-head PR run [42286374983](https://github.com/Hamudifr/Capri/actions/runs/42286374983) and post-merge main run [42286526969](https://github.com/Hamudifr/Capri/actions/runs/42286526969) both passed compileall, Capri Doctor 6/6, operational health 7/7, and 141 tests on each actual Python 3.11/3.12/3.13 interpreter. All six job logs were inspected.

SQLite now provides durable local audit events and atomic cross-executor/process grant-ID consumption. It is not encrypted; the host still owns backups, retention, restore drills, monitoring, cryptographic approval issuance, identity, and handler isolation.
