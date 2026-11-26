# R53: APC2 empty-fibre theorem and greedy iteration template

## Reorient the bad-pair count

Fix a nonempty survivor set S of search circuits, M=|S|, and r=2n+2. Let U=S^r. Let Q be the set of satisfying pairs (x,w) with R(x,w)=1. Define Z subset U x Q by (u,(x,w)) in Z iff every circuit in tuple u fails verification on x.

For a fixed q=(x,w), the fibre in U is F_x^r. Under the contrary assumption that every satisfiable x has more than half of S successful, |F_x|<M/2, hence |F_x^r|<= (M/2)^r. Since |Q|<=2^(2n), the ordinary counting bound is

|Z| <= 2^(2n)(M/2)^r = |U|/4.

## Direct APC2 empty-fibre route

Jeřábek's Theorem 3.20 is an empty-fibre averaging theorem: if X,Y,Z are bounded Sigma^b_1-definable, Z subset X x Y, and Z is approximately bounded by s*t, then either X is approximately bounded by s-1, or some x in X has a fibre of size at most floor(t(1+2epsilon)).

Apply it with X=U, Y=Q, and Z the bad incidence relation. Theorem 3.21 (approximate increasing enumeration) applied to U supplies lower/upper size parameters a<=b<=a(1+eta), with PV2 surjection/coretraction maps. In particular U is not approximately bounded by a-1, while its upper size is at most a(1+eta).

The R52 product/fibre bound and Theorem 3.19 (parameterized-family counting) give an APC2 upper bound for Z of the form Z <= a*theta, where theta is bounded by

(1+eta)(1+4epsilon)(1+epsilon)^(r+1)/4

up to the exact rounding conventions of the counting relations. Choose epsilon=eta=1/(1000r), r=2n+2. The losses remain close to 1, so theta<0.26. Apply Theorem 3.20 with outer epsilon0=1/100. Then theta(1+2epsilon0)<1, and the resulting fibre bound is floor(theta(1+2epsilon0))=0.

Therefore there is a tuple u in U with an empty bad fibre: for every satisfying pair (x,w), at least one circuit in u outputs a valid witness for x. A first-valid-output selector decides SAT. Under the explicit selector-size condition O(r(s+V(n)))<=s^3, this contradicts SAT_n notin SIZE(s^3).

This is a strong APC2 single-step proof route using existing theorems 3.19, 3.20, and 3.21, not a new APC2 MinMax theorem. The exact translation of all approximate-size relations and rounding remains to be written line by line.

## Greedy iteration template

Jeřábek's Theorem 4.2 formalizes the tournament principle in APC2 by repeatedly selecting a vertex that eliminates at least half the current survivor set. Our survivor process has the same abstract shape:
- S(H) consists of circuits solving every prior selected formula.
- The APC2 single-step lemma supplies a satisfiable (x,w) for which at most half of S(H) survives.
- Append (x,w) to H and continue.
- After O(log N)=O(s log(n+s)) stages, no circuit survives.

Theorem 4.2 supplies a close induction template, but the adaptation is not completed. The exact induction formula, Sigma^b_2/Pi^b_1 complexity reduction, relative-size invariant, and history encoding remain proof obligations.

## Search-to-decision bridge audit

A naive conversion takes a decision circuit C and builds a search circuit B_C using SAT self-reduction. The formulas queried by B_C depend on earlier answers of C; the full tree of possible prefixes can have 2^n nodes. A fixed polynomial-size decision anti-checker cannot simply include every possible query formula and its satisfying witness.

Thus the search anti-checker does not automatically yield Pich-Santhanam's fixed labelled decision anti-checker or KPS's transfer premise. A polynomial-size fixed query set, a nonadaptive reduction, or proof-system certification of the adaptive computation is still needed.

## Status

- R52 finite bad-pair inequality: proved.
- APC2 single-step empty-fibre route: strongly supported by exact existing theorems; line-by-line formula-class and parameter derivation remains.
- Full APC2 greedy iteration: template identified via Theorem 4.2; adaptation not completed.
- Deterministic polynomial-time anti-checker generator: open.
- Search-to-decision / Pich-Santhanam / KPS bridge: open.
- KPS short EF transfer proofs: open.
- P != NP: open. No separation proof obtained.

## Sources

- Jeřábek, *Bounded Arithmetic and Complexity*, Chapter II, Theorems 3.19, 3.20, 3.21, and 4.2: https://users.math.cas.cz/~jerabek/papers/dsc.pdf
- Jeřábek, *Approximate counting by hashing in bounded arithmetic*, JSL 74 (2009): https://doi.org/10.2178/jsl/1245158087
- Pich and Santhanam, *Towards P != NP from Extended Frege lower bounds*: https://arxiv.org/abs/2312.08163
- Khaniki, Pich, and Sokolov, *Efficient Adversaries*, CCC 2026: https://doi.org/10.4230/LIPIcs.CCC.2026.8
