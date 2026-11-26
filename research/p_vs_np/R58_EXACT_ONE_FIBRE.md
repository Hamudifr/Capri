# R58: exact extraction from the one-element APC2 fibre

R54/R57 apply Jeřábek Theorem 3.20 with t=1 and sufficiently small epsilon. The theorem yields a fibre F satisfying F ≼_epsilon floor(1(1+2epsilon))=1.

This approximate upper bound can be converted into an actual list of at most one element. Jeřábek Chapter II, Corollary 3.10 states that if s≤epsilon^{-1} is logarithmically bounded, then X ≼_epsilon s iff there exists a sequence of length at most s containing every element of X. Since s=1 and epsilon^{-1} is logarithmically bounded, the bad fibre has an explicit sequence of length zero or one.

Repaired flow:
1. Theorem 3.19 bounds the bad incidence relation.
2. Theorem 3.20 with t=1 gives a selected tuple whose bad-pair fibre is approximately bounded by one.
3. Corollary 3.10 converts that fibre into a list of length at most one.
4. If empty, the tuple already covers every satisfiable formula.
5. If the unique pair is (x,w), the contrary hypothesis ensures a successful circuit C* in S for x; append it.
6. The enlarged tuple covers every satisfiable formula and yields a SAT decision circuit by first-valid-output verification.

This closes the exact-one extraction detail. It does not close the overall APC2 proof: nested error/floor bookkeeping, the formal contrary-hypothesis/failure-set bounds, the extra-circuit existence proof, the Theorem 3.17 survivor split, and the history induction remain.

Status: one-element extraction closed; APC2 single-step formalization incomplete; greedy iteration open; deterministic generator and KPS/EF bridge open; P != NP open.

Source: Jeřábek, *Bounded Arithmetic and Complexity*, Chapter II, Corollary 3.10 and Theorems 3.19–3.21:
https://users.math.cas.cz/~jerabek/papers/dsc.pdf
