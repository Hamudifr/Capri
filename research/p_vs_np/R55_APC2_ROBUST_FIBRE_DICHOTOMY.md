# R55: robust APC2 fibre dichotomy for the search-survivor step

## Objective

Repair the R54 gap: derive the approximate upper bound on each bad fibre from the contrary hypothesis, without trying to distinguish an exact one-circuit difference around one half of a sparse survivor set.

Primary source: Jeřábek, *Bounded Arithmetic and Complexity*, Chapter II, especially Theorem 3.17 (disjoint-union dichotomy), Corollary 3.18(ii) (products), Theorems 3.19–3.21 (parameterized averaging, empty-fibre averaging, and approximate enumeration).

## 1. Partition the survivor set

Let S be a nonempty PV-definable set of candidate SAT search circuits. For each n-bit formula x, define the disjoint PV-definable partition

- G_x = { C in S : R(x,C(x)) = 1 }, the successful search circuits;
- F_x = S \\ G_x, the failing search circuits.

Here R is the polynomial-time SAT witness verifier. Thus G_x and F_x are in the relevant Sigma^b_1 class, and G_x disjoint-union F_x = S.

Apply Theorem 3.21 to S with relative error eta. Obtain parameters a,b and PV2 maps giving:
- an injection [a] -> S;
- a surjection [b] -> S;
- a <= b <= ceil(a(1+eta)).

In particular S is approximately bounded by b, while [a] embeds into S.

Set M=b, s=ceil(3M/4), and t=ceil(M/4). Since s+t+1 >= M, Theorem 3.17 applied to G_x and F_x gives, for every x,

G_x <=_eta A  OR  F_x <=_eta B,

where A=ceil(s(1+2eta)) and B=ceil(t(1+2eta)).

This is the key robust dichotomy. It does not ask APC2 to distinguish a strict majority from a tie. Under the contrary hypothesis that no satisfiable formula has G_x <=_eta A, every satisfying formula x has F_x <=_eta B.

The target survivor reduction is now a factor close to 3/4, not exactly 1/2. This is fully sufficient for logarithmically many rounds.

## 2. Bad-pair incidence relation

Let Q = {(x,w): R(x,w)=1}, the satisfying formula/witness pairs. There are at most 2^(2n) such pairs when formula and witness encodings each have length n.

Choose r=n+1 and U=S^r. Define Z subset U x Q by

(u,(x,w)) in Z iff every circuit in tuple u fails verification on x.

For a fixed q=(x,w), its Z-fibre is exactly F_x^r. Under the no-small-success contrary hypothesis, Theorem 3.17 gives F_x <=_eta B. Corollary 3.18(ii) therefore gives

F_x^r <=_eta ceil((1+eta)^(r+1) B^r).

Theorem 3.19, with Q as the first coordinate and U as the second, gives

Z <=_eta ceil(2^(2n) (1+eta)^(r+1) B^r (1+4eta)).

The relation is correctly oriented: Theorem 3.19 bounds the total incidence set from the number of formula/witness pairs times the maximum bad-tuple fibre.

## 3. Compare the incidence upper bound with a lower bound on U

The injection [a] -> S from Theorem 3.21 induces a PV2 injection [a]^r -> U. Under the standard base-a encoding, [a]^r is an interval of length a^r. Thus U has a relative lower-size certificate of scale a^r.

For large a, use
- eta = 1/(1000r);
- b <= a(1+eta)+1;
- B <= (b/4)(1+2eta)+2.

Consequently,

B/(a/4) <= (1+eta+1/a)(1+2eta)+8/a.

If a >= 1000r, the product of all relative-error factors in the Z bound is less than 1.02. Hence

Z < 0.26 a^r,

because 2^(2n)/4^r = 1/4 for r=n+1.

Choose s0=floor(a^r/2). Monotonicity gives Z <=_eta s0. On the other hand, U is not <=_eta s0-1: the injection [a^r] -> U and the constant-factor gap between a^r and s0 contradict an approximate upper bound of roughly half that interval. This last interval-size implication should be written explicitly from the definition of <=_eta, using the counting/surjection lemmas in §3.2–3.3.

Small-parameter branch: if a < 1000r, Theorem 3.21 supplies a polynomial-length enumeration of S. In that case the success/failure partition and the product S^r can be counted exactly through their canonical indexed encodings; do not use the asymptotic 0.26 estimate with additive ceiling errors. The exact small-case derivation still needs to be written out in the formal proof.

## 4. Apply the empty-fibre averaging theorem and repair one remaining pair

