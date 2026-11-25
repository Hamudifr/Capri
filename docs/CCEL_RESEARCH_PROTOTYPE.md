# CCEL: Causal Compression and Experiment Loop

## Rust implementation

The canonical CCEL computational core is implemented in Rust in `rust/ccel-core` and integrated into `main` by PR #143 (squash commit `08dbb878941501ca9cdc02afceb1ba68db3877b1`). It uses the standard library only and follows the latest stable toolchain through `rust-toolchain.toml`. Python remains available for Capri orchestration and integrations, not as the canonical CCEL search engine. The current support policy targets Python 3.15.x only; earlier multi-version runs are historical verification, not ongoing support.

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
1. Specify an explicit policy for cross-depth consistent hypotheses, including calibrated abstention or candidate retention without allowing duplicate programs to distort probe entropy.
2. Freeze a new v2 held-out transfer set after any algorithm change; do not tune on v1.1 and report it as held-out success.
3. Profile search and candidate growth after the ambiguity policy is specified.
4. Expand to object-centric or causal DSL operations only if broader transfer evidence shows the current spatial DSL is the limiting factor.
5. Compare against an LLM-only baseline only if a genuinely no-cost model is available.

## Historical initial implementation and benchmark — 2026-11-24

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

## Integrated mainline checkpoint — 2026-11-24

- PR #143 was marked ready and squash-merged. Merge commit: `08dbb878941501ca9cdc02afceb1ba68db3877b1`; main readback confirms this exact SHA.
- Exact pre-merge head: `0d2ae79471622827d7fbc409f9e3afeb0ac369c1`.
- Post-merge Rust CI #47 (run 45476320233) passed: rustfmt, Clippy with warnings denied, 16 unit tests, 1 compile-fail documentation test, release build, CCEL transfer v1.1 and matched Rust/Python synthesis benchmark.
- Post-merge Python CI #837 (run 45476320184) passed on Python 3.11, 3.12, 3.13 and 3.15; each version installed the package, passed CLI and Capri Doctor, and ran all 493 tests.
- Exact pre-merge four-language benchmark #24 (run 45475772478) passed with shared checksum `61ba73df36b48d49`: C 7.540 ms, C++ 6.953 ms, Rust 5.184 ms, Python 1,365.941 ms for the same Game of Life kernel. These are single-runner medians, not a universal language ranking.
- Matched CCEL synthesis microbenchmark on the same runner: Rust 12.877806 ms per 10,000 rounds (776,529.79 ops/s); Python 0.929720 s (10,755.93 ops/s), about 72.2x on this one task. This is a narrow implementation benchmark, not a general system speedup claim.
- Transfer pilot v1.1: current synthesizer 10/11 total (8/8 unique, 1/2 ambiguity, 1/1 out-of-DSL rejection); single-operation baseline 9/11 (6/8 unique, 2/2 ambiguity, 1/1 rejection); identity baseline 1/11. All returned programs reproduce demonstrations. The cross-depth ambiguity miss is documented in `benchmarks/ccel-transfer/README.md`. This is a narrow synthetic diagnostic, not broad generalization evidence.
- Historical compatibility floor at that checkpoint was `>=3.11`; the current support policy supersedes it with `>=3.15,<3.16`. The expanded 3.15 matrix exposed and fixed a nondeterministic test fixture that sometimes failed to alter a signature's final hex digit.
