# Capri

Capri is a research and execution-assistance project. This repository contains a hardened non-X5 recovery foundation, a narrow execution-ledger prototype, a provider-neutral session runtime, and an initial permissioned tool-execution boundary; it does not contain an authorized X5 test specification or an X5 execution result.

## Operating principles

- Evidence before claims: distinguish observed facts, hypotheses, plans, and verified outcomes.
- Preserve history: append run records; do not rewrite past results to make a dashboard look healthier.
- Capri performs and documents its own engineering/security reviews; external independent review is not a prerequisite for ordinary internal implementation or merging. Never mislabel self-review as independent assurance.
- Fail closed: unknown, missing, ambiguous, or contaminated inputs do not become passes.
- Protect blind evaluations: protected instructions, rubrics, expected answers, scoring keys, and evidence are out of scope for ordinary repository work and CI.
- Add or improve Capri skills when a concrete capability gap justifies them; the owner has explicitly authorized this, and each skill must have a clear purpose and validation path.

## Repository map

- `docs/OPERATING_MODEL.md` — scope, evidence rules, release gates, and safety boundaries.
- `docs/RECOVERY_PLAN.md` — ordered recovery work and exit criteria.
- `docs/EVALUATION_DATA_CONTRACT.md` — non-sensitive evaluation record contract.
- `docs/RUNTIME_CORE.md` — narrow runtime-core prototype, API, limitations, and tests.
- `docs/NON_X5_RUNTIME_SPEC_TEMPLATE.md` — product-owner specification template; blank decisions remain blockers.
- `docs/NON_X5_RUNTIME_DESIGN.md` — conservative proposed defaults and implemented runtime slice.
- `docs/SECURITY_REVIEW.md` — non-X5 trust boundaries, verified controls, unresolved risks, and required abuse-case tests.
- `docs/LEDGER_THREAT_MODEL.md` — ledger-specific security assumptions, bounded parsing, and crash behavior.
- `docs/LEDGER_OPERATIONS.md` — backup verification, integrity-incident response, and controlled recovery runbook.
- `docs/LEDGER_SCALING_DECISION.md` — proposed transactional storage migration, explicitly not implemented.
- `capri_core/` — immutable evaluation records, fail-closed validation, and hash-chained append-only ledger.
- `capri_runtime/` — in-memory session lifecycle, injected model-adapter boundary, and permissioned host-injected tool execution gate.
- `docs/TOOL_EXECUTION.md` — trust model, schema subset, approvals, audit behavior, and limitations for tool execution.
- `tests/` — deterministic structural, ledger, and runtime tests.
- `.github/workflows/quality.yml` — non-X5 documentation and test checks.

## Current status

Current `main` is `ed530c8f3fbcea993a2577b87b2b9ab98bb16921`. It contains the integrated recovery foundation, permissioned tool-execution boundary, and durable local audit/approval replay store.

