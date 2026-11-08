# Capri Capability Roadmap — X6 Foundation to X7 and X8

**Status:** Active engineering direction  
**Last updated:** 2026-11-07  
**Purpose:** Move Capri from a collection of useful runtime components toward a coherent, reliable autonomous operating system for delegated work.

This roadmap defines capability outcomes, not marketing labels. A milestone is complete only when the behavior is implemented, tested, observable, and documented. A larger number does not imply greater intelligence by itself.

## Capability baseline — X6 (working label)

"X6" is a retrospective label for the current integrated foundation, not a previously approved version specification.

Already present in the repository:
- Provider-neutral model/tool orchestration with bounded rounds and transcript budgets.
- Permission-filtered tool discovery and execution through a trusted host boundary.
- Action-bound approvals, redacted audit events, and durable local approval replay protection.
- Durable sessions with principal ownership and request-scoped host composition.
- Persistent task plans, worker leases, checkpoints, bounded retries, cancellation, and lease recovery.
- Bounded local project memory, a Notion memory adapter, and separate untrusted-memory delivery.
- Optional OpenAI Responses API adapter with offline tests.
- Private consistent backups for the four local SQLite stores.

This is a strong component foundation. It is not yet a complete autonomous agent: natural-language goal planning, end-to-end goal ownership, a supervised host service, real identity-provider integration, complete memory ACL enforcement, hard per-principal budgets, and production observability remain incomplete.

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
   - Connect goal plans to the durable task engine.
   - Maintain a single goal record across multiple tasks and sessions.
   - Checkpoint after meaningful steps and persist evidence references.
   - Support pause, resume, cancel, retry, and escalation without duplicating side effects.
   - Require idempotency at side-effect boundaries; treat uncertain outcomes as uncertain.

4. **Policy and resource budgets**
   - Enforce per-principal limits for tool calls, runtime, context, and provider usage.
   - Fail closed when a budget cannot be evaluated.
   - Keep paid provider use disabled unless the owner explicitly configures credentials and approves spending.
   - Route actions requiring approval to a host-controlled approval experience.

5. **Supervised host lifecycle**
   - Provide a host service entry point with graceful startup/shutdown, health/readiness probes, and worker supervision.
   - Keep authentication, secret custody, scheduling, and process supervision in the trusted host.
   - Make background execution explicit and inspectable; never imply that Capri works between sessions without a running host or automation.

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
| 1 | Goal/task data model and principal-scoped task ownership | X7 | Migration tests, ownership isolation tests, bounded schema |
| 2 | Goal planner protocol and deterministic plan validator | X7 | Adversarial planner-output tests; no permission escalation |
| 3 | Goal coordinator linking planner, task engine, session, and evidence | X7 | End-to-end fake-adapter tests across restart/recovery |
| 4 | Execution budget and provider spend guard | X7 | Over-budget rejection before model/tool invocation |
| 5 | Supervised host service and health lifecycle | X7 | Startup/shutdown, health, worker recovery tests |
| 6 | Goal acceptance and evidence report | X7 | Read-back verification and partial/uncertain outcome tests |
| 7 | Outcome journal and correction/supersession workflow | X8 | Provenance, correction, retention, and conflict tests |
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

Start with **X7.1: principal-scoped durable goal/task ownership**. The existing task store persists plans and leases but does not yet provide the same principal-bound ownership model already implemented for sessions. Close that gap before allowing model-generated plans to enter durable execution.
