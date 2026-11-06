# Ledger scaling architecture decision

**Status: PROPOSED — NOT IMPLEMENTED**  
**Scope: non-X5 execution metadata only**

## Context

The current JSONL ledger is intentionally small and dependency-free. It validates the complete hash chain before every append, retaining all historical run IDs in memory to enforce unique IDs and parent-before-child lineage. This gives simple, inspectable files but means append and verification are O(n) in record count, with O(n) ID memory. It also relies on an operational single-writer-process rule and cannot atomically commit a record plus a separate index.

Do not add an index sidecar to the current JSONL implementation without a crash-consistency design. A stale or partially updated index could cause duplicate-ID or parent checks to become incorrect.

## Proposed next storage boundary

When operational measurements justify moving beyond JSONL, evaluate a standard-library SQLite backend rather than adding an independently updated sidecar index.

Candidate properties:

- Store each immutable record, its previous hash, and its computed hash in one table.
- Enforce run_id uniqueness with a database unique constraint.
- Enforce parent references with a foreign key and an explicit earlier-record ordering check inside the same write transaction.
- Store the current chain head in a metadata row updated in the same transaction as the inserted record.
- Use a write transaction (BEGIN IMMEDIATE) so competing writer processes serialize at the database boundary.
- Add indexes for supported query patterns only after those patterns are specified and measured.
- Use append-only triggers or restricted repository APIs to reject record updates/deletes; migrations remain separately authorized.
- Define and test backup/checkpoint behavior before selecting WAL or another journal mode.
- Preserve the existing canonical JSON payload and SHA-256 chain encoding unless a versioned migration is approved.

SQLite still serializes writers; it is not a multi-writer distributed database. Network filesystems and multi-host deployments require a separate architecture decision.

## Migration safety requirements

A future migration must:

1. Stop/quiesce the JSONL writer and preserve the original source file.
2. Verify the source JSONL chain with the current implementation.
3. Import records in source order inside a controlled migration.
4. Recompute every canonical payload hash and previous-hash link; do not trust copied hash fields alone.
5. Verify unique run IDs and parent-before-child relationships during import.
6. Commit atomically, then independently scan the database and compare record count, ordered run IDs, and final chain head with the source.
7. Preserve the original JSONL file as a read-only migration artifact until retention policy authorizes disposal.
8. Test rollback, interrupted migration, backup restore, and export/re-import equivalence.

No migration should be run against evaluation evidence without an explicit owner-approved plan.

## Decision gates before implementation

Do not implement this proposal until the owner supplies:

- Expected record volume and growth rate.
- Required append and query latency objectives.
- Deployment topology (single host, multiple processes, containers, or multiple hosts).
- Backup, retention, encryption, and recovery-point/recovery-time objectives.
- Supported read/query patterns and export requirements.
- Ownership of schema evolution and migration approval.

## Current decision

Keep the bounded JSONL implementation for the recovery foundation. It is suitable only for small, single-writer, local workloads. The 1 MiB entry ceiling bounds individual parser input, not total ledger growth. The SQLite proposal is a design candidate, not a claim of production scalability or a completed migration.