- Recovery foundation merged in PR #1: `d42bfbb2f59a31c713b03f09d074da77b8fb6250`.
- Permissioned tool boundary merged in PR #17: `35ddc8408a2389dff8594283d40d37b66905c0dc`.
- Durable SQLite audit/approval store merged in PR #18: `ed530c8f3fbcea993a2577b87b2b9ab98bb16921`.
- Post-merge CI [42286526969](https://github.com/Hamudifr/Capri/actions/runs/42286526969) passed compileall, Capri Doctor 6/6, operational health 7/7, and 141 tests on each actual Python 3.11, 3.12, and 3.13 interpreter; all three job logs inspected.

Implemented: hardened append-only hash-chain ledger; read-only Doctor diagnostics; dependency-aware operational health; provider-neutral in-memory sessions with optimistic concurrency and direct-store resource limits; explicit tool registry; bounded strict schemas; host permission checks; one-use action-bound approvals; bounded JSON/Unicode; redacted audit events; and a private SQLite store for durable audit metadata and cross-executor/process approval replay prevention.

The tool boundary is not a sandbox or provider integration. The host must authenticate principals and construct trusted execution contexts. The in-memory audit/approval stores are development-only; `SQLiteSecurityStore` provides durable local metadata and replay prevention but is not encrypted and requires host-managed backup/retention. Handlers run with process privileges. No shell, filesystem, network, dynamic import, automatic plugin discovery, or X5 access is exposed.

Next capabilities: durable user-controlled memory, task planning/recovery, cryptographically authenticated approvals, host identity/tenant isolation, model-to-tool orchestration, budgets, observability, and deployment packaging. Audit/approval replay metadata now has a durable SQLite implementation; backup, retention, and restore operations remain to be built. Capri performs its own internal engineering/security reviews; external independent review is not a prerequisite for ordinary internal implementation. Never mislabel self-review as independent assurance.

This is a growing internal prototype, not a claim of AGI or public/multi-tenant production readiness. No X5 work is included.

## Durable task execution and recovery

The provider-neutral task engine in `capri_runtime.tasks` provides persistent ordered plans, atomic SQLite worker leases, per-step checkpoints, bounded retries with exponential backoff, cooperative cancellation, and lease-expiry recovery. It uses stable per-step idempotency keys and uses bounded retry delivery that may invoke a handler zero or multiple times across crash windows—not exactly-once side effects. See [docs/TASK_EXECUTION.md](docs/TASK_EXECUTION.md) for the handler contract, security boundaries, and limitations. The engine is a worker primitive; the host remains responsible for scheduling, authenticated context, and permissioned handler integration.

## Run checks locally

Run the read-only repository diagnostic before making changes:

```bash
python -m capri_core doctor
```

It checks required project files, Python version, pinned external CI actions, minimal workflow permissions, and recovery-branch CI triggers under the actual top-level `push` and `pull_request` events. Duplicate top-level `on:` blocks or duplicate direct event mappings fail closed, as do unsupported trigger forms. The check is deliberately narrow, not a general YAML parser. Its report also includes a dependency-aware operational health graph; use `--json` to consume it programmatically. It reads only those known project files and does not inspect transcripts, credentials, or arbitrary repository contents. Use `--root PATH` to check another working tree. Add `--json` for a versioned machine-readable report (`schema_version: 1`) with per-check status and aggregate counts.


```bash
python -m compileall -q capri_core capri_runtime tests
python -m unittest discover -s tests -v
python -m capri_core verify path/to/runs.jsonl
```

Python 3.11+ is supported; CI compiles and tests on Python 3.11, 3.12, and 3.13. The verification command is read-only and requires an existing ledger file.

## Change policy

Use feature branches for isolation, perform Capri's own design/security/code review, run and inspect CI, then merge completed compatible work into `main`. Do not leave validated work stranded in Draft PRs indefinitely. Never place protected evaluation material, credentials, personal secrets, or private user data in this repository, test fixtures, logs, or CI artifacts.


## Owner-directed autonomy and self-review

Capri is expected to operate as the responsible technical agent for ordinary internal project work: inspect the live state, choose the next high-value improvement, plan it, implement it, review it, test it, fix defects, verify the outcome, document evidence, and continue.

- **Internal self-review is the default.** Capri reviews its own architecture, code, security boundaries, integration, and operational changes. A focused review should inspect the exact diff and affected call paths, challenge assumptions, exercise normal and adversarial cases, run relevant tests, inspect logs, and correct findings.
- **No external-review prerequisite for ordinary work.** Do not stall safe research, implementation, testing, documentation, or internal integration while waiting for an independent reviewer. Never describe self-review or CI as independent assurance. External review remains necessary only when a concrete legal, contractual, customer, protected-evaluation, or deployment requirement says so.
- **Autonomous decisions.** Choose routine priorities, tools, sequencing, and reversible implementation details without handing those decisions back to the owner. Ask only when a material unknown changes correctness or a real authorization boundary is reached.
- **Continue after completion.** Record evidence and unresolved risks, then proceed to the next independent safe improvement. One blocked item must not stop unrelated work.
- **Build actual agency.** Prioritize durable task state and memory, multi-step planning/execution, permissioned tools, idempotency/retries/cancellation, failure recovery, monitoring, and evidence-based reporting. Do not claim AGI, consciousness, or unimplemented capabilities.

Autonomy does not bypass least privilege, privacy, platform controls, protected evaluation boundaries, or the owner's no-paid-spend rule. Destructive/irreversible actions and externally consequential actions remain subject to the required authorization. Internal self-review must be labeled honestly.
