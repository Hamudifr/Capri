# Capri C migration

This directory contains the native GNU C11 implementation being built toward a repository-wide Capri migration.

## Current native modules

- **CCEL research engine**: bounded grid transformations, synthesis, prediction, and probe selection in include/ccel.h and src/ccel.c.
- **Core evaluation records**: fixed-capacity record types and validation in include/capri_core.h and src/capri_core.c. Validation rejects malformed UTF-8 (including surrogate encodings), unterminated fixed fields, unknown controlled-vocabulary dimensions, invalid enum states, invalid timezone-aware RFC 3339 timestamps, inconsistent evaluator/evidence stages, and self-parent lineage.
- **Native SQLite sessions**: principal-owned durable sessions, immutable ownership rows, strict transcript validation, optimistic version-checked turn commits, durable turn leases, integrity checking, validated atomic online backups, and safe restore-to-new-database in include/capri_session_store.h and src/capri_session_store.c. The database and transcript remain plaintext.
- **Authenticated session gateway**: opaque, length-delimited credentials are resolved by an injected host callback into a validated principal ID; session CRUD, turn commits, and lease operations are then restricted to that principal in include/capri_session_host.h and src/capri_session_host.c. The gateway does not retain credentials or act as an identity provider.

The core validator is a native library component, not a wrapper around Python. Its current record contract is an initial port; exact field-by-field parity with every Python record edge case remains to be established.

## Contract and build

- Language baseline: GNU C11.
- Portability target: POSIX.1-2024 for host-facing system interfaces.
- CCEL links the C math library. Native session persistence requires SQLite 3.38+ with built-in JSON support and POSIX threads.
- Public interfaces are declared in include/; implementations are in src/.
- Bounded inputs are validated before processing. Allocation failures are explicit errors.
- Ownership is explicit: result objects returned by CCEL synthesis, prediction, and probe selection must be released with their matching *_free function. Session records returned by the native store own a heap-allocated messages_json field and must be released with capri_session_free().

```sh
make -C c test
make -C c clean all
```

## Migration policy

The requested end state is a genuinely C-based Capri runtime. Python and Rust remain in the repository as behavioral references until each native subsystem passes parity and security regression tests. No legacy implementation is removed as part of the initial port.

The migration covers, as one coordinated release:
1. CCEL research engine.
2. Core records, validation, ledger, and diagnostics.
3. Runtime and SQLite persistence.
4. Host tool execution, authorization, approvals, and recovery.
5. Memory, orchestration, and provider integrations.
6. Tests, documentation, build system, packaging, and CI.
7. Compilation, differential regression tests, sanitizer checks, and security verification.

The work is committed in small, reviewable units so each subsystem can be compiled, tested, and audited without weakening the overall one-go migration goal. Host identity and authorization remain outside model control; model output is untrusted data, never authority. Approval grants must be bound to the exact principal, tool, operation, argument digest, expiry, and single-use identifier. External side effects must not be blindly replayed after uncertain outcomes.

The C port is not complete merely because it compiles. Behavioral parity, malformed-input handling, memory ownership, overflow safety, persistence integrity, and security-boundary equivalence are release requirements.


## Native SQLite session milestone

The first C persistence slice now covers:

- Private existing parent directory (owner-only permissions), current-user-owned regular database file, no symlink or hard-link database aliases, and mode 0600.
- SQLite foreign keys, recursive triggers, trusted-schema restrictions, WAL, FULL synchronous commits, a busy timeout, and defensive mode where supported.
- Atomic creation of a session with an immutable principal-owner row.
- Principal-scoped reads and close operations that hide foreign and legacy-unowned sessions as not found.
- Legacy create/get/commit/close and turn-lease compatibility for unowned sessions only; these APIs cannot read or mutate principal-owned sessions.
- Strict JSON message-shape, role-order, UTF-8, per-message size, transcript-version, and history validation.
- Optimistic version-checked turn commits in BEGIN IMMEDIATE transactions.
- Durable claim, renew, and release operations for principal-bound turn leases, with active lease fencing on commits and corruption detection for malformed persisted lease timestamps/owner tokens.
- Per-handle thread serialization plus SQLite transaction locking across independent handles/processes.
- Fresh zero-length database files receive the complete schema atomically. Existing databases are validation-only on open: missing ownership/lease tables, required indexes, immutable-owner triggers, primary keys, or foreign keys are rejected before schema/journal-mode changes. Startup never silently recreates missing security objects. The Python SQLite session store enforces the same schema-object contract.
- New databases set SQLite user_version 1 and require the complete session-table CHECK constraints. Unversioned user_version 0 Python stores remain readable for compatibility with existing sessions; unknown schema versions and weakened version-1 constraints fail closed. Both C and Python validate the versioned schema profile.

This is an initial native session-store milestone, not parity with the complete Python SQLiteSessionStore. Native backup, integrity-check, and restore-to-new-path APIs are implemented: restore validates the source snapshot and publishes a new database without overwriting an existing destination or modifying the live store. This is intentionally not an in-place replacement API; host shutdown, selection of the recovery point, and switching the host to the restored path remain host-controlled. If backup/restore returns an I/O error after the no-overwrite publication link succeeds, a complete destination may already exist while temporary-file cleanup or parent-directory durability is uncertain. Callers must inspect the destination before retrying; do not blindly retry. The thin authenticated session gateway now composes the store with a host-supplied credential resolver. It validates resolver output and maps invalid/expired/revoked credentials to an authorization denial while preserving a distinct resolver-infrastructure error. Cross-principal and nonexistent session IDs both map to not-found. The gateway does not own the store or resolver context, and it does not add an identity provider, HTTP server, IPC, tool authorization, approvals, or provider execution. Full C HostRuntime integration remains outstanding. Transcripts are plaintext and require host-managed encryption, access control, retention, and backup protection. Principal IDs and lease-owner tokens now use Unicode code-point limits matching Python's character-count semantics. The native C API limits session IDs to 36 UTF-8 bytes (runtime-generated IDs are UUIDs), while Python's low-level store can address broader nonblank IDs; sessions created through either runtime use UUIDs. This is a documented low-level API boundary, not a claim of full edge-case parity. Backup and restore destination connections fail closed when busy-timeout or defensive-mode configuration fails.