Apply Theorem 3.20 to X=U, Y=Q, Z as above, with s=s0 and t=1. Since Z <=_eta s0 and U is not <=_eta s0-1, there is u in U whose bad Q-fibre has size at most

floor(1(1+2eta)) = 1.

If the fibre is empty, u already contains a successful search circuit for every satisfiable formula.

If the fibre consists of one pair (x,w), the contrary hypothesis says G_x is not <=_eta A, hence G_x is nonempty. Choose C* in G_x and append it to u. The enlarged tuple of r+1=n+2 circuits covers every satisfiable formula. The nonemptiness-to-witness step should be explicitly formalized using the available bounded least-number principle for the Sigma^b_1 predicate defining G_x.

A first-valid-output selector plus R decides SAT. Its circuit size is O((n+2)(s+V(n))), where V(n) is the verifier circuit size. Require the explicit slack

O((n+2)(s+V(n))) <= s^3.

This contradicts SAT_n notin SIZE(s^3). Therefore the contrary hypothesis is false: there exists a satisfiable x for which G_x <=_eta A. Retaining G_x shrinks the survivor set by a constant factor (at most about 0.76 for the displayed error choice).

## 5. What this appears to repair

The R54 critical gap was: “derive an approximate upper bound for F_x from the contrary hypothesis that G_x contains more than half of S.”

R55 replaces that brittle half-threshold with a theorem-level dichotomy:
- either G_x is approximately at most 3/4 of S (the desired survivor reduction);
- or F_x is approximately at most 1/4 of S (which makes the bad-pair fibres small enough to invoke Theorems 3.19 and 3.20).

The proof no longer needs to express or count an exact strict majority of an arbitrary sparse Sigma^b_1 set. The 3/4–1/4 split leaves a constant margin.

## 6. Status and remaining verification

- The finite combinatorial idea and the theorem-level partition route are source-checked.
- The approximate error calculation for a>=1000r gives a conservative incidence ratio below 0.26, subject to the exact ceiling conventions being copied into the formal derivation.
- The small-a exact-counting branch needs a complete written derivation.
- The interval lower-bound implication U not <=_eta s0-1 needs an explicit proof from Jeřábek's definitions and surjection lemmas.
- The nonempty G_x witness extraction and the full formula-class/quantifier bookkeeping must be checked in T^1_2(alpha)+rWPHP(PV2(alpha)).
- The greedy iteration over history-dependent survivor sets remains open; Theorem 4.2 is a template, not an automatic corollary.
- This remains a search anti-checker route. It does not by itself provide the Pich–Santhanam decision anti-checker/assignment-label object or KPS's short EF transfer certificates.
- No deterministic polynomial-time anti-checker generator is obtained.
- No P != NP proof is obtained.

## Primary source

Emil Jeřábek, *Bounded Arithmetic and Complexity*, Chapter II:
https://users.math.cas.cz/~jerabek/papers/dsc.pdf

Relevant source locations:
- Theorem 3.17: disjoint-union dichotomy.
- Corollary 3.18(ii): products of logarithmically many definable sets.
- Theorem 3.19: parameterized-family averaging.
- Theorem 3.20: approximate empty-fibre averaging.
- Theorem 3.21: approximate enumeration with PV2 maps and sections.


## R55 parameter and small-survivor audit

Write r=n+1, eta=1/(1000r), and let a be the lower parameter from Theorem 3.21. For a>=1000r, b/a<=1+2/(1000r), and

4B/a <= (b/a)(1+2eta)+8/a <= 1+0.012002/r.

Thus the normalized incidence bound is

Z/a^r <= (1/4)(1+eta)^(r+1)(1+4eta)(4B/a)^r
       < (1/4) exp(0.0015+0.002+0.012002)
       < 0.254,

using r>=2. This is a conservative analytic bound, stronger than the earlier <0.26 estimate.

If a<1000r, then b=O(n). Theorem 3.21 gives a PV2 enumeration of S of polynomial length. Deduplicate the list and count G_x and F_x exactly by scanning it. Under the contrary hypothesis that no satisfiable x has |G_x|<=3|S|/4, every satisfying x has |F_x|<|S|/4. The per-q fibre bound is then exact, and Theorem 3.19 can still handle the large product universe U=S^r. This avoids applying the large-a ceiling estimate in the small case.

Remaining formal check: write the section/coretraction composition explicitly to show U not <=_eta floor(a^r/2)-1. Theorem 3.21 supplies a section for the injection [a] -> S; taking r-fold products gives a section [a]^r -> U. Combine this with the surjection characterization of approximate upper size and exact counting on the interval [a^r].
