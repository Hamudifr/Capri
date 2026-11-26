# R58: fibre-complexity audit of the Sigma-2 survivor induction

## Executive finding

R57's history-packing idea handles the certificates for the polynomially many selected survivor stages. It does **not** automatically handle the exponentially large family of fibre certificates used inside the R56 incidence argument.

The R56 large-step proof assumes, under a contradiction hypothesis, that every satisfying formula/witness pair q=(x,w) has a failure fibre F_x^r approximately bounded by B^r. It then applies Jeřábek Corollary 3.18(ii) and Theorem 3.19 to bound the total bad incidence E ⊆ Q × U, and Theorem 3.20 to find a tuple with at most two exceptional pairs.

Here Q contains up to 2^(2n) formula/witness pairs. A direct certificate for each fibre has polynomial length, but the complete family of certificates has exponential total length. It cannot simply be appended to the polynomial-length survivor history.

This is a genuine proof-theoretic gap in the R57 blueprint. It does not refute the finite incidence calculation or the source theorem. It means the required uniform one-step implication has not yet been shown to be Sigma^b_2.

## 1. Exact source audit

Jeřábek, *Bounded Arithmetic and Complexity*, Chapter II:

- Definition 3.1 and Remark 3.2: for a Sigma^b_1-definable set X, the relation X ≼_epsilon s is Sigma^b_2. The hash sequence is existentially supplied; its isolation condition is Pi^b_1.
- Theorem 3.19: if X ≼_epsilon s and every x in X has fibre Z_x ≼_epsilon t, then Z ≼_epsilon ceil(st(1+4epsilon)). The source explicitly notes that the straightforward proof needs Pi^b_2-LIND and that the theorem is not a forall-Sigma^b_2 statement. It then gives a PV_2-based modification to lower the complexity of the induction used in its proof.
- Theorem 3.20: the empty-fibre/averaging theorem has a cleaner formula-class statement. Its proof explicitly says that the argument formalizes in S^2_2(alpha)+sWPHP(PV_2(alpha)) and that the resulting statement is forall-Sigma^b_2.
- Theorem 4.2: the tournament principle is proved by Sigma^b_2-LIND. Its induction step uses Theorems 3.17 and 3.20 directly. This is a genuine template for history-dependent shrinkage, but it does not automatically supply R56's global incidence bound.

Primary source: https://users.math.cas.cz/~jerabek/papers/dsc.pdf
Useful locations: Theorem 3.19, PDF pp. 78–80; Theorem 3.20, p. 80; Theorem 3.21, pp. 80–82; Theorem 4.2, pp. 84–85.

## 2. Why R57 certificate packing is insufficient as written

Let Q = {(x,w): R(x,w)=1}, with |Q| up to 2^(2n). For each q=(x,w), the R56 contradiction argument obtains a bound on F_x^r, where F_x is the set of current survivor circuits that fail on x.

A certificate of F_x^r ≼_epsilon B^r consists of a polynomial-size family of hash matrices, but a separate certificate is associated with each q. Storing all of them literally requires exponential length.

The formula shape also matters. A single assertion F_x^r ≼ B^r is Sigma^b_2. The pointwise family
  forall q in Q, F_x^r ≼ B^r
is not automatically Sigma^b_2 merely because each individual relation is Sigma^b_2. Its direct quantifier form has the universal q-block outside the existential hash-certificate block. One cannot silently commute those blocks.

Theorem 3.19 proves a suitable fibre-averaging principle in Jeřábek's theory, but its source discussion explicitly warns that its statement/proof is not directly the forall-Sigma^b_2 package needed for the proposed R57 induction. The PV_2-based proof modification is important, but it does not by itself establish that the *R56 one-step implication*, with the global SAT-hardness contradiction and exponentially many fibres, is a Sigma^b_2 formula.

Therefore the R57 sentence “pack all certificates into one polynomial-length string” is valid for the O(m) stage certificates, but is not a valid justification for packing the 2^(2n) per-fibre certificates. This is the precise correction.

## 3. What remains valid

The following parts are not invalidated by this audit:

1. The finite search-circuit survivor construction and its polynomial support bound, conditional on the circuit-hardness and selector-size assumptions.
2. The R56 numerical incidence estimate, conditional on the per-fibre approximate bounds.
3. The two-exceptional-pair rounding repair and the append-at-most-two-circuits selector repair.
4. The small-survivor branch based on Theorem 3.21 and Corollary 3.10.
5. The recurrence estimate for the large branch, conditional on a valid one-step transition.
6. The fact that a history of polynomially many selected formula/witness pairs and their own stage certificates can be encoded in polynomial length.
7. Jeřábek Theorem 4.2 as a model for a Sigma^b_2 history induction when the local transition has the right formula class.

What is not established is the low-complexity derivation of the global bad-incidence bound from the contradictory pointwise fibre condition.

## 4. Candidate repairs to investigate

### A. A uniform fibre-certificate selector

Try to prove that the dichotomy from Theorem 3.17 can be made uniform in x by a single PV_2(alpha) procedure that outputs either:
- a certificate G_x ≼ A, or
- a certificate F_x ≼ B.

