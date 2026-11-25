# Host execution evidence journal

## Purpose

`SQLiteExecutionEvidenceJournal` records a minimal, host-authenticated source event for later strategy evaluation. It binds a verified execution to an authenticated task claim, trusted strategy identity, classified task family, canonical result digest and host-derived outcome/metrics.

This is a host library primitive. It is not a worker scheduler, strategy router, model tool, or deployed evidence collector.

## Trusted host wiring

Construct the journal only inside the trusted host process and inject:

- `authenticate_collector(credential)`: authenticate a host-held collector credential and return its principal.
- `classify_task(principal_id, task_id)`: derive a `TaskClassification` from trusted, authenticated task metadata. Never use a model-authored family label. Return an allow-listed `task_family` and a stable matched-cohort `scenario`.
- `resolve_strategy(principal_id, claim)`: resolve the strategy class, strategy ID, and explicit version actually selected by trusted host policy for this claim.
- `verify_result(principal_id, claim, result, result_sha256)`: independently verify the execution result and derive the outcome and bounded metrics. Return an exact `VerifiedExecutionResult` whose digest matches the supplied canonical result digest.
- A host-held HMAC provider with a non-exported key. Do not expose the journal, key provider, credential, or callbacks through model-visible tools.

The authenticated principal identifier uses the same 256-character bound as the host authority, session store, and principal-owned task APIs. The task claim is revalidated against the authoritative `SQLiteTaskStore` and principal ownership is checked before any event is persisted. The journal and `TaskEngine` must share the exact same `SQLiteTaskStore` object.

## Lifecycle

1. A trusted worker obtains a live `TaskClaim`.
2. The worker executes the host-authorized handler.
3. Configure `TaskEngine` with both `execution_evidence_journal` and a host-only `execution_evidence_credential(claim)` resolver. After a principal-owned handler returns and its result passes JSON validation, `TaskEngine` calls `record_execution_and_finish(credential, claim, result)`.
4. The journal authenticates the collector, classifies the task, resolves the strategy, hashes a bounded canonical result snapshot, and asks the injected verifier to derive outcome/metrics. The verifier receives its own decoded copy and cannot mutate the result snapshot that will be persisted.
5. In one `BEGIN IMMEDIATE` transaction, the journal revalidates the live task lease, appends the signed evidence event, updates the task result/state, and appends the task lifecycle event. These writes commit or roll back together. A crash cannot leave a newly written evidence event without the matching task completion.
6. If any evidence or task-completion write fails after the handler may have caused a side effect, the transaction rolls back and `TaskEngine` moves the still-live task to `reconciliation_required`. Hosts must implement reconciliation procedures for this state.
7. Only after the task reaches `succeeded` can the returned `host-execution-event:<uuid>` reference be admitted into a strategy cohort. Admission rechecks principal ownership, the exact completed task step/attempt, and the canonical digest of the result persisted at that step.
8. The existing `SQLiteStrategyEvidenceManifestStore` can use the journal's `classify_task_family` and `validate_source_events` methods as its trusted callbacks.

A task step attempt admits at most one evidence event, regardless of strategy ID. A repeated write is idempotent only when the claim/result digests, principal, strategy class/version, task classification, verified outcome, and all measured metrics match. Any drift is rejected as conflicting evidence.

The lower-level `record_execution()` method can append a pending event without completing a task; such an event is integrity-checkable but is not eligible for strategy evidence until it matches a successful task result. The production `TaskEngine` integration uses `record_execution_and_finish()` to avoid the split-transaction window.

## Data minimization and integrity

The journal stores task/principal identifiers, claim and result digests, strategy identity/version, trusted family/scenario, verified categorical outcome, bounded metrics, timestamp, key ID, event digest, HMAC signature, and canonical payload. It does not persist raw task inputs, prompts, model output, credentials, or raw results.

SQLite update/delete triggers provide append-only guards. Canonical payload hashes and duplicated-row binding checks are included in task-store backup/integrity validation. `SQLiteExecutionEvidenceJournal.integrity_check()` additionally verifies HMAC signatures using the live host key provider. A database-only backup cannot independently verify HMACs without that host key, which is intentionally not copied into the database.

## Important limits

- A signed event proves that the configured trusted host callbacks attested to the recorded execution metadata. It does not make a defective or dishonest verifier correct.
- Cryptographic integrity and cohort admissibility are separate: `integrity_check()` validates stored signatures, while `validate_source_events()` additionally requires successful task completion and an exact persisted-result digest match.
- Strategy identity is only as reliable as the injected host resolver.
- Task-family classification is only as reliable as the injected host classifier and its source metadata.
- Evidence collection is opt-in. The embedding host must construct the journal with trusted callbacks, then configure `TaskEngine` with that journal and a credential resolver that returns a host-held collector credential for the claim's principal. Never expose either object or credential resolver to model-visible tools.
- No live evidence collection, shadow-mode measurement, automatic strategy selection, promotion, canary, or activation is enabled by adding this module.
- The journal must be integrated and tested against the real host execution path before evidence is treated as production-collected.

## Verification

The tests cover principal authentication, current-claim validation, host-result-verifier failure, family allow-listing, idempotent replay, raw-result minimization, signed payload tampering, observation rebinding, successful-task/result-digest admission, atomic evidence/task completion, rollback on completion failure, task-store backup/integrity validation, verifier mutation isolation, and fail-closed reconciliation. Exact-head GitHub Actions results are recorded on the pull request.
