# Capri recovery plan

This plan is ordered by dependency. Statuses describe verified deliverables, not a claim that the whole Capri system is complete.

## Phase 0 — Preserve boundaries

- [x] Confirm four canonical Capri skills are enabled; do not modify them.
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

Known historical snapshot (2026-11-05, metadata-only, protected scenario excluded): 36 database records, all marked Pass, Self evaluator, Self-Scored stage; 16 records were marked as retests. This is 36 records, not 36 proven unique scenarios. No independent reviews were recorded. Evidence content could not be safely audited because protected-evaluation indicators appeared in retrieved material; inspection was stopped. Re-query and re-verify before relying on this snapshot.

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
