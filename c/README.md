# Capri C migration

This directory contains the native GNU C11 implementation being built toward a repository-wide Capri migration.

## Current native modules

- **CCEL research engine**: bounded grid transformations, synthesis, prediction, and probe selection in include/ccel.h and src/ccel.c.
- **Core evaluation records**: fixed-capacity record types and validation in include/capri_core.h and src/capri_core.c. Validation rejects malformed UTF-8 (including surrogate encodings), unterminated fixed fields, unknown controlled-vocabulary dimensions, invalid enum states, invalid timezone-aware RFC 3339 timestamps, inconsistent evaluator/evidence stages, and self-parent lineage.

The core validator is a native library component, not a wrapper around Python. Its current record contract is an initial port; exact field-by-field parity with every Python record edge case remains to be established.

## Contract and build

- Language baseline: GNU C11.
- Portability target: POSIX.1-2024 for host-facing system interfaces.
- CCEL currently links only the C math library. Core record validation has no external runtime dependency.
- Public interfaces are declared in include/; implementations are in src/.
- Bounded inputs are validated before processing. Allocation failures are explicit errors.
- Ownership is explicit: result objects returned by CCEL synthesis, prediction, and probe selection must be released with their matching *_free function.

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
