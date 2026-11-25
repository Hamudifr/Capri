# R40–R41: KPT selector collapse under P = NP

**Status:** Conditional theorem only. No unconditional P ≠ NP proof and no proof of the required existential antichecker statement.

## 1. Starting point

Pich–Santhanam, preprint Theorem 7 / §3, considers a feasible SAT-antichecker output:

- either a polynomial-size SAT-search circuit (B), with
  [
  orall x,y;[SAT_n(x,y)	o SAT_n(x,B(x))],
  ]
- or a finite package (Q=(A,A',D)) with unique labels (y_x), label validity
  [
  orall xin A;orall y;[SAT_n(x,y)	o SAT_n(x,y_x)],
  ]
  and disagreement with every size-(n^K) decision circuit (C).

Replacing the uniform generator by existential quantifiers gives a (orallSigma^b_2) statement (S_K). If (PV_1dash S_K), KPT witnessing yields a constant number (c) of polynomial-time functions (f_1,ldots,f_c). At history (h_{<i}), (f_i) outputs (B_i,Q_i), and the KPT disjunct has the form
[
P_i =
[ SAT_n(x_i,y_i)	o SAT_n(x_i,B_i(x_i)) ]
lor
[ D'_i(\tilde y_i)land Refute(C_i,Q_i)].
]
Here (D'_i) is the remaining bounded matrix condition and (C_i) is chosen after (Q_i) is output. The KPT theorem proves the disjunction of the (P_i)'s for every challenge tuple.

## 2. The FP^NP selector

At each stage, evaluate (f_i) on the current history and make at most three NP queries.

1. **Bad search circuit:** Is there (x,y) with (SAT_n(x,y)=1) and (SAT_n(x,B_i(x))=0)? If no, return (B_i), which is a correct global search circuit.
2. If yes, retain a witness ((x_i,y_i)), falsifying the first disjunct.
3. **Bad bounded matrix:** Is there (	ilde y_i) with (D'_i(	ilde y_i)=0)? If yes, choose it and any (C_i), falsifying the second disjunct.
4. If no, (D'_i) holds for every (	ilde y_i). The package-validity conditions in the remaining bounded matrix therefore hold.
5. **Evading circuit:** Is there a size-(n^K) circuit (C_i) agreeing with all labels on (A_i)? This is NP: guess its description and check the polynomial-size support. If yes, choose it, falsifying the second disjunct.
6. If no, return (Q_i), which is a valid antichecker against every size-(n^K) decision circuit.

If all (c) stages continued, every (P_i) would be false, contradicting the KPT disjunction. Hence the selector halts within (c) rounds. Witness recovery for the NP queries uses polynomially many NP-oracle queries, so the selector is in (FP^{NP}).

The three query predicates are NP because:
- a bad (B_i) has an explicit formula and satisfying assignment;
- a falsifier of (D'_i) is an explicit bounded string;
- an evading circuit has polynomial description length, and agreement is checked over the explicitly listed polynomial-size support.

## 3. Conditional collapse theorem

**Theorem (derived conditional implication).** If (PV_1) proves (S_K) for every sufficiently large fixed exponent (K), then (P\ne NP).

**Proof.** Assume (P=NP). Then (FP^{NP}=FP), so the selector above is a uniform polynomial-time function (G_K) outputting either a correct SAT-search circuit (B) or a valid package (Q).

Fix a search-circuit exponent (k>1). Choose (K) large enough that for every size-(n^k) search circuit (C), the decision circuit
[
D_C(x):=SAT_n(x,C(x))
]
has size at most (n^K). The only extra size is the fixed polynomial-time SAT-verifier circuit.

Define (f^k(C)):
- If (G_K) returns (B), output any fixed pair. The first disjunct of Pich–Santhanam's (w_n^k(f^k)) is true because (B) solves SAT search.
- If (G_K) returns (Q), scan (A) for (x) with (SAT_n(x,y_x)\ne D_C(x)). Such an (x) exists because (Q) refutes (D_C). The mismatch cannot be a false positive: if (D_C(x)=1), then (C(x)) is a satisfying assignment, and label validity forces (y_x) to satisfy (x). Thus the mismatch is a false negative, and (f^k(C)=(x,y_x)) is a satisfying formula/witness pair on which (C) fails. The second disjunct is true.

Under (P=NP), (G_K) and (f^k) are polynomial-time. Hence (w_n^k(f^k)) is a tautology for all sufficiently large (n), for every (k>1). Pich–Santhanam Corollary 1 gives
[
NP\not\subseteq SIZE[n^\ell]quad\text{for every }\ell,
]
contradicting (P=NP), since (P=NP) implies (NP=P\subseteq SIZE[n^d]) for some fixed (d). Therefore (P\ne NP).

**Scope:** the implication assumes (PV_1\vdash S_K) for all sufficiently large (K). It does not prove any (S_K), and so is not an unconditional P-vs-NP proof.

## 4. APX1 extension

Chen–Li–Oliveira–Williams (ECCC TR26-015, 2026) Theorem 5.12 gives a KPT witnessing theorem for (APX_1\vdash\forall x\exists y\forall z\,\phi(x,y,z)), with quantifier-free PV matrix. The extracted terms are in (PV(P)), where (P) is the approximate-counting oracle. The existentialized antichecker statement has this bounded quantifier shape after packaging the bounded matrix.

Under (P=NP), (PH=P), hence (BPP=P). Bit-by-bit, polynomial-output (prBPP) functions are then in (prP). In particular, CAPP and the APX1 oracle (P) can be simulated by a uniform deterministic polynomial-time algorithm. The APX1 KPT terms therefore become uniform polynomial-time functions in the standard model. The same (FP^{NP}) path selector (with its (P)-oracle calls simulated in P) collapses to P, and the same (f^k) construction applies.

Thus the analogous conditional implication is:
[
\bigl(\forall K\text{ sufficiently large},; APX_1\vdash S_K\bigr)
\quad\Longrightarrow\quad P\ne NP.
]

This does **not** show that an APC1 proof of (S_K) is an APX1 proof. The theories differ; the APX1 route requires its own formalization.

## 5. Refuter(Yao) boundary

APX1 Theorem 1.9 applies to APX1-provably total TFNP relations
[
\forall x\exists y\;\phi(x,y)
]
with quantifier-free PV verification, and reduces them to Refuter(Yao). The KPT selector's output correctness is a universal property: either (B_i) solves SAT on every input, or (Q_i) is valid and refutes every circuit. This is not a quantifier-free PV relation, so Theorem 1.9 does not directly apply.

A proof-carrying selector that outputs an EF proof of one of these universal correctness conditions would be a different search problem. APX1-provable totality of that proof-carrying relation remains unproved.

## 6. Open obligations

1. Prove the existentialized statement (S_K) in (PV_1) or (APX_1) for all sufficiently large (K).
2. Audit the bounded-matrix split (D'_i) against the full source formula when formalizing the selector.
3. Formalize the FP^NP selector and its output relation in a proof assistant; no such formalization is claimed here.
4. Determine whether the APC1 finite MinMax route can yield (S_K), and whether any such proof can be weakened to APX1.
5. Do not infer a deterministic selector without (P=NP), and do not claim a short EF proof of selector correctness.

## Sources

- Pich–Santhanam, *Towards P ≠ NP from Extended Frege lower bounds*, preprint §3, Theorem 7, Theorem 1 and Corollary 1: https://arxiv.org/abs/2312.08163
- Published JACM version: https://doi.org/10.1145/3801091
- Chen–Li–Oliveira–Williams, *A Theory for Probabilistic Polynomial-Time Reasoning*, ECCC TR26-015 (2026), Theorems 1.9 and 5.12: https://eccc.weizmann.ac.il/report/2026/015/download/
- APX1 preprint: https://arxiv.org/abs/2602.09302
