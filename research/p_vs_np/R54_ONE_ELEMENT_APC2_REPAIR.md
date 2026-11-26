# R54: one-element repair of the APC2 empty-fibre gap

## Correction to R53

R53 overstated the direct conclusion of Jeřábek Theorem 3.20. The theorem says that if X,Y,Z are bounded Sigma^b_1 definable, Z subset X x Y, and Z is approximately bounded by s*t, then either X is approximately bounded by s-1 or some x in X has a fibre of size at most floor(t(1+2epsilon)). With integer t=1 and small epsilon, this is at most one, not zero.

## Finite combinatorial repair

Let S be a nonempty survivor set of size-s SAT search circuits, M=|S|. Put r=2n+2 and U=S^r. Let Q be all satisfying formula/witness pairs (x,w) with R(x,w)=1. Define Z subset U x Q so (u,(x,w)) belongs to Z exactly when every circuit in tuple u fails verifier R on x.

Assume every satisfiable x has more than M/2 successful circuits in S. Then for each q=(x,w), the number of tuples in U that fail on x is at most (M/2)^r. There are at most 2^(2n) pairs in Q, so

|Z| <= 2^(2n)(M/2)^r = |U|/4.

Theorem 3.19 is the natural APC2 averaging tool for turning the per-q fibre bounds into a global approximate incidence bound. Theorem 3.20 can then be applied with first coordinate U and t=1, provided the exact approximate-size parameters are set so Z is bounded by s0 and U is not bounded by s0-1. The constant 1/4 gap leaves room to choose s0 around 0.3 to 0.5 of |U|, after relative-error losses.

The theorem then yields a tuple u with at most one bad satisfying pair (x,w). If there is no such pair, u already covers all satisfiable formulas. If exactly one pair remains, all circuits in u fail on its formula x. By the contrary assumption, some C* in S succeeds on x. Append C*. The enlarged tuple has no bad satisfying pair: it solves x via C*, and the original tuple solved every other satisfiable formula.

Thus a tuple of at most r+1=2n+3 search circuits covers every satisfiable formula. A first-valid-output selector plus the deterministic verifier decides SAT. Require explicit selector circuit size O((2n+3)(s+V(n)))<=s^3.

## Critical formalization gap

The finite cardinality proof is not yet an APC2 proof. In particular, one must derive the approximate relation for each bad fibre from the formalized contrary hypothesis that every satisfiable formula has more than half of S successful. Exact cardinality is not directly available for arbitrary Sigma^b_1 sets in APC2.

The proof must:
1. State the contrary hypothesis using APC2's approximate-size relation or an equivalent bounded formula.
2. Use Theorem 3.21 to obtain lower/upper approximate size parameters for S and U=S^r.
3. Derive a relative upper bound for each failure set F_x, not merely appeal to the external inequality |F_x|<|S|/2.
4. Use Corollary 3.18(ii) for products F_x^r and Theorem 3.19 for the family of fibres indexed by Q.
5. Choose s0 and epsilon so Z is approximately bounded by s0, while U is not approximately bounded by s0-1.
6. Apply Theorem 3.20 and verify the resulting fibre bound is at most one.
7. Formalize the final extra-circuit repair and selector-size bound inside the theory.

The approximate size parameters from Theorem 3.21 have PV2 maps with sections and are at-most-two-to-one; they provide the needed near-cardinality infrastructure, but the comparison between each F_x and S under the contrary hypothesis is still the key missing derivation.

## Iteration caveat

Jeřábek Theorem 4.2 is the tournament principle. Its proof is a useful model for a repeated survivor-size invariant and Sigma^b_2 induction, but it does not directly apply to this bipartite circuit/formula relation. The greedy history-dependent induction must be separately formalized.

## Status

- R53's empty-fibre conclusion: corrected.
- One-element repair: valid in finite combinatorics under the stated hardness and selector-size assumptions.
- APC2 single-step proof: promising, not completed; per-fibre approximate bound is the critical open obligation.
- APC2 greedy iteration: open.
- Deterministic polynomial-time anti-checker generator: open.
- Search-to-decision/Pich-Santhanam/KPS bridge: open.
- KPS short EF transfer certificates: open.
- P != NP: open. No separation proof obtained.

## Primary source

Emil Jeřábek, *Bounded Arithmetic and Complexity*, Chapter II, especially Theorems 3.19, 3.20, 3.21, Corollary 3.18, and Theorem 4.2:
https://users.math.cas.cz/~jerabek/papers/dsc.pdf
