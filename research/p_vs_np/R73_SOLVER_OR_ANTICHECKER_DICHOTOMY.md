# R73: unconditional SAT-solver / anti-checker dichotomy

## Purpose

R73 removes the circuit-hardness assumption from the R72 one-step lemma by retaining the alternative that the majority tuple itself is a small SAT decision circuit. This yields an unconditional disjunction:

- a size-s^3 decision circuit for SAT_n exists; OR
- a polynomial-size labelled decision anti-checker exists against size-s circuits.

The disjunction has the same broad semantic shape as the two alternatives in Pich–Santhanam Theorem 7. It is not yet their feasible generator: no PV_1 function or S^1_2 proof is obtained, and no EF/P≠NP conclusion follows.

Primary sources:
- Jeřábek, *Approximate counting by hashing in bounded arithmetic*, https://users.math.cas.cz/~jerabek/papers/hash.pdf.
- Pich–Santhanam, *Towards P≠NP from Extended Frege Lower Bounds*, https://users.ox.ac.uk/~coml0742/papers/eopt.pdf, Theorem 7.

## 1. Unconditional one-step disjunction

Fix a current survivor set S of size-s decision circuits with Theorem 3.21 parameters a<=b. Use the same m,r,delta,kappa and q,A parameters as R72.

For every formula x, Theorem 3.17 gives:
F_x <=_delta q OR G_x <=_delta A.

There are two cases.

**Case 1: a shrink formula exists.**
There is an x with G_x <=_delta A. This is the successor step from R70/R72.

**Case 2: no shrink formula exists.**
Then F_x <=_delta q for every x. The R69 tagged-fibre incidence argument applies unchanged:
- the mixed-radix tag injection bounds each majority-error fibre B_x;
- Theorem 3.19 bounds the global incidence E;
- if every tuple had a majority error, the projection E -> S^r would have a PV_2(alpha) section;
- Corollary 3.11 and the Theorem 3.21 lower interval bound contradict this.

Therefore some tuple u has a majority circuit correct on every n-bit input. That majority circuit is a decision circuit D of size O(rs)=O(ns^2)<=s^3 for sufficiently large s>=Kn.

Thus the uniform one-step statement is:
D(n,s) OR exists x (G_x <=_delta A),
where D(n,s) means a size-s^3 circuit correctly decides SAT_n.

The small branch has the same disjunction. Deduplicate the exact survivor list and let N=|S|. If no formula has |G_x|<=floor(N/2), the majority of the distinct S circuits decides SAT. Otherwise the formula shrinks the survivor set by at least half.

## 2. Formula class

Relative to the SAT Sigma-b-1 oracle alpha:
- D(n,s) is Sigma-b-2(alpha): existentially choose the circuit D, then universally verify its answer on all n-bit inputs.
- exists x (G_x <=_delta A) is Sigma-b-2(alpha), since G_x is Sigma-b-1(alpha) and approximate size is Sigma-b-2(alpha).
- Their disjunction remains Sigma-b-2(alpha).

The one-step disjunction is therefore suitable for the same S^2_2(alpha)+BB-Sigma-b-3(alpha)+sWPHP(PV_2(alpha)) proof target as R72.

## 3. Iterating the disjunction

Use the R71 history invariant, but add a solver flag:
- If D(n,s) is produced at any stage, stop and retain D.
- Otherwise append the shrink formula and its hash certificate, update S_i, and continue.
- If no solver appears in T=4 ceil(log_2(M_0+1)) stages, the survivor set becomes empty and the history is an anti-checker.

The resulting statement has the form:
D(n,s) OR exists H Cert(n,s,H),
where Cert is the packed Sigma-b-2(alpha) history/anti-checker certificate from R71. The disjunction is Sigma-b-2(alpha), and its universal closure is a candidate forall-Sigma-b-2(alpha) theorem.

Theorem 2.1 with i=1 would then conserve it to T^1_2(alpha)+rWPHP(PV_2(alpha)); after substituting SAT for alpha, the target is T^2_2+rWPHP(PV_3).

## 4. Search-solver conversion

Pich–Santhanam's solver alternative is a search circuit, while D is a decision circuit. Under the standard length-preserving SAT self-reduction encoding, D can be converted into a search circuit:
- On input formula x, query D on the restriction x with the first variable fixed to 0.
- If D says satisfiable, retain 0; otherwise retain 1.
- Repeat for all variables, padding restricted formulas back to the fixed n-bit encoding length.
- Output the resulting assignment.

The constructed search circuit uses O(n) copies of D plus polynomial control logic, so its size is O(n s^3+poly(n)). The conversion from the description of D to the search-circuit description is a polynomial-time transformation. The length-preserving encoding/padding assumption must be stated explicitly in any formal theorem.

## 5. Relation to Pich–Santhanam and KPS

This is a meaningful structural improvement: the bounded-arithmetic statement now has the same broad output alternatives as Pich–Santhanam's Theorem 7:
1. a SAT search solver; or
2. a labelled decision anti-checker.

But the crucial constructive requirement is still absent. Pich–Santhanam require a polynomial-time function f and an S^1_2 proof that f outputs one of these alternatives. R73 provides only existential bounded-arithmetic existence in a stronger theory, with an adaptive witnessing extraction still to be analyzed.

A possible KPT direction is to extract a constant adaptive list of PV_3/FP^{Sigma_2} witnesses from the T^2_2+rWPHP(PV_3) statement. Under P=NP, PH collapses and FP^{Sigma_2}=FP, so such a list might become polynomial-time evaluable. This remains speculative. Pich–Santhanam §3 explicitly show that replacing their p-time generator by existential quantifiers yields a forall-Sigma-b-2 statement and KPT's constant adaptive list; later outputs depend on earlier challenges, so the list does not directly give short EF proofs. Their §1.1.3 also says the feasible-MinMax route they know needs polynomial-precision APC_1 counting. Our current route is APC_3 / Sigma-b-2 relative counting, so it is above that target and no APC_1 descent is established.

The exact gaps are:
- no KPT witnessing theorem has yet been verified for this exact T^2_2+rWPHP(PV_3) theory;
- even if PH collapse makes the extracted functions polynomial-time, adaptive-list dependence does not itself produce the S^1_2 correctness proof required by Pich–Santhanam;
- the APC_3 construction has not been reduced to APC_1 / PV_1;
- it does not supply the short EF transfer certificates required by KPS Theorem 11.

Do not claim that P=NP yields a contradiction from this disjunction.

## 6. Exact remaining work

1. Formalize the one-step D OR shrink statement in S^2_2(alpha)+BB-Sigma-b-3(alpha)+sWPHP(PV_2(alpha)).
2. Iterate it with the R71 packed invariant, including the solver-stop branch, and verify the final formula remains Sigma-b-2(alpha).
3. Apply Theorem 2.1 conservation only after the universal closure is proved to be forall-Sigma-b-2(alpha).
4. Verify the decision-to-search circuit conversion for the exact SAT encoding and its size.
5. Check KPT witnessing for T^2_2+rWPHP(PV_3), including adaptive-list complexity under P=NP.
6. Separately solve the S^1_2 proof and KPS EF-certificate gaps.

R73 is an unconditional existential solver-or-anti-checker dichotomy blueprint, not a feasible generator or a P≠NP proof.
