# Capri recovery plan

## Live reconciliation — 2026-11-07 18:36 CET (authoritative)

This section is the current repository snapshot. Older reconciliation blocks below are retained as historical records and must not be treated as current state.

### Current repository state

- Private repository: `Hamudifr/Capri`.
- Latest verified code-changing mainline commit: PR #120 merge `0965e539609b7fc94bcf000d0ba6f2fca8bc7f59`.
- Open pull requests: 2 Draft PRs: [#121](https://github.com/Hamudifr/Capri/pull/121) (memory input ordering) and [#122](https://github.com/Hamudifr/Capri/pull/122) (runtime documentation reconciliation). Neither has exact-head CI; both are intentionally CI-skipped while private-runner cost remains unverified.
- Main includes the non-X5 recovery foundation, permissioned tool boundary, durable audit/approval storage, principal-owned SQLite sessions, the OpenAI Responses API adapter, request-scoped host composition, durable task engine/worker, SQLite/Notion memory providers, Notion REST transport hardening, expiring-memory invariants, and private consistent backups for all four local SQLite stores.
- PR #120 exact-head CI run [42382331774](https://github.com/Hamudifr/Capri/actions/runs/42382331774), post-merge push run [42382405035](https://github.com/Hamudifr/Capri/actions/runs/42382405035), and latest-main push run [42382504366](https://github.com/Hamudifr/Capri/actions/runs/42382504366) passed compilation, Capri Doctor 6/6, operational health 7/7, and 425 tests on Python 3.11, 3.12, and 3.13. The latest run's three Python logs were inspected, including the actual hard-link alias failure tests and adversarial Doctor permission tests.
- Optional live Notion REST smoke was skipped. No live OpenAI API request, API key creation, paid API usage, deployment, public release, or protected X5 access occurred.

### Model and host runtime

- `OpenAIResponsesAdapter` implements the memory-aware model adapter using the standard library and the official Responses API. Function calls remain proposals and pass through ToolOrchestrator, ToolExecutionBridge, host permissions, approval controls, and audit.
- Full provider output continuation items, including reasoning items returned alongside function calls, are retained in the bounded private session transcript and replayed with tool outputs.
- Retrieved memory is sent separately from trusted host instructions. Main currently appends that user input item after the conversation transcript; draft PR #121 proposes prepending it and explicitly labeling it as reference data, not a new request. PR #121 has no exact-head CI and remains Draft.
- `CapriHostRuntime` composes a trusted HostAuthorityResolver, principal-owned SQLite sessions, ToolOrchestrator, optional principal-scoped memory resolver, and optional host-managed TaskWorker. It is request-scoped, not an HTTP server or daemon.
- SQLite session owner rows are created atomically, cannot be reassigned/deleted through database triggers, and are checked before memory retrieval/model invocation. Cross-principal and legacy unowned sessions are hidden as not found.
- Session, security, task, and memory SQLite stores all expose private consistent backup methods with integrity and store-specific validation. Backups are plaintext and must be protected.
- No live provider call was made. `OPENAI_API_KEY` and `CAPRI_OPENAI_MODEL` require deliberate host provisioning; API usage may incur charges separate from ChatGPT subscriptions. No hard currency spend cap is implemented.

### Current open work

- Draft PR #121: memory-to-model input ordering mitigation; source/test/docs readback verified, but no local tests or exact-head CI. Keep Draft until a verified no-cost test route is available.
- Draft PR #122: this runtime architecture/lifecycle documentation reconciliation; docs-only, CI intentionally skipped.
- `main` remains unprotected (`protected: false`). Do not enable paid protection or rulesets; preserve feature-branch review and manual evidence checks.

### Remaining work, ordered

1. Integrate a real authentication provider and test memory-provider ACLs; session ownership is implemented but does not by itself prove complete tenant isolation.
2. Build a supervised host process / API service with explicit lifecycle, approval UX, scheduling, health probes, and graceful shutdown.
3. Add per-principal request/token budgets and hard spend controls before any paid provider is enabled.
4. Add end-to-end adversarial tests for hostile memory, retrieved documents, forged tool calls, approval replay, and tool-result prompt injection.
5. Add redacted structured observability, live-dependency health probes, alerting hooks, and incident/recovery runbooks.
6. Add encrypted backup storage, scheduled/off-site copies, retention/compaction, and tested restore drills. Backup methods exist, but no backup policy or disaster-recovery exercise is implemented.
7. Add deployment packaging and process supervision; keep deployment internal/private until controls are verified.
8. Verify live Notion REST only when least-privilege credentials and repository Actions secrets/variables are deliberately configured. Verify live OpenAI only if the owner deliberately provisions an API key and accepts API charges. Never request or commit credentials in chat/Git.

### Delivery policy

Capri owns routine design, implementation, self-review, testing, integration, and documentation. External independent review is not a prerequisite for ordinary internal engineering. Use isolated feature branches, inspect exact diffs, run and inspect CI, verify dependency ancestry, and integrate completed compatible work. Keep self-review distinct from independent assurance.

No paid spend, subscriptions, credential/private-data exposure, destructive deletion, public release, platform-control bypass, or protected X5 access is authorized by this standing engineering mandate. Continue independent safe work when an external dependency is unavailable.

---


## Current reconciliation — 2026-11-06 19:58 UTC

This block is the current source of truth. Older snapshots below are retained as historical evidence and must not be read as current state.

### Owner directive and delivery policy

The owner delegates routine engineering direction to Capri: choose priorities, architecture, tools, sequencing, implementation, testing, integration, and documentation independently. Capri performs its own design, security, code, integration, and operational reviews; fixes findings; runs reproducible checks; inspects logs; and records evidence. External independent review is not a prerequisite for ordinary internal implementation or merging. Label internal self-review honestly; never describe it as independent assurance.

`main` is the delivery branch, not a permanent holding area. Use feature branches, inspect diffs, validate dependency ancestry and CI, preserve rollback, then merge completed work. Do not leave validated work stranded in Draft PRs without a concrete reason. No paid spend/subscriptions, credential/private-data exposure, platform-control bypass, or destructive/external action outside the user's grant. Preserve the protected X5 boundary.

### Current mainline state

- Current `main`: `ed530c8f3fbcea993a2577b87b2b9ab98bb16921`.
- PR #1 integrated the recovery foundation: `d42bfbb2f59a31c713b03f09d074da77b8fb6250`.
- PR #17 integrated the permissioned tool-execution boundary: `35ddc8408a2389dff8594283d40d37b66905c0dc`.
- PR #18 integrated durable audit and approval replay storage: `ed530c8f3fbcea993a2577b87b2b9ab98bb16921`.
- PR #18 exact-head run [42286374983](https://github.com/Hamudifr/Capri/actions/runs/42286374983) and post-merge main run [42286526969](https://github.com/Hamudifr/Capri/actions/runs/42286526969) both passed compileall, Capri Doctor 6/6, operational health 7/7, and 141 tests on each actual Python 3.11, 3.12, and 3.13 interpreter. All six job logs were inspected.
- PR #17 and #18 are closed/merged; implementation issue #16 is closed. No open PR remains from these deliveries.
- Repository remains private; `main` is unprotected under the current free/private configuration. Do not pay or publish merely to obtain rulesets.

### Implemented capabilities

- Typed evaluation metadata and fail-closed validation.
- Hash-chained append-only ledger with bounded parsing, private file permissions, symlink/path protections, crash-durability handling, hard-link/inode uncertainty latching, and operational runbooks.
- Read-only Capri Doctor and dependency-aware operational health.
- Provider-neutral in-memory sessions with optimistic concurrency and input/output/history limits enforced at Runtime and direct SessionStore commit boundaries.
- Permissioned tool execution in `capri_runtime.tools`: explicit registry, trusted handler injection, bounded strict schema subset, exact host permission checks, principal/tool/argument-digest-bound expiring one-use approval grants, strict JSON/Unicode and byte limits, redacted audit events, and fail-closed audit-start persistence.
- Durable local tool-security metadata in `capri_runtime.security_store.SQLiteSecurityStore`: SQLite WAL/FULL synchronous audit persistence and atomic cross-executor/process approval replay prevention; private POSIX directory/file checks and symlink/hard-link rejection.

### Permissioned tool execution — scope and limits

The tool boundary is a host-invoked execution gate, not a sandbox and not a model-provider integration. The model cannot grant itself permissions or approvals. Host code must authenticate the principal and construct trusted `ExecutionContext` and `ApprovalGrant` objects. The default in-memory approval store and audit sink are development-only. `SQLiteSecurityStore` provides durable local audit/replay metadata but is not encrypted and requires host-managed backups, retention, monitoring, and restore testing. Handlers run with Python process privileges and must be trusted. No shell, filesystem, network, dynamic import, automatic plugin discovery, or X5 access is included.

### Remaining engineering priorities

1. Durable, user-controllable memory with explicit export/deletion/retention controls.
2. Task planning, execution state, idempotency, retries, cancellation, and recovery.
3. Host identity/authorization and tenant isolation before any hosted multi-user deployment.
4. End-to-end model-to-tool orchestration with untrusted-content isolation, provider-aware budgets, observability, packaging, backup, and rollback.
5. Audit-store backup/restore, retention/compaction, monitoring, cryptographically authenticated approvals, and same-host tamper-resilience.

### Delivery and production position

The recovery foundation and first tool-execution gate are integrated and CI-verified on three Python versions. This is meaningful internal capability progress, not a claim of AGI or public/multi-tenant production readiness. Production release gate not met: public/hosted deployment remains a separate engineering gate until identity/authorization, tenant isolation, secrets handling, retention/deletion, provider budgets, monitoring, backups, rollback, handler isolation, audit-store recovery/retention, cryptographically authenticated approvals, and adversarial end-to-end validation are implemented. No protected X5 access or evaluation is authorized by ordinary engineering work.

## Phase 0 — Preserve boundaries

- [x] Inspect the current five-skill Notion registry; owner authorizes new or improved skills when a concrete capability gap and validation path justify them.
- [x] Establish protected blind-evaluation restrictions.
- [x] Create an isolated recovery branch.
- [ ] Maintain a minimal contamination log without protected content.

## Phase 1 — Establish a reviewable repository

- [x] Add repository purpose, operating model, and evaluation data contract.
- [x] Add deterministic structural tests.
- [x] Add CI for non-protected checks.
- [x] Perform Capri's internal review, validate the integrated PR, and merge the recovery foundation into `main` through PR #1.

## Phase 2 — Reconcile evaluation evidence

- [ ] Obtain a fresh, authorized, metadata-only export of non-protected records.
- [ ] Reconcile run count versus unique scenario count and retest lineage.
- [ ] Validate evidence-stage completeness without opening protected material.
- [ ] Perform Capri's own review of non-protected evaluation metadata, evidence completeness, and retest lineage.
- [ ] Use an independent evaluator only if a specific evaluation protocol or external requirement explicitly requires one; never label self-review as independent.

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
- [x] Implement the provider-neutral permissioned tool-execution gate with strict schemas, host permissions, action-bound approvals, bounded JSON, redacted audit, and regression tests.
- [ ] Implement concrete model/tool adapters, durable user memory, task orchestration, persistence strategy, and deployment packaging.
- [ ] Add security, privacy, resilience, and integration tests.

The session runtime is intentionally process-local and memory-only. A separate permissioned tool-execution gate now exists, but it is not wired to a concrete model provider and is not a sandbox. The repository still lacks durable user memory, host authentication, tenant isolation, provider integration, and deployment. The ledger remains a separate single-writer metadata component.

## Phase 4 — Internal verification and controlled release

- [x] Perform Capri's own design, code, security, integration, and operational self-review for the current integrated foundation.
- [x] Run the assembled repository suite on Python 3.11, 3.12, and 3.13; inspect every job log and record the exact commit/run evidence.
- [x] Implement and test the first permissioned tool-execution boundary; see `docs/TOOL_EXECUTION.md`.
- [ ] Implement durable user-controlled memory, identity/tenant isolation, task recovery, budgets, cryptographically authenticated approvals, and observability.
- [ ] Complete adversarial and end-to-end tests for the implemented agent capabilities.
- [ ] Verify backups, recovery, rollback, deployment configuration, and data-retention/deletion behavior before public or multi-tenant deployment.
- [ ] Run the protected blind evaluation only through its authorized designated environment and procedure.
- [ ] Record the outcome exactly as reported by that process; do not infer it.

External independent review is not a prerequisite for routine internal implementation or merging. If a specific contract, regulation, customer commitment, or protected evaluation explicitly requires an independent evaluator, record that narrow requirement separately; never label Capri's self-review as independent.

## Exit criteria

The initial non-X5 recovery foundation is now integrated into `main` and passes the post-merge three-version CI suite. Broader agent engineering remains in progress until permissioned tool execution, durable memory, task recovery, identity/tenant isolation, and observability are implemented and tested. Production deployment is a separate gate requiring privacy/retention, budgets, monitoring, backup, rollback, and adversarial validation. The protected blind evaluation remains separate and may only be run through its authorized process.


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
