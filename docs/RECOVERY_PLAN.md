# Capri recovery plan

## Current reconciliation — 2026-11-06

This dated section supersedes older status snapshots below where they conflict. Historical records remain intact for audit purposes.

### Skill registry

The live Notion enabled-skills registry returned **five enabled Capri skills** on 2026-11-06: Identity and Session Continuity; Agency and Self-Direction; Adversarial Research and Verification; Execution Memory and Process Ledger; and Engineering and Security Release Operations. This is a Notion registry observation. It must not be conflated with any separate agent-role architecture or treated as authorization to add more skills. Keep the existing set stable while independent evaluation remains incomplete.

### Evaluation evidence

The latest metadata-only query of the Capri Evaluation Runs data source returned 39 records across 22 distinct Scenario IDs: 37 Pass, 2 Not Run, 0 Fail, 0 Retest Needed; 37 Self / Self-Scored; 0 Independent and 0 Independently Reviewed; 2 evaluator types untyped. Five-field evidence completeness is 26/39. M4 and X5 remain Not Run. The protected X5 page and criteria were not opened. Self-scored Pass labels are provisional and do not satisfy independent evaluation.

### Repository and release state

- **Eight open Draft/unmerged PRs:** #1, #4, #5, #6, #10, #12, #14, #15.
- PR #11 is closed as superseded by #12; PR #13 is closed as superseded by #14.
- PR #6 current head: `803be03306ad44de7d24cbd59de8a89ca8e0f15a`; exact-head run [42242311834](https://github.com/Hamudifr/Capri/actions/runs/42242311834) passed compileall, Capri Doctor 6/6, operational health 7/7, and 92 tests on each actual Python 3.11/3.12/3.13 job (276 executions). All three logs inspected.
- Ledger stack #4 → #10 → #14 → #15 is now ancestry-reconciled:
  - PR #10 head `b97aff61c79dbbf53ab2f65ba499290281c30919`; run [42270848931](https://github.com/Hamudifr/Capri/actions/runs/42270848931) passed 75 tests per actual Python version.
  - PR #14 head `35fcc988d9a5babeae2636d1b198c280200194be`; 10 commits ahead / 0 behind its PR #10 base; run [42271093562](https://github.com/Hamudifr/Capri/actions/runs/42271093562) passed 77 tests per actual Python version.
  - PR #15 head `5265ce5be3c0ca2d6ff8c5ee78441b58aaa5fb0a`; 4 commits ahead / 0 behind its PR #14 base; only `tests/test_runtime_core.py` changes in its PR diff; run [42271543329](https://github.com/Hamudifr/Capri/actions/runs/42271543329) passed 80 tests per actual Python version.
  - All three ledger runs passed compileall; all nine logs were inspected and confirmed the actual interpreter versions. The workflow explicitly sets `python-version: ${{ matrix.python-version }}`.
- The earlier PR #10 run [42241452411](https://github.com/Hamudifr/Capri/actions/runs/42241452411) is superseded for multi-interpreter claims because its setup-python step omitted the matrix input. The omission has been corrected and the current heads revalidated.
- PR #15 covers hard-link aliases after partial-write, flush, file-fsync, and first-create directory-fsync failures; blocked alias operations preserve bytes and leave an unrelated ledger usable.
- The independent ledger security-review packet is prepared in Notion: [review handoff](https://app.notion.com/p/410ac6905d2681ef8551f668cd52e252?pvs=204). It is not an independent review. PR #14 and #15 have zero submitted reviews.
- `main` remains unchanged at `228669ed8b0c02db669cc082ac256e7491a26201`. All PRs remain Draft/unmerged.
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


## Exact-head refresh — 2026-11-06 19:42 UTC

This section supersedes the PR #6 head and workflow evidence stated in the earlier current-reconciliation block above. The earlier `803be03306ad44de7d24cbd59de8a89ca8e0f15a` reference is historical, not current.

- PR #6 latest head: `c78a12621240d6bc1a3a5bb312fb079e7b12c43e`; head branch `feature/capri-health-model`, based on `feature/capri-doctor` at `b3845e9cddede6c8cccce446ed21e9be5d5d987e`; direct GitHub PR state is open, Draft, mergeable, clean.
- Exact-head Actions run [42272079825](https://github.com/Hamudifr/Capri/actions/runs/42272079825) completed successfully. All three actual Python 3.11, 3.12, and 3.13 jobs passed compileall, Capri Doctor 6/6, operational health 7/7, and 92 unittest cases each (276 executions). All three job logs were inspected.
- `docs/OPERATING_MODEL.md` at this exact PR #6 head includes section 7, **Autonomous ownership — Rule #1**, with the inspect → prioritize → implement → test → read-back verify → ledger → continue loop and explicit authority boundaries.
- The quality workflow at this head explicitly installs `${{ matrix.python-version }}`, uses pinned action SHAs, and declares workflow-level `contents: read`. Its PR branch filter covers `main`, `recovery/non-x5-foundation`, and `feature/capri-doctor`; the ledger stack uses the PR #14 base workflow for its own stacked PR triggers.
- Current open Draft PR inventory remains #1, #4, #5, #6, #10, #12, #14, and #15. PR #11 and #13 are superseded/closed. Ledger heads and CI evidence are listed in the current reconciliation block above and remain separately verified.

This refresh is documentation and evidence reconciliation only. It does not convert internal checks into independent review, approve the non-X5 product specification, satisfy independent evaluation, or authorize a merge/release. All PRs remain Draft/unmerged and the release gate remains NOT MET.


## PR #6 base-stack reconciliation — 2026-11-06 20:05 UTC

The current PR #6 branch has been reconciled with the latest PR #5 / recovery base. This section supersedes the earlier PR #6 head reference `7db0e784a78191fc502f443ad5d38460e99d25e0` above.

- Current PR #6 head before this documentation refresh: `f2676812d8530391069b9061c3748c92aca579e2`.
- Current base PR #5 head: `1b7ac13c9fe2de10d24703008084144726886ac7`.
- The PR #6 tree now includes the reconciled PR #5 head as an ancestor (compare: 46 ahead / 0 behind). The current non-X5 design document was synchronized into the PR #6 tree; its recovery plan, operating model, health implementation, and tests are preserved.
- Exact-head run [42274055988](https://github.com/Hamudifr/Capri/actions/runs/42274055988) passed compileall, Capri Doctor 6/6, operational health 7/7, and 92 tests on actual Python 3.11, 3.12, and 3.13 (276 executions). All three job logs inspected.
- The current PR #6 head remains Draft/open/unmerged. No merge, deployment, or release is authorized by this reconciliation.

The release gate remains NOT MET pending independent review, explicit non-X5 specification approval, assembled-stack acceptance, independent non-X5 evaluation, and governance evidence.
