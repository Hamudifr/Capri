# Capri Polyglot Performance Architecture and Migration Plan

- **Status:** Proposed implementation plan; complements accepted ADR-0001.
- **Date:** 2026-11-25
- **Base:** `main` at `5de569a3ed061f3eda7509420ef74a8aabb3ce89`
- **Intent:** Optimize the complete system, not maximize the number of native-language files.

## Executive decision

Capri should evolve into a **Python + Rust system with a deliberately small C interoperability layer**. This is a whole-system optimization strategy, not a blanket source translation.

- **Python is the product/control plane:** orchestration, provider and Notion adapters, host composition, developer API, policy composition, and workflows whose dominant cost is network or database I/O.
- **Rust is the native systems core:** bounded CPU-heavy algorithms, complex concurrent components, memory-sensitive data processing, and isolated components where ownership and concurrency safety matter.
- **C is the portability/ABI leaf:** small routines that must interoperate with C consumers, embedded targets, operating-system APIs, or an existing C ecosystem. C is not the default language for new Capri business logic.
- **SQLite remains SQLite:** it is already a mature native C database engine. Reimplementing its callers in C does not remove disk synchronization, query planning, lock contention, or transaction costs.
- **No C++ layer is planned by default.** Introduce another implementation language only for a concrete dependency or platform requirement.

The target is fewer expensive operations, shorter critical paths, bounded memory, predictable tail latency, strong isolation, portable builds, and low maintenance cost. Native code is a means, not the goal.

## Evidence from the current repository

At the current mainline checkpoint:

- The installable product is a zero-runtime-dependency Python package supporting Python 3.11+.
- `capri_runtime/` contains orchestration, tools, approvals, tasks, goals, memory, Notion and provider adapters, host composition, and SQLite stores.
- `rust/ccel-core/` is an existing standard-library-only Rust research core. It is not yet the main runtime.
- C, C++, Rust, and Python benchmark implementations already exist under `benchmarks/four-language/`.
- The four-language benchmark verifies identical output checksums on a single-threaded Conway's Game of Life workload. Across three CI batches, Rust's median kernel time was 9.169 ms, C 9.707 ms, C++ 10.000 ms, and the straightforward Python loop 2,043.594 ms. This supports native implementation for suitable CPU-bound kernels only; it does not rank whole applications or establish Rust's universal superiority.
- The first runtime baseline measured goal create/read at 3,604.917 µs median, task create/read at 2,696.935 µs, task claim at 1,717.520 µs, tool validation/dispatch at 55.453 µs, and tool-free orchestration at 14.217 µs. These are single shared-runner observations, not stable cross-machine targets.
- The current runtime benchmark explicitly says the first baseline does not justify a Rust/C migration.

**Interpretation:** the largest measured latencies are in persistence operations, not Python dispatch. The next optimization experiment should investigate SQLite query/transaction/connection behavior and end-to-end workload profiles before considering native rewrites. A faster language around an I/O-bound operation is unlikely to materially improve it.

## Target architecture

```text
                Host / CLI / future UI
                         |
                Python product API
                         |
       +-----------------+------------------+
       |                 |                  |
  Goal/task flow    Provider adapters   Notion/connectors
       |                 |                  |
       +----------- Policy / authority -----+
                         |
             Stable domain contracts
                         |
        +----------------+----------------+
        |                                 |
  Python fallback                 Optional native modules
        |                                 |
        +----------------+----------------+
                         |
               Rust native core
             (bounded, measured kernels)
                         |
           Narrow versioned C ABI where
             portability/interoperability
                    requires it
                         |
              OS / SQLite / host APIs
```

The diagram is logical, not a mandate to route every operation through FFI. Most calls should remain entirely in Python or entirely in one native component. Avoid chatty cross-language calls.

## Component placement

| Component family | Default | Optimization direction |
|---|---|---|
| Provider adapters, HTTP, Notion REST | Python | Connection reuse where safe, strict timeouts, bounded retries, payload limits, pagination correctness |
| Goal/task orchestration and policy composition | Python initially | Reduce duplicate reads/writes, clarify state transitions, measure scheduling/lock contention |
| SQLite stores and backups | Python API + SQLite C engine | Profile query plans, indexes, transaction boundaries, connection lifecycle, WAL/checkpoint policy, fsync and backup costs |
| Pure validation and bounded parsing | Python initially; Rust only if measured | Differential tests, explicit bounds, fuzzing, avoid redundant validation |
| Knowledge graph and memory retrieval | Python initially | Corpus-size benchmarks, ranking quality/latency trade-offs, cache hit/miss metrics, bounded traversal |
| CCEL and future CPU-heavy search | Rust | Preserve the existing Rust crate; profile allocations, candidate growth, data layout, parallelism and algorithmic complexity |
| Platform/embedded adapters and C consumers | C where required | Minimal portable leaf modules with explicit ownership and a stable ABI |
| CLI and developer experience | Python | Keep installation simple and retain a pure-Python fallback |

Security-sensitive policy must remain enforced by the trusted host. Moving code to Rust or C does not itself create authorization, tenant isolation, sandboxing, or correct policy.

## Optimization sequence

### Phase 0 — Measurement foundation

1. Keep the current runtime benchmark as a smoke baseline, but add representative multi-operation workloads and workload sizes.
2. Record CPU time, wall time, p50/p95/p99, throughput, peak RSS, allocation/GC pressure where available, database bytes, lock waits, cache hit rates, and startup/import time.
3. Profile the slowest end-to-end flows before selecting a component.
4. Use repeated runs on the same hardware class and preserve raw results and environment metadata.
5. Keep performance thresholds separate from correctness/security gates.

