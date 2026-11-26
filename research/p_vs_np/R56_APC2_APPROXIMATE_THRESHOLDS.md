# R56: APC2 single-step with explicit approximate-size thresholds

Let Theorem 3.21 provide a<=b<=a(1+eta), with a PV2 injection [a]->S and a PV2 surjection [b]->S. Let U=S^r, r=6n, Q the satisfying formula/witness pairs, and F_x the search circuits failing verifier R on x.

Contrary hypothesis: for every satisfying pair (x,w), F_x is approximately bounded by 3b/4.

Corollary 3.18(ii) bounds F_x^r by approximately (1+epsilon)^(r+1)(3b/4)^r. Theorem 3.19, with Q as first coordinate, gives a bad-incidence upper bound approximately
(1+4epsilon) 2^(2n)(1+epsilon)^(r+1)(3b/4)^r.

Relative to a^r this is at most
(729/1024)^n (1+eta)^r (1+epsilon)^(r+1)(1+4epsilon),
below 0.72 for sufficiently small inverse-linear errors (e.g. scale 1/(1000r), with nested constants adjusted).

Choose s0 near 3a^r/4. The injection [a^r]->U implies U is not approximately bounded by s0-1. Theorem 3.20 with t=1 yields a tuple with at most one bad satisfying pair. The contrary hypothesis ensures a successful circuit exists for the one remaining formula; append it. A first-valid-output selector decides SAT, subject to O((6n+1)(s+V(n)))<=s^3.

For the selected x, F_x is not approximately bounded by 3b/4. Apply Theorem 3.17 to S=F_x disjoint union G_x, with parameters near 3b/4 and 0.3a. The F_x branch contradicts the choice of x, so G_x is approximately bounded by about 0.31a. This is a candidate constant-factor survivor invariant.

Open: exact error/floor bookkeeping, proof that the extra successful circuit exists internally, history-dependent induction, verifier size constants, and the KPS/EF bridge. No P-vs-NP proof.
Source: https://users.math.cas.cz/~jerabek/papers/dsc.pdf
