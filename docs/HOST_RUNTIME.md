# Host runtime and principal-owned sessions

## Scope

`CapriHostRuntime` is a request-scoped composition layer. It wires trusted authentication, durable principal-owned sessions, the existing `ToolOrchestrator`, optional memory retrieval, and an explicitly injected task worker.

It is not an HTTP server, daemon, deployment package, authentication provider, or production multi-tenant service. Construction starts no thread and makes no model-provider request.

## Session ownership

`SQLiteSessionStore` now supports atomic `create_for_principal()` and owner-scoped read, close, commit, and lease operations.

- A session is created together with its immutable owner row in one SQLite transaction.
- Owner-scoped operations use the authenticated principal returned by `HostAuthorityResolver`, never a client-supplied principal ID.
- A session owned by another principal and a legacy unowned session both appear as `SessionNotFoundError`; the host does not disclose whether a foreign session ID exists.
- The host runtime wraps the SQLite store in a `PrincipalBoundSessionStore` for the entire coordinated turn, including durable lease claims, heartbeat renewals, reads, and commits.
- Existing sessions created through the legacy unscoped `create()` API remain unowned. They are not automatically assigned to any principal and cannot be accessed through `CapriHostRuntime`.

Owner rows have no public reassignment or deletion API and SQLite triggers reject direct owner updates/deletes. A privileged host with direct database access can still bypass application boundaries; protect the SQLite file and its directory. SQLite transcripts are plaintext, not encrypted at rest.

`SQLiteSessionStore.backup_to()` creates a consistent private snapshot that includes ownership records and triggers. The backup is also plaintext; see [SQLITE_SESSION_BACKUP.md](SQLITE_SESSION_BACKUP.md). Task, memory, security, and session stores now expose private consistent backup methods; the backups remain plaintext and no scheduler, retention policy, or automated restore workflow is provided. See [SQLITE_STORE_BACKUP.md](SQLITE_STORE_BACKUP.md).

## Composition

The host supplies:

The SQLite session store's `max_output_chars` must be at least the greater of the orchestrator's `max_output_chars` and `max_tool_message_bytes`; `max_tool_chars` must cover `max_tool_message_bytes`. CapriHostRuntime validates these limits at construction and fails early if they are incompatible.

1. A trusted `HostAuthorityResolver` whose authentication callback maps opaque credentials to stable principal IDs and whose permission callback returns current least-privilege grants.
2. A private `SQLiteSessionStore`.
3. A configured `ToolOrchestrator`, including the model adapter and `ToolExecutionBridge`.
4. Optionally, a memory resolver with signature `(principal_id, session_id, user_text) -> UntrustedMemoryContext | None`. It must enforce principal-scoped memory access. The resolver runs only after authentication, session ownership, and input validation succeed.
5. Optionally, a `TaskWorker`. The host explicitly runs it through `run_task_worker(stop_event)` under its own process supervisor.

Example:

```python
from capri_runtime import (
    CapriHostRuntime,
    HostAuthorityResolver,
    OpenAIResponsesAdapter,
    SQLiteSessionStore,
    ToolExecutionBridge,
    ToolExecutor,
    ToolOrchestrator,
    ToolRegistry,
)

authority = HostAuthorityResolver(
    authenticate=authenticate_opaque_credential,
    permissions_for=load_current_permissions,
)
sessions = SQLiteSessionStore("/private/capri/sessions.sqlite3", max_output_chars=131072)
adapter = OpenAIResponsesAdapter.from_environment()
bridge = ToolExecutionBridge(ToolExecutor(ToolRegistry(), audit_sink))
orchestrator = ToolOrchestrator(adapter, bridge)
host = CapriHostRuntime(authority, sessions, orchestrator)

session = host.create_session(request_credential)
result = host.run_turn(request_credential, session.session_id, "Hello")
```

The OpenAI adapter reads `OPENAI_API_KEY` and `CAPRI_OPENAI_MODEL` only when explicitly constructed from the environment. Its first model call can incur separate API charges. This documentation and test suite make no provider request and do not provision credentials.

## Approval and worker boundaries

`CapriHostRuntime` returns the committed `OrchestrationResult`, including any `approval_required` outcomes. The embedding host remains responsible for presenting an approval request and connecting the existing `HostToolGateway` / `HostApprovalService` challenge workflow to its user interface. Do not treat a model-generated tool call as approval.

The optional task worker is not automatically started. `run_task_worker(stop_event)` blocks in the current process until the host sets the stop event. Use a real process supervisor for restart policy, shutdown, logs, and health checks. Task handlers must remain idempotent and enforce their own authorization.

## Validation and limitations

The host-runtime tests cover:
- Principal-owned session creation and persistence.
- Cross-principal denial for reads, turns, and close.
- Denial before memory retrieval or model invocation.
- Ownership-scoped durable lease and commit paths.
- Closed-session behavior, invalid inputs, and redacted memory resolver errors.

These tests establish an application-level session ownership boundary, not complete tenant isolation. Before external multi-user deployment, add authentication integration tests, memory-provider ACL tests, rate limiting, per-principal provider budgets, approval UX, structured observability, encrypted backup storage, task/memory-store backups, retention and restore drills, and deployment hardening.
