# CCEL held-out transfer pilot

Dataset: **CCEL-TRANSFER-v1.1**  
Executable fixture and scorer: `rust/ccel-core/examples/transfer_eval.rs`

## Purpose and scope

Measure whether the current bounded synthesizer can infer a spatial transformation from demonstrations and apply it to a different query grid. This is a small, deterministic, synthetic transfer pilot over the eight symmetries expressible by the current five-operation DSL, plus ambiguity and out-of-DSL rejection cases.

The 11 fixed cases comprise:
- Five single-operation transformations: clockwise rotation, counter-clockwise rotation, horizontal flip, vertical flip, transpose.
- Two composed transformations: 180-degree rotation and anti-diagonal reflection.
- Two ambiguity probes: same-depth ambiguity and cross-depth ambiguity.
- One multi-demonstration case that resolves ambiguity.
- One unsupported cell-wise increment case that should be rejected.

All demonstration grids, demonstration outputs, query grids, expected query outputs, intended solution descriptions and expected outcome classes are literal fixture data in the Rust example. The original ten-case v1 pilot was authored specifically for this task and not sampled from the implementation's unit tests. Version 1.1 adds a targeted cross-depth ambiguity diagnostic after v1 exposed that same-depth ambiguity was tested but shortest-program ambiguity was not. No synthesizer algorithm change was made between v1 and v1.1. Because the added case was motivated by the v1 source/result review, v1.1 is an adversarial diagnostic extension, not a blind independent test set.

## Pre-registered scoring

1. **Unique task:** pass only if the synthesizer returns exactly one distinct query output and it equals the expected output.
2. **Ambiguous task:** pass only if the synthesizer returns more than one distinct query output and the expected output is among them. Returning one unjustifiably confident output fails.
3. **Out-of-DSL task:** pass only if no consistent program is returned.
4. Every returned program must reproduce every demonstration exactly.
5. Report raw per-case results, total outcome success, unique-task success, ambiguity preservation, rejection accuracy, candidate program counts, minimum depth, and elapsed time.

Denominators are fixed at 11 total cases: 8 unique-output cases, 2 ambiguity cases, and 1 rejection case.

## Baselines and system under test

- **Identity baseline:** predicts the query unchanged only when identity fits every demonstration.
- **Single-operation baseline:** independently enumerates identity plus each of the five individual DSL operations and preserves all distinct consistent query outputs.
- **Current synthesizer:** production Rust `synthesize` and `predict`, maximum depth 3 and the standard candidate budget.

All methods receive identical demonstrations and query inputs. The single-operation baseline is deliberately shallower; it tests whether composition adds value. The current synthesizer is not modified for this evaluation.

## Results

The original v1 run passed its ten registered outcomes (8 unique, 1 same-depth ambiguity, 1 rejection). The v1.1 extension exposes an important limitation in the current synthesizer:

- Current synthesizer: **10/11 total**, with **8/8 unique**, **1/2 ambiguity**, and **1/1 rejection**.
- Single-operation baseline: **9/11 total**, with **6/8 unique**, **2/2 ambiguity**, and **1/1 rejection**.
- Identity baseline: **1/11 total**, with **0/8 unique**, **0/2 ambiguity**, and **1/1 rejection**.
- Returned current programs reproduce all demonstrations exactly.

The two composed tasks are solved at depth 2, where the single-operation baseline fails. However, the cross-depth ambiguity probe fails: its one demonstration is horizontally symmetric, so both identity (depth 0) and horizontal flip (depth 1) fit. The synthesizer stops at the minimum consistent depth and returns only identity. It therefore predicts the query unchanged instead of preserving both plausible outputs. The single-operation baseline returns multiple candidates and correctly marks the query as ambiguous.

This is not evidence that the DSL needs more operations. It is a model-selection/ambiguity-policy limitation: shortest-program preference currently suppresses longer consistent explanations. Keep this failure visible; do not tune against v1.1 and then call it held-out success. Any algorithm correction should be evaluated on a separately versioned v2 set with new cases.

## Reproduction

Run from the repository root:

```sh
cargo run --manifest-path rust/ccel-core/Cargo.toml --example transfer_eval --release
```

The Rust quality workflow runs this command on every relevant PR update. It checks program validity, baseline counts, unique-task performance and out-of-DSL rejection. The known cross-depth ambiguity miss remains visible in the per-case output and total score; it is not silently converted into a pass.

## Limitations

This is a diagnostic pilot, not a statistically powered benchmark and not evidence of general ARC, object-centric, causal, natural-image, or real-world reasoning ability. The cases are synthetic and concentrated on a narrow transformation family. One deterministic run gives no confidence interval. Runtime is runner-dependent. A passing CI job establishes only that the evaluator ran and its locked expectations held on these fixed cases; the 10/11 task score is the actual observed capability result, not 100% generalization.
