# Append-only outcome journal

## Purpose

`capri_runtime.outcomes` records durable, principal-owned observations about goal, task, workflow, decision, and system outcomes. It is an evidence and continuity primitive for later evaluation. It does not train a model, change policy, grant tool permissions, or automatically treat an observation as verified truth.

## Record contract

Each immutable `OutcomeRecord` contains:
- principal owner and subject identity (`subject_type`, `subject_id`);
- bounded outcome category and status (`outcome_type`, `status`);
- a short summary;
- provenance (`source_type`, optional opaque `source_reference`);
- confidence classification and recorded timestamp;
- optional idempotency key;
- optional correction lineage (`supersedes_id`, `correction_reason`).

Allowed source types distinguish user reports, host observations, tool results, verification, system reconciliation, and explicit user corrections. Confidence is descriptive metadata, not a cryptographic proof or automatic truth score.

## Append and correction semantics

- `append_for_principal` adds a new row. A caller-supplied idempotency key replays the original row only when the payload matches; reuse with a different payload fails.
- `correct_for_principal` appends a new row linked to the prior row. It never updates or deletes historical evidence.
- Only the current unsuperseded row can be corrected. A unique successor constraint prevents competing corrections, including concurrent writers.
- Corrections retain the same principal, subject, and outcome category. A correction reason is mandatory.
- Default listing returns only current records. `include_superseded=True` returns the full historical chain.
- The store does not infer goal success, automatically write from task reconciliation, or promote confidence. These are separate policy decisions.

## Security and durability

- The host API authenticates each request and binds all reads, appends, corrections, and lists to the resolved principal.
- Records are bounded plain text and typed metadata. Do not store secrets or sensitive personal data in summaries or source references.
- SQLite lives in a private host-controlled directory; POSIX path, owner, file-mode, and link-count checks are repeated on connection.
- Connections enable foreign keys, recursive triggers, trusted-schema restrictions, and FULL synchronous durability.
- SQLite triggers reject record updates and deletes. Integrity checks validate trigger presence, row schemas, foreign keys, and correction ancestry.
- `backup_to` uses the shared online-backup primitive, validates the completed snapshot, and publishes without replacing an existing destination.
- The database is not encrypted. Protect it and its backups through host filesystem controls.

## Host API

`CapriHostRuntime` accepts an optional `SQLiteOutcomeStore` and exposes:
- `record_outcome`
- `correct_outcome`
- `get_outcome`
- `list_outcomes`

Storage health includes the outcome journal when configured. No background worker or external provider is started by constructing the runtime.

## Limitations and next step

This is a durable journal, not an automated learning loop. It has no cross-store transaction with goal/task state, no external evidence verifier, no retention/deletion workflow, no automatic goal-outcome capture, and no model adaptation. Future consumers must treat summaries and references as untrusted evidence, preserve provenance, and distinguish observed, user-reported, inferred, and independently verified results.

Next package: X8.2 memory retrieval evaluation and ranking, using a labelled offline dataset and regression thresholds before any strategy adaptation.
