# Capri runtime runtime specification — approval template

**Status: DRAFT / NOT APPROVED / NOT IMPLEMENTATION AUTHORITY**

This document is a decision template. It records the minimum product decisions required before implementing a runtime. Blank or unresolved fields are blockers, not permission for implementers to choose defaults.

This template describes ordinary Capri runtime behavior and evaluation requirements. Include the scenarios, criteria, expected outcomes, and evidence needed to make the specification reproducible. Do not include credentials, private user data, or customer-confidential information.

## 1. Ownership and approval

- Product owner:
- Specification author:
- Approver with authority to define runtime behavior:
- Specification version:
- Approval date:
- Related requirements or design documents:

Approval statement: "I authorize implementation of the runtime behaviors defined in this specification."

## 2. Purpose and boundaries

- Primary user problem Capri solves:
- Intended users and operating context:
- Explicit non-goals:
- Supported workflows:
- Out-of-scope workflows:
- Relationship between assistant-facing behavior and background automation:

## 3. Runtime interface

For each entry point, define:

| Entry point | Input schema | Output schema | Authentication context | Side effects |
|---|---|---|---|---|
| Interactive request | TBD | TBD | TBD | TBD |
| Scheduled task | TBD | TBD | TBD | TBD |
| Tool callback | TBD | TBD | TBD | TBD |

- Transport/protocol:
- Schema/versioning policy:
- Correlation and idempotency identifiers:
- Streaming requirements:
- Maximum input/output sizes:

## 4. Session lifecycle

Define states and allowed transitions. Do not assume a lifecycle based on the prototype.

- Session creation:
- Session identity and tenant/user isolation:
- Active/idle/closed/failed states:
- Resume behavior:
- Concurrent request behavior:
- Cancellation semantics:
- Session expiry and cleanup:
- Recovery after process restart:

## 5. Memory and persistence

For each memory class, specify source, owner, read/write authority, retention, and deletion behavior.

| Memory class | Purpose | Read rules | Write rules | Retention | User deletion behavior |
|---|---|---|---|---|---|
| Session state | TBD | TBD | TBD | TBD | TBD |
| User-approved durable memory | TBD | TBD | TBD | TBD | TBD |
| Project/workspace state | TBD | TBD | TBD | TBD | TBD |
| Execution/evaluation metadata | TBD | TBD | TBD | TBD | TBD |

- Source-of-truth hierarchy:
- Conflict resolution:
- Export and portability:
- Backup and restore:
- Data residency and privacy constraints:

## 6. Model and tool adapters

For each model/provider/tool, define:

| Adapter | Allowed operations | Data permitted | Approval required | Timeout/retry | Failure behavior |
|---|---|---|---|---|---|
| Model provider | TBD | TBD | TBD | TBD | TBD |
| Read-only tools | TBD | TBD | TBD | TBD | TBD |
| Write-capable tools | TBD | TBD | TBD | TBD | TBD |

- Tool authorization model:
- User confirmation requirements:
- Least-privilege rules:
- Secret storage and rotation:
- Prompt-injection and untrusted-output handling:
- Audit events:

## 7. Reliability and lifecycle controls

- Timeout budgets by operation:
- Retry policy and idempotency:
- Backoff and circuit-breaking:
- Rate limits and quotas:
- Cancellation and rollback:
- Partial failure behavior:
- Queueing and concurrency limits:
- Graceful shutdown:
- Observability and alert thresholds:

## 8. Security and privacy

- Threat actors and trust boundaries:
- Authentication:
- Authorization:
- Tenant isolation:
- Encryption in transit and at rest:
- Secret management:
- Personal-data classification and minimization:
- Data deletion guarantees:
- Audit-log access and retention:
- Incident response and breach handling:

## 9. Deployment and operations

- Deployment target and supported environments:
- Supported Python/runtime versions:
- Storage and database requirements:
- Network dependencies:
- Configuration contract:
- CI/CD and release process:
- Rollback strategy:
- Backup/restore objectives (RPO/RTO):
- Service ownership and on-call expectations:

## 10. Acceptance criteria

Every acceptance criterion must be testable without protected continuity benchmark material.

| ID | Scenario | Given | When | Then / observable result | Test owner |
|---|---|---|---|---|---|
| NXR-001 | Session creation | TBD | TBD | TBD | TBD |
| NXR-002 | Session resume | TBD | TBD | TBD | TBD |
| NXR-003 | Memory authorization | TBD | TBD | TBD | TBD |
| NXR-004 | Tool permission denial | TBD | TBD | TBD | TBD |
| NXR-005 | Timeout/retry | TBD | TBD | TBD | TBD |
| NXR-006 | Cancellation | TBD | TBD | TBD | TBD |
| NXR-007 | Persistence recovery | TBD | TBD | TBD | TBD |
| NXR-008 | User data deletion | TBD | TBD | TBD | TBD |
| NXR-009 | Auditability | TBD | TBD | TBD | TBD |

## 11. Open decisions and sign-off

| Decision | Options considered | Selected option | Rationale | Owner | Status |
|---|---|---|---|---|---|
| Runtime architecture | TBD | TBD | TBD | TBD | Open |
| Session store | TBD | TBD | TBD | TBD | Open |
| Memory policy | TBD | TBD | TBD | TBD | Open |
| Adapter boundary | TBD | TBD | TBD | TBD | Open |
| Deployment target | TBD | TBD | TBD | TBD | Open |

### Approval checklist

- [ ] All required sections completed or explicitly marked not applicable with rationale.
- [ ] All unresolved decisions have named owners and due dates.
- [ ] Privacy/security requirements reviewed.
- [ ] Acceptance criteria are testable and reproducible.
- [ ] No credentials, private user data, or customer-confidential information is included.
- [ ] Authorized product owner approved this exact version.

**Implementation gate:** no session orchestration, durable memory policy, model/tool adapter, or deployment behavior may be represented as product-correct until this specification is approved. The existing ledger prototype may be reused only within its documented limitations.
