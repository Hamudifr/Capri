# CCEL: Causal Compression and Experiment Loop

## Rust-first implementation

The canonical CCEL computational core is implemented in Rust on the isolated experiment branch for predictable performance, memory safety and future parallel search. The crate is rust/ccel-core, uses the standard library only, and follows the latest stable toolchain through rust-toolchain.toml. Python remains available for Capri orchestration and integrations, not as the canonical CCEL search engine. Python CI selects 3.x to follow the latest stable release; the package floor is 3.15.

A same-runner synthetic microbenchmark has now measured Rust against a Python reference. It demonstrates a speed advantage on that specific task only, not a general system-wide speedup. Rust is not itself an intelligence breakthrough.

## Purpose and current scope

A research-only prototype for a non-LLM cognitive component. It learns a bounded family of grid transformations from examples, preserves ambiguity between consistent programs, predicts unseen inputs and selects an informative supplied probe.

This is not AGI and is not claimed to outperform frontier LLMs generally. The current implementation is a small deterministic program-synthesis experiment.

## Core loop
1. Encode observations as validated grids.
2. Enumerate bounded candidate programs in a small transformation DSL.
3. Select minimum-depth consistent program families.
4. Preserve equally simple explanations rather than silently choosing one.
5. Predict each model's output for a new input.
6. Select a safe supplied probe with maximum predictive entropy.
7. Compare observation with predictions and rerun synthesis.

## Current DSL
- Rotate clockwise / counter-clockwise
- Flip horizontally / vertically
- Transpose

Search is bounded by depth and candidate count. Inputs are limited to 30x30 grids with integer cells 0..9. The Rust core has no third-party crate dependencies, network access, model API calls or side effects.

## Limitations
- Finite hypothesis search, not a general world model.
- No learned causal relations, object concepts, language, temporal dynamics or real-world actions yet.
- Probe selection ranks caller-supplied safe probes; it does not autonomously generate the full experiment space.
- Hand-designed DSL and priors constrain generalization.
- This is a component experiment, not an autonomous agent or AGI.

## Next experiments
1. Compile and test exact Rust source on latest stable; resolve every compiler, format and Clippy finding.
2. Establish Python-vs-Rust parity tests on identical frozen inputs and edge cases.
3. Benchmark release builds with repeated runs and record hardware/toolchain; profile before optimizing.
4. Add compositional object-centric DSL: connected components, recoloring, object movement, conditional rules.
5. Generate bounded safe experiments and compare active versus passive acquisition.
6. Evaluate on frozen held-out synthetic tasks with composition and distractor shifts.
7. Compare against simple heuristics and an LLM-only baseline only if a genuinely no-cost model is available.
8. Add causal interventions and temporal transition tasks only after transfer tests pass.

## Verified initial implementation and benchmark — 2026-11-24

- Rust stable compiler: 1.100.0; Cargo 1.100.0; target x86_64-unknown-linux-gnu; Ubuntu 26.04.1 GitHub-hosted runner.
- Rust core uses a flat contiguous row-major Vec<u8> buffer with explicit height and width. This avoids one allocation per row and improves locality. Row views are borrowed slices; transformations allocate a single output buffer.
- Rust CI on exact branch head: rustfmt check, Clippy with warnings denied, 13 unit tests, release build, and matched benchmark all passed.
- Python CI on exact branch head: Python 3.15.2, package installation, CLI, Capri Doctor, and all 493 existing tests passed.
- Matched synthetic task: learn a 20x20 grid clockwise rotation using the five-operation DSL, depth limit 1, 10,000 synthesis rounds, 100 warmups, median of 5 samples, same Ubuntu x86_64 runner.
- Latest exact-head Rust release: 13.451898 ms per 10,000 rounds = 743,389.52 operations/second.
- Latest exact-head Python 3.15.2 reference: 0.966640 s per 10,000 rounds = 10,345.11 operations/second.
- Observed ratio: about 71.9x faster for this specific microbenchmark. Recent exact-head runs ranged from about 71.9x to 77.4x; run-to-run variation shows why the ratio must not be generalized.
- The first nested-Vec Rust version measured 183,717 ops/s; the flat-buffer version measured 749,805 ops/s in a later run, an indicative ~4.1x difference across separate CI runs, not a controlled paired A/B. The flat layout remains the better design hypothesis, but paired profiling is still needed.
- These are microbenchmark results, not a general system speedup claim. They do not measure end-to-end agent reasoning, large-scale memory pressure, multi-core scaling, or generalization.

Latest exact-head CI: Rust #19 (45460261275), 14 tests passed; Python #808 (45460261361), 493 tests passed on Python 3.15.2. PR #143 remains draft and unmerged.
