# R60: history-dependent APC2 induction for the greedy search anti-checker

## PV survivor histories

A history H is a sequence of satisfying formula/witness pairs H=((x0,w0),...,(x{k-1},w{k-1})), each satisfying deterministic verifier R. Define

S(H)={C in C_{n,s}: for every i<k, R(x_i,C(x_i))=1}.

For polynomial k and polynomial s, H has polynomial bit length. Membership in S(H) is deterministic polynomial time, so S(H) is PV-definable uniformly in H. Appending q=(x,w) intersects the survivor set with G_x={C in S(H):R(x,C(x))=1}.

## Single-step property

R59 proposes, conditionally on SAT_n notin SIZE(s^3), that every nonempty S(H) has a satisfying pair q=(x,w) such that the next survivor set G_x has approximate size at most about 0.31a(H), where a(H) is the lower approximate-size parameter from Jeřábek Theorem 3.21. We may weaken the bound to rho0=0.35 to leave error slack. The exact single-step error constants remain to be proved.

## Candidate induction

Let N_s bound the number of size-s search-circuit descriptions, with log N_s=O(s log(n+s)). Let rho=0.4. Define

P(k): there exists a history H of length k such that S(H) is approximately bounded above by floor(N_s*rho^k), with relative error delta.

P(k) is intended to be Sigma^b_2: the history is existentially bounded and the approximate-size relation is Sigma^b_2 by Jeřábek Chapter II, Definition 3.1 / Remark 3.2.

Base: the empty history has S(H)=C_{n,s}, contained in the code universe of size N_s.

Step:
- If S(H) is empty, append a fixed satisfiable pair; the set remains empty.
- Otherwise use the single-step theorem to choose q with S(Hq) approximately bounded by rho0*a(H).
- Theorem 3.21 gives an injection [a(H)]→S(H). If S(H) is approximately bounded by B, Theorem 3.8 gives an approximate surjection onto a power of S(H). Compose with the retraction S(H)→[a(H)]; rWPHP implies a(H)≤B(1+delta).
- Thus S(Hq) is bounded by rho0(1+small error)B≤rho B.

Choose delta and per-step eta parameters of order 1/(100K), where K=O(log N_s), so cumulative errors stay inside the 0.35-to-0.4 margin. K is polynomial in n for polynomial s.

After K=ceil(log_{1/rho} N_s)+O(1) stages, floor(N_s*rho^K)=0, forcing S(H)=empty. This would give a polynomial-size nonuniform search anti-checker.

## Relation to Jeřábek Theorem 4.2

Theorem 4.2 proves the tournament principle using a Sigma^b_2 length-induction invariant and a repeatedly shrinking PV survivor set. Our relation is not a tournament, so Theorem 4.2 is not directly invoked. We adapt only the proof architecture: PV survivor sets, a constant-factor step, approximate-size invariant, and length induction.

## Proof-theoretic caveat

The induction formula P(k) is Sigma^b_2, but the conditional hypothesis SAT_n notin SIZE(s^3) is high-complexity when expanded arithmetically. It can be used as a standing assumption in the step derivation without adding it to P(k), but Jeřábek's forall-Sigma^b_2 conservativity does not automatically transfer an arbitrary implication with a high-complexity antecedent. The exact conditional theory must be checked.

## Remaining

- Prove R59 single-step with fixed rho0=0.35 and exact nested errors.
- Prove parameter propagation and floors.
- Check P(k) formula complexity.
- Formalize the conditional hardness premise without smuggling it into the induction formula.
- Verify polynomial history length and selector size.
- Determine whether the conditional induction is provable in APC2 or requires a stronger theory.
- Uniform generator, Pich-Santhanam decision anti-checker, KPS EF certificates remain open.
- No P != NP proof.

Source: Jeřábek, *Bounded Arithmetic and Complexity*, Chapter II, Definition 3.1, Remark 3.2, Theorems 3.8, 3.17-3.21, 4.2:
https://users.math.cas.cz/~jerabek/papers/dsc.pdf
