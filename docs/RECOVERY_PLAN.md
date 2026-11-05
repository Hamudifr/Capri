# Capri recovery plan

This plan is ordered by dependency. Statuses below describe this branch's deliverables, not a claim that the whole Capri system is complete.

## Phase 0 — Preserve boundaries

- [x] Confirm four canonical Capri skills are enabled; do not modify them.
- [x] Establish explicit X5 blind-evaluation restrictions.
- [x] Create an isolated recovery branch.
- [ ] Maintain a minimal contamination log without protected content.

## Phase 1 — Establish a reviewable repository

- [x] Add repository purpose, operating model, and evaluation data contract.
- [x] Add deterministic structural tests.
- [x] Add CI for non-X5 checks.
- [ ] Obtain human review and merge through a pull request.

## Phase 2 — Reconcile non-X5 evaluation evidence

- [ ] Obtain a fresh, authorized, metadata-only export of non-X5 records.
- [ ] Reconcile run count versus unique scenario count and retest lineage.
- [ ] Validate evidence-stage completeness without opening protected material.
- [ ] Identify eligible records for a genuinely independent reviewer.
- [ ] Record reviewer identity/role and review artifacts; never self-label as independent.

Known historical snapshot (2026-11-05, metadata-only, X5 excluded): 36 database records, all marked Pass, Self evaluator, Self-Scored stage; 16 records were marked as retests. This is 36 records, not 36 proven unique scenarios. No independent reviews were recorded. Evidence content could not be safely audited because protected-evaluation indicators appeared in the retrieved material; inspection was stopped. Re-query and re-verify before relying on this snapshot.

## Phase 3 — Implement the actual Capri runtime

- [ ] Recover an authorized, non-protected product/technical specification.
- [ ] Define runtime boundaries, interfaces, state model, and failure behavior.
- [ ] Implement the smallest vertical slice with tests.
- [ ] Add security, privacy, resilience, and regression tests.
- [ ] Document deployment and rollback.

No runtime specification was safely available during this recovery pass. Do not invent product behavior to fill this gap.

## Phase 4 — Independent verification and release

- [ ] Commission an independent evaluator who did not author the implementation or self-score the runs.
- [ ] Review non-X5 evidence and defects.
- [ ] Confirm the non-X5 release gate.
- [ ] Run X5 only after the authorized X5 instructions are provided to the designated blind environment.
- [ ] Record the X5 outcome exactly as reported by that process; do not infer it.

## Exit criteria

Recovery is complete only when implementation exists, tests pass in CI, non-X5 evidence is reconciled, independent review is documented, release gates are satisfied, and X5 has been completed through its authorized blind procedure. Until then, overall status remains **in progress / release gate not met**.
