# R71: packed survivor-history invariant and conservation audit

## Purpose

R71 turns the R70 one-step result into an explicit history-induction blueprint. The goal is to identify exactly what must be stored, the formula class of the invariant, the theory needed for the induction, and the final conservation statement.

This is still a formalization plan, not a completed proof. In particular, the uniform one-step theorem must be written and checked inside the theory before the induction can be claimed.

Primary source: Jeřábek, *Approximate counting by hashing in bounded arithmetic*, https://users.math.cas.cz/~jerabek/papers/hash.pdf, especially Definition 3.1, Corollary 3.5, Theorems 3.17, 3.19, 3.21, and Theorem 2.1.

## 1. Fixed parameters and survivor predicate

Fix input length n and circuit size s. Let:
- m = ceil(s^(1/3));
- r be the least odd integer at least m^3(n ln 2+12);
- delta = epsilon_0 = 1/(1000r);
- kappa = 1/(50r);
- T = 4*ceil(log_2(M_0+1)), where M_0 is the initial Theorem 3.21 upper parameter.

Let alpha(x) be the SAT decision predicate, represented as a Sigma-b-1 oracle. For a history H_i=(x_0,...,x_{i-1}), define:
S_i(C) iff C is an n-input size-s decision circuit and, for every j<i, C(x_j)=alpha(x_j).

For fixed polynomial-length H_i, S_i is PV_1(alpha), hence Sigma-b-1(alpha). The predicates F_{i,x} and G_{i,x} are also Sigma-b-1(alpha): they are obtained by testing C(x) against the oracle bit alpha(x). The error predicate and its negation are both available as Delta-b-1(alpha) predicates.

## 2. Theorem 3.21 parameters at every stage

Apply Jeřábek Theorem 3.21 to S_i with precision delta. It supplies near-cardinality parameters a_i,b_i and PV_2(alpha) maps forming the section/retraction pairs:
- [b_i] -> S_i -> [b_i];
- [a_i] -> S_i -> [a_i].

In particular, the PV_2(alpha) surjection [b_i] -> S_i gives S_i <=_delta b_i by Corollary 3.5. After substituting the SAT Sigma-b-1 predicate for alpha, these maps are PV_3 and the sets are Sigma-b-2.

Theorem 3.21 also gives a_i <= b_i <= ceil(a_i(1+delta)). In the large branch a_i>=100r, this implies b_i/a_i<=1+kappa.

## 3. Uniform successor lemma

The R70 proof should be stated uniformly for every history H_i and its current Theorem 3.21 parameters.

**Successor lemma (target statement).** Assuming every size-s^3 decision circuit has an n-bit SAT counterexample, there exist a formula x_i and an approximate-size certificate W_i such that:
- G_{i,x_i} <=_delta A_i;
- the next survivor set is S_{i+1}=G_{i,x_i};
- its next Theorem 3.21 upper parameter satisfies b_{i+1} <= (16/25)b_i.

Parameter propagation (do not skip this step): if G_{i,x_i} <=_delta A_i and Theorem 3.21 returns lower parameter a_{i+1}, its section/retraction pair gives a PV_3 retraction G_{i,x_i} -> [a_{i+1}]. Theorem 3.8 gives a PV_3 surjection [d]^c -> G_{i,x_i}^c with d=ceil(A_i(1+delta)). Compose the two maps. sWPHP(PV_3) forces a_{i+1}<=d. Therefore
b_{i+1} <= ceil(a_{i+1}(1+delta))
         <= ceil(ceil(A_i(1+delta))(1+delta)).
This is the justified two-loss recurrence; it does not assume the unproved shortcut a_{i+1}<=A_i.

Large branch:
- If a_i>=100r, use R69's tagged-fibre incidence bound and R70's Theorem 3.17 dichotomy.
- Theorem 3.17 gives F_{i,x}<=_delta q_i or G_{i,x}<=_delta A_i for every x.
- If no x has the second property, all F_{i,x}<=q_i, and the R69 incidence contradiction constructs a majority circuit deciding SAT.
- Hence some x has G_{i,x}<=A_i. The R70 ceiling calculation gives A_i<=0.63b_i and b_{i+1}<=ceil(A_i(1+delta))<=0.64b_i=16b_i/25.

Small branch:
- If a_i<100r, then b_i<=100r+2.
- Use the PV_3 enumeration [b_i]->S_i, deduplicate it, and let N_i=|S_i| be the exact number of distinct survivors. If N_i=0, terminate.
- If every formula had more than N_i/2 agreeing circuits, the majority of the distinct list would decide SAT. Therefore some x has |G_{i,x}|<=floor(N_i/2).
- Filtering/deduplicating the list gives an exact enumeration of G_{i,x}, hence G_{i,x}<=_delta floor(N_i/2) by Corollary 3.5. Use its exact size as b_{i+1}; then b_{i+1}<=floor(N_i/2)<=b_i/2. This avoids a rounding stall for small integers and guarantees strict shrink.

Thus each nonterminal stage shrinks b_i by at least 16/25. The chosen T exceeds the number of rounds needed to reach b_T=0.

## 4. The packed induction invariant

A suitable invariant I(i,H_i,W_{<i}) contains:
1. H_i is a list of i selected formulas.
2. For every j<i, W_j is a hash-isolation certificate for S_{j+1}<=_delta A_j.
3. S_i is the survivor set computed from H_i.
4. The current Theorem 3.21 parameters a_i,b_i and their section/retraction maps are the outputs of the uniform PV_2(alpha) construction on S_i.
5. The recurrence bound 25^i*b_i <= 16^i*b_0 holds.