### Phase 1 — Optimize the existing architecture first

Prioritize persistence because it dominates the current measured baseline:

- Inspect SQLite query plans and indexes for goal creation/read, task creation/read, and task claiming.
- Separate SQL execution time from transaction commit and synchronization time.
- Check whether repeated serialization, validation, or full-record materialization is avoidable without weakening invariants.
- Evaluate transaction batching only where atomicity and crash semantics remain unchanged.
- Measure connection reuse and lock contention under concurrent principals/workers.
- Evaluate WAL/checkpoint and synchronous settings only against the documented durability threat model. Never weaken durability merely to improve a benchmark.
- Add workload-size and concurrency sweeps; do not infer scalability from one-operation microbenchmarks.

Then optimize pure Python paths through algorithmic improvements, bounded caching, reduced copying, and fewer round trips. These changes often outperform a language rewrite while preserving portability.

### Phase 2 — Native candidates, one vertical slice at a time

A component is eligible only when profiling shows it is a material CPU or memory hotspot, or a documented portability/ABI requirement exists.

Candidate order:

1. Profile and improve the existing Rust CCEL core. It already has a native boundary and measured workload evidence.
2. Evaluate bounded deterministic algorithms only after representative profiling. Memory ranking, validation, serialization, and graph traversal are candidates to measure, not pre-approved ports.
3. Consider Rust for complex concurrent or stateful native components where a stable contract can isolate ownership.
4. Use C for a small low-level leaf only when C interoperability, embedded support, OS APIs, or portability provides a real advantage.
5. Do not rewrite HTTP, provider, Notion, task policy, or orchestration code merely to make the repository "native."

For each candidate, keep the Python implementation as the behavioral oracle and fallback until the native path is proven.

### Phase 3 — Stable boundary and packaging

- Define versioned, language-neutral inputs/outputs, explicit lengths, bounds, ownership, lifetime, errors, cancellation, thread-safety, and side-effect rules.
- Prefer coarse-grained calls. Never cross FFI once per field or tiny item.
- If Rust is loaded in-process, expose a narrow C ABI or a deliberately selected Python extension interface. Choose only after packaging and performance experiments.
- For C ABI: version structures, validate struct sizes, use explicit buffer lengths, document allocator ownership, return stable error codes, and prevent panics/exceptions crossing the boundary.
- Avoid returning pointers to temporary memory or exposing compiler-specific layouts.
- Keep native acceleration optional initially. If the extension is unavailable or incompatible, fall back to the Python implementation.
- Build reproducible wheels/artifacts for supported OS/CPU targets before making native code mandatory.

### Phase 4 — Promotion and retirement

Promote a native implementation only after exact behavior, differential tests, malformed-input tests, fuzz/property tests where appropriate, concurrency/failure tests, supported-platform builds, and end-to-end benchmarks pass.

Retire the Python reference only after:
- all callers and persisted formats are accounted for;
- the fallback period has elapsed;
- rollback is tested;
- package installation works on the full supported matrix; and
- the owner-visible compatibility impact is documented.

## Quantitative promotion gates

These are proposed engineering gates, not measured claims:

- Correctness: 100% differential agreement on the locked regression corpus, with explicit expected differences versioned.
- Security: no new trust bypass; bounded input and memory; sanitizer/fuzz coverage appropriate to the module.
- Performance: target at least 2x improvement in the isolated hot operation **and** at least 10% improvement in a representative end-to-end workload, or document a compelling memory/portability/security benefit.
- Tail latency: no unexplained p95/p99 regression in adjacent workflows.
- Resource use: measure RSS, allocations, startup and packaging overhead; do not trade a small CPU win for a large memory or operational penalty.
- Reliability: crash, cancellation, timeout, concurrency and rollback tests pass.
- Maintenance: one canonical implementation per component; no duplicate Python/Rust/C business logic after promotion.

A candidate that fails the gates remains experimental. A benchmark win on a toy kernel is not sufficient.

## Non-negotiable invariants

- Preserve the current host authorization boundary and principal scoping.
- Never let model output or retrieved content become authority.
- Preserve uncertain-side-effect quarantine and idempotency semantics.
- Preserve SQLite backup integrity, atomic publication, privacy permissions, and recovery behavior.
- Preserve the zero-runtime-dependency Python installation until an explicit packaging decision is justified.
- Do not silently change persisted formats, cryptographic boundaries, or durability guarantees.
- No paid tooling, hosted runners, services, or subscriptions without explicit owner approval.

## Immediate work package

1. Add a persistence-focused benchmark that separates SQL, transaction commit, and serialization costs for the existing goal/task workloads.
2. Add concurrent task-claim and principal-isolation workloads with correctness assertions.
3. Profile representative runtime paths and identify the top CPU, I/O, and allocation costs.
4. Optimize the highest-impact SQLite/query/algorithmic bottleneck in Python first.
5. Re-run the same workload and publish before/after distributions.
6. Select one native vertical slice only if the measured end-to-end gain clears the promotion gates.

## Governance and execution status

This plan is a design artifact, not a completed migration. No production runtime component has been ported by this document. The current Actions hold recorded in CAP-192 prohibits triggering or rerunning GitHub Actions before 2026-12-01; any PR/CI sequence must recheck that restriction and runner/billing constraints after that date.

The accepted [ADR-0001](ADR-0001-hybrid-language-strategy.md) remains the language-placement decision. This plan expands its whole-system optimization and migration procedure without superseding its safety gates.
