# Capri recovery plan

## Current reconciliation — 2026-11-06

This dated section supersedes older status snapshots below where they conflict. Historical records remain intact for audit purposes.

### Skill registry

The live Notion enabled-skills registry returned **five enabled Capri skills** on 2026-11-06: Identity and Session Continuity; Agency and Self-Direction; Adversarial Research and Verification; Execution Memory and Process Ledger; and Engineering and Security Release Operations. This is a Notion registry observation. It must not be conflated with any separate agent-role architecture or treated as authorization to add more skills. Keep the existing set stable while independent evaluation remains incomplete.

### Evaluation evidence

A fresh metadata-only query of the Capri Evaluation Runs data source returned 39 records across 22 distinct Scenario IDs: 37 Pass, 2 Not Run, 0 Fail, 0 Retest Needed; 37 Self / Self-Scored; 0 Independent and 0 Independently Reviewed; 2 evaluator types untyped. Five-field evidence completeness is 26/39. M4 and X5 remain Not Run. The protected X5 page and criteria were not opened. Self-scored Pass labels are provisional and do not satisfy independent evaluation.

### Repository and release state

- Seven open Draft/unmerged PRs: #1, #4, #5, #6, #10, #12, #14.
- PR #11 is closed as superseded by #12; PR #13 is closed as superseded by #14.
- PR #6's current head is `ca245a18533f7e9084a5bbbf81df595fb73fae28`; exact-head Actions run [42241949677](https://github.com/Hamudifr/Capri/actions/runs/42241949677) passed compileall, Capri Doctor, and 92 tests on each of Python 3.11, 3.12, and 3.13. All three logs were inspected; Doctor 6/6 and operational health 7/7. The health-model contract now rejects blank IDs and unsupported status values; regression tests cover malformed values and unknown-state propagation.
- CI trigger duplication was reduced on PR #1, #6, and #10 heads: commits `fed330e03a3e55ecc1f5307e684fbc842eddea29`, `75ebc6fb44c628620d036f3fdb111ab0a2ea422c`, and `27cc8ab7e25c84381db572285ba1bdd6d6d3a3a5` each now use one `pull_request` matrix for PR-head updates; exact runs `42241438580`, `42241341292`, and `42241452411` passed.
- Release gate remains **NOT MET** pending independent security review, authorized non-X5 specification approval, assembled-stack integration/acceptance, independent non-X5 acceptance, and governance evidence. Do not merge or deploy from CI alone.

## Phase 0 — Preserve boundaries

- [x] Confirm the current five-skill Notion registry; do not add or modify skills without a separate governance decision.
- [x] Establish protected blind-evaluation restrictions.
- [x] Create an isolated recovery branch.
- [ ] Maintain a minimal contamination log without protected content.

## Phase 1 — Establish a reviewable repository

- [x] Add repository purpose, operating model, and evaluation data contract.
- [x] Add deterministic structural tests.
- [x] Add CI for non-protected checks.
- [ ] Obtain human review and merge through a pull request.

## Phase 2 — Reconcile evaluation evidence

- [ ] Obtain a fresh, authorized, metadata-only export of non-protected records.
- [ ] Reconcile run count versus unique scenario count and retest lineage.
- [ ] Validate evidence-stage completeness without opening protected material.
- [ ] Identify eligible records for a genuinely independent reviewer.
- [ ] Record reviewer role and review artifacts; never self-label as independent.

Known historical snapshot (2026-11-05, metadata-only, protected scenario excluded): 36 database records, all marked Pass, Self evaluator, Self-Scored stage; 16 records were marked as retests. This is 36 records, not 36 proven unique scenarios. No independent reviews were recorded. Evidence content could not be safely audited because protected-evaluation indicators appeared in retrieved material; inspection was stopped. The 2026-11-06 snapshot above supersedes these historical counts. Re-query and re-verify before relying on either snapshot.

## Phase 3 — Runtime foundation

- [x] Implement immutable evaluation metadata records.
- [x] Implement fail-closed validation with defensive type checks.
- [x] Implement a single-writer append-only JSONL ledger with SHA-256 hash chaining and integrity verification.
- [x] Validate stored records on read, including schema, evidence-stage consistency, unique IDs, and retest-parent ordering.
- [x] Test missing evidence, evaluator-stage mismatch, invalid field types, timestamp validation, retest lineage, duplicate identifiers, unknown parents, malformed entries, rehashed invalid records, and tamper detection.
- [x] Add a minimal provider-neutral session runtime foundation on the recovery branch.
- [x] Add in-memory session creation, retrieval, and closure.
- [x] Add an injected model-adapter boundary without binding Capri to a provider or credentials.
- [x] Add atomic turn commits, typed failures, bounded input/output/session history, and optimistic concurrency conflict detection.
- [x] Reject commits after a session is closed during adapter execution.
- [x] Add dedicated regression tests for output/history limits, direct commit validation, boolean configuration, and close-during-generation.
- [x] Add tests for session lifecycle, adapter failures, validation, and concurrent turns.
- [x] Enforce session-history limits atomically inside the session store, including direct commits.
- [x] Require injected stores to match the runtime history-limit configuration.
- [x] Pin GitHub Actions dependencies to immutable commit SHAs.
- [x] Add a non-X5 security review with trust boundaries, unresolved risks, and an abuse-case test plan.
- [ ] Obtain an authorized, completed non-protected product specification and ratify proposed defaults.
- [ ] Define durable memory, tool authorization, identity/tenant isolation, and deployment from that specification.
- [ ] Implement concrete model/tool adapters, persistence strategy, and deployment packaging.
- [ ] Add security, privacy, resilience, and integration tests.

The implemented runtime slice is intentionally process-local and memory-only. It is not production-ready and does not include a concrete model provider, tool execution, durable storage, authentication, tenant isolation, or deployment. The ledger remains a separate single-writer metadata component.

## Phase 4 — Independent verification and release

- [ ] Commission an independent evaluator who did not author the implementation or self-score the runs.
- [ ] Review non-protected evidence and defects.
- [ ] Confirm the non-protected release gate.
- [ ] Run the protected blind evaluation only through its authorized designated environment and procedure.
- [ ] Record the outcome exactly as reported by that process; do not infer it.

## Exit criteria

Recovery is complete only when the actual runtime is implemented against an authorized specification, tests pass in CI, evidence is reconciled, independent review is documented, release gates are satisfied, and the protected blind evaluation is completed through its authorized process. Until then, overall status remains **in progress / release gate not met**.
