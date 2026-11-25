# Lean formalization kernel

This package formalizes the abstract finite causal-game lemma used in the R36 KPT analysis.

- `Wins Q n h`: every challenge either is covered at the current history or leaves a winning continuation.
- `wins_has_terminal`: a finite winning game has a reachable history whose package covers all challenges.

The theorem uses Lean 4.24.0 and only Lean's standard library (`Std`) plus classical choice. GitHub Actions build and axiom audit passed on 2026-11-25 (run 45696083281). The audit checked five declarations under the allowlist `propext`, `Classical.choice`, and `Quot.sound`.

Scope limitation: this does **not** formalize the original bounded-arithmetic KPT theorem, SAT-specific package predicates, the search-circuit branch, or the translation to Extended Frege. It is a verified abstract kernel, not a P vs NP proof.
