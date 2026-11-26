# R61: disjunctive induction and the proof-theoretic transfer audit

## Objective

Repair the R60 obstacle: the previous induction treated the hardness premise SAT_n notin SIZE(s^3) as a standing assumption. Its arithmetic complexity is too high to simply carry it through a universal-Sigma^b_2 conservativity argument.

The new proposal internalizes the alternative in the induction invariant.

## 1. The global search-circuit alternative is Sigma^b_1

Let R_n(x,w) be the polynomial-time verifier for the SAT witness relation, with x and w ranging over the standard bounded input and witness domains. For a chosen explicit selector-size bound L(n,s), define

D(n,s) := exists search circuit C of size at most L(n,s) such that
          for all x,w, R_n(x,w)=1 implies R_n(x,C(x))=1.

The universal quantifiers are bounded and the matrix is PV. Thus D is Sigma^b_1.

If D holds, the circuit B(x):=R_n(x,C(x)) decides SAT_n: satisfiable x has some w with R_n(x,w), hence R_n(x,C(x)); unsatisfiable x has no accepting output. The decision circuit has size at most L(n,s)+V(n), where V(n) is the verifier circuit size. The exact selector/verifier overhead must be absorbed into the chosen L and hardness threshold.

This is preferable to using SAT_n in SIZE(t) directly as the induction alternative: the latter has a more complicated quantifier pattern because SAT membership itself contains an existential witness.

## 2. Disjunctive local step

Let H be a history and S(H) its PV-definable survivor set from R60. Let P(k) assert that some length-k history has S(H) approximately bounded by the current threshold B_k. P(k) is intended to be Sigma^b_2, since the approximate-size relation for a Sigma^b_1 set is Sigma^b_2 (Jeřábek, Chapter II, Definition 3.1 and Remark 3.2).

Restate the R59 single-step argument as the disjunction:

For every admissible H,
  D(n,s) OR
  exists satisfying pair q=(x,w) such that S(Hq) is approximately bounded
  by rho_0*a(H),

where rho_0 can be weakened to 0.35 after the exact error calculation.

Reason: if no such shrink pair exists, the R59 incidence/fibre argument yields the bounded tuple and (if needed) one repair circuit. The first-valid-output selector built from that tuple is a global search circuit of size at most L(n,s), establishing D. Otherwise a shrink pair exists.

This implication is not yet a completed formal derivation. It depends on finishing R59's exact nested error/floor proof and verifying the selector-size bound.

## 3. The disjunctive induction invariant

Define

I(k) := D(n,s) OR P(k).

Since D is Sigma^b_1 and P(k) is Sigma^b_2, I(k) is Sigma^b_2.

- Base: P(0) holds because the empty history's survivor set is contained in the explicit circuit-description universe of size N_s.
- Step: assume I(k). If D holds, I(k+1) holds immediately. Otherwise P(k) supplies a history H; apply the disjunctive local step. Its D branch establishes I(k+1), and its shrink branch extends H and establishes P(k+1), provided the R59 parameter-comparison lemma and cumulative error budget are formalized.
- Iterate for K=O(log N_s)=O(s log(n+s)) steps. For polynomial s(n), K is polynomial in n. Use the appropriate Sigma^b_2 length-induction instance with an explicit length parameter large enough to cover K; do not silently treat successor induction as available in T^1_2.

At the final stage choose K so that B_K<1. The approximate upper bound then forces S(H)=empty, using the zero-size clause in the approximate-size definition. Thus the final disjunction is:

D(n,s) OR exists polynomial-length history H such that
  for every size-s search circuit C, some pair (x_i,w_i) in H
  has R_n(x_i,C(x_i))=0.

The anti-checker alternative is a bounded universal condition over circuit descriptions and history indices, so the final disjunction is at most Sigma^b_2 (and plausibly Sigma^b_1 under the direct encoding). Its universal closure over n,s is therefore a candidate forall-Sigma^b_2 consequence.

