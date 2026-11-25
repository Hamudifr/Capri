# Lean formalization kernel

This package formalizes the abstract finite causal-game lemma used in the R36 KPT analysis.

- `Wins Q n h`: every challenge either is covered at the current history or leaves a winning continuation.
- `wins_has_terminal`: a finite winning game has a reachable history whose package covers all challenges.

The theorem uses only Lean's standard library (`Std`) and classical choice. It does **not** formalize the original bounded-arithmetic KPT theorem, SAT-specific package predicates, proof-system assumptions, or an EF lower bound.

CI uses `leanprover/lean-action@v1` with no Mathlib dependency. The source is not considered verified until the GitHub Actions build passes.
