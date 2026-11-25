# Host execution evidence journal

## Purpose

`SQLiteExecutionEvidenceJournal` records a minimal, host-authenticated source event for later strategy evaluation. It closes the gap between a caller-provided evidence locator and an authenticated record of a task claim and verified result.

This is a host library primitive. It is not a worker scheduler, strategy router, model tool, or deployed evidence collector.

## Trusted host wiring

Construct the journal only inside the trusted host process and inject:

- `authenticate_collector(credential)`: authenticate a host-held collector credential and return its principal.
- `classify_task(principal_id, task_id)`: derive a `TaskClassification` from trusted, authenticated task metadata. Never use a model-authored family label. Return an allow-listed `task_family` and a stable matched-cohort `scenario`.
- `resolve_strategy(principal_id, claim)`: resolve the strategy class, strategy ID, and explicit version actually selected by trusted host policy for this claim.
- `verify_result(principal_id, claim, result, result_sha256)`: independently verify the execution result and derive the outcome and bounded metrics. Return an exact `VerifiedExecutionResult` whose digest matches the supplied canonical result digest.
- A host-held HMAC provider with a non-exported key. Do not expose the journal, key provider, credential, or callbacks through model-visible tools.

The task claim is revalidated against the authoritative `SQLiteTaskStore` and principal ownership is checked before any event is persisted. `TaskEngine` requires the journal to share the exact same store object as the worker.

## Lifecycle

1. A trusted worker obtains a live `TaskClaim`.
2. The worker executes the host-authorized handler.
3. Configure `TaskEngine` with both `execution_evidence_journal` and a host-only `execution_evidence_credential(claim)` resolver. After a principal-owned handler returns and its result passes JSON validation, `TaskEngine` calls `record_execution(credential, claim, result)` before `finish_step` consumes the claim lease. Legacy unowned tasks are not recorded.
4. The journal hashes the canonical bounded result, asks the injected verifier to independently derive outcome/metrics, signs canonical event metadata, and appends the event to the shared private SQLite database.
5. The returned `host-execution-event:<uuid>` reference can populate a `StrategyObservation.evidence_ref`.
6. The existing `SQLiteStrategyEvidenceManifestStore` can use the journal's `classify_task_family` and `validate_source_events` methods as its trusted callbacks.

A repeated write for the same task step, attempt, and strategy is idempotent only when the claim and result digests match. Conflicting replay is rejected.

## Data minimization and integrity

The journal stores task/principal identifiers, claim and result digests, strategy identity/version, trusted family/scenario, verified categorical outcome, bounded metrics, timestamp, key ID, event digest, HMAC signature, and canonical payload. It does not persist raw task inputs, prompts, model output, credentials, or raw results.

SQLite update/delete triggers provide append-only guards. Canonical payload hashes and duplicated-row binding checks are included in task-store backup/integrity validation. `SQLiteExecutionEvidenceJournal.integrity_check()` additionally verifies HMAC signatures using the live host key provider. A database-only backup cannot independently verify HMACs without that host key, which is intentionally not copied into the database.

## Important limits

- A signed event proves that the configured trusted host callbacks attested to the recorded execution metadata. It does not make a defective or dishonest verifier correct.
- Strategy identity is only as reliable as the injected host resolver.
- Task-family classification is only as reliable as the injected host classifier and its source metadata.
- Evidence collection is opt-in. The embedding host must construct the journal with trusted callbacks, then configure `TaskEngine` with that journal and a credential resolver that returns a host-held collector credential for the claim's principal. Never expose either object or credential resolver to model-visible tools.
- If evidence recording fails after a handler may have performed a side effect, `TaskEngine` moves the task to `reconciliation_required` instead of marking it successful or retrying blindly. Hosts must implement reconciliation procedures for this state.
- No live evidence collection, shadow-mode measurement, automatic strategy selection, promotion, canary, or activation is enabled by adding this module.
- The journal must be integrated and tested against the real host execution path before evidence is treated as production-collected.

## Verification

The module's tests cover principal authentication, current-claim validation, host-result-verifier failure, family allow-listing, idempotent replay, raw-result minimization, signed payload tampering, observation rebinding, task-store backup/integrity validation, successful `TaskEngine` collection before completion, and fail-closed reconciliation when evidence recording fails. Exact-head GitHub Actions results are recorded on the pull request.