## 4. Conservativity audit: exact theorem statement matters

Jeřábek, *Approximate counting by hashing in bounded arithmetic*, Theorem 2.1 states:

S^{i+1}_2(alpha) + BBSigma^b_{i+2}(alpha) + sWPHP(PV_{i+1}(alpha))
is forall-Sigma^b_{i+1}(alpha)-conservative over
T^i_2(alpha) + rWPHP(PV_{i+1}(alpha)).

For i=1, the stated theorem includes the BB Sigma^b_3(alpha) instance. The earlier R60 shorthand mentioning only S^2_2+sWPHP was incomplete as a statement of the conservation theorem's hypotheses. The next audit must establish exactly how this BB Sigma^b_3 instance is supplied in the application, whether it is derivable in the relevant proof base, or whether a different conservation route is needed. Do not claim the transfer to APC2 until this is settled.

The source also states rWPHP(f,g) follows from either sWPHP(f) or iWPHP(g), so the rWPHP part is compatible with sWPHP once the other hypotheses are in place. This does not by itself discharge the BB Sigma^b_3 requirement.

## 5. What this fixes, and what it does not

Potentially fixed:
- The high-complexity hardness assumption no longer needs to sit outside the induction as an untracked antecedent.
- The global search-circuit alternative can be kept as a Sigma^b_1 disjunct.
- The combined induction predicate remains Sigma^b_2, matching the conservativity target.

Still open:
1. Complete R59's single-step proof with exact parameters, floors, formula classes, and PV_2 maps.
2. Prove the local disjunction D OR shrink inside the stronger theory.
3. Prove the parameter comparison a(H) <= B_k(1+delta) with exact composition maps and rWPHP instances.
4. Give a fully explicit cumulative error schedule and K bound.
5. Formalize the length-induction range and history encodings.
6. Resolve the BB Sigma^b_3 hypothesis in Jeřábek Theorem 2.1 and show the transfer is genuinely available over APC2.
7. Check selector circuit size and the resulting SAT decision circuit size with explicit verifier overhead.
8. Return to the missing decision/search and KPS proof-certificate transfer interface.

No deterministic generator, KPS EF certificates, or P != NP proof has been obtained.

## Sources

- Jeřábek, *Approximate counting by hashing in bounded arithmetic*, Theorem 2.1, Definition 3.1, Remark 3.2, Theorems 3.8, 3.17-3.21: https://users.math.cas.cz/~jerabek/papers/hash.pdf
- Jeřábek, *Bounded Arithmetic and Complexity*, Chapter II: https://users.math.cas.cz/~jerabek/papers/dsc.pdf
- Jeřábek, *Dual weak pigeonhole principle, Boolean complexity, and derandomization* (for the definition and provability context of sharply bounded collection): https://users.math.cas.cz/~jerabek/papers/wphp.pdf

## Status

R61 is a proof-theoretic route refinement and audit note, not a proved APC2 anti-checker theorem. The disjunctive induction is promising but conditional on the explicit obligations above.

### R61 addendum: source precedent for the conservation step

A nuance from the primary paper: Jeřábek's proof of Theorem 3.20 explicitly says that its argument formalizes in S²₂(α)+sWPHP(PV₂(α)), that the resulting statement is ∀Σᵇ₂, and that Theorem 2.1 transfers it to T¹₂(α)+rWPHP(PV₂(α)). Thus the BBΣᵇ₃ clause in the general statement of Theorem 2.1 should not be treated as an automatic fatal obstruction. The source's own application indicates that the needed auxiliary condition is available in that specific formalization or through an equivalent application of the theorem. For the new disjunctive induction, we must reproduce that precise formal route rather than merely cite S²₂ in isolation.

Primary source: https://users.math.cas.cz/~jerabek/papers/hash.pdf (proof of Theorem 3.20 and Theorem 2.1).
