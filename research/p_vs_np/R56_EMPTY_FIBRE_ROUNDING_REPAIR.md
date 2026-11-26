# R56: empty-fibre rounding repair and selector audit

## Executive correction

R55 incorrectly read Jeřábek Theorem 3.20 as giving at most one exceptional bad pair when its parameter t=1. The actual conclusion is

  fibre <= ceil(t(1+2 epsilon)).

For every positive epsilon, ceil(1+2epsilon)=2. Thus the theorem gives at most TWO exceptional formula/witness pairs, not one.

This does not destroy the selector argument. There are at most two distinct exceptional formulas among two pairs. For each distinct exceptional formula x, the contrary hypothesis that G_x is not approximately bounded by A implies G_x is nonempty, because the empty set is approximately bounded by every nonnegative parameter. Choose one circuit C_x in G_x and append it. At most two circuits are appended.

The resulting tuple has at most r+2=n+3 search circuits, not n+2. On any satisfiable input z:
- if z is not one of the exceptional formulas, the original tuple u contains a circuit that outputs a valid witness;
- if z is exceptional, its appended C_x outputs a valid witness.

A first-valid-output selector with the SAT verifier therefore decides SAT. For standard formula/witness encodings, the verifier has O(n) circuit size, so the selector has size O((n+3)(s+n))=O(ns+n^2). Under s>=K n and fixed circuit basis, this is O(s^2), hence <=s^3 for sufficient fixed slack.

## Corrected one-step proof skeleton

Fix input length n, target circuit size s, r=n+1, and outer approximation error epsilon=1/(1000r). Let S be a nonempty PV-definable family of candidate search circuits.

1. Apply Theorem 3.21 to S. In the source's notation it gives lower parameter a and upper parameter b with a<=b<=ceil(a(1+epsilon)), together with a section [a]->S and retraction S->[a].
2. Set M=b, p=ceil(3M/4), q=ceil(M/4). Since p+q+1>=M, S is approximately bounded by p+q+1. Theorem 3.17 applied to G_x dot-union F_x=S yields G_x <=_epsilon A or F_x <=_epsilon B, where A=ceil(p(1+2epsilon)), B=ceil(q(1+2epsilon)).
3. Assume for contradiction that every satisfiable x has G_x not <=_epsilon A. Then every satisfying formula/witness pair has F_x <=_epsilon B.
4. Let Q={(x,w):R(x,w)=1}, |Q|<=2^(2n), U=S^r. Let Z⊆Q×U contain (q,u) iff all circuits in u fail verification on q's formula. Each Q-fibre is F_x^r. Corollary 3.18(ii) and Theorem 3.19 give the incidence upper bound
   Z <=_epsilon ceil(2^(2n)(1+epsilon)^(r+1)B^r(1+4epsilon)).
5. Theorem 3.21's section [a]->S gives a section [a^r]->U. For a>=100r, the refined numerical estimate below shows the incidence bound is <0.28a^r, while s0=floor(a^r/2). Thus Z <=_epsilon s0.
6. To invoke Theorem 3.20, distinguish its internal precision delta from the outer approximation epsilon. Its proof chooses delta with (1+delta)^(6N)<=1+epsilon/2, where U⊆[0,2^N). Establish U not <=_delta s0-1: if it were, Theorem 3.8 would give a PV2 surjection [d]^c -> U^c with d=ceil((s0-1)(1+delta)); composing with the r-fold retraction U-> [a]^r gives a surjection [d]^c -> [a^(r)]^c. Since d<a^r, exact interval counting contradicts this. Therefore Theorem 3.20 applies with X=U, Y=Q, t=1.
7. Theorem 3.20 gives u∈U with its bad Q-fibre approximately bounded by ceil(1(1+2epsilon))=2. Since 2<=epsilon^-1, Corollary 3.10 turns this into an actual list of at most two exceptional pairs.
8. For each distinct exceptional formula x, choose C_x∈G_x and append it. The resulting at-most-(n+3)-tuple yields the SAT decision circuit described above, contradicting SAT_n notin SIZE(s^3).

Thus the contrary hypothesis fails, and some satisfiable x has G_x <=_epsilon A. This is the corrected one-step survivor-reduction conclusion.

## Small-parameter branch: simpler direct finish

If a<100r, then a<=100r-1 and b<=ceil(a(1+epsilon))<=100r. Since b<=epsilon^-1=1000r, Corollary 3.10 converts S <=_epsilon b into an actual list of at most b circuits covering S.

