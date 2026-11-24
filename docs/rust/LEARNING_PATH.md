# Rust mastery track for Capri

**Toolchain policy:** latest stable Rust, selected by the stable channel. No obsolete compiler pin. Use the latest stable edition, currently Rust 2024. Before material development record rustc version, Cargo version, target triple and date.

**Goal:** build durable, demonstrated expertise across Rust, its standard library, tooling, performance, systems programming and production engineering. “100%” is an ambition, not a claim that a finite checklist exhausts a living language. Preserve explanations, runnable examples, exercises, corrections, benchmark results and review questions. Reading is not mastery.

## Curriculum

### 0. Computing foundations
Binary and data representation; memory; stack and heap; pointers and alignment; CPU caches; processes and threads; files and sockets; compilation and linking; algorithms, complexity and invariants.

### 1. Toolchain and Cargo
rustup channels, components and targets; rustc; Cargo packages, crates, workspaces and modules; manifests, lockfiles, features and profiles; build scripts; publishing; rustfmt, Clippy, rustdoc, rust-analyzer; compiler diagnostics; reproducible and offline builds; cross-compilation.

### 2. Language fundamentals
Bindings, mutability, constants, shadowing, scalar and compound types, inference, functions, expressions, blocks, control flow, loops, ranges, structs, enums, methods, associated functions, pattern matching, destructuring, modules, visibility and documentation.

### 3. Ownership and memory
Ownership, moves, Copy, Clone, borrowing, references, mutable aliasing, slices, String and str, lifetimes and elision, Drop and RAII; Box, Rc, Arc, Cell, RefCell, Weak, Pin and Cow; interior mutability, cycles, allocation and stack/heap tradeoffs.

### 4. Error handling and API design
Option, Result, question-mark operator, custom errors, source chains, panic/unwind/abort; invariants, newtypes, builders, typestate, sealed traits; parsing, validation, integer overflow, bounds and resource limits.

### 5. Generics and traits
Traits and implementations, coherence and orphan rules, blanket implementations, generic bounds, associated types/constants, default methods, supertraits, static/dynamic dispatch, trait objects, vtables, lifetimes in traits, HRTBs, GATs, impl Trait, Send, Sync, Unpin, variance and PhantomData.

### 6. Iterators and standard library
Iterator adapters and consumers, IntoIterator, Vec, VecDeque, slices, arrays, maps, sets, heaps, BTree structures, hashing, sorting, strings, formatting, parsing, Unicode, bytes, paths, filesystem, environment, time, Read/Write/Seek, buffered I/O and channels.

### 7. Concurrency and parallelism
Threads and scoped threads, channels, Mutex, RwLock, Condvar, atomics and memory orderings; Send/Sync; data races and logical races; deadlocks and poisoning; work stealing, bounded queues, backpressure, cancellation, Rayon, deterministic parallel search, contention, NUMA and cache locality.

### 8. Async Rust
Future, Pin, Context, Waker and poll; async/await state machines; executors and runtimes; structured concurrency, cancellation, timeouts, async I/O, streams, backpressure, task supervision and graceful shutdown. Understand when async is inappropriate for CPU-bound work.

### 9. Unsafe Rust and soundness
Raw pointers, unsafe blocks/functions/traits, unions, MaybeUninit, ManuallyDrop, aliasing, provenance, validity, initialization, alignment, data races and undefined behavior; safety contracts, encapsulation, safe abstractions, Miri, sanitizers and fuzzing. A compiling program is not proof of soundness.

### 10. Macros and metaprogramming
macro_rules, matchers, hygiene and repetition; procedural derive, attribute and function-like macros; TokenStream; syn/quote ecosystem; const generics, const evaluation, build scripts, diagnostics and compile-time tradeoffs.

### 11. Systems and interoperability
C ABI, extern blocks, repr(C), bindgen/cbindgen, callbacks, ownership across FFI, static/dynamic libraries, ABI stability, plugins, shared memory, mmap, processes, signals, sockets, Unix/Windows APIs, embedded and no_std, alloc, interrupts, WebAssembly and cross-compilation.

