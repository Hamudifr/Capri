# Capri recovery plan

## Current reconciliation — 2026-11-06 19:35 UTC

This block is the current source of truth for implementation and delivery. Older snapshots below are retained as history and must not be read as current state.

### Owner directive and operating policy

The owner delegates routine engineering direction to Capri: choose priorities, tools, architecture, sequencing, implementation, testing, integration, and documentation without asking for routine decisions. Capri performs its own design, security, code, integration, and operational reviews; fixes findings; runs reproducible checks; inspects logs; and records evidence. External independent review is not a prerequisite for ordinary implementation, integration, or merging completed work. Internal work must be labeled honestly as Capri self-review, never independent assurance.

`main` is the delivery branch, not a permanent holding area. Use feature branches for isolation, validate changes and dependency ancestry, preserve rollback, then merge completed work into `main`. Do not leave finished work in Draft PRs indefinitely. No paid spend or subscriptions, credential/private-data exposure, security-control bypass, or destructive/external action outside the user's grant. Preserve the protected X5 boundary and its authorized process.

### Skill registry

The live Notion enabled-skills registry returned five enabled Capri skills on 2026-11-06. The owner has now explicitly authorized Capri to add or improve skills when a concrete capability gap justifies them. Do not add skills cosmetically; each new skill must have a clear purpose, scope, validation method, and safe operating boundaries. The current five-skill count is a historical registry observation, not a prohibition on future improvements.

### Evaluation evidence

The latest metadata-only Notion query returned 39 records across 22 distinct Scenario IDs: 37 Pass, 2 Not Run, 0 Fail, 0 Retest Needed; 37 Self / Self-Scored; 0 Independent and 0 Independently Reviewed; 2 evaluator types untyped. Five-field evidence completeness is 26/39. M4 and X5 remain Not Run. The protected X5 page and criteria were not opened. Self-scored Pass labels remain provisional; this evaluation-data limitation does not block ordinary engineering delivery.

### Integrated repository state

