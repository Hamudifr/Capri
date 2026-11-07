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
- `docs/CAPRI_AUTONOMY_AND_CONTINUITY.md` — canonical Capri identity, owner-granted autonomy, execution, layered memory, safety boundaries, and cross-session handoff doctrine.
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
- `capri_runtime/` — provider-neutral sessions, permissioned tool execution and model-call bridge, durable task execution, and bounded SQLite/Notion memory.
- `pyproject.toml` — minimal Python 3.11+ package metadata; no runtime dependencies are declared.
- `docs/TOOL_EXECUTION.md` — trust model, schema subset, approvals, audit behavior, and limitations for tool execution.
- `docs/OPENAI_RESPONSES_ADAPTER.md` — optional concrete OpenAI Responses API adapter, safe configuration, cost boundary, and offline validation.
- `docs/MEMORY_STORE.md` — durable memory contract, trust rules, privacy constraints, and limitations.
- `docs/NOTION_MEMORY_ADAPTER.md` — Notion REST setup, host transport contract, mapping, correction recovery, optional live smoke test, and limitations.
- `tests/` — deterministic structural, ledger, and runtime tests.
- `.github/workflows/quality.yml` — non-X5 documentation and test checks.

## Current status

**Verified checkpoint — 2026-11-07 (after PR #113 merge)**

- Current `main`: `2e5749c8a2cd3110a7ef9a909ba87866542ea5f4` (documentation refresh after PR #113).
- Latest verified exact-head CI: PR #113 run [42379590963](https://github.com/Hamudifr/Capri/actions/runs/42379590963) passed compilation, Capri Doctor 6/6, operational health 7/7, and **390 tests** on Python 3.11, 3.12, and 3.13. All three job logs were inspected. This run tested the PR head before merge; post-merge push CI is not verified here. The optional live Notion REST smoke test was skipped.
- The repository contains the integrated non-X5 recovery foundation, append-only hash-chain ledger, provider-neutral session runtime, permissioned tool-execution boundary, durable SQLite task engine and worker, durable audit/approval storage, and bounded local project memory.
- Memory includes the SQLite provider, Notion memory adapter, standard-library Notion REST transport, explicit read-only data-source schema preflight, and `create_notion_memory_adapter_from_environment()`. `build_untrusted_memory_context()` prepares bounded eligible memory for separate model-adapter delivery.
- The connected Notion data-source metadata was inspected read-only: required logical properties and supported option labels are present. The connector normalizes text fields as `text`; this is **not** an authenticated raw REST schema preflight.
- The optional live Notion REST smoke test remains skipped. Authenticated REST create/read/correct/search/archive/trash behavior is not yet verified, and no always-on Capri process is connected to Notion.
- `OpenAIResponsesAdapter` now implements the provider-neutral memory-aware tool-adapter protocol using the standard library and the Responses API. Offline fake-response tests cover request/response parsing and memory separation. No live API call, paid usage, running host process, or end-to-end prompt-injection resistance is claimed.
- This remains an internal engineering prototype, not a claim of AGI, consciousness, or public/multi-tenant production readiness. No X5 work is included.

### Recent verified integration milestones

- [PR #101](https://github.com/Hamudifr/Capri/pull/101) — require non-null Source URLs for direct Notion REST writes.
- [PR #102](https://github.com/Hamudifr/Capri/pull/102) — preserve numeric Retry-After on normal HTTP 429 responses without automatic retries.
- [PR #103](https://github.com/Hamudifr/Capri/pull/103) — reject credential-bearing and malformed Source URLs at both adapter boundaries.
- [PR #104](https://github.com/Hamudifr/Capri/pull/104) — consolidate owner-directed autonomy, self-review, safety, and continuity doctrine.
- [PR #105](https://github.com/Hamudifr/Capri/pull/105) — detect case-variant duplicate Notion page UUIDs.
- [PR #109](https://github.com/Hamudifr/Capri/pull/109) — enforce exact HTTPS Notion API final origin, including port and userinfo checks.
- [PR #68](https://github.com/Hamudifr/Capri/pull/68) — repeated Notion pagination cursor/page detection.
- [PR #69](https://github.com/Hamudifr/Capri/pull/69) — strict Notion page-property type validation.
- [PR #70](https://github.com/Hamudifr/Capri/pull/70) — freshness ranking for equal-relevance Notion memory results.
- [PR #71](https://github.com/Hamudifr/Capri/pull/71) — explicit Tags requirement at the adapter boundary.
- [PR #74](https://github.com/Hamudifr/Capri/pull/74) — read-only Notion data-source schema preflight.
- [PR #75](https://github.com/Hamudifr/Capri/pull/75) — preflight wired into the live smoke test and setup guidance.
- [PR #76](https://github.com/Hamudifr/Capri/pull/76) — bounded untrusted memory context builder.
- [PR #77](https://github.com/Hamudifr/Capri/pull/77) — exact-type enforcement at the orchestration memory boundary.
- [PR #78](https://github.com/Hamudifr/Capri/pull/78) — require all supported Notion Tags options.
- [PR #79](https://github.com/Hamudifr/Capri/pull/79) — explicit environment factory that preflights before returning a Notion adapter.
- [PR #113](https://github.com/Hamudifr/Capri/pull/113) — enforce required expiry timestamps for `expire_30d` / `expire_90d` records at the immutable untrusted-memory context boundary; exact-head CI passed 390 tests across Python 3.11/3.12/3.13.

### Earlier foundation milestones

- Recovery foundation merged in PR #1: `d42bfbb2f59a31c713b03f09d074da77b8fb6250`.
- Permissioned tool boundary merged in PR #17: `35ddc8408a2389dff8594283d40d37b66905c0dc`.
- Durable SQLite audit/approval store merged in PR #18: `ed530c8f3fbcea993a2577b87b2b9ab98bb16921`.
- Durable project memory core merged in PR #24: `6c01190033c7ade9bb40414a0d86f5444fca0b46`.

### Remaining implementation gates

- Authenticated live Notion REST verification and a successful create/read/correct/search/archive/trash smoke run.
- A real host process that constructs and uses the Notion adapter, owns token rotation, and provides scheduling/process supervision.
- Live provider verification for the optional OpenAI adapter (requires a deliberately provisioned API key and acceptance of separate API charges); no API key or paid request is assumed.
- Host identity/tenant isolation, provider-aware budgets, observability, deployment packaging, and operational backup/restore/retention.
- External services and paid infrastructure are not assumed or provisioned.

## Model-to-tool orchestration\n\nThe provider-neutral `ToolExecutionBridge` validates bounded structured call batches and routes requests through the trusted `ToolExecutor`. It enforces both message-count and aggregate UTF-8 transcript budgets, reserving result capacity before executing side effects. The `ToolOrchestrator` adds a host-injected structured model adapter and bounded multi-round loop. It exposes only tools permitted by the host context, never derives authority from model output, preserves one-use approval requirements, and marks audit failures as uncertain rather than retrying. It remains provider-neutral: the host supplies provider integration, identity, and approval UX; `SessionTurnCoordinator` can provide same-process transcript persistence and concurrency control, while multi-process locking remains a host responsibility. See [docs/TOOL_EXECUTION.md](docs/TOOL_EXECUTION.md).\n\n## Durable task execution and recovery

The provider-neutral task engine in `capri_runtime.tasks` provides persistent ordered plans, atomic SQLite worker leases, per-step checkpoints, bounded retries with exponential backoff, cooperative cancellation, and lease-expiry recovery. It uses stable per-step idempotency keys and uses bounded retry delivery that may invoke a handler zero or multiple times across crash windows—not exactly-once side effects. See [docs/TASK_EXECUTION.md](docs/TASK_EXECUTION.md) for the handler contract, security boundaries, and limitations. The engine includes an explicit host-started TaskWorker polling loop with graceful stop-event handling and concurrent lease heartbeats; the host remains responsible for process supervision, scheduling policy, authenticated context, and permissioned handler integration. Shutdown is cooperative between tasks; an active handler is not forcibly interrupted.

## Install locally

The repository is installable as a Python package with no declared runtime dependencies:

```bash
python -m pip install .
```

The package includes `capri_core` and `capri_runtime`; build tooling is isolated to the package build. No provider SDK, database server, or paid service is required for the local library.

## Run checks locally

Run the read-only repository diagnostic before making changes:

```bash
capri doctor
```

If you are running directly from a source checkout without installing the package, use `python -m capri_core doctor` instead.

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
\n\n## Durable conversation sessions\n\n`SQLiteSessionStore` provides private SQLite persistence for conversation transcripts and optimistic version checks across process restarts. The database must live in an existing private directory; contents are plaintext, so hosts must protect backups and device access.\n

The session stores expose `commit_turn_messages` for atomically persisting a complete model/tool transcript (user message, assistant tool-call messages, tool results, and final assistant response) as one versioned turn.


`SessionTurnCoordinator` serializes orchestration and transcript commit under a bounded per-session lock. With `SQLiteSessionStore`, it also acquires and renews a durable cross-process lease and fences the transcript commit by owner token; the in-memory store provides process-local locking only. It checks message-count, assistant-output, tool-result, and user-input limits before side effects. Lease expiry cannot forcibly stop a paused handler, so external side effects still require idempotency and handler-level authorization.


Session stores apply a separate `max_tool_chars` limit to persisted tool-result messages (default 131,072 characters), distinct from assistant-output limits.

