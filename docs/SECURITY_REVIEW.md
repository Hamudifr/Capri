# Non-X5 runtime security review

**Status: DESIGN REVIEW / PARTIALLY IMPLEMENTED CONTROLS / NOT A SECURITY CERTIFICATION**

This document records the current trust boundaries, verified controls, and unresolved risks for the non-X5 runtime foundation. It does not define protected evaluation behavior.

## Scope and assets

The current runtime is a synchronous Python library with process-local sessions and a host-injected text adapter. It does not execute tools, persist transcripts, retrieve external documents, or authenticate users.

Assets requiring protection as the runtime grows:
- session transcripts and user-provided content;
- session identifiers and tenant ownership mappings supplied by the host;
- model-provider credentials held by host adapters;
- provider outputs and operational metadata;
- repository credentials and CI supply-chain integrity.

## Trust boundaries

1. **Host application → runtime:** caller identity and authorization are not established by the runtime. A session UUID is an identifier, never an authorization token.
2. **Runtime → model adapter:** adapter code is host-supplied and may call an external provider. The runtime treats adapter exceptions and outputs as untrusted.
3. **Model output → downstream application:** output is plain text and must not be treated as safe HTML, SQL, shell input, policy, or authorization evidence.
4. **Repository → CI actions:** workflow dependencies execute code in the CI environment and must be pinned and granted minimum permissions.

## Controls verified in the current foundation

- Input, output, and session-history character/message bounds.
- Evaluation metadata rejects lone Unicode surrogate code points before UTF-8 ledger serialization.
- Session-history limit is enforced both before model invocation and atomically inside `SessionStore.commit_turn`.
- An injected store must use the same history limit as its `Runtime`.
- Immutable session/message snapshots and optimistic version checks.
- A session closed while a model call is in progress cannot accept the late response.
- Adapter exception details are suppressed from the public runtime exception.
- The runtime does not log transcript content or provider credentials.
- CI declares `contents: read` and pins checkout/setup-python actions to immutable commit SHAs.

These controls reduce accidental resource abuse and concurrency defects; they do not make the runtime a multi-tenant security boundary.

## Unresolved risks — do not silently choose policy

| Risk | Current state | Required decision or implementation |
|---|---|---|
| Authentication and session ownership | Host responsibility | Define identity provider, ownership model, authorization checks |
| Cross-tenant isolation | Not implemented | Tenant boundary and negative isolation tests |
| Session count growth | Store has no max-session or expiry policy | Approve quotas, retention, deletion, and expiry before eviction |
| Transcript persistence | Not implemented | Approve storage, encryption, backups, access, export, deletion |
| Adapter timeout/cancellation | No runtime timeout | Define adapter cancellation contract and provider-specific timeout behavior |
| Token/cost budget | Character limits only | Define provider-aware token, spend, and request budgets |
| Rate limiting | Not implemented | Define per-user/tenant/IP quotas at host boundary |
| Tool execution | Disabled | Define per-tool allowlists, authorization, schema validation, approval and audit policy |
| Retrieval/prompt injection | No retrieval path | Treat retrieved material as untrusted data; test direct and indirect injection at every action boundary |
| Observability | Minimal | Define redacted structured metadata, retention, alerting, and incident response |

## Required abuse-case tests before agent capabilities

Use harmless fixtures and instrumented fake adapters/tools. Do not use real destructive actions or protected evaluation material.

- Session ID guessing/reuse cannot cross user or tenant boundaries.
- User-supplied or retrieved instructions cannot change tool authorization.
- Untrusted content cannot trigger an unauthorized tool call.
- Tool arguments are validated against strict schemas and caller permissions.
- Memory poisoning and cross-session transcript leakage are rejected.
- Model output cannot reach HTML, SQL, shell, or filesystem sinks without destination-specific validation.
- Repeated retries, recursive tool calls, and expensive outputs hit bounded budgets.
- High-impact actions pause for action-specific approval and cannot self-approve.
- Logs and errors do not disclose prompts, transcripts, credentials, or personal data.

## CI supply-chain posture

The quality workflow uses minimal `contents: read` permissions and immutable action commit references. The current references were verified against the official `actions/checkout` v6 and `actions/setup-python` v7 Git tags; their action metadata declares the Node.js 24 runtime. Review action updates as code changes and keep references immutable.

## Release position

The runtime is not approved for public or multi-tenant deployment. Production readiness requires an approved non-X5 product/security specification, host-level identity and authorization, retention/deletion decisions, operational budgets, provider integration, integration/adversarial tests, independent review, and deployment review.

No X5 instructions, rubrics, expected answers, hidden criteria, scoring keys, or evidence are part of this document or the implementation.