- Current recovery branch head: `602ba5d370982495486092019197f3577974c355`.
- The assembled branch contains the original recovery foundation plus the integrated Doctor/operational-health stack, private ledger permissions, path/symlink protections, crash-durability handling, hard-link/inode uncertainty latching, and store-level input/output/history limits.
- The Doctor/health stack (#5/#6) was merged through PR #6. PR #5 was closed as superseded.
- Ledger permissions (#4) were merged. The ledger path/durability changes from #10, inode identity guard from #14, and additional failure-stage regression tests from #15 were integrated into the same recovery branch; those PRs were closed as superseded after integration.
- Runtime store-level message bounds from #12 were integrated; #12 was closed as superseded.
- Current integrated CI: push run [42280421240](https://github.com/Hamudifr/Capri/actions/runs/42280421240) and PR run [42280430210](https://github.com/Hamudifr/Capri/actions/runs/42280430210). Both passed compileall, Capri Doctor 6/6, operational health 7/7, and 114 tests on each actual Python 3.11, 3.12, and 3.13 interpreter. All six job logs were inspected.
- PR #1 is the integration PR from recovery to `main`; it is currently open and Draft, with clean mergeability and the same 114-test exact-head CI. It is the next delivery action.
- `main` remains at `228669ed8b0c02db669cc082ac256e7491a26201` until the integration PR is merged. It is currently unprotected. GitHub's rulesets endpoint returned HTTP 403 because rulesets require a paid plan or a public repository; do not upgrade or publish merely to obtain them.

### Current implementation limits and next priorities

Implemented: typed evaluation metadata, fail-closed validation, hash-chained append-only ledger, hardened filesystem access and crash handling, read-only Doctor diagnostics, dependency-aware operational health, and a provider-neutral in-memory session runtime with direct-store resource bounds.

Not implemented: concrete model/provider adapter, permissioned tool execution, durable memory/transcript persistence, authenticated identity and tenant isolation, task planning/queueing, long-running task recovery, provider-aware budgets/rate limits, comprehensive observability, and deployment packaging.

Next engineering priorities, in order: (1) permissioned tool registry/execution with strict schemas, least privilege, per-action authorization, bounded recursion/cost, audit records, and untrusted-content isolation; (2) durable, user-controllable memory with retention/export/deletion semantics; (3) task planning, execution state, retries, idempotency, and recovery; (4) end-to-end and adversarial integration tests; (5) observability and deployment packaging. Build these as small independently tested capabilities. Do not claim full autonomy or AGI before the capabilities exist and are verified.

### Delivery status

The integrated recovery branch is a tested internal prototype, not a public or multi-tenant production deployment. Capri's internal self-review is the default engineering review. Before any public deployment, separately verify identity/authorization, tenant isolation, secrets handling, retention/deletion, provider budgets, monitoring, backups, rollback, and data exposure. No X5 access or evaluation is authorized by ordinary engineering work.

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

## Phase 4 — Internal verification and controlled release

- [x] Perform Capri's own design, code, security, integration, and operational self-review for the current integrated foundation.
- [x] Run the assembled repository suite on Python 3.11, 3.12, and 3.13; inspect every job log and record the exact commit/run evidence.
- [ ] Implement and test permissioned tool execution, durable memory, identity/tenant isolation, task recovery, budgets, and observability.
- [ ] Complete adversarial and end-to-end tests for the implemented agent capabilities.
- [ ] Verify backups, recovery, rollback, deployment configuration, and data-retention/deletion behavior before public or multi-tenant deployment.
- [ ] Run the protected blind evaluation only through its authorized designated environment and procedure.
- [ ] Record the outcome exactly as reported by that process; do not infer it.

External independent review is not a prerequisite for routine internal implementation or merging. If a specific contract, regulation, customer commitment, or protected evaluation explicitly requires an independent evaluator, record that narrow requirement separately; never label Capri's self-review as independent.

## Exit criteria

Internal engineering recovery is complete when the current code and docs are integrated into main, reproducible tests pass, critical risks are documented, and the implemented capabilities meet their stated boundaries. Production deployment is a separate gate requiring identity, authorization, privacy/retention, budgets, monitoring, backup, rollback, and adversarial validation. The protected blind evaluation remains separate and may only be run through its authorized process.


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


## Current ledger stack heads — 2026-11-06 20:24 UTC

This section supersedes the older #10/#14/#15 head references in the earlier reconciliation snapshots above.

- PR #4: `9bb4c021ccf7db24de6d4423816619a79ab6a459`, based on recovery foundation `fed330e03a3e55ecc1f5307e684fbc842eddea29`; run [42273444013](https://github.com/Hamudifr/Capri/actions/runs/42273444013) passed 63 tests per Python version.
- PR #10: `3697f6440d0b56fc83c17bbb53234acaeb613a64`, based on current PR #4 head; run [42274529813](https://github.com/Hamudifr/Capri/actions/runs/42274529813) passed compileall and 75 tests per actual Python 3.11/3.12/3.13.
- PR #14: `da25bff24a9c4fdcad997591caabfa193df35f21`, based on current PR #10 head; run [42274695527](https://github.com/Hamudifr/Capri/actions/runs/42274695527) passed compileall and 77 tests per actual Python version.
- PR #15: `da2c3ec28412937c1993dcbe18132d73edeaa593`, based on current PR #14 head; 7 commits ahead / 0 behind; its PR diff remains only `tests/test_runtime_core.py`. Current tree `5322c19330c13181254f17927d10564d26befb5e` is identical to the tree tested by run [42274759020](https://github.com/Hamudifr/Capri/actions/runs/42274759020), which passed compileall and 80 tests per actual Python version.

All nine job logs for runs 42274529813, 42274695527, and 42274759020 were inspected and confirmed the actual Python interpreter versions. These are automated tests, not independent security review or release acceptance. All PRs remain Draft/unmerged; `main` remains unchanged.


## Full live PR inventory and stack validation — 2026-11-06 20:28 UTC

This is the latest reconciled inventory and supersedes earlier head snapshots above.

| PR | Current head | Base | Exact-head or identical-tree CI |
|---|---|---|---|
| #1 | `fed330e03a3e55ecc1f5307e684fbc842eddea29` | `main` | [42241438580](https://github.com/Hamudifr/Capri/actions/runs/42241438580): 61 tests per Python 3.11/3.12/3.13 |
| #4 | `9bb4c021ccf7db24de6d4423816619a79ab6a459` | `recovery/non-x5-foundation` | [42273444013](https://github.com/Hamudifr/Capri/actions/runs/42273444013): 63 tests per version |
| #5 | `1b7ac13c9fe2de10d24703008084144726886ac7` | `recovery/non-x5-foundation` | Tree-identical to [42273893547](https://github.com/Hamudifr/Capri/actions/runs/42273893547): Doctor 5/5 and 66 tests per version |
| #6 | `f66cb8c1ce6165d0185b982ebd006fe397111984` | `feature/capri-doctor` | [42275074323](https://github.com/Hamudifr/Capri/actions/runs/42275074323): Doctor 6/6, health 7/7, and 92 tests per version |
| #10 | `3697f6440d0b56fc83c17bbb53234acaeb613a64` | `security/ledger-private-permissions-v2` | [42274529813](https://github.com/Hamudifr/Capri/actions/runs/42274529813): 75 tests per version |
| #12 | `7e37138b8dc3f353c300c8bca7a9bb8a3a74b5dc` | `recovery/non-x5-foundation` | Tree-identical to [42275168468](https://github.com/Hamudifr/Capri/actions/runs/42275168468): 64 tests per version |
| #14 | `da25bff24a9c4fdcad997591caabfa193df35f21` | `security/ledger-path-hardening` | [42274695527](https://github.com/Hamudifr/Capri/actions/runs/42274695527): 77 tests per version |
| #15 | `da2c3ec28412937c1993dcbe18132d73edeaa593` | `fix/ledger-inode-uncertainty-rebased-2026-11-06` | Tree-identical to [42274759020](https://github.com/Hamudifr/Capri/actions/runs/42274759020): 80 tests per version; test-only diff |

The #4 → #10 → #14 → #15 ledger stack is ancestry-reconciled: each dependent PR includes its current base as an ancestor (PR #10: 12 ahead / 0 behind; PR #14: 12 ahead / 0 behind; PR #15: 7 ahead / 0 behind). The #1 → #5 → #6 Doctor/recovery stack is also reconciled; PR #6 contains current PR #5 head as an ancestor (46 ahead / 0 behind at its latest pre-documentation merge commit). PR #12 now includes current recovery base (10 ahead / 0 behind).

All relevant three-version job logs were inspected. Each job installed and ran its labelled Python interpreter. The PR #10 matrix setup explicitly passes `matrix.python-version`. The earlier PR #10 run 42241452411 remains superseded for multi-interpreter claims. PR #5's failed intermediate run 42273662466 is retained in Actions history and documented in the PR description; subsequent tree-equivalent run 42273893547 passed Doctor 5/5. PR #15 and #12 final merge commits preserve the exact tested tree of their immediately preceding commits; their evidence is described as tree-equivalent rather than falsely attributed to a different commit SHA.

Exactly eight PRs are open; all remain Draft and unmerged: #1, #4, #5, #6, #10, #12, #14, #15. `main` remains unchanged at `228669ed8b0c02db669cc082ac256e7491a26201` and is unprotected. Repository remains private. No paid upgrade, public exposure, merge, deployment, release, or protected X5 access occurred.

Release gate remains **NOT MET** pending genuinely independent security review, explicit approval or replacement of non-X5 specification v0.2, assembled-stack acceptance, independent non-X5 evaluation, and governance evidence. The current Notion decision handoff is [here](https://app.notion.com/p/410ac6905d268165be22e79be52684b7); the independent ledger review packet is [here](https://app.notion.com/p/410ac6905d2681ef8551f668cd52e252).
