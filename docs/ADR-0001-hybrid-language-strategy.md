# Architecture Decision: Hybrid Python, Rust, and C Strategy

- **Status:** Accepted
- **Date:** 2026-11-25
- **Scope:** Capri repository and future native components
- **Decision owner:** Project owner
- **Supersedes:** Any blanket instruction to rewrite the entire repository in C. It does not remove the owner's preference to use C where it is the better engineering choice.

## Decision

Capri will use a **pragmatic hybrid architecture**, not a repository-wide language rewrite.

1. **Python remains the application and orchestration layer for now.** It owns high-level workflows, provider adapters, Notion integration, host composition, task coordination, and the developer-facing package/API. These areas are integration-heavy and benefit from Python's existing implementation and ecosystem. Rewriting them in C would create a large compatibility, memory-safety, and maintenance burden without a demonstrated benefit.
2. **Rust is the preferred native implementation language for complex safety-sensitive or concurrent systems components when a native implementation is justified.** It is also the established language of the existing CCEL research crate. Preserve and extend that crate in Rust unless a measured, specific reason supports another language.
3. **C is a first-class option for small portable low-level components, stable C ABI surfaces, embedded/system interfaces, and code whose consumers require C interoperability.** Keep C modules narrow, dependency-light, explicit about ownership, and independently testable.
4. **Do not create a Python → Rust → C stack for one feature.** A component should normally have one native implementation and one clearly documented boundary. C ABI is an interoperability contract, not a reason to implement the same logic three times.
5. **No language is presumed faster.** Benchmark representative workloads on supported targets before moving code for performance. Correctness, security, portability, maintainability, and operational cost take precedence over language preference.

## Current observed baseline

At the decision revision:

- The installable product is a dependency-free Python package (`capri_core` and `capri_runtime`) requiring Python 3.11 or newer at decision time; the current support policy supersedes this with `>=3.15,<3.16`.
- The runtime includes orchestration, permissioned tool execution, durable SQLite stores, task execution, memory, Notion adapters, and provider integration.
- The repository contains a separate experimental Rust crate at `rust/ccel-core`; it is not the main Python runtime.
- No C source tree or C build target is present in the repository root. A separate C learning/benchmark lab exists in project records, but it is not the production runtime.
- The repository README explicitly describes Capri as an experimental Python runtime and distinguishes the Rust research component.
- The roadmap's next capability milestone is X7 durable goal planning/coordinator and budget enforcement. That is application behavior, not a reason to rewrite it in C.

These observations are not a claim that every Python module should remain Python forever. They establish the migration baseline.

## Target component boundaries

| Layer | Default language | Responsibilities | Move only when |
|---|---|---|---|
| Product/control plane | Python | Goal/task orchestration, provider and Notion adapters, host composition, workflow APIs | A separately measured operational constraint justifies a replacement |
| Native systems core | Rust | Complex stateful/concurrent primitives, memory-sensitive algorithms, security-sensitive native components | A native boundary has a clear contract and validated benefit |
| Portable ABI / low-level leaf | C | Small portable routines, OS/embedded interfaces, stable C ABI consumers | C portability or interoperability is materially useful |
| Research | Existing language | CCEL remains Rust; preserve standalone experiments | A scoped port is justified by correctness, portability, or measured results |

## Migration method: vertical slices, not translation

For each candidate component:

1. Identify a concrete bottleneck, safety boundary, portability requirement, or integration need. Do not select a component merely because it is written in Python.
2. Define a language-neutral contract: inputs/outputs, encoding, ownership, lifetime, bounds, error model, cancellation, thread-safety, versioning, and side-effect semantics.
3. Keep the existing implementation as the behavioral reference while building the replacement behind a narrow interface.
4. Add contract, boundary, malformed-input, failure-cleanup, and differential tests. Use fuzzing/property tests where proportionate.
5. Benchmark representative workloads with reproducible inputs, warmups, repeated runs, variance, compiler flags, and correctness checks.
6. Integrate behind an opt-in or reversible adapter. Compare outputs and operational behavior before changing the default.
7. Promote only when correctness and operational gates pass. Retain rollback and compatibility paths for at least one release cycle where feasible.
8. Remove the old implementation only after call sites, persisted formats, external consumers, and rollback requirements have been checked.

## FFI and process-boundary rules

- Prefer coarse-grained calls over chatty per-field FFI.
- Use explicit lengths for byte buffers; do not assume arbitrary data is NUL-terminated UTF-8.
- Document which side allocates and frees each object. Prefer caller-owned output buffers or paired allocator/free functions.
- Never expose Rust internal types, Python objects, or compiler-specific layouts as a public ABI.
- Version exported interfaces and validate sizes/versions before reading structs.
- Map errors to stable codes and bounded messages; never let Rust panics or foreign exceptions cross the boundary.
- Specify thread-safety and cancellation behavior. Do not hold the GIL or native locks across long-running callbacks without a measured reason.
- For a standalone worker process, use a versioned, bounded protocol and explicit timeouts, shutdown, and crash-recovery semantics.
- Avoid adding runtime dependencies or complicated native packaging until the selected boundary demonstrably needs them.

## Candidate order

1. **Do not delay X7 for a language rewrite.** Implement the durable goal contract, planner protocol, coordinator, and budget checks in the current Python architecture first. This is the fastest path to validated user-visible capability and keeps the existing API stable.
2. Add instrumentation and representative benchmarks to identify actual CPU, memory, serialization, and latency hotspots.
3. Evaluate one isolated native candidate at a time. Choose Rust for complex ownership/concurrency or security-sensitive logic; choose C for a small portable ABI/system leaf.
4. Consider native acceleration for bounded deterministic algorithms before moving provider, Notion, database orchestration, or general workflow code.
5. Expand only after measured gains exceed build, packaging, FFI, testing, and maintenance costs.

## Acceptance gates

A native migration is accepted only when:

- Existing public behavior and persisted-data compatibility are preserved or explicitly versioned.
- Differential and regression tests cover valid, invalid, boundary, and failure cases.
- Sanitizers/static analysis/fuzzing are applied where supported and proportionate.
- Supported platforms and compiler/toolchain versions are stated.
- Benchmarks demonstrate a material benefit for the target workload, or the portability/security/ABI requirement is documented.
- Build/install/packaging works in CI for the supported matrix.
- The old path can be restored without data loss during the migration window.

## Explicit non-goals

- Translating every Python file into C.
- Rewriting the existing Rust CCEL crate into C for uniformity.
- Introducing a microservice architecture or multiple native runtimes without an operational requirement.
- Claiming a speedup based on language reputation or a single synthetic benchmark.
- Breaking the zero-runtime-dependency Python package without a justified, reviewed packaging decision.

## Immediate next action

Continue with **X7.2 durable goal records and planner protocol in Python**, preserving the current host permission boundary and task engine. Add profiling/benchmark hooks only where they answer a concrete question. Revisit native implementation after an actual hotspot or ABI requirement is measured.
