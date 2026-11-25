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
| 7 | Outcome provenance, correction and supersession integrity | X8 | **Implemented in PR #173:** domain-local goal/task/SQLite-memory event histories remain sources of truth; task and memory events reject UPDATE/DELETE; SQLite memory correction enforces active-head and one-successor invariants; Notion correction rejects forks and supports explicit partial-state reconciliation; goal/task/memory adapters expose a read-only CloudEvents 1.0 projection with bounded PROV-style actor/revision/derivation metadata. The unnecessary global journal from PR #172 was removed. |
| 8 | Memory retrieval evaluation and ranking | X8 | **Merged in PR #174:** shared deterministic field-weighted lexical ranking for SQLite and Notion, plus a labelled synthetic hard-negative benchmark (12 records, 3 queries). Measured NDCG@5 1.000, MRR@5 1.000, Recall@5 1.000 versus prior freshness-first NDCG@5 0.570642 and MRR@5 0.333333. Exact-head and post-merge five-version CI passed. This is lexical relevance, not semantic retrieval. |
| 9 | Skill discovery, authoring, and validation pipeline | X8 | **Merged in PR #175:** dependency-free static validator for repository-local Agent Skills, strict frontmatter/name/directory/metadata checks, relative-resource containment, symlink rejection, duplicate discovery warnings, `capri skills validate` CLI, authoring guide, 22 validator tests, and five-version CI gate. Both repository skills validate with zero warnings. Notion and installed-plugin skill registries remain separate systems. |
| 10 | Strategy evaluation and reversible adaptation | X8 | **X8.4 control plane and trusted host composition implemented.** PR #213 delivered the evaluator, principal-scoped strategy registry/approval/rollback and signed execution-evidence journal. PR #230 composed the exact shared TaskEngine/task-store/evidence journal with the signed strategy approval/evidence authorities in `CapriHostRuntime`. Nexus Worker Registry host gateway and capacity reservations landed in PRs #220 and #224; PR #231 made committed-release-to-host-load handoff atomic. Exact-head quality run [45675940962](https://github.com/Hamudifr/Capri/actions/runs/45675940962) passed 955 tests, Capri Doctor 6/6, operational health 7/7, memory retrieval regression and skill validation. PR #235 merged principal/task-bound host reservation, supervisor-authenticated commit and release APIs. Exact-head quality run [45677812733](https://github.com/Hamudifr/Capri/actions/runs/45677812733) passed 962 tests, Doctor 6/6 and operational health 7/7. Implemented in PR #239: a required durable lifecycle AuditSink, structured digest-bound worker events, append-only SQLite audit rows, persistent operation markers, detection of unmatched reservations and explicit restart-reconciliation acknowledgement. Exact-head quality run [45683114481](https://github.com/Hamudifr/Capri/actions/runs/45683114481) passed 973 tests; offline runtime baseline [45683114802](https://github.com/Hamudifr/Capri/actions/runs/45683114802) passed; post-merge quality run [45683455088](https://github.com/Hamudifr/Capri/actions/runs/45683455088) passed. No worker dispatch, process launch, IPC, OS isolation or durable worker registry is implemented. No production MAC key or collector credential is provisioned; active strategy is not yet consumed by task execution.

## Operating rules

- Work in small, integrated increments. Prefer working behavior over accumulating documents or feature labels.
- Continue ordinary internal engineering without waiting for an external reviewer; perform and record Capri's own exact-diff, security, and regression review.
- Do not merge a feature merely because it compiles. Run focused tests, the full suite, supported Python matrix, and inspect CI logs.
- Preserve the user's no-paid-spend constraint. Use fake/offline adapters for development.
- Do not claim autonomous background operation until a supervised host or enabled automation actually runs it.
- Do not claim learning or self-improvement unless a measured, reproducible feedback loop changes future behavior.
- Keep privacy, least privilege, approval, idempotency, and evidence requirements intact.

## Immediate next engineering action

X7.2–X7.7 and X8.1–X8.3 are merged and validated. X8.2's labelled retrieval benchmark achieved NDCG@5/MRR@5/Recall@5 of 1.000/1.000/1.000 against the prior 0.570642/0.333333/1.000 baseline. X8.3 PR #175 added repository-local Agent Skills discovery/validation, the `capri skills validate` CLI, authoring guidance, 22 validator tests, and five-version CI; both current skill packages pass with zero warnings. X8.4 includes the offline evaluator, principal-scoped registry/approval/rollback control plane, signed execution-evidence journal, and trusted host composition (PR #213 and #230). PR #239 has since merged the durable worker lifecycle AuditSink, pending-operation markers and fail-closed restart reconciliation; the older wording below about the audit sink being unimplemented is historical and superseded.

**Current continuation (2026-11-25):**
- Draft PR #241, `feat/nexus-sqlite-host-integration-2026-11-25`, adds the durable SQLite Nexus registry to `CapriHostRuntime`, enforces the exact shared `SQLiteTaskStore` instance, recovers reservations by authenticated `(principal_id, task_id)`, validates registry state during task-store backup/integrity checks, and rejects forged capability/protocol context. Exact head `388a119e3a8962620a653a3cf07863d4546f0615`: Repository quality workflow [45689155774](https://github.com/Hamudifr/Capri/actions/runs/45689155774) passed 992 tests, Doctor 6/6, memory retrieval and skill validation; Offline runtime performance workflow [45689156153](https://github.com/Hamudifr/Capri/actions/runs/45689156153) passed. This is branch validation only; PR remains Draft/unmerged.
- Draft PR #236, `migration/native-sqlite-session-2026-11-25`, adds a native GNU11 SQLite session store with Python/C transcript parity. Exact head `4c973187775a555c0a6757dabebd82b94d1f31a5`: Native C workflow [45688178515](https://github.com/Hamudifr/Capri/actions/runs/45688178515) passed optimized build, native tests and ASan/UBSan; repository quality [45688178650](https://github.com/Hamudifr/Capri/actions/runs/45688178650) passed 978 tests and Doctor 6/6. This is a staged C persistence milestone, not full runtime parity or cutover.
- Both PRs remain Draft. No merge, main-branch migration, production routing, dispatch, process launch, IPC or OS isolation is included. Live repository metadata currently reports public visibility; confirm intended visibility before any future public merge/release.

**Next engineering action:** complete final security review of PR #241, then request/record the owner's merge decision. After that milestone, add trusted host supervisor APIs for descriptor updates, quarantine, quarantine recovery and retirement, with durable lifecycle audit transitions and restart/reconciliation tests. Keep worker dispatch disabled until supervisor identity, policy revalidation, host-observed unreserved load, response authentication, and process-level isolation/supervision are independently implemented and verified. For the C track, keep the native store separate until host credential resolution, encryption/retention policy, protected backups, and broader tool/approval/ledger/memory/orchestration/provider parity are planned. No paid provider calls or new runtime dependencies were added.
