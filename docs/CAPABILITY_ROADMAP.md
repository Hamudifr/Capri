# Capri Capability Roadmap — X6 Foundation to X7 and X8

**Status:** Active engineering direction  
**Last updated:** 2026-11-25  
**Purpose:** Move Capri from a collection of useful runtime components toward a coherent, reliable autonomous operating system for delegated work.

This roadmap defines capability outcomes, not marketing labels. A milestone is complete only when the behavior is implemented, tested, observable, and documented. A larger number does not imply greater intelligence by itself.

## Capability baseline — X6 (working label)

"X6" is a retrospective label for the current integrated foundation, not a previously approved version specification.

Already present in the repository:
- Provider-neutral model/tool orchestration with bounded rounds and transcript budgets.
- Permission-filtered tool discovery and execution through a trusted host boundary.
- Action-bound approvals, redacted audit events, and durable local approval replay protection.
- Durable sessions and tasks with principal ownership, request-scoped host composition, immutable owner records, and principal-specific handler allowlists.
- Persistent task plans, worker leases, checkpoints, explicit pre-side-effect retries, cancellation, and `reconciliation_required` quarantine for uncertain outcomes; expired running work is never blindly replayed.
- Bounded local project memory, a Notion memory adapter, and separate untrusted-memory delivery.
- Optional read-only Notion knowledge-graph retrieval with deterministic bounded lexical ranking, provenance, contradiction handling, and a short process-local cache; retrieved context remains untrusted.
- Optional OpenAI Responses API adapter with offline tests and separate memory/knowledge context inputs.
- Private consistent no-replace backups for the four local SQLite stores; backups remain plaintext and require host-managed protection.

This is a strong component foundation, not yet a complete autonomous agent. The durable goal contract/coordinator, principal-scoped execution budgets, and in-process supervised host lifecycle are now implemented. Remaining gaps include a natural-language planner adapter, real identity-provider integration, complete memory/graph ACL enforcement, an owner-facing reconciliation experience, production metrics/alerts, and deployment-level process supervision.

## X7 — Autonomous Operations

**Outcome:** Capri can accept a delegated outcome, turn it into a bounded plan, execute the plan through authorized capabilities, monitor progress, recover from interruption, and report only verified completion.

### Required capabilities

1. **Goal intake and contract**
   - Normalize a user request into an outcome, constraints, deadline, and definition of done.
   - Preserve explicit user constraints and distinguish hard requirements from preferences.
   - Detect missing information only when it blocks safe or correct execution.

2. **Planning and decomposition**
   - Produce a typed, bounded plan with dependencies, expected outputs, risk class, and verification criteria.
   - Separate research, read-only actions, reversible writes, and consequential actions.
   - Validate every proposed tool against host-provided capabilities; model output never grants permission.
   - Estimate time, tool calls, context, and provider usage before execution.

3. **Execution control**
   - Connect goal plans to the durable task engine. Principal-owned task creation, read/cancel access, handler allowlists, and safe task-level retry/quarantine are implemented.
   - Maintain a single goal record across multiple tasks and sessions; goal-level ownership and coordination remain to be built.
   - Checkpoint after meaningful steps and persist evidence references.
   - Add goal-level pause, resume, cancel, retry, and escalation without duplicating side effects. Task-level cancellation, explicit pre-side-effect retries, and uncertain-outcome quarantine are implemented; there is no owner-facing reconciliation API yet.
   - Require idempotency at side-effect boundaries; never automatically replay an uncertain outcome.

4. **Policy and resource budgets**
   - Enforce per-principal limits for tool calls, runtime, context, and provider usage.
   - Fail closed when a budget cannot be evaluated.
   - Keep paid provider use disabled unless the owner explicitly configures credentials and approves spending.
   - Route actions requiring approval to a host-controlled approval experience.

5. **Supervised host lifecycle**
   - **Implemented in PR #169:** `CapriHostService` provides explicit start/stop, cooperative worker-thread supervision, bounded shutdown waits, redacted health snapshots, and integrity checks for configured durable stores.
   - Keep authentication, secret custody, scheduling, and process-level supervision in the trusted host; an external supervisor remains responsible for process restart and OS-level limits.
   - Background execution remains opt-in and inspectable; constructing a runtime/service starts no thread.

6. **Completion verification**
   - Define an acceptance check for each goal and step.
   - Read back changed resources and verify external outcomes where possible.
   - Produce a concise evidence-backed completion report with failed, partial, and unverified items clearly separated.

### X7 acceptance metrics

- 100% of executed actions pass the host permission boundary.
- 100% of consequential actions have the required valid approval before invocation.
- 100% of task plans satisfy configured bounds before persistence.
- No automatic retry of an uncertain non-idempotent side effect.
- Every completed goal has machine-readable acceptance checks and read-back evidence.
- Budget enforcement tests prove that over-budget work is rejected before provider/tool invocation.
- Crash/restart tests prove that goals resume from durable checkpoints without silently duplicating completed side effects.

## X8 — Adaptive Intelligence

**Outcome:** Capri improves its future decisions and workflows from verified outcomes and user corrections, without turning untrusted content into policy or silently changing its authority.

### Required capabilities

1. **Outcome-based learning**
   - Compare planned outcomes with observed results.
   - Record concise lessons, failure causes, and successful patterns with provenance and confidence.
   - Distinguish user-directed facts, verified observations, and inferred hypotheses.
   - Allow corrections and supersession; never silently rewrite historical evidence.

