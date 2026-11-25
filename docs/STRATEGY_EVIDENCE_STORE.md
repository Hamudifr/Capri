# SQLite strategy evidence manifest store

## Status

Provides a private append-only SQLite manifest backend on the same protected database as `SQLiteTaskStore`. It stores only bounded, privacy-minimized `StrategyObservation` metadata and host-derived task-family labels. It does not store prompts, model outputs, secrets, or raw user content.

## Required host trust callbacks

All three callbacks are mandatory:

- `authenticate_collector(credential)` derives the principal from trusted host credentials.
- `classify_task_family(principal_id, task_id)` derives one allow-listed family from trusted task metadata. Current allowlist: coding, formatting, general_qa, research, retrieval, summarization, writing.
- `validate_source_events(principal_id, strategy_class, observations, task_families)` verifies every opaque evidence reference, task ownership, outcome and metric against genuine host execution records. It must return literal `True`.

No default classifier or permissive validator is provided. Missing, invalid, mixed-family, or unverifiable source records fail closed.

## End-to-end composition

1. The authenticated host collector calls `register_manifest` with a complete baseline/candidate observation cohort.
2. The store recomputes the cohort evaluation and fingerprint, derives a single task family for every task, validates all source events, and writes a canonical immutable manifest.
3. The returned `StrategyEvidenceContext` points to `sqlite-strategy-manifest:<sha256>`.
4. Pass `store.attest_manifest` and `store.verify_manifest` to `HostStrategyEvidenceAuthority`. Issue the signed token from the trusted host only.
5. Register the candidate with the signed token as `evidence_manifest_ref` and `authority.verify` as `SQLiteStrategyStore.evidence_verifier`.

The verifier reopens the manifest by digest, replays the cohort evaluation, re-derives task families, and revalidates source events at candidate admission.

## Storage and privacy

Manifest rows have immutable update/delete triggers and are hashed over canonical JSON. The digest covers all observations, opaque evidence references, task-family labels, principal, strategy versions and cohort metadata. The store rejects non-opaque evidence references and stores no free-form prompts or outputs. The database inherits `SQLiteTaskStore` private-file and directory protections.

## Limits

- The manifest store cannot prove its own callbacks are truthful. The host must implement them against authenticated source-of-truth execution records.
- Current task lifecycle events alone do not contain all strategy outcome metrics; a host adapter must collect metrics from trusted execution telemetry and bind them to task IDs.
- The store attests candidate admission only. Independent staged-promotion replay and activation-time revalidation remain required.
- No strategy is activated or routed. Canary routing, monitoring and automatic rollback remain separate future work.
