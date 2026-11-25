# Capri C migration

This directory is the first native-C port in the staged migration of Capri.

## Contract

- Language baseline: ISO C17.
- Portability target: POSIX.1-2024 for host-facing system interfaces; the CCEL library itself uses ISO C and the C math library only.
- No third-party runtime dependency.
- Public interfaces are declared in `include/ccel.h`; implementation is in `src/ccel.c`.
- Bounded inputs are validated before processing. Allocation failures are explicit errors.
- Ownership is explicit: result objects returned by synthesis, prediction, and probe selection must be released with their matching `*_free` function.

## Build and test

```sh
make -C c test
make -C c clean all
```

## Migration policy

The repository-wide conversion is incremental. This port does not replace or delete the existing Python or Rust implementation. The current Rust CCEL crate remains the behavioral reference until differential tests establish parity. Each subsystem is migrated behind a C API, receives equivalent regression/security tests, and is integrated only after exact-head validation. Python and Rust files remain in place during the transition so existing users and workflows are not broken.

Planned sequence:
1. CCEL bounded grid transformations, synthesis, prediction, and probe selection.
2. Core records, validation, ledger, and diagnostics.
3. Runtime primitives and persistence, retaining SQLite's stable C API.
4. Host orchestration, tool authorization, approvals, memory, provider adapters, and task recovery.
5. Port test contracts and benchmark harnesses; update build/CI and packaging.
6. Remove legacy language implementations only after feature parity, migration notes, and a deliberate release decision.

The C port is not considered complete merely because it compiles. Behavioral parity, malformed-input handling, memory ownership, overflow safety, and security-boundary equivalence are release requirements.
