# CCEL held-out transfer pilot

Dataset: **CCEL-TRANSFER-v1**  
Fixture and executable scorer: `rust/ccel-core/examples/transfer_eval.rs`

## Purpose and scope

Measure whether the current bounded synthesizer can infer a spatial transformation from demonstrations and apply it to a different query grid. This is a small, deterministic, synthetic transfer pilot over the eight symmetries expressible by the current five-operation DSL, plus ambiguity and out-of-DSL rejection cases.

The ten fixed cases are:
- Five single-operation transformations: clockwise rotation, counter-clockwise rotation, horizontal flip, vertical flip, transpose.
- Two composed transformations: 180-degree rotation and anti-diagonal reflection.
- One deliberately ambiguous one-demonstration case.
- One multi-demonstration case where the ambiguity is resolved.
- One unsupported cell-wise increment case that should be rejected.

All demonstration grids, demonstration outputs, query grids, expected query outputs, intended solution descriptions and expected outcome classes are literal fixture data in the Rust example. The fixtures were authored specifically for this pilot and are not sampled from the implementation's unit tests. No fixture is changed after observing a result; any correction or expansion becomes a new dataset version.

## Pre-registered scoring

The scorer and criteria are fixed before the first evaluation run:

1. **Unique task:** pass only if the synthesizer returns exactly one distinct query output and it equals the expected output.
2. **Ambiguous task:** pass only if the synthesizer returns more than one distinct query output and the expected output is among them. Returning one unjustifiably confident output fails.
3. **Out-of-DSL task:** pass only if no consistent program is returned.
4. Every returned program must reproduce every demonstration exactly.
5. Report raw per-case results, total outcome success, unique-task success, ambiguity preservation, rejection accuracy, candidate program counts, minimum depth, and elapsed time.

Denominators are fixed at 10 total cases: 8 unique-output cases, 1 ambiguity case, and 1 rejection case.

## Baselines and system under test

- **Identity baseline:** predicts the query unchanged only when identity fits every demonstration.
- **Single-operation baseline:** independently enumerates identity plus each of the five individual DSL operations and preserves all distinct consistent query outputs.
- **Current synthesizer:** the production Rust `synthesize` and `predict` functions, with maximum depth 3 and the standard candidate budget.

All methods receive identical demonstrations and query inputs. The single-operation baseline is deliberately shallower; it tests whether composition adds value. The current synthesizer is not modified for this evaluation.

## Reproduction

Run from the repository root:

```sh
cargo run --manifest-path rust/ccel-core/Cargo.toml --example transfer_eval --release
```

The Rust quality workflow runs this command on every relevant PR update. The executable exits non-zero if a pre-registered expected outcome fails or a returned program contradicts its demonstrations.

## Limitations

This is a diagnostic pilot, not a statistically powered benchmark and not evidence of general ARC, object-centric, causal, natural-image, or real-world reasoning ability. The cases are synthetic and concentrated on a narrow transformation family. One deterministic run gives no confidence interval. Runtime is runner-dependent. A passing result establishes only behavior on these ten fixed cases; failure analysis and broader, separately versioned task families are required before making wider generalization claims.
