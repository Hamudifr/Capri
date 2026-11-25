# R36: finite-game audit for P-vs-NP anticheckers

This directory contains a deliberately isolated research experiment. It is not imported by Capri runtime code and adds no runtime dependency.

## What is tested

- A finite zero-sum payoff LP for direct input-example games.
- The identity-matrix transcript counterexample: pointwise coverage alone can have value 1/M.
- Mutual information for deterministic finite response maps.
- A synthetic constant-round causal KPT game. Following an evading challenge at each stage must terminate at a package covering the entire finite challenge universe if the all-sequences KPT property holds.

## Run

Requires Python 3, NumPy, and SciPy.

    python -m pip install numpy scipy
    python minimax_audit.py
    python -m unittest -v

## Mathematical status

The KPT terminal-package lemma recorded in R36 is a derived adversarial-path argument from the exact KPT predicate in Pich–Santhanam, *Towards P != NP from Extended Frege lower bounds*, preprint §3. At each round, the KPT function outputs its package before the current circuit challenge. If no output search circuit is globally correct, choose a witness that falsifies the search branch. If the bounded validity predicate has a falsifying input, choose it; otherwise choose a circuit that evades the package unless the package already refutes every circuit. Continuing for all constant-many rounds would falsify every KPT disjunct, contradiction.

This is a nonuniform existence argument. It does not construct the history in deterministic polynomial time, prove P != NP, prove SAT not in P/poly, or provide a PV1/S1_2-provably correct selector.

The Python tests are finite sanity checks only. They do not prove the asymptotic KPT lemma.

## Sources

- Pich–Santhanam preprint: https://users.ox.ac.uk/~coml0742/papers/eopt.pdf
- Published version: https://doi.org/10.1145/3801091
- Chen–Li–Oliveira–Williams, APX1: https://arxiv.org/abs/2602.09302