If such a selector exists with the right proof of correctness, the second branch under the no-success assumption could provide the fibre certificates on demand without storing them all. This is only a candidate: the branch predicate itself involves approximate-size statements with a Sigma^b_2 witness, so a PV_2 selector is not automatic. The construction must be derived from the actual proof of Theorem 3.17, not assumed.

### B. A specialized forall-Sigma^b_2 incidence lemma

Prove a version of the incidence bound tailored to the relation
  E(q,u) iff every circuit in tuple u fails verification on q's formula,
where Q is the set of satisfying formula/witness pairs and U=S^r.

The target should be a single forall-Sigma^b_2 implication:
  (uniform survivor-size certificate and SAT-hardness disjunction)
  -> exists u in U with at most two exceptional q.

It must avoid a separately quantified hash certificate for every q. A direct proof may use the tuple sampling structure, the fact that the failure predicate is PV, and the polynomially bounded sample length r=n+1. No such proof has yet been obtained.

### C. Replace the incidence proof with a tournament/partial-colouring argument

Jeřábek Theorem 4.2 avoids Theorem 3.19 in its induction step by using the split theorem and the empty-fibre theorem directly. Investigate whether the SAT survivor game can be encoded as a suitable partial colouring or multi-coordinate relation to invoke Theorem 4.3 or a related forall-Sigma^b_2 principle.

This is not yet a reduction. The theorem's hypotheses about dense partial colourings and its conclusion about small exceptional sets must be matched exactly; it cannot be cited merely because both arguments resemble a counting/averaging proof.

### D. Accept a stronger formula class, then assess the cost

If the one-step statement is inherently Pi^b_3 or Sigma^b_3 in its direct formulation, determine whether a stronger induction theory can prove the iteration. Then separately assess whether its propositional translation yields a proof system strong enough for the Pich–Santhanam/KPS route. This may leave the original EF objective behind, so it is a fallback rather than the preferred repair.

## 5. Revised proof status

| Component | Status |
| --- | --- |
| R49 decision-survivor lemma | Mathematically proved conditionally |
| R51 search-survivor lemma | Mathematically proved conditionally |
| R56 finite incidence arithmetic | Conditional on pointwise fibre bounds |
| Jeřábek Theorem 3.19 source statement | Source-verified |
| Theorem 3.19 as a direct forall-Sigma^b_2 induction step | Not available as stated |
| R57 stage-history packing | Valid for polynomially many stage certificates |
| Packing all per-q fibre certificates | Invalid as a literal polynomial-length argument |
| Uniform PV_2 fibre-certificate selector | Open |
| Specialized forall-Sigma^b_2 incidence lemma | Open |
| Direct tournament/partial-colouring reformulation | Open |
| Bounded-arithmetic polynomial-size search anti-checker | Not proved |
| Uniform anti-checker generator | Open |
| Pich–Santhanam decision anti-checker / KPS EF transfer | Open |
| P ≠ NP | Open |

## 6. Next concrete task

Do not continue the R57 induction algebra until the one-step formula-class problem is solved. First inspect the proof of Theorem 3.17 and determine whether its approximate-size dichotomy has a uniform PV_2 witness selector. In parallel, formulate the exact specialized incidence statement and compare its quantifier prefix with Jeřábek Theorem 3.19 and Theorem 3.20.

A successful repair must explicitly provide:
1. the selector or incidence witness;
2. its polynomial description-size bound;
3. a single Sigma^b_2 correctness formula (or an honestly stronger formula class);
4. a proof that no exponentially long family of fibre certificates is being hidden in the notation.

## Status

R58 is a source-checked correction and research-direction update. It is not a proof of a bounded-arithmetic anti-checker, a decision anti-checker, an EF lower bound, or P ≠ NP.


## R62 correction and supersession

The claim above that the exponentially many fibre certificates cannot be packed is true as a literal storage observation, but it is **not a necessary step in the R56 proof**. Theorem 3.19 can be invoked as an internal theorem on the universally defined fibre family; no explicit list of all fibre certificates is needed. Its not being a direct forall-Sigma^b_2 statement does not prevent its use as an internal lemma in S^2_2(alpha)+sWPHP(PV_2(alpha)). The actual target is to prove the final disjunctive one-step lemma in Sigma^b_2 and transfer its universal closure.

R62 also corrects the t=1 rounding: Theorem 3.20 gives at most ceil(1+2delta)=2 exceptional pairs, not one. The global search-circuit alternative D is Sigma^b_2, not Sigma^b_1, because its universal quantifiers range over all n-bit formulas and witnesses. These corrections and a conservative parameter split are developed in R62: [R62_DISJUNCTIVE_STEP_AND_ROUNDING_AUDIT.md](R62_DISJUNCTIVE_STEP_AND_ROUNDING_AUDIT.md).

**Status:** the original diagnosis that certificate packing is a necessary barrier is retracted. The remaining proof obligations are the exact local disjunction, parameter propagation, error schedule, and conservativity transfer. No bounded-arithmetic anti-checker or P != NP proof is claimed.
