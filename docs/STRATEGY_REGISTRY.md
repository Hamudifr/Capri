# X8.4 principal-scoped strategy registry

## Status

The offline evaluator is implemented in `capri_core.strategy`. This module adds a durable, principal-scoped registry and host API for immutable strategy versions, evaluation summaries, approval-gated activation, append-only transition history, and rollback.

It is a control-plane capability only. The task engine and model orchestration do not automatically read or apply the active strategy. No strategy code is stored or executed.

## Storage boundary

- `SQLiteStrategyStore` wraps the exact existing `SQLiteTaskStore` instance and shares its private SQLite database, connection validation, lock, and filesystem protections.
- It refuses another store type or a different task-store instance when composed into `CapriHostRuntime`.
- Strategy configurations are bounded JSON data only. Reserved keys that could alter permissions, tool allowlists, budgets, spend limits, safety policy, prompts, credentials, or executable code are rejected at every nesting level.
- Strategy versions, evaluation summaries, and activation events are immutable. The active pointer is a projection checked against the event history on every read.
- The event history is generation-ordered and SHA-256 hash-chained per principal and strategy class. This is tamper-evident against accidental changes, not a cryptographic signature or protection against an attacker who can rewrite the whole database.

## Candidate admission

A candidate must:
1. Be compared with a registered baseline.
2. Have an eligible offline `StrategyEvaluation` with at least 20 matched pairs.
3. Supply the original observations; the store recomputes the evaluation and requires an exact result/fingerprint match.
4. Supply a bounded evidence-manifest locator. The locator is not proof. Candidate admission also requires a trusted host-injected `evidence_verifier`; if absent, false, or failing, registration is denied before any evaluation row is written. The verifier receives an immutable context binding principal, strategy class, baseline/candidate IDs and versions, cohort fingerprint/schema, manifest locator, and matched-pair count. It must load the source journal, authenticate provenance and task-family classification, reconstruct the cohort, and confirm the exact fingerprint. It must be read-only and must not trust caller-supplied observations or model assertions.
5. Register a data-only configuration. Registration does not activate the candidate.

The store persists only the evaluation summary and fingerprint, not raw observations or conversation content.

## Activation and rollback

Activation and rollback are denied by default unless the store is constructed with a trusted host-owned `approval_verifier`. There is no caller-supplied `approved=True` switch and the model never receives the verifier.

A host-issued `StrategyActivationGrant` binds the exact strategy version measured in the cohort. Each observation carries a version; mixed versions within a strategy cohort are rejected; the registry requires the candidate and registered baseline versions to match the evaluated versions. The grant binds:
- principal;
- strategy class, ID and version;
- evaluation fingerprint (or null for a baseline);
- exact configuration SHA-256;
- action (activate or rollback);
- expected active generation;
- issue/expiry timestamps (maximum 15-minute lifetime);
- one-use grant ID and approver identity.

The host verifier must authenticate the grant's signature/authorization. The store independently checks the fields, expiry, principal, config/evaluation fingerprints, grant replay, and generation compare-and-swap inside an atomic SQLite write transaction. The host grant issuer must independently re-verify the candidate's authenticated evidence manifest and task-family classification before signing, including for legacy candidate rows created before an `evidence_verifier` was configured; admission-time verification does not retroactively authenticate old rows.

Rollback is not deletion or time travel. It appends a new `rollback` event pointing to a version that was previously active. The former state remains in history.

## Host API

When a trusted host supplies the exact task store and configured strategy store, `CapriHostRuntime` exposes principal-scoped methods to:
- register a baseline;
- register a recomputed candidate;
- read the active strategy;
- activate with a host-authenticated grant;
- roll back with a host-authenticated grant;
- read the verified activation history.

The host must keep the approval verifier and grant issuance outside model-visible tools. A deployment should bind it to its existing authentication/approval service. The included test verifier is only a test fixture.

## Explicit non-goals

- No automatic strategy selection or shadow execution in the task engine yet.
- No execution of configuration strings, scripts, tool names, or code.
- No change to model weights, provider calls, tool permissions, allowlists, budgets, spend limits, or safety policy.
- No secret manager, signature key, or approval UI is created by this library.
- No encryption-at-rest guarantee beyond the existing private SQLite storage controls.
- No claim that a candidate generalizes beyond its evaluated cohort.

## Next integration gates

1. Connect the host approval verifier to the existing signed approval service, with a reviewed operation binding.
2. Add shadow-mode runtime instrumentation that records recommendations without changing execution.
3. Evaluate strategy versions across representative scenario classes and measure uncertainty, safety regressions, and operational cost.
4. Only then consider host-controlled live selection. Preserve explicit approval and a tested rollback path.
