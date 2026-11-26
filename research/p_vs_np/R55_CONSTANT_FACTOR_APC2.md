# R55: constant-factor strengthening for APC2 survivor reduction

Use r=6n and assume every satisfiable formula is solved by at least one quarter of S, so each failure set has size at most 3|S|/4. The number of satisfying formula/witness pairs is at most 2^(2n), and

2^(2n)(3/4)^(6n)=(729/1024)^n<0.712.

This is a larger counting margin than the half-success / r=2n+2 construction. The APC2 formalization target is to express each failure set's approximate upper bound and apply Corollary 3.18(ii), Theorem 3.19, then Theorem 3.20. The latter yields a tuple with at most one bad pair; append one successful circuit to repair it.

The successful survivor set should then be bounded using Theorem 3.17, giving a constant-factor shrink. Exact error composition and formula-class bookkeeping remain open.

Status: stronger finite counting margin; APC2 formalization not complete; no P-vs-NP proof.
Source: https://users.math.cas.cz/~jerabek/papers/dsc.pdf
