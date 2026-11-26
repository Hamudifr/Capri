# R52: APC2 relative-counting route for the search survivor lemma

## New finite counting refinement

Fix a nonempty survivor set S of n-input, n-bit-output SAT search circuits of size at most s. Let M=|S| and let R(x,w) be the deterministic polynomial-time SAT witness verifier. For x, write G_x={C in S:R(x,C(x))=1} and F_x=S\\G_x.

Set r=2n+2 and U=S^r. Define
B={(x,w,(C_1,...,C_r)): x,w in {0,1}^n, R(x,w)=1, and for every j<r, R(x,C_j(x))=0}.

Assume every satisfiable x has |G_x|>M/2. Then for each fixed (x,w) with R(x,w)=1, the fiber of B has at most (M/2)^r tuples. There are at most 2^(2n) pairs (x,w), hence

|B| <= 2^(2n)(M/2)^r = M^r/4 = |U|/4.

If every tuple in U were bad for some satisfiable formula, projection (x,w,tuple)->tuple would be onto U, contradicting |B|<|U|. Thus some r-tuple from S has at least one valid witness output for every satisfiable formula.

A first-valid-output selector plus the deterministic verifier decides SAT. Its circuit size is O(r(s+V(n))), where V(n) is the verifier circuit size. Require explicit slack O((2n+2)(s+V(n)))<=s^3. Under SAT_n notin SIZE(s^3), the assumption fails: some satisfiable (x,w) has |G_x|<=M/2, so at least half the survivor circuits fail on x.

The extra n witness bits are important. This counts formula/witness pairs and avoids treating the NP predicate SAT(x) as if it were deterministic. It is the corrected bounded-arithmetic-friendly form of R51's finite sampling argument.

## Greedy consequence

At each stage select a satisfiable pair (x_i,w_i) defeating at least half the current survivor search circuits, then retain only circuits C with R(x_i,C(x_i))=1. The survivor set halves. Since log of the number of size-s circuit descriptions is O(s log(n+s)), after O(s log(n+s)) stages no circuit survives. The selected formula/witness pairs form a polynomial-size nonuniform search anti-checker whenever s is polynomial in n. Repeated formulas can be deduplicated by retaining the first selected witness.

## APC2 formalization candidate

The survivor predicate S(H), tuple set U=S(H)^r, and bad-pair set B are PV / Sigma^b_1 definable: histories are polynomial length and all checks use the deterministic verifier R. Including w in B avoids a coNP validity predicate.

APC1's additive-error counting is unsuitable for exponentially sparse survivor sets. Jeřábek's APC2 framework (T^1_2+sWPHP(PV2)) supplies multiplicative/relative approximate counting for bounded Sigma^b_1 sets, including sparse sets. The relevant tools in *Bounded Arithmetic and Complexity*, Chapter II, are:
- Corollary 3.18: products and unions of logarithmically many sets;
- Theorem 3.19: counting parameterized families / averaging;
- Corollary 3.11: monotonicity under PV2 surjections;
- Theorem 3.13: approximate union bounds;
- the approximate increasing-enumeration result for bounded Sigma^b_1 sets.

Intended formal proof:
1. Count U and each fiber F_x^r with relative error.
2. Apply Theorem 3.19 to the family indexed by (x,w), with empty fibers when R(x,w)=0, obtaining the upper bound corresponding to 2^(2n)(M/2)^r.
3. Use a sufficiently small inverse-polynomial error budget so the factor-1/4 gap survives.
4. If projection B->U were onto, combine approximate enumerations / surjections and the relative size bounds to contradict the strict constant-factor gap.
5. Conclude a tuple outside the projection, then iterate the halving lemma over the polynomial-length history.

This is a strong formalization candidate, not yet a completed APC2 proof. The exact formula classes, lower-bound comparison for U, surjection composition, and induction over histories still need a line-by-line derivation.

## What remains open

- APC2 proof of the parameterized-fiber inequality and projection contradiction.
- APC2 proof of the full polynomial-length greedy iteration.
- Witnessing/search complexity of the resulting anti-checker. APC2 provability does not imply a deterministic polynomial-time generator.
- Pich-Santhanam feasible anti-checker / KPT witnessing bridge.
- KPS short EF transfer proofs.
- P != NP. No separation proof obtained.

## Sources

- Jeřábek, *Approximate counting by hashing in bounded arithmetic*, JSL 74 (2009), 829-860: https://doi.org/10.2178/jsl/1245158087
- Jeřábek, *Bounded Arithmetic and Complexity* (2021), Chapter II: https://users.math.cas.cz/~jerabek/papers/dsc.pdf
- Pich and Santhanam, *Towards P != NP from Extended Frege lower bounds*: https://arxiv.org/abs/2312.08163
- Khaniki, Pich, and Sokolov, *Efficient Adversaries*, CCC 2026: https://doi.org/10.4230/LIPIcs.CCC.2026.8
