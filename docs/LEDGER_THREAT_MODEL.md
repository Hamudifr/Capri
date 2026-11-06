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
- Lone Unicode surrogate code points are rejected before UTF-8 canonical serialization.
- Strict JSON parsing rejects duplicate object keys and non-standard numeric constants.
- Canonical JSON serialization is used as hash input.
- SHA-256 hash chaining detects accidental or partial modification of existing entries.
- Run identifiers are unique within a ledger; retest parents must precede children.
- Newly created ledger parent directories request mode `0700`; ledger files are created with mode `0600` and, on POSIX, existing file modes are tightened to `0600` on append. This is filesystem-mode hardening, not user/tenant authorization; existing parent directories remain operator-owned.
- Existing file modes are tightened only after the ledger chain, record validation, lineage, and new-entry size checks succeed; a rejected append does not change permissions.
- Ledger reads and writes reject symlink path components and non-regular final files. On POSIX systems with `dir_fd`, `O_DIRECTORY`, and `O_NOFOLLOW`, parent components are traversed without following symlinks and the final file is opened with `O_NOFOLLOW`, then checked with `fstat`. Platforms without those primitives use pre-open `lstat` checks; a concurrent path swap remains possible, so this fallback is not equivalent protection. Parent-directory ownership and trust remain operator responsibilities.
- Writes flush and call `fsync` before returning.
- First-time file creation fsyncs the ledger file and then its containing directory on POSIX; every newly created parent directory is also fsynced together with the directory containing it. Ordinary appends fsync only the file.
- A write, flush, or fsync failure after writing begins latches both the normalized path and the opened file identity (`st_dev`, `st_ino`) in the current process. Reads and appends through hard-link aliases therefore fail closed too, including scans supplied with an already-open descriptor. If a write somehow starts without a captured identity, the process-wide ledger guard fails closed. These latches are process-local and are lost on restart; preserve the original file and inspect a copy before retrying after any such failure. To prevent inode-number reuse from poisoning an unrelated file, the process retains one duplicate descriptor for each uncertain inode (up to 128). These descriptors pin the original inodes until process exit. If the guard limit is reached, the process-wide ledger guard fails closed rather than dropping identity protection.
- The in-process reentrant lock serializes threads sharing this module instance.
- Verification and append validation scan the JSONL file line by line; append/verify retain run IDs for duplicate and parent checks rather than retaining every decoded entry.
- Binary bounded reads enforce a configurable per-entry byte ceiling before decoding/parsing (default: 1 MiB); writes enforce the same ceiling.
- An unterminated final line is rejected as an incomplete/corrupt entry rather than accepted as a complete JSON record.
- The verification CLI is read-only and refuses a missing or non-file path.

## Known limitations

- **No authenticity:** an attacker who can rewrite the entire file can recompute every hash. A hash chain is not a digital signature or trusted timestamp.
- **No application access control:** POSIX file modes reduce accidental local disclosure, but user identity, authorization, ownership, parent-directory permissions for existing paths, host hardening, and non-POSIX ACL behavior remain operator responsibilities. The ledger remains plaintext.
- **No encryption:** the ledger is plaintext JSONL.
- **Single writer only:** the lock is process-local. Multiple processes or hosts can race and corrupt ordering.
- **No transactional storage:** a process or machine failure can leave a partial final line. Verification and subsequent appends fail closed; recovery/repair tooling is not implemented. Preserve the original and recover only from a verified backup or a separately reviewed copy—never auto-truncate.
- **No backup or retention system:** operators must provide backups, retention, and secure deletion.
- **No evidence verification:** a non-empty evidence reference is not proof that the evidence exists, is immutable, or supports the outcome.
- **Linear scan and ID memory:** append and verification remain O(n) in ledger length; the run-ID set remains O(n) memory. This avoids retaining the full decoded ledger but is not a scalable indexed store.
- **Configurable entry ceiling:** the default 1 MiB limit may need an explicitly reviewed adjustment for legitimate larger evidence metadata. The limit bounds a single decoded entry, not total ledger size or the O(n) run-ID set.
- **No migration framework:** changes to record fields or controlled vocabularies require an explicit versioned migration plan before deployment.

## Operational guidance

1. Keep the ledger in a directory writable only by its service account. New ledger files use POSIX mode `0600`, and a newly created immediate parent directory requests `0700`; verify existing directory ownership/permissions and non-POSIX ACLs separately.
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