2. **Context and memory quality**
   - Retrieve memories by relevance, freshness, scope, and confidence.
   - Measure retrieval usefulness and stale/contradictory memory rates.
   - Apply retention, correction, export, and deletion policies through explicit user-controlled paths.
   - Keep retrieved memory and external content untrusted; they cannot grant tools, permissions, or override host policy.

3. **Skill discovery and improvement**
   - Detect repeated workflows and recurring failure patterns.
   - Propose a skill only when it solves a distinct recurring capability gap.
   - Give each skill a clear trigger, inputs, authority boundary, procedure, and validation suite.
   - Test new or changed skills against representative and adversarial cases before enabling them.

4. **Self-evaluation and regression prevention**
   - Maintain task-level evaluations for planning quality, tool selection, execution reliability, verification quality, and user corrections.
   - Compare new strategies against a stable baseline.
   - Use regression tests before promoting a changed workflow.
   - Never use self-scored success as proof of independent assurance.

5. **Strategy adaptation**
   - Choose future methods based on observed success, cost, latency, and risk.
   - Prefer simpler and cheaper strategies when outcomes are equivalent.
   - Keep adaptation bounded, explainable, reversible, and auditable.
   - Do not modify model weights, platform instructions, or security policy.

### X8 acceptance metrics

- Memory retrieval precision and usefulness are measured on a labelled test set.
- User corrections are incorporated with provenance and can be superseded or reversed.
- Every enabled skill has trigger tests, safety-boundary tests, and regression tests.
- Strategy changes are evaluated against a stable baseline before promotion.
- No memory or retrieved document can expand authority or permission.
- Improvements demonstrate measurable gains in task success, verification quality, recovery, or efficiency without worsening safety guardrails.

## Sequenced implementation plan

| Order | Work package | Milestone | Exit evidence |
|---|---|---|---|
| 1 | Principal-scoped durable task ownership and safe task recovery | X7 | **Implemented:** immutable owner rows, scoped idempotency/read/cancel/events, handler allowlists, explicit retries, uncertain-outcome quarantine, backup validation, and adversarial tests |
| 2 | Durable goal record and goal planner protocol | X7 | **Implemented in PR #162:** principal-owned SQLite goal contracts, constraints/deadline/acceptance criteria, versioned lifecycle, data-only planner protocol and allowlist validator; five-version CI passed |
| 3 | Deterministic goal-plan validator and coordinator linking planner, task engine, session, and evidence | X7 | **Implemented in PR #163:** deferred task activation, immutable goal-task links, idempotent crash recovery, cancellation coordination, hashed step evidence, terminal outcome reconciliation, and explicit acceptance verification; five-version CI passed |
| 4 | Execution and provider request budget guard | X7 | **Implemented in PR #164:** persistent per-principal quotas for provider calls/input bytes, tool calls, task steps/input bytes; atomic pre-invocation reservations; budget-wait recovery; fail-closed provider/tool/task enforcement; exact-head and post-merge CI passed on Python 3.11–3.15. Exact provider tokens/cost and synchronous handler preemption remain explicitly out of scope. |
| 5 | Supervised host service and health lifecycle | X7 | **Implemented in PR #169:** explicit start/stop, cooperative worker shutdown, timeout/retry semantics, redacted health snapshots, store integrity checks, and worker failure recovery tests; OS process supervision remains external |
| 6 | Owner-facing goal acceptance and evidence report (X7.7) | X7 | **Implemented in the X7.7 feature slice:** authenticated read-only report projection, task progress, explicit owner-acceptance status, partial/uncertain/missing-task states, bounded evidence references, and raw-payload redaction; exact-head five-version CI is the merge gate |
| 7 | Outcome provenance, correction and supersession integrity | X8 | **In progress:** retain goal/task/memory domain stores as sources of truth; add immutable task/memory event rows, enforce one active memory correction head, reconcile interrupted Notion corrections, and expose a read-only CloudEvents-style projection with bounded provenance metadata. No second global event database. |
| 8 | Memory retrieval evaluation and ranking | X8 | Labelled benchmark and regression threshold |
| 9 | Skill discovery, authoring, and validation pipeline | X8 | Skill trigger/safety/regression test suite |
| 10 | Strategy evaluation and reversible adaptation | X8 | Baseline comparison, rollback, and audit trail |

## Operating rules

- Work in small, integrated increments. Prefer working behavior over accumulating documents or feature labels.
- Continue ordinary internal engineering without waiting for an external reviewer; perform and record Capri's own exact-diff, security, and regression review.
- Do not merge a feature merely because it compiles. Run focused tests, the full suite, supported Python matrix, and inspect CI logs.
- Preserve the user's no-paid-spend constraint. Use fake/offline adapters for development.
- Do not claim autonomous background operation until a supervised host or enabled automation actually runs it.
- Do not claim learning or self-improvement unless a measured, reproducible feedback loop changes future behavior.
- Keep privacy, least privilege, approval, idempotency, and evidence requirements intact.

## Immediate next engineering action

X7.2–X7.7 are merged and validated. X7.5 established an offline baseline; X7.6 added supervised host lifecycle; X7.7 added authenticated, read-only goal reports with owner-acceptance status and sanitized evidence. X8.1 follows the Systems research decision: strengthen existing goal/task/memory event histories with a common provenance envelope and correction-head/reconciliation invariants. Do not add a second global event database without a demonstrated cross-domain atomic ordering/replay need. The current implementation branch is `fix/x8-domain-local-event-integrity-2026-11-25`; exact-head five-version CI is the merge gate. Next after X8.1 is X8.2: labelled memory retrieval evaluation and ranking. Keep the Python baseline and do not port to Rust/C without repeated same-runner measurements plus profiling. No paid provider calls or new dependencies.
