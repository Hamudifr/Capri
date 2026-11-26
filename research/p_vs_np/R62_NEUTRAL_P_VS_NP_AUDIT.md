# R62: neutral P vs NP framing and correction of the R61 disjunctive route

## Project framing correction

The research question is P versus NP, not a presumed proof of P ≠ NP. Both outcomes remain live:
- P = NP: a deterministic polynomial-time algorithm for any NP-complete problem such as SAT.
- P ≠ NP: a proof that some NP language, equivalently SAT, has no deterministic polynomial-time decision algorithm.

No result in R1–R61 establishes either outcome. All future work must evaluate both directions and must not describe a proposed lower-bound route as evidence that P ≠ NP is true.

## R61 correction 1: formula complexity of the global search-circuit alternative

R61 defined

D(n,s) := ∃ circuit C of size ≤ L(n,s) ∀x,w
          [R_n(x,w)=1 → R_n(x,C(x))=1].

The universal quantification over all n-bit inputs and polynomial-length witnesses is a bounded, not sharply bounded, quantifier. In the standard Buss hierarchy, Σᵇ₀ consists of sharply bounded formulas; Σᵇ₁ permits bounded existential quantifiers and sharply bounded universal quantifiers; a bounded universal quantifier after the existential circuit gives a Σᵇ₂ pattern. Thus D is generally Σᵇ₂, not Σᵇ₁ as R61 stated.

The disjunction I(k)=D∨P(k) can still be Σᵇ₂ if P(k) is genuinely Σᵇ₂ and all parameters/encodings stay within the intended bounded language. This repairs the immediate formula-class mismatch, but it does not prove the induction.

Reference for the hierarchy definitions: Jalali and Ježil, “Feasibility of primality in bounded arithmetic,” Section 2.1, https://www.cambridge.org/core/journals/forum-of-mathematics-sigma/article/feasibility-of-primality-in-bounded-arithmetic/18A1BD004161C115D21E117A20B0B172 ; and Buss's original bounded-arithmetic framework.

## R61 correction 2: the disjunction is not itself a P vs NP resolution

The proposed local disjunction is of the form:

D_L(n,s) OR ∃q [S(Hq) has shrunk],

where D_L asserts a search circuit of size L(n,s) that succeeds on every satisfiable input.

If L is substantially larger than the survivor circuit bound s (for example L=s³ or another polynomial blow-up), this is a size trade-off, not a contradiction. The anti-checker branch rules out circuits in the survivor class, while the D branch permits a circuit in a potentially larger class. Both branches can coexist.

Even if D_L holds for every n with polynomial L, it yields nonuniform polynomial-size search circuits. That is weaker than a uniform deterministic polynomial-time SAT algorithm and does not by itself prove P=NP. Conversely, if one establishes that SAT has no polynomial-size search circuits, then SAT is not in P/poly, which would imply P≠NP. But the current argument does not establish that lower bound.

A correct future proof must state the exact circuit size on both sides, quantify over all n, and show that the anti-checker rules out every polynomial bound, not merely one selected size class.

## Decision/search equivalence audit

For SAT, decision-to-search can be obtained by self-reduction with polynomial overhead: use a decision procedure for restricted formulas to choose a satisfying assignment bit by bit. For nonuniform circuits, a family of polynomial-size decision circuits similarly gives polynomial-size search circuits by composing the decision circuits for the restricted instances, with explicit size accounting.

Search-to-decision is immediate from a total search circuit C and the verifier: decide SAT(x) by evaluating R(x,C(x)). For unsatisfiable x no witness can pass; for satisfiable x, the search guarantee ensures acceptance.

These reductions do not identify uniform P with nonuniform P/poly. The uniformity distinction must remain explicit.

## Balanced proof obligations

### Equality route
1. Construct a deterministic polynomial-time SAT algorithm, or a deterministic polynomial-time algorithm for another NP-complete language.
2. Prove correctness for all inputs and polynomial worst-case running time.
3. Derive P=NP through polynomial-time many-one reductions.

No such algorithm is currently supplied by this project.

### Separation route
1. Prove a superpolynomial lower bound for general deterministic circuits for SAT, or prove SAT is outside P by another valid route.
2. If using the search anti-checker, prove it excludes every polynomial-size search-circuit family and account for decision-to-search overhead.
3. Avoid relying on a finite family of hard instances, restricted circuit models, or nonuniform statements that do not imply the required uniform separation.
4. Address known barriers and explain exactly why the proof method escapes their hypotheses.

No such lower bound is currently supplied by this project.

### R59–R61 technical route
1. Complete the finite/APC₂ single-step argument with exact maps, error parameters, floors, and repair circuit.
2. Prove the local disjunction with exact and compatible circuit-size bounds.
3. Prove parameter propagation and cumulative errors.
4. Formalize the Σᵇ₂ length-induction instance and verify the precise conservation theorem hypotheses.
5. Determine what the final disjunction actually proves: a search circuit, a nonuniform anti-checker, or a uniform lower bound. Do not silently upgrade one to another.
6. Independently search for counterexamples to every lemma and for routes toward P=NP as well as P≠NP.

## Current conclusion

R61's Σᵇ₁ classification of D was incorrect; corrected to Σᵇ₂. The disjunctive induction remains a candidate only. Its size trade-off does not yet resolve P vs NP. The project is explicitly neutral. No proof of P=NP or P≠NP has been found.

## Sources
- Buss, bounded arithmetic hierarchy; see also the definitions in Jalali–Ježil (2026): https://www.cambridge.org/core/journals/forum-of-mathematics-sigma/article/feasibility-of-primality-in-bounded-arithmetic/18A1BD004161C115D21E117A20B0B172
- Jeřábek, Approximate counting by hashing in bounded arithmetic: https://users.math.cas.cz/~jerabek/papers/hash.pdf
- Jeřábek, Bounded Arithmetic and Complexity: https://users.math.cas.cz/~jerabek/papers/dsc.pdf

Status: correction and neutral research reset, not a P vs NP result.