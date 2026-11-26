# R51: search-circuit survivor anti-checker

## Result

This note records a separate combinatorial anti-checker for the **search** version of SAT. It is not the decision-majority anti-checker from R49.

Fix a standard SAT encoding at input length (n). Let (mathcal C_{n,s}) be the finite set of circuits of size at most (s) with (n) input bits and (n) output bits, viewed as candidate witness finders. Let (R(x,w)) be the polynomial-time relation checking whether (w) satisfies formula (x).

For a nonempty survivor set (S_i\subseteq\mathcal C_{n,s}), call (C\in S_i) successful on satisfiable (x) when (R(x,C(x))=1).

Assume that a tuple of (n+1) candidate circuits, combined with a first-valid-output selector and the verifier (R), would produce a decision circuit for (mathrm{SAT}_n) of size at most (s^3). This is satisfied for sufficiently large (s) relative to the polynomial verifier overhead, under a fixed standard encoding and circuit basis.

Suppose every satisfiable (x) had strictly more than half of (S_i) successful. Sample (t=n+1) circuits independently and uniformly from (S_i). For any fixed satisfiable (x), the probability that all (t) sampled circuits fail is strictly less than (2^{-t}). By a union bound over at most (2^n) formula encodings, the probability that some satisfiable formula has no successful sampled solver is strictly less than (2^n2^{-(n+1)}=1/2). Thus a fixed tuple exists that contains a successful solver for every satisfiable formula.

A circuit can run the (t) solvers, test each output with (R), and return the first valid witness. A final verifier bit decides satisfiability. By the parameter assumption this is a size-(s^3) decision circuit, contradicting
\[
\mathrm{SAT}_n\notin\mathrm{SIZE}(s^3).
\]

Therefore some satisfiable formula (x_i) has at least half of (S_i) failing. Choose a satisfying witness (y_i), and retain only successful circuits:
\[
S_{i+1}=\{C\in S_i:R(x_i,C(x_i))=1\}.
\]
Then (|S_{i+1}|\le |S_i|/2). After at most (\lceil\log_2|\mathcal C_{n,s}|\rceil+1=O(s\log(n+s))) stages, no circuit survives. The selected formula/witness pairs form a polynomial-size nonuniform search anti-checker: every size-(s) search circuit fails to output a satisfying assignment on at least one selected formula.

## Why this route is useful

- Survivor membership is PV: it checks the polynomial-time witness relation on the explicitly stored prior formula/witness pairs.
- The failure predicate (\neg R(x,C(x))) is also PV. This avoids the coNP-valid-label predicate that complicated arbitrary decision-label constructions in R44–R45.
- The construction is closer to the search-oriented feasible-antichecker statement in Pich–Santhanam, Section 3 / Theorem 7.
- This is still a nonuniform existence proof. It does not compute the selected (x_i,y_i) in polynomial time.
- It is not automatically the same object as KPS's decision-circuit lower-bound premise \(\mathrm{lb}_A(\mathrm{SAT},s)[B]\). The search-to-decision/transfer interface must be proved, not assumed.

## Exact formalization target

For an explicit history
\[
H_i=((x_0,y_0),\ldots,(x_{i-1},y_{i-1})),
\]
define (S(H_i)) by the PV predicate that a circuit succeeds on every stored formula. For a fixed satisfiable (x), the failure predicate (\neg R(x,C(x))) is PV.

The desired bounded-arithmetic lemma says that, under the SAT decision-circuit hardness premise and sufficient parameter slack, every nonempty PV-definable survivor set (S(H_i)) has a satisfiable formula (x) on which at least half its circuits fail. Iterating this polynomially many times yields a fixed polynomial-size formula/witness list defeating every size-(s) search circuit.

The key open formal step is to prove the sampling/union-bound argument in APC₁ using polynomial-precision **relative** approximate counting for succinctly defined sets (S(H_i)^t) and their bad subsets. Approximate counting against the ambient universe is insufficient if (S(H_i)) is exponentially sparse. The proof must preserve relative counts. This is the concrete bridge to the feasible-MinMax/APC₁ issue identified by Pich–Santhanam.

An APC₁ proof of this lemma would be meaningful progress, but would still need a careful translation to the exact \(\forall\Sigma^b_2\) anti-checker statement and its corresponding propositional proof system. It would not by itself establish ordinary EF transfer proofs.

## Source audit

Pich–Santhanam, *Towards P ≠ NP from Extended Frege lower bounds*:
- Sections 1.1.3 and 3 identify APC₁-precision MinMax plus existential replacement of the polynomial-time witnessing function as a route to anticheckers in APC₁.
- Section 3 explains that existential replacement yields a \(\forall\Sigma^b_2\) statement. KPT witnessing produces a finite adaptive list of functions whose later outputs can depend on earlier universal challenges; this prevents directly extracting the required single uniform SAT-search solver in EF.
- The paper lists replacement of the polynomial-time reductions in Theorems 3–5 by existential quantifiers as an open problem.

Khaniki–Pich–Sokolov, *Efficient Adversaries*, CCC 2026, Theorem 11 still requires provably constructive anticheckers and short proof-system derivations of the transfer implication. Lipton–Young plus a semantic case split gives true transfer tautologies but not necessarily short EF proofs.

Sources:
- https://users.ox.ac.uk/~coml0742/papers/eopt.pdf
- https://eccc.weizmann.ac.il/report/2023/199/
- https://drops.dagstuhl.de/storage/00lipics/lipics-vol383-ccc2026/html/LIPIcs.CCC.2026.8/LIPIcs.CCC.2026.8.html

## Status

- Search-circuit survivor lemma: **proved combinatorially**, conditional on the stated SAT decision-circuit hardness and selector-size slack.
- Polynomial-size nonuniform search anti-checker: **proved** from the lemma.
- Uniform polynomial-time generator: **open**.
- APC₁ relative-counting proof: **open**.
- Exact bridge to KPS's decision anti-checker and EF transfer certificates: **open**.
- (P\ne NP): **open**. No separation proof is claimed.