### 12. Performance and compute
Release profiles, LTO, codegen units, PGO, LLVM IR and assembly; statistically sound benchmarks, perf, flamegraphs, sampling and tracing; allocation profiling, cache locality, branch prediction, SIMD, vectorization, data-oriented design, arenas, slabs, zero-copy and batching; GPU interoperability when justified. Compare against correct baselines on identical hardware and budgets.

### 13. Production and security
Dependency minimization, lockfiles, supply-chain review, cargo-audit/cargo-deny, reproducible builds, SBOMs, signing, release automation, semantic versioning, observability, tracing, metrics, crash diagnostics, input validation, resource exhaustion, DoS resistance, secret handling, fault injection, fuzzing, threat models and rollback.

### 14. Compiler and language internals
Parsing, HIR/MIR concepts, borrow checking, trait solving, monomorphization, LLVM optimization, code generation, linkers, incremental compilation, editions, RFCs, stabilization and nightly feature gates. Distinguish stable guarantees from implementation details.

### 15. Specializations
Databases and storage engines; parsers and compilers; game engines and simulation; distributed systems and networking; cryptography; scientific computing and numerical stability; ML inference kernels and tensor layouts; real-time systems, embedded firmware, robotics and control. Specialize according to measured Capri workloads.

## Learning and retention protocol
For each topic:
1. Read current official documentation or a primary source.
2. Explain it in original words and list prerequisites.
3. Build a minimal runnable example in this repository.
4. Solve an exercise without copying the answer.
5. Add normal, edge and failure tests.
6. Explain tradeoffs and common failure modes.
7. Record corrections and unresolved questions.
8. Revisit with retrieval questions; update notes when the language/toolchain changes.

Track each topic as **unseen, studied, practiced, tested, retained, or needs revision**. Only mark retained after successful explanation and a delayed retrieval check. Store concise durable knowledge, not unfiltered dumps.

## Primary references
- Rust Book: https://doc.rust-lang.org/book/
- Rust Reference: https://doc.rust-lang.org/reference/
- Standard Library: https://doc.rust-lang.org/std/
- Cargo Book: https://doc.rust-lang.org/cargo/
- Rust by Example: https://doc.rust-lang.org/rust-by-example/
- Rustonomicon: https://doc.rust-lang.org/nomicon/
- Unstable Book: https://doc.rust-lang.org/unstable-book/
- Rust Forge: https://forge.rust-lang.org/
- Release announcements: https://blog.rust-lang.org/releases/

## Current status
- Latest-stable toolchain policy and curriculum: recorded.
- CCEL Rust core: initial code drafted; compile, tests, lint, benchmarks and parity checks pending.
- Demonstrated mastery: not yet assessed.


## Learning progress — first applied systems lesson (2026-11-24)

**Topic:** contiguous memory layout, Vec, slices, ownership and data-oriented design.

- Status: tested; delayed retrieval review still required before marking retained.
- Applied to CCEL Grid: replace Vec<Vec<u8>> with one row-major Vec<u8>, plus height and width.
- Index formula: row * width + column. A row is borrowed as a slice; no row-copy is needed for read-only views.
- Why: nested vectors require separate row allocations and indirection. A flat buffer gives one allocation, contiguous storage, predictable indexing and improved cache locality.
- Safety: Grid owns its buffer; callers receive shared slices. Transformations build a separate output buffer, avoiding aliasing and preserving safe Rust.
- Evidence: the same 20x20 rotation-synthesis benchmark improved from 183,717 ops/s (nested rows) to 749,805 ops/s (flat buffer) across separate CI runs, an indicative ~4.1x change that still needs a paired A/B test.
- Rust CI: 13 unit tests, Clippy, formatting, release build and benchmark passed on Rust 1.100.0.
- Python CI: all 493 existing Capri tests passed on Python 3.15.2.

Next learning topics: ownership/moves/borrowing in detail; lifetimes; slice APIs; iterator design; then profiling and parallel search.
