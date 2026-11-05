# Ledger backup and recovery runbook

## Scope and safety

This runbook applies only to the non-X5 local JSONL ledger prototype. It does not authorize access to protected evaluation material. Treat a verification failure as an integrity incident: preserve the original file, do not edit it in place, and do not silently truncate a partial final line.

The prototype supports one writer process per ledger file. Stop or otherwise quiesce the writer before taking a filesystem copy. Do not copy a live file while an append is in progress.

## Create and verify a backup

Set explicit paths for the source and backup. The backup destination must not be the source path.

```bash
LEDGER="/var/lib/capri/runs.jsonl"
BACKUP="/var/backups/capri/runs-$(date -u +%Y%m%dT%H%M%SZ).jsonl"

# Stop/quiesce the Capri process that owns the ledger before copying.
install -D -m 0600 -- "$LEDGER" "$BACKUP"
python -m capri_core verify "$BACKUP"
sha256sum -- "$LEDGER" "$BACKUP"
```

A successful verification confirms the copied bytes form a valid chain according to the current schema. Matching SHA-256 values confirm the source and backup copies are byte-identical at the time of the copy. Neither check proves that the records are truthful, independently reviewed, or authentic against an attacker able to rewrite the entire ledger.

Store backups in an access-controlled location with retention and encryption appropriate to the host's data classification. The prototype does not implement backup scheduling, encryption, retention, or secure deletion.

## Respond to a verification failure

1. Stop the writer and prevent further writes to the affected ledger.
2. Preserve the original file byte-for-byte; record its filesystem metadata and a SHA-256 digest.
3. Make a separate forensic copy and perform inspection only on that copy.
4. Verify the most recent known-good backup using the current application version.
5. Compare the verified backup with the forensic copy. Do not infer that a valid prefix makes the remaining tail safe to discard.
6. Restore only through an operator-approved recovery procedure: preserve the failed original, stage the chosen backup at a new path, verify the staged copy, then perform a controlled service cutover.
7. Record who approved the recovery, the source backup, hashes, timestamps, and any data loss window.

## Explicitly unsupported recovery actions

- No automatic truncation or repair of a partial final line.
- No automatic acceptance of a valid prefix when later records are corrupt.
- No rewriting or re-hashing records to make verification pass.
- No multi-process or multi-host concurrent writer mode.
- No guarantee that a filesystem copy taken while a writer is active is consistent.

## Upgrade and schema changes

Before changing record schemas or hash-chain encoding, create and verify a backup. Define a versioned migration with deterministic input/output, preserve the original ledger, and verify the migrated output independently. The current prototype has no migration framework; do not migrate production or evaluation evidence with ad hoc scripts.
