# R45: APC2 validity-constrained MinMax for the full SAT function

**Status:** New finite-game construction and formalization route. APC2 MinMax proof and VAPC2 KPT details remain open; no P-vs-NP proof is claimed.

## 1. Valid SAT-label pairs

Define
[
V_n(x,y):=orall y'in{0,1}^n,[SAT_n(x,y')	o SAT_n(x,y)].
]
Equivalently,
[
V_n(x,y)iff SAT_n(x,y)lor UNSAT_n(x).
]

Thus:
- if x is satisfiable, V_n(x,y) holds exactly for satisfying assignments y;
- if x is unsatisfiable, V_n(x,y) holds for every y;
- every formula x has at least one valid y.

This is a certificate-free way to represent the true SAT decision bit. Every valid pair (x,y) has SAT_n(x,y)=SAT(x).

The predicate V_n is coNP: its negation has a satisfying assignment y' with SAT_n(x,y')=1 and SAT_n(x,y)=0.

## 2. Finite game

For a size-s decision circuit C, define
[
M(C,(x,y)):=V_n(x,y)land[SAT_n(x,y)
e C(x)].
]
Set M=0 on invalid pairs. Since V_n is coNP and the rest is polynomial-time, M is coNP, hence Δ₂^P / P^NP.

The game has:
- rows: all size-s decision circuits C on n-bit formulas;
- columns: all pairs (x,y)∈{0,1}^{2n};
- payoff: M(C,(x,y)).

Invalid columns have payoff zero for every row. Any positive-value maximin strategy can be restricted to valid columns by deleting invalid mass and renormalizing.

## 3. Constant-error minimax lemma

Assume SAT_n has no size-s³ decision circuit and s≥c n.

**Claim:** the game value is at least (1/2-1/sqrt{s}).

Proof:
1. Suppose the value were smaller. By finite minimax, there is a distribution ν over size-s circuits with expected error below (1/2-1/sqrt{s}) on every valid pair.
2. Draw M₀=Kns circuits independently from ν and take their majority D.
3. For each fixed valid pair, Hoeffding bounds the majority error by exp(-Ω(Kn)).
4. Choose K large enough and union-bound over at most 2^{2n} pairs. A fixed majority circuit is correct on every valid pair.
5. Every formula x has at least one valid y, and all valid y carry the true SAT label. Hence D(x)=SAT(x) for all x, contradicting the size-s³ lower bound.
6. The majority circuit has size O(M₀s)=O(ns²)≤s³ after parameter padding.

Thus the value is at least (1/2-1/sqrt{s}), at least 1/4 for s≥16.

Sampling t=O(s log s) valid pairs from an optimal maximin distribution and union-bounding over at most 2^{O(s log s)} size-s circuits gives a polynomial-size support that defeats every size-s decision circuit.

Project the support to formulas and keep one valid y_x per formula. All valid y for the same x have the same SAT bit, so deduplication preserves every circuit mismatch. The resulting A,Y package satisfies
[
orall xin A orall y',[SAT_n(x,y')	o SAT_n(x,y_x)]
]
and every size-s circuit disagrees with SAT_n(x,y_x) somewhere on A.

## 4. Why APC2 is the natural theory

APC2 = T₂¹+sWPHP(PV₂), where PV₂ represents FP^NP functions. Jeřábek's approximate-counting framework gives additive approximate counting for Δ₂^P / P^NP-definable sets. Both V_n and M(C,(x,y)) are coNP, hence within that class.

This avoids the two limitations of earlier routes:
- Unlike direct uniform SAT(x) payoff counting in APC1, the validity/payoff predicate is within APC2's Δ₂ counting reach.
- Unlike R42's certificate-expanded canonical pair, it covers all unsatisfiable formulas, including those without short P-refutations.

**Important:** Counting Δ₂ sets does not automatically prove finite MinMax. The exact polynomial-precision MinMax/strategy-existence theorem for this succinct coNP matrix remains open.

## 5. Conditional KPT collapse route

A plausible extension of R43 is available for APC2, but the exact VAPC2 KPT theorem must be checked before treating it as closed.

APC2 has a universal conservative extension based on VPV₂ (FP^NP functions) and witnessed dWPHP(PV₂). Skolemizing dWPHP introduces functions h_F returning values outside the range of an FP^NP map F.

The missing-range relation for h_F is Π₂^P: a counterexample to “v is outside the range” consists of an input u and an NP-oracle computation witnessing F(u)=v. Under P=NP, PH collapses, so this relation becomes polynomial-time decidable. Since dWPHP guarantees a missing value, search-to-decision yields a uniform FP function h_F.

The KPT terms for the universal extension are built from FP^NP functions and h_F symbols. Under P=NP these become FP. Subject to verifying the Skolemized-KPT extension for VAPC₂, an APC2 proof of S_K for every sufficiently large exponent would therefore give the R40 path selector in P and imply P≠NP via Pich–Santhanam Corollary 1.

This is a derived conditional route, not a quoted theorem from CKKO21.

## 6. Exact remaining work

1. Formalize the validity predicate V_n and the game payoff M in the chosen APC2 language.
2. Prove the approximate MinMax theorem for the exponentially large game using only APC2's polynomial-precision counting.
3. Formalize the sampling/union-bound support construction and the projection/deduplication to A,Y.
4. Verify the resulting formula is exactly the required ∀Σ₂^b SAT-antichecker statement S_K.
5. Prove the witnessed-KPT extension for VAPC₂, then complete the conditional P=NP collapse argument.

## Sources

- Jeřábek, *Approximate Counting by Hashing in Bounded Arithmetic*, Theorem 2.3: https://users.math.cas.cz/~jerabek/papers/hash.pdf
- Jeřábek, *Approximate Counting in Bounded Arithmetic*: https://users.math.cas.cz/~jerabek/papers/apx.pdf
- Cook–Kolokolova–Krajíček–Oliveira, *LEARN-Uniform Circuit Lower Bounds and Provability in Bounded Arithmetic*, §4.5 / Theorem 4.14: https://dcs.warwick.ac.uk/~igorcarb/documents/papers/CKKO21.pdf
- Pich–Santhanam, *Towards P != NP from Extended Frege lower bounds*, Theorem 7 / Corollary 1: https://arxiv.org/abs/2312.08163
