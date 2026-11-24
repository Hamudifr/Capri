# CCEL: Causal Compression and Experiment Loop

## Rust-first implementation

The canonical CCEL computational core is implemented in Rust on the isolated experiment branch for predictable performance, memory safety and future parallel search. The crate is rust/ccel-core, uses the standard library only, and follows the latest stable toolchain through rust-toolchain.toml. Python remains available for Capri orchestration and integrations, not as the canonical CCEL search engine. Python CI tests 3.11, 3.12, 3.13 and 3.15; the package floor remains 3.11.

A same-runner synthetic microbenchmark has now measured Rust against a Python reference. It demonstrates a speed advantage on that specific task only, not a general system-wide speedup. Rust is not itself an intelligence breakthrough.

## Purpose and current scope

A research-only prototype for a non-LLM cognitive component. It learns a bounded family of grid transformations from examples, predicts unseen inputs and selects an informative supplied probe. It currently preserves ambiguity only among equally shallow (minimum-depth) consistent programs; it can suppress longer consistent alternatives when a shorter program fits.

This is not AGI and is not claimed to outperform frontier LLMs generally. The current implementation is a small deterministic program-synthesis experiment.

## Core loop
1. Encode observations as validated grids.
2. Enumerate bounded candidate programs in a small transformation DSL.
3. Select minimum-depth consistent program families.
4. Preserve equally simple explanations rather than silently choosing one; deeper consistent explanations are currently excluded once a shallower family is found.
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
- Minimum-depth search can suppress longer but still consistent explanations. The v1.1 transfer pilot demonstrates a cross-depth ambiguity case where identity is returned confidently even though a deeper horizontal flip also fits the demonstration. This is a model-selection/uncertainty limitation, not evidence that more DSL operations are needed.
- This is a component experiment, not an autonomous agent or AGI.

## Next experiments
1. Compile and test exact Rust source on latest stable; resolve every compiler, format and Clippy finding.
2. Establish Python-vs-Rust parity tests on identical frozen inputs and edge cases.
3. Benchmark release builds with repeated runs and record hardware/toolchain; profile before optimizing.
4. Specify an explicit policy for cross-depth consistent hypotheses, including calibrated abstention or candidate retention without allowing duplicate programs to distort probe entropy.
5. Freeze a new v2 held-out transfer set after any algorithm change; do not tune on v1.1 and report it as held-out success.
6. Profile search and candidate growth after the ambiguity policy is specified.
7. Expand to object-centric or causal DSL operations only if broader transfer evidence shows the current spatial DSL is the limiting factor.
8. Compare against an LLM-only baseline only if a genuinely no-cost model is available.

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

Latest exact-head validation on PR head 7c5e4b08bfe21a7e1938f512a92fa60b288c8334: Rust workflow #43 (45475068727) passed rustfmt, Clippy, 16 unit tests, 1 compile-fail documentation test, release build, transfer evaluation and matched Rust/Python benchmark. The four-language benchmark workflow #15 (45475068842) passed. Python contract workflow #826 (45475068702) passed on Python 3.11, 3.12, 3.13 and 3.15; each version completed package install, CLI, Capri Doctor and the full test suite.

Transfer pilot v1.1: current synthesizer 10/11 total (8/8 unique, 1/2 ambiguity, 1/1 out-of-DSL rejection); single-operation baseline 9/11 (6/8 unique, 2/2 ambiguity, 1/1 rejection); identity baseline 1/11. All returned programs reproduce demonstrations. The known cross-depth ambiguity miss is recorded in benchmarks/ccel-transfer/README.md. This is a narrow synthetic pilot, not broad generalization evidence.
