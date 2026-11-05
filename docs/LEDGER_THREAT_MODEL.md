# Ledger threat model and operational controls

## Scope

This document covers only the local JSONL execution-ledger prototype in `capri_core`. It is not a threat model for the complete Capri agent, which has not been specified or implemented.

## Protected assets

- Integrity and ordering of non-protected run metadata.
- Availability and readability of the ledger file.
- Confidentiality of any external evidence referenced by a record.

Do not store protected blind-evaluation content, credentials, secrets, or personal data in records or evidence references.

## Trust assumptions

- The host operating system and Python runtime are trusted.
- Filesystem permissions are correctly configured by the operator.
- Exactly one writer process owns a ledger file at a time.
- Evidence references are opaque pointers; this library does not fetch or authorize them.

## Implemented controls

- Runtime type and enum validation before append and after decode.
- Strict JSON parsing rejects duplicate object keys and non-standard numeric constants.
- Canonical JSON serialization is used as hash input.
- SHA-256 hash chaining detects accidental or partial modification of existing entries.
- Run identifiers are unique within a ledger; retest parents must precede children.
- Writes flush and call `fsync` before returning.
- The in-process reentrant lock serializes threads sharing this module instance.
- Verification and append validation scan the JSONL file line by line; append/verify retain run IDs for duplicate and parent checks rather than retaining every decoded entry.
- Binary bounded reads enforce a configurable per-entry byte ceiling before decoding/parsing (default: 1 MiB); writes enforce the same ceiling.
- An unterminated final line is rejected as an incomplete/corrupt entry rather than accepted as a complete JSON record.
- The verification CLI is read-only and refuses a missing or non-file path.

## Known limitations

- **No authenticity:** an attacker who can rewrite the entire file can recompute every hash. A hash chain is not a digital signature or trusted timestamp.
- **No access control:** file permissions, user identity, and host hardening are external responsibilities.
- **No encryption:** the ledger is plaintext JSONL.
- **Single writer only:** the lock is process-local. Multiple processes or hosts can race and corrupt ordering.
- **No transactional storage:** a process or machine failure can leave a partial final line. Verification and subsequent appends fail closed; recovery/repair tooling is not implemented. Preserve the original and recover only from a verified backup or a separately reviewed copy—never auto-truncate.
- **No backup or retention system:** operators must provide backups, retention, and secure deletion.
- **No evidence verification:** a non-empty evidence reference is not proof that the evidence exists, is immutable, or supports the outcome.
- **Linear scan and ID memory:** append and verification remain O(n) in ledger length; the run-ID set remains O(n) memory. This avoids retaining the full decoded ledger but is not a scalable indexed store.
- **Configurable entry ceiling:** the default 1 MiB limit may need an explicitly reviewed adjustment for legitimate larger evidence metadata. The limit bounds a single decoded entry, not total ledger size or the O(n) run-ID set.
- **No migration framework:** changes to record fields or controlled vocabularies require an explicit versioned migration plan before deployment.

## Operational guidance

1. Keep the ledger in a directory writable only by its service account.
2. Enforce one writer process per file; do not share a writable ledger over a network filesystem.
3. Back up the file before upgrades and verify the backup.
4. Treat verification failures as integrity incidents. Preserve the original file and investigate a copy; do not silently rewrite or truncate it.
5. Keep evidence in an independently access-controlled store and use opaque, non-secret references.
6. Do not treat a successful hash check as independent review or proof of evaluation correctness.

## Verification

Run:

```bash
python -m capri_core verify path/to/runs.jsonl
```

The command prints only validity, record count, and the chain head hash. It does not print record contents or modify the file.