The hash certificates are polynomial length. From Definition 3.1, for an upper parameter A:
- the number of hash matrices is polynomial in log(A) and delta^(-1);
- each matrix has polynomially many bits in the circuit-description length and log(A).

Here delta^(-1)=1000r and the number of stages T=O(log M_0), so the entire history and all W_j fit in one polynomial-length string.

Formula class:
- Each S_i and G_{i,x_i} is Sigma-b-1(alpha).
- Each approximate-size assertion G_{i,x_i}<=_delta A_i is Sigma-b-2(alpha), by Definition 3.1 / Remark 3.2.
- Its hash matrices are existentially packed; all isolation checks form one Pi-b-1(alpha) block.
- The history invariant I(i,...) is therefore Sigma-b-2(alpha).

The successor lemma is a Sigma-b-2(alpha) extension statement: append x_i and W_i. Length induction on I is therefore available in S^2_2(alpha), provided the uniform successor lemma is proved there with the required collection axioms.

At i=T, b_T=0. Definition 3.1 stipulates S_T<=_delta0 iff S_T is empty. Since S_T(C) is PV_1(alpha), terminal emptiness is Pi-b-1(alpha), and it can be conjoined with the stage verification block. Thus the final existential history statement remains Sigma-b-2(alpha), not a higher alternation.

## 5. Theory strength and conservation

The one-step proof invokes:
- Jeřábek Theorem 3.19 for the uniform incidence family;
- Theorem 3.17 for the disjoint-union dichotomy, whose proof uses BB-Sigma-b-3(alpha);
- Theorem 3.21 and Corollary 3.5 for near-cardinality and enumeration;
- sWPHP(PV_2(alpha)) and the relevant PV_2(alpha)-LIND formalization.

The natural proof theory is therefore:
S^2_2(alpha) + BB-Sigma-b-3(alpha) + sWPHP(PV_2(alpha)).

After substituting the SAT Sigma-b-1 predicate for alpha, this becomes:
S^3_2 + BB-Sigma-b-4 + sWPHP(PV_3).

The final conditional statement has the right conservation shape. Let Hard(n,s) be:
for every size-s^3 circuit C, there exists an n-bit x with Err(C,x).
Because Err is quantifier-free in alpha, Hard is Pi-b-2(alpha), and not-Hard is Sigma-b-2(alpha). If Cert(n,s,H) is the packed Sigma-b-2(alpha) history statement above, then:
Hard(n,s) -> exists H Cert(n,s,H)
is equivalent to not-Hard OR exists H Cert, still Sigma-b-2(alpha). Its universal closure over n,s is forall-Sigma-b-2(alpha), which becomes forall-Sigma-b-3 after SAT substitution.

Jeřábek Theorem 2.1 with i=1 gives the corresponding conservation:
S^2_2(alpha)+BB-Sigma-b-3(alpha)+sWPHP(PV_2(alpha))
is forall-Sigma-b-2(alpha)-conservative over
T^1_2(alpha)+rWPHP(PV_2(alpha)).
After SAT substitution, this is the route from S^3_2+BB-Sigma-b-4+sWPHP(PV_3) to T^2_2+rWPHP(PV_3).

This conservation step is source-matched if, and only if, the packed invariant and conditional theorem are actually proved with the stated Sigma-b-2(alpha) formula class. The theorem's presence in the literature does not substitute for that formalization.

## 6. Labels and resulting nonuniform object

Once the history is constructed, every size-s circuit is eliminated at some selected formula x_i. A unique label can be assigned by:
- y_i = lexicographically least satisfying assignment if x_i is satisfiable;
- y_i = 0^n if x_i is unsatisfiable.

The lexicographic search uses polynomially many SAT-oracle prefix queries, so it is PV_2(alpha). The label-validity condition forall w (SAT(x_i,w) -> SAT(x_i,y_i)) is Pi-b-1 and can be included in the verification block. The resulting formula/label list has polynomial size and is a nonuniform labelled decision anti-checker against size-s circuits.

It is not the Pich-Santhanam feasible generator: the list is obtained by an existential bounded-arithmetic history, not by a PV_1 function with an S^1_2 proof. The conditional anti-checker also assumes the very SAT circuit lower bound it targets. No unconditional separation follows.

## 7. Remaining proof obligations

1. Formalize the uniform R69 incidence theorem for history-defined S_i, including the PV_3 default/section searches and exact parameter dependencies.
2. Prove the large/small successor lemma as a single Sigma-b-2(alpha) implication in S^2_2(alpha)+BB-Sigma-b-3(alpha)+sWPHP(PV_2(alpha)).
3. Define the invariant I precisely, including the polynomial bounds on each hash matrix and all Theorem 3.21 parameters.
4. Prove the successor extension and terminal b_T=0 within the stated length-induction theory.
5. Verify the final universal closure is forall-Sigma-b-2(alpha), then apply Theorem 2.1 exactly.
6. Independently audit the unique-label construction and the distinction between nonuniform existence and a PV_1 generator.
7. Only after these steps, investigate whether the T^2_2+rWPHP(PV_3) conclusion can reach the Pich-Santhanam/KPS EF certificate target.

R71 is a precise induction blueprint, not a completed bounded-arithmetic proof.
