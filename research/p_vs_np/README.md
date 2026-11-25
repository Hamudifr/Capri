# R36: finite-game audit for P-vs-NP anticheckers

This directory contains a deliberately isolated research experiment. It is not imported by Capri runtime code and adds no runtime dependency.

## What is tested

- A finite zero-sum payoff LP for direct input-example games.
- The identity-matrix transcript counterexample: pointwise coverage alone can have value 1/M.
- Mutual information for deterministic finite response maps.
- A synthetic constant-round causal KPT game.
- Exhaustive enumeration of all 16,384 three-round causal package strategies over a two-element challenge universe. Every strategy satisfying the all-sequences KPT property has a terminal package covering the whole universe.

## Run

Requires Python 3, NumPy, and SciPy.

    python -m pip install numpy scipy
    python minimax_audit.py
    python -m unittest -v

## Mathematical status

The KPT terminal-package lemma recorded in R36 is a derived adversarial-path unpacking of the exact KPT predicate in Pich–Santhanam, *Towards P != NP from Extended Frege lower bounds*, preprint §3. At each round, the KPT function outputs its package before the current circuit challenge. If no output search circuit is globally correct, choose a witness that falsifies the search branch. If the bounded validity predicate has a falsifying input, choose it; otherwise choose a circuit that evades the package unless the package already refutes every circuit. Continuing for all constant-many rounds would falsify every KPT disjunct, contradiction.

This is the Student–Teacher interpretation: the KPT functions are the Student; the previous circuits, formula/witness pairs, and auxiliary inputs are the Teacher's counterexamples. Ježil–Tsintsilidas (2026), Theorems 1.6–1.8, classify PV1-provable forall-exists-forall statements as constant-round, one-query-per-round Student–Teacher games. Their adaptivity/parallelism separations are general results and do not prove this SAT-specific selector impossible.

This is a nonuniform existence argument. It does not construct the history in deterministic polynomial time, prove P != NP, prove SAT not in P/poly, or provide a PV1/S1_2-provably correct selector.

The Python tests are finite sanity checks only. They do not prove the asymptotic KPT lemma.

## Sources

- Pich–Santhanam preprint: https://users.ox.ac.uk/~coml0742/papers/eopt.pdf
- Published version: https://doi.org/10.1145/3801091
- Ježil–Tsintsilidas, *Parallelism and Adaptivity in Student-Teacher Witnessing* (2026): https://arxiv.org/abs/2602.19934
- Chen–Li–Oliveira–Williams, APX1: https://arxiv.org/abs/2602.09302


# R37: OPS selector and verified Lean kernel

## Additional artifacts

- OPS_SELECTOR_ROUTE.md: OPS Lemma 4.1 / Theorem 1.4 hardness-magnification route, the fixed-family versus input-dependent anti-checker distinction, the APC1 relative-counting obstruction, and the soft-weight floor experiment.
- ops_selector_toy.py and test_ops_selector_toy.py: finite adaptive-selector example; 3 tests.
- soft_weights_floor_test.py and test_soft_weights_floor_test.py: finite counterexample to naive raw per-expert polynomial floors in multiplicative weights; 2 tests.
- formalization/: Lean 4.24.0 proof of the abstract finite causal-game terminal-package lemma. GitHub Actions run 45696083281 passed; axiom audit checked five declarations under the allowlist propext, Classical.choice, Quot.sound.

## R37 mathematical status

OPS gives a near-linear-in-truth-table-length selector under NP ⊆ Circuit[poly]. Its construction uses relative approximate counting of the circuits still consistent with the growing sample. This does not directly transfer to APC1's polynomial-precision additive counting, because late survivor sets can be exponentially sparse. A naive raw-weight floor also fails in a finite expert game: a polynomial floor destroys concentration, while a normalized floor is exponentially small per expert.

The Lean result formalizes only the abstract causal-game terminal lemma. It does not formalize the bounded-arithmetic KPT theorem, SAT-specific package predicates, the search-circuit branch, or EF translation. No P-vs-NP proof is claimed.

All five Python tests pass. Main remains untouched; the R37 work is isolated on this research branch.


# R40–R41: KPT selector collapse under P = NP

See [R40–R41 conditional KPT selector analysis](R40_KPT_COLLAPSE_CONDITIONAL.md).

The new note proves a conditional implication: if the existential SAT-antichecker statements are provable in PV1 (or, separately, APX1) for every sufficiently large fixed circuit exponent, then P != NP. The proof uses a constant-round KPT path selector in FP^NP; under P = NP, this selector becomes uniform polynomial time and yields the witness functions required by Pich–Santhanam Corollary 1.

This is not an unconditional P-vs-NP proof. The main open obligation remains proving the existential antichecker statement in the required bounded-arithmetic theory. The APX1 Refuter(Yao) theorem does not directly witness the higher-quantifier selector.


# R42: certificate-lifted canonical-pair MinMax

See [certificate-lifted canonical-pair MinMax analysis](R42_CERTIFICATE_LIFTED_MINMAX.md).

The key representation change is to use certified encodings z=(formula, label, witness-or-refutation) as the MinMax column domain. The payoff valid(z) AND (C(formula) != label) is a total PV predicate, unlike the direct SAT-disagreement payoff. Under canonical-pair hardness, majority amplification gives a constant game value and a polynomial-size certificate-carrying antichecker support.

This is a formalization route, not a proof of canonical-pair hardness or of the APC1/APX1 MinMax theorem. The universal antichecker proof and full KPS transfer implication remain open.
