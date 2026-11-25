# Capri core and runtime architecture

This document summarizes the current non-X5 implementation. Capri is an evolving Python library and host-composition foundation, not a complete autonomous agent, hosted service, or production multi-tenant deployment.

## Core ledger

`capri_core` provides typed evaluation records, fail-closed validation, and `HashChainLedger`, an append-only JSONL ledger with a SHA-256 hash chain.

The ledger rejects malformed records, duplicate JSON keys, invalid hash links, oversized or unterminated entries, symlink/non-regular paths, and unsafe parent traversal. On supported POSIX systems it uses no-follow directory traversal and validates opened file identity. A write, flush, or fsync failure after writing begins latches both the normalized path and the opened inode in the current process; hard-link aliases are blocked. The inode guard pins descriptors up to a bounded cap, after which the process fails closed globally.

The ledger is plaintext, tamper-evident rather than authenticated, and supports one writer process per file. Platform fallback and recovery procedures are documented in [LEDGER_THREAT_MODEL.md](LEDGER_THREAT_MODEL.md) and [LEDGER_OPERATIONS.md](LEDGER_OPERATIONS.md).

## Runtime layers

### Provider-neutral in-memory runtime

`capri_runtime.runtime.Runtime` and `SessionStore` remain a small provider-neutral, process-local prototype. The host injects a `ModelAdapter`; the runtime commits a user/assistant turn only after a successful response and uses optimistic version checks to prevent stale concurrent commits.

Defaults for this in-memory API:

| Setting | Default | Scope |
| --- | ---: | --- |
| `max_input_chars` | 16,000 | One user message |
| `max_output_chars` | 64,000 | One assistant message |
| `max_tool_chars` | 131,072 | One tool message |
| `max_session_messages` | 200 | One transcript |

Limits count Python string characters, not UTF-8 bytes or provider tokens. There is no aggregate session-count or total-memory quota. Closing an in-memory session does not provide deletion, expiry, or retention management.

### Durable sessions and host composition

`SQLiteSessionStore` persists transcripts in a private SQLite database and supports cross-process optimistic commits, durable turn leases, and immutable principal ownership. Default per-session limits match the table above. The parent directory must be private (0700 or stricter on POSIX); the database file is kept at 0600. Session transcripts are plaintext.

`CapriHostRuntime` is a request-scoped composition layer. It authenticates through an injected `HostAuthorityResolver`, binds every session operation to the resolved principal, checks ownership before memory retrieval or model invocation, and composes `ToolOrchestrator` with optional memory resolution and a host-managed `TaskWorker`.

This is an application-level ownership boundary, not proof of complete tenant isolation. No concrete identity provider, HTTP server, daemon, or deployment package is included. Construction starts no background thread. The host owns authentication integration, process supervision, credentials, and lifecycle. See [HOST_RUNTIME.md](HOST_RUNTIME.md).

### Model and tool execution

`OpenAIResponsesAdapter` is the concrete bounded Responses API adapter. It preserves provider continuation items and converts model function calls into proposals for `ToolOrchestrator`; the model does not directly receive host permission or approval authority. The adapter reads `OPENAI_API_KEY` and `CAPRI_OPENAI_MODEL` only when explicitly constructed from the environment. A live provider request can incur separate API charges; no live request or credential provisioning is implied by this repository.

The permissioned tool boundary uses an explicit registry, strict bounded schemas, host permission checks, action-bound one-use approvals, and redacted durable audit/replay metadata. Handlers are trusted host code executed with the process's privileges. This is not a sandbox. See [OPENAI_RESPONSES_ADAPTER.md](OPENAI_RESPONSES_ADAPTER.md) and [TOOL_EXECUTION.md](TOOL_EXECUTION.md).

### Memory

SQLite and Notion memory providers, bounded retrieval, expiry checks, immutable context validation, and escaped serialization are implemented. Search is deterministic substring matching, not semantic/vector retrieval. Retrieved content is untrusted reference data and must never be promoted into trusted host instructions or tool authority. Serialization and prompt placement are mitigations, not provider-enforced isolation or proof of end-to-end prompt-injection resistance.

The current mainline adapter sends memory separately from the trusted `instructions` field. Draft PR #121 proposes placing that memory item before the conversation transcript so it cannot appear as the newest user turn; that ordering change is not part of main until merged. See [MEMORY_STORE.md](MEMORY_STORE.md) and [MEMORY_AWARE_MODEL_ADAPTER.md](MEMORY_AWARE_MODEL_ADAPTER.md).

### Durable tasks

`SQLiteTaskStore`, `TaskEngine`, and `TaskWorker` provide bounded plans, atomic claims, leases, checkpoints, retries, cancellation at step boundaries, and abandoned-work recovery. Plans contain 1–32 steps; each step permits 1–10 attempts; leases are bounded to 5–3,600 seconds; retry backoff is capped at one hour. Execution is at-least-once, not exactly-once. Side-effecting handlers must enforce the stable per-step idempotency key at the side-effect boundary.

The worker is explicitly host-managed. It starts no thread during construction, does not forcibly interrupt a running handler, and is not a scheduler daemon. See [TASK_EXECUTION.md](TASK_EXECUTION.md).

## Storage, lifecycle, and resource limits

- SQLite session, memory, task, and security stores use private local files and store-specific validation. Their database contents and current backups are plaintext; encryption and key management are not implemented.
- Session limits are per transcript. There is no aggregate session-count, total-memory, or provider-token quota. Sessions have no implemented expiry/deletion/retention workflow; closed sessions remain persisted.
- Memory expiry is evaluated during retrieval and by an explicit sweep; no background expiry worker or continuous synchronization service is started.
- Task plans and individual JSON payloads are bounded, but there is no hosted scheduler or global spend control.
- No per-principal request/token budgets, hard provider spend cap, or automatic rate limiter is implemented.
- Backup methods exist for all four local SQLite stores, but there is no backup scheduler, off-site policy, encrypted backup format, retention/compaction policy, or tested automated restore drill.
- Durable local audit and approval replay protection exist, but the store is not encrypted and approval records are not cryptographically authenticated.
- Host authentication is injected; a production identity provider and complete remote tenant isolation are not implemented.
- Tool handlers run with process privileges; no general sandbox or privilege-separated execution service is implemented.

## Minimal in-memory runtime example

```python
from capri_runtime import Runtime, SessionStore

class EchoAdapter:
    def complete(self, session_id, user_text, history):
        return f"You said: {user_text}"

runtime = Runtime(adapter=EchoAdapter(), store=SessionStore())
session = runtime.create_session()
updated = runtime.respond(session.session_id, "Hello, Capri")
print(updated.version, updated.messages[-1].content)
runtime.close_session(session.session_id)
```

For durable principal-owned sessions, use the host composition described in [HOST_RUNTIME.md](HOST_RUNTIME.md), not this in-memory example.

## Validation

Run locally:

```bash
python -m compileall -q capri_core capri_runtime tests
python -m unittest discover -s tests -v
```

The quality workflow validates Python 3.15 only. Commit-specific counts and outcomes belong to exact-head GitHub Actions evidence, not a hard-coded claim in this document.

## Release position

The implemented foundation is meaningful internal capability, not a claim of AGI or production readiness. Internal self-review is the default for ordinary engineering; it must not be described as independent assurance. Public or hosted multi-tenant release remains blocked on identity-provider integration, tenant-isolation evidence, provider budgets, retention/deletion controls, encrypted backup and restore drills, operational observability, process supervision, handler isolation, and end-to-end adversarial validation. The protected evaluation boundary remains separate and must not be crossed by ordinary engineering work.
