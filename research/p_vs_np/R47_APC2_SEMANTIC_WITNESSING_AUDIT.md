# R47: APC2 semantic witnessing audit

**Status:** Source audit. No exact APC2 selector theorem for the SAT antichecker statement is established here.

## 1. Theory distinction

In CKKO21's two-sorted notation:

- VAPC1 is VPV1 plus dWPHP for VPV1 functions.
- VAPC2 is the corresponding extension of VPV2 by dWPHP for VPV2 functions.
- The first-order APC2 presentation used in R45 is T2^1 + sWPHP(PV2). Preserve the exact axiom scheme and witnessing formulation when moving between presentations.

CKKO21 explicitly explains that dWPHP axioms are existential, so the resulting theory is not universal and ordinary KPT does not apply directly. Their VAPC1 treatment first builds a conservative universal extension with new Skolem function symbols for dWPHP witnesses, then obtains a **semantic** KPT witnessing statement. The resulting student is randomized; the new Skolem functions are not ordinary polynomial-time functions. The VAPC2 section is the relevant higher-oracle analogue.

## 2. Source-supported result

CKKO21 Theorem 1.5(4), under the paper's stated formalizations, gives the VAPC2 boundary:

```
either VAPC2 proves SAT in io-SIZE[poly],
or ZPP^NP is not contained in io-SIZE_SAT[n^k].
```

In particular, VAPC2 does not prove the corresponding ZPP^NP circuit upper bound under the paper's hypotheses.

This confirms a randomized NP-oracle / LEARN-uniform character to VAPC2 witnessing. It does **not** by itself establish the exact KPT disjunction for Pich–Santhanam's S_K, nor the deterministic FP^NP path selector used in R40/R43.

## 3. Conditional collapse under P=NP: plausible bridge, exact proof required

There is a plausible way the APC2 conditional route could survive:

1. Assume P=NP. Then PH=P, so NP-oracle computations and fixed-level Sigma_j^P/Pi_j^P counterexample predicates collapse to P.
2. If the VAPC2 semantic witnessing protocol for the exact S_K statement has polynomially many random bits, polynomially many rounds, and a polynomial-hierarchy-verifiable success condition, its oracle calls and output verification become polynomial-time under P=NP.
3. A randomized search protocol with inverse-polynomial success and a P-decidable success predicate can be amplified; since BPP=P under P=NP, the amplified search can be derandomized.
4. The resulting deterministic selector could then be fed into the R40 argument, yielding the Pich–Santhanam witness functions and the contradiction with P=NP.

This is **not yet a theorem**. Required checks:

- exact VAPC2 semantic KPT theorem and quantifier form;
- whether S_K lies in its permitted formula class;
- constant or polynomial number of adaptive EQ/counterexample rounds;
- success probability and whether a successful package/search circuit can be verified in a fixed PH level;
- consistent assignment of all relevant Skolem-function values in the semantic model;
- preservation of the all-histories guarantee after derandomization.

BPP=P under P=NP is not by itself enough. The exact randomized protocol and its success predicate must first be shown to fit the collapse.

## 4. Correction to R45

Replace the compressed phrase “subject to the standard Skolemized-KPT extension for VAPC2” with:

> **Conditional APC2 route (not closed):** If the exact VAPC2 semantic witnessing theorem applies to S_K, and if its randomized NP-oracle Student–Teacher protocol can be derandomized and its counterexample oracle simulated in P under P=NP, then the R40 contradiction argument would imply P != NP from APC2 proofs of S_K for all sufficiently large K. The required formula-class and semantic-witnessing checks remain open.

Do not state APC2 proves S_K for all K implies P != NP as established until these checks are completed. R40 (PV1) and R43 (APC1) conditional implications are separate and unaffected.

## 5. Status

- **Verified source boundary:** dWPHP extensions are not universal; ordinary KPT does not apply directly. CKKO21 uses conservative extensions and semantic randomized witnessing.
- **Verified source boundary:** VAPC2 is the FP^NP/dWPHP level, and CKKO21 Theorem 1.5(4) gives the stated ZPP^NP circuit-upper-bound unprovability consequence.
- **Plausible but open:** under P=NP, a suitable VAPC2 randomized semantic selector may collapse to P.
- **Not established:** exact semantic KPT theorem for S_K, deterministic selector, APC2 conditional P != NP theorem.
- **Still open:** APC2 proof of the validity-constrained finite MinMax statement and its translation to S_K.

## Sources

- Carmosino, Kabanets, Kolokolova, Oliveira, *LEARN-Uniform Circuit Lower Bounds and Provability in Bounded Arithmetic* (2021), especially §2.5 and §4.5, Theorem 1.5(4): https://www.dcs.warwick.ac.uk/~igorcarb/documents/papers/CKKO21.pdf
- Jeřábek, *Approximate Counting by Hashing in Bounded Arithmetic*: https://users.math.cas.cz/~jerabek/papers/hash.pdf
- Pich–Santhanam, *Towards P != NP from Extended Frege Lower Bounds*: https://doi.org/10.1145/3801091
