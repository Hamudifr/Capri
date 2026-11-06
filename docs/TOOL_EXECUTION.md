# Permissioned tool execution boundary

## Purpose and current status

`capri_runtime.tools` provides a provider-neutral execution gate between model-proposed tool calls and host-implemented handlers. A model-generated name and argument object are only a request. They are never authority.

This is an internal capability foundation. It does not connect a model provider, discover plugins, execute shell commands, perform network requests, read/write files, or authenticate a person. The host application remains responsible for trusted identity, permission issuance, user approval UX, and durable audit storage.

## Execution sequence

1. The host resolves the authenticated principal and constructs an immutable `ExecutionContext`.
2. The host registers explicit `ToolSpec` objects with injected Python handlers in a `ToolRegistry`.
3. The executor resolves the exact tool name. Unknown tools fail closed.
4. The executor checks the exact permission string in the trusted host context.
5. Arguments are canonicalized as strict UTF-8 JSON, bounded by bytes, and validated against the tool's deliberately limited schema.
6. Consequential tools require an `ApprovalGrant` matching the principal, tool name, and SHA-256 digest of the exact canonical arguments. Grants must be timezone-aware and unexpired, and are consumed once per executor instance.
7. A redacted `started` audit event must persist before the handler is invoked. If this write fails, the handler is not called.
8. The injected handler receives a fresh JSON-decoded copy of the validated arguments. Exceptions are suppressed; raw arguments and handler output are never included in audit events.
9. Results must be valid JSON with string object keys, valid Unicode scalar values, and fit within the configured byte limit.
10. A completion/failure audit event is written. If this write fails after the handler has run, the caller receives `AuditError`; the external side effect may already have happened and its outcome is uncertain.

## Schema subset

Supported schema keywords are `type`, `properties`, `required`, `additionalProperties: false`, `items`, `enum`, `minLength`, `maxLength`, `minimum`, `maximum`, `minItems`, and `maxItems`. Supported types are object, array, string, integer, number, boolean, and null. The root argument schema must be an object. Unsupported keywords, undeclared fields, duplicate registration, and invalid definitions are rejected. Nesting is limited to 16 levels and object properties to 128 fields.

## Approval and authority model

- Permission strings and the principal identity come from the host, never from model output.
- An approval grant is scoped to one principal, one tool, one exact argument digest, and an expiry.
- With the default in-memory store, grants are one-use within one executor instance unless the same store is shared. Inject `SQLiteSecurityStore` as both `audit_sink` and `approval_store` to persist consumed grant IDs across executor instances and processes.
- The grant dataclass is not a cryptographic signature. Only trusted host code may construct grants after authenticating the user's approval. Do not deserialize arbitrary model/user JSON directly into an `ExecutionContext` or `ApprovalGrant`.
- A permission check is not a substitute for per-resource authorization. A handler must still enforce ownership, tenant scope, and domain invariants before performing its action.
- The executor is not a sandbox. Handlers execute with the Python process's privileges. Register only trusted, reviewed host functions.

## Audit and failure behavior

Audit events contain event ID, UTC timestamp, principal ID, tool name, canonical argument digest, status, and a bounded error code. They deliberately omit raw arguments, prompts, outputs, credentials, and secrets.

The supplied `InMemoryAuditSink` and default `InMemoryApprovalStore` are process-local, non-durable development implementations; the default approval store is scoped to one executor unless deliberately shared. `SQLiteSecurityStore` is now available as a standard-library durable implementation of both `AuditSink` and `ApprovalStore`. It requires an existing private directory, rejects symlink/non-regular database paths, enforces POSIX directory ownership/private mode and database mode 0600, uses SQLite WAL with full synchronous commits, and atomically consumes grant IDs with `BEGIN IMMEDIATE` plus a unique primary key. Its audit table stores only redacted metadata. Hosts still own backup, retention, access control, integrity monitoring, and key/host security. Audit persistence is fail-closed before handler invocation. A completion-audit failure after a handler returns is inherently an uncertain-outcome case; callers must not blindly retry non-idempotent actions.

## Explicit non-goals and next hardening

Not implemented: cryptographically authenticated approvals, durable cross-process replay prevention, handler sandboxing, cancellation/timeouts, per-tool rate limits, per-principal quotas, tenant identity, durable audit storage, tool discovery, model-provider integration, or automatic retries.

Before exposing consequential handlers to an actual model, add host authentication and authorization, durable grant replay protection, durable audit storage, idempotency keys for side effects, rate/resource budgets, handler timeouts/cancellation, and adversarial integration tests. Keep dangerous capabilities absent by default.

## Durable store verification

`SQLiteSecurityStore` is covered by `tests/test_security_store.py`: database permissions, integrity check, audit readback across instances, durable approval replay prevention, concurrent single-winner consumption, expiry, symlink rejection, and unsafe/missing parent directories. The SQLite store does not encrypt data; its database contains only redacted operational metadata and consumed grant identifiers. The host must keep the parent directory private and provide backups/retention controls.
