# CCEL: Causal Compression and Experiment Loop

## Purpose

A research-only prototype for a non-LLM cognitive core. It learns a bounded family of grid transformations from examples, preserves ambiguity between consistent programs, predicts unseen inputs, and selects an informative probe from a supplied set.

This is not AGI and is not claimed to outperform frontier LLMs generally. The current implementation is a tiny deterministic program-synthesis experiment.

## Core loop

1. Encode observations as validated grids.
2. Enumerate bounded candidate programs in a small transformation DSL.
3. Select the minimum-depth consistent program family.
4. Preserve all equally simple explanations instead of silently choosing one.
5. Predict each model's output for a new input.
6. Select a safe supplied probe with maximum predictive entropy.
7. Compare the observed result with predictions and rerun synthesis with the new evidence.

## Current DSL

- Rotate clockwise / counter-clockwise
- Flip horizontally / vertically
- Transpose

Search is bounded by depth and candidate count. Inputs are limited to 30x30 grids with integer cells 0..9. The implementation has no external dependencies, no network access, no model API calls, and no side effects.

## Important limitations

- This is finite hypothesis search, not a general world model.
- It does not yet learn causal relations, object concepts, language, temporal dynamics, or actions in a real environment.
- Probe selection only ranks candidate grids supplied by the caller; it does not autonomously generate a complete experiment space.
- The DSL and its priors are hand-designed, so generalization is limited by the representation.
- It is a component experiment, not an autonomous agent or an AGI.

## Next experiments

1. Add a compositional object-centric DSL with color remapping, connected components, object movement, and conditional rules.
2. Add bounded candidate generation for experiments and compare active versus passive example acquisition.
3. Evaluate on a frozen held-out synthetic suite with systematic composition and distractor shifts.
4. Compare against simple heuristics and, only if a no-cost model is available, an LLM-only baseline under matched information and compute budgets.
5. Add causal intervention and temporal transition tasks only after the basic program learner passes transfer tests.
