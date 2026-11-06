# Capri core and runtime prototype

This document describes the implemented non-X5 foundation in `capri_core` and `capri_runtime`. It is a narrow, dependency-free Python library prototype, not a complete Capri agent or a recovered historical product specification.

## Components

### `capri_core`: records and execution ledger

- `EvaluationRecord`: immutable typed metadata with stable run/scenario identifiers, controlled status/evaluator/evidence-stage enums, timestamp, evidence reference, and optional retest parent.
- `validate_record`: fail-closed validation, including defensive type checks, controlled dimensions, timezone-aware ISO 8601 timestamps, evidence-stage consistency, and rejection of lone Unicode surrogates.
- `HashChainLedger`: append-only JSONL storage. Each entry hashes the canonical record plus the previous hash. Reads and appends validate record structure, unique run IDs, and retest-parent ordering. Malformed entries, duplicate JSON keys, non-standard numeric constants, broken links, invalid records, oversized entries, unterminated tails, symlink paths, and non-regular files are rejected.

Ledger security and operational limitations are documented in `docs/LEDGER_THREAT_MODEL.md` and `docs/LEDGER_OPERATIONS.md`. In particular, the ledger is plaintext, has no authenticity or application authorization, and supports one writer process per file. Platform-specific path-race limitations and the process-local uncertain-write latch are documented there.

### `capri_runtime`: in-memory session lifecycle

The runtime provides:

- `SessionStore`: thread-safe, process-local storage for immutable session snapshots.
- `Runtime`: synchronous orchestration around a host-injected `ModelAdapter`.
- `ModelAdapter`: protocol with `complete(session_id, user_text, history) -> str`; the host owns provider SDKs and credentials.
- `Session` and `Message`: immutable dataclasses representing lifecycle state and transcript messages.
- Typed failures: `ValidationError`, `SessionNotFoundError`, `SessionClosedError`, `SessionConflictError`, `SessionLimitError`, and `RuntimeExecutionError`, all derived from `RuntimeErrorBase`.

The runtime commits a user/assistant pair only after a successful adapter response. It uses optimistic version checks so a concurrent turn or a close operation prevents a stale response from being committed. The store enforces its history limit again under the commit lock.

### Runtime defaults

| Setting | Default | Behavior |
|---|---:|---|
| `max_input_chars` | 16,000 | Reject larger user input before adapter invocation |
| `max_output_chars` | 64,000 | Reject larger adapter output before transcript commit |
| `max_session_messages` | 200 | Reject a turn that would exceed the limit; no automatic truncation |

The store independently enforces input/output character limits at the `commit_turn` boundary and rechecks the history limit under its commit lock. This matters because callers can access `SessionStore.commit_turn` directly; runtime-only checks are not a storage boundary. The history limit must allow at least one complete turn (two messages). Boolean, non-integer, or non-positive resource limits are rejected. An injected `SessionStore` must have the same input, output, and history limits configured on the `Runtime`. Limits count Python string characters, not UTF-8 bytes or provider tokens.

The store still has no aggregate session-count or total-memory quota. Session creation is therefore unbounded, and closed sessions remain resident in memory. This is an explicit prototype limitation: session expiry, deletion, cleanup, and retention semantics remain unresolved in the non-X5 specification and are not inferred or implemented here.

## Minimal runtime use

```python
from capri_runtime import Runtime, SessionStore

class EchoAdapter:
    def complete(self, session_id, user_text, history):
        return f"You said: {user_text}"

store = SessionStore(max_session_messages=200)
runtime = Runtime(
    adapter=EchoAdapter(),
    store=store,
    max_input_chars=16_000,
    max_output_chars=64_000,
    max_session_messages=200,
)

session = runtime.create_session()
updated = runtime.respond(session.session_id, "Hello, Capri")
print(updated.version, updated.messages[-1].content)
runtime.close_session(session.session_id)
```

The adapter receives an immutable snapshot of prior messages. It must return non-empty text. Adapter exception details are suppressed behind `RuntimeExecutionError`; the runtime does not log transcripts or provider credentials.

## Minimal ledger use

```python
from capri_core import (
    EvaluationRecord, EvidenceStage, EvaluatorType,
    HashChainLedger, Status,
)

ledger = HashChainLedger("data/non-x5-runs.jsonl")
record = EvaluationRecord(
    run_id="run-001",
    scenario_id="scenario-alpha",
    dimension="Agency",
    status=Status.PASS,
    evaluator_type=EvaluatorType.SELF,
    evidence_stage=EvidenceStage.SELF_SCORED,
    evidence_ref="evidence://your-authorized-reference",
    run_at="2026-11-05T08:00:00Z",
)
ledger.append(record)
print(ledger.verify())
```

## Security and operational boundaries

The session runtime is a library boundary, not an authentication or tenant-isolation boundary. A session UUID is an identifier, never an authorization token. The host application must authenticate callers, authorize access to each session, isolate tenants, protect adapter credentials, and control logging.

The runtime currently has no concrete model provider, network transport, tool execution, retrieval, durable transcript storage, cross-process session sharing, session expiry, deletion/retention policy, provider-aware token or spend budgets, rate limiting, cancellation contract, or deployment packaging. Add these capabilities incrementally with explicit trust boundaries, least-privilege tool authorization, bounded resource use, privacy/retention controls, adversarial tests, and rollback behavior. Do not treat an unresolved proposal as an approved product requirement.

The ledger hash chain is tamper-evident, not a digital signature or proof of authorship. It is plaintext, has no application access control, and does not provide cross-process locking or automatic repair. Use one writer process per file. Preserve corrupt originals and recover only from a verified backup through an operator-approved procedure.

Do not put protected evaluation instructions, rubrics, expected answers, scoring keys, credentials, secrets, or personal data in the repository, test fixtures, ledger, or CI artifacts. This prototype does not implement protected evaluation behavior.

## Validation

Run:

```bash
python -m compileall -q capri_core capri_runtime tests
python -m unittest discover -s tests -v
```

CI runs compilation and the regression suite on Python 3.11, 3.12, and 3.13. Exact commit-specific test counts and outcomes belong to the associated GitHub Actions run, not a hard-coded documentation claim.

## Remaining gates

- The non-X5 runtime design and specification template contain proposed defaults; unresolved owner decisions remain blockers, not implied authorization.
- Capri's internal design, code, and security self-review is the default review path; external independent review is not a prerequisite for ordinary internal implementation or merging. Any specific contractual, regulatory, or protected-evaluation requirement for independent assessment remains narrowly scoped and must not be misrepresented as self-review.
- Authentication, authorization, tenant isolation, durable memory, retention/deletion, tool execution, provider integration, operational budgets, and production deployment require separate design and review.
- The six-value non-protected dimension vocabulary is intentionally controlled and must be versioned before changing.
- This prototype is not approved for public or multi-tenant production deployment.