Suppose every satisfiable formula x had at least one successful circuit in S. Run all circuits in this list on an input z, verify their outputs, and accept iff one is a valid satisfying assignment. This is a SAT decision circuit of size O(b(s+n))=O(ns+n^2), at most s^3 for sufficient fixed slack when s>=Kn. Contradiction. Therefore some satisfiable x has G_x=empty, eliminating the entire survivor set in one step.

This direct argument avoids forcing the large-a incidence ratio through small rounding-dominated parameters. The large-a branch begins at a>=100r.

## Refined large-a ratio

For r=n+1, epsilon=1/(1000r), a>=100r, b<=ceil(a(1+epsilon)), and B<=ceil(ceil(b/4)(1+2epsilon)), we have

b/a <= 1+0.011/r,
4B/a <= (b/a)(1+2epsilon)+8/a
      <= (1+0.011/r)(1+0.002/r)+0.08/r
      <= 1+0.094/r.

Consequently,

Z/a^r <= (1/4)(1+epsilon)^(r+1)(1+4epsilon)(4B/a)^r
      < (1/4) exp(0.0015+0.002+0.094)
      < 0.276.

Including the outer ceiling remains below 0.28 because a>=100r and r>=2. Since s0=floor(a^r/2), the incidence bound is comfortably below s0.

## Iteration audit: a plausible recurrence, not yet a formal theorem

If one-step survivor reduction is available uniformly for every history-defined nonempty survivor set S_i, then Theorem 3.21 lets us update its approximate upper parameter. Let M_i be the upper parameter. The candidate recurrence is

  A_i = ceil(ceil(3M_i/4)(1+2epsilon)),
  M_(i+1) <= ceil(A_i(1+epsilon)).

For M_i>=100r and sufficient fixed rounding slack, this is at most 0.76 M_i. Hence O(log M_0) rounds reach M_i<100r. At that point Corollary 3.10 gives an actual O(n)-length enumeration of S_i, and the direct small-parameter argument eliminates it in one final step.

The unresolved formal issue is not the arithmetic recurrence. It is the proof-theoretic complexity of selecting and storing the next formula/witness at each round. Theorem 3.20's proof explicitly builds a PV2 interval-search function for its fibre witness, which is promising. But the implication from the assumed SAT circuit lower bound plus the selector contradiction to a uniformly witnessable next formula must be written with exact formula classes and induction. Theorem 4.2 (tournament principle) is a useful model for history-dependent bounded induction, but is not by itself a proof of this iteration.

## Source-checked details

- Theorem 3.17 conclusion uses ceilings: X <= ceil(s(1+2epsilon)) or Y <= ceil(t(1+2epsilon)).
- Corollary 3.18(ii) gives the product factor (1+epsilon)^(r+1).
- Theorem 3.19 gives Z <= ceil(st(1+4epsilon)).
- Theorem 3.20 gives a fibre <= ceil(t(1+2epsilon)); its proof chooses a finer internal delta and explicitly constructs an interval-search PV2 function.
- Corollary 3.10 converts approximate size to an actual covering sequence when the parameter is <=epsilon^-1.
- Theorem 3.21 gives s<=t<=ceil(s(1+epsilon)), a section s->X and retraction X->s.

Primary source: Emil Jeřábek, *Bounded Arithmetic and Complexity*, Chapter II:
https://users.math.cas.cz/~jerabek/papers/dsc.pdf

Relevant source passages: Theorem 3.17 (PDF pp. 76–77), Corollary 3.18 and Theorem 3.19 (pp. 78–79), Theorem 3.20 (p. 80), Corollary 3.10 (p. 74), Theorem 3.21 (pp. 80–82), Theorem 4.2 (pp. 84–85).

## Status

- R55 one-exceptional-pair claim: corrected; actual bound is two pairs.
- Finite combinatorial repair: append one successful circuit per distinct exceptional formula; at most two additions.
- Selector size: O(ns+n^2), with explicit standard-encoding and s>=Kn assumptions.
- Small-a branch: direct O(n)-circuit enumeration and selector contradiction; no incidence estimate needed.
- Large-a branch: refined incidence ratio below 0.28, safely below s0≈a^r/2.
- Theorem 3.20 internal precision: separated from outer approximation epsilon.
- Single-step APC2 formalization: not complete.
- History-dependent iteration: not proved; recurrence is a candidate.
- Uniform anti-checker generator: not obtained.
- Pich–Santhanam decision anti-checker / KPS EF transfer certificate: still open.
- P != NP: not proved.
