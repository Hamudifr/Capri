# R42: certificate-lifted canonical-pair MinMax game

**Status:** Formalization route, not a P-vs-NP proof. The nonuniform support existence is classical; the point here is to express the canonical-pair payoff as a total PV predicate.

## 1. Canonical pair and certificate domain

For a proof system P and polynomial refutation bound w(n), define
[
U_n={xin{0,1}^n:x	ext{ is satisfiable}},
qquad
V_{n,w}={x:x	ext{ has a P-refutation of size }le w(n)}.
]
Both are NP sets with polynomial-time verifiers. Soundness gives (U_ncap V_{n,w}=arnothing).

Let (N=operatorname{poly}(n,w)) be large enough to encode a fixed-length string
[
z=(x,b,omega),
]
where either:
- (b=1) and (omega) is a satisfying assignment for (x), or
- (b=0) and (omega) is a P-refutation of (x) of size at most (w).

The validity predicate (mathrm{Vld}_{n,w}(z)) is PV. For a decision circuit (C) on formula inputs (x), define
[
e(C,z)=mathrm{Vld}_{n,w}(z)land[C(x)
e b].
]
This is a total polynomial-time predicate in the circuit description and z. Invalid encodings have payoff zero. Since the valid domain is nonempty, mass on invalid columns can be removed and renormalized without decreasing any circuit's expected payoff.

## 2. Constant-error game-value lemma

Assume:
- no size-(s^3) circuit separates (U_n) from (V_{n,w});
- (sge cN) for a sufficiently large constant c.

Consider the finite zero-sum game whose circuit player chooses a size-s decision circuit C and whose input player chooses z∈{0,1}^N, with payoff e(C,z).

**Claim:** the game value is at least (1/2-1/sqrt{s}).

Proof:
1. Suppose the value were smaller. By minimax, there is a distribution (
u) over size-s circuits with expected error below (1/2-1/sqrt{s}) on every z.
2. Draw (M=Ns) circuits independently from (
u) and take their majority.
3. For each fixed z, Hoeffding bounds the majority error by (exp(-2M/s)=exp(-2N)).
4. A union bound over all (2^N) encodings leaves positive probability of a majority circuit correct on every valid z.
5. The majority circuit depends only on x. It accepts every x∈U_n and rejects every x∈V_{n,w}, separating the canonical pair.
6. Its size is (O(Ms)=O(Ns^2)le s^3) for s≥cN, contradiction.

Thus the value is at least (1/2-1/sqrt{s}). For s≥16 this is at least 1/4.

Now sample (t=O(slog s)) certificate encodings from an optimal maximin distribution. Since the number of size-s circuits is at most (2^{O(slog s)}), a union bound gives a multiset (Z^*) of t valid encodings such that every size-s circuit mislabels at least one sample.

## 3. Projecting the support to SAT labels

Project (Z^*) to formula components and deduplicate, obtaining (Asubseteq{0,1}^n). Because the pair is disjoint, all valid certificates for a fixed formula have the same label.

For each x∈A:
- If its label is 1, set (y_x) to the attached satisfying assignment.
- If its label is 0, retain the P-refutation and set (y_x=0^n).

Then (SAT_n(x,y_x)) equals the label, and every size-s decision circuit disagrees with (SAT_n(x,y_x)) on some x∈A.

For P=EF, each label-validity implication
[
orall y,[SAT_n(x,y)	o SAT_n(x,y_x)]
]
has a polynomial-size EF proof:
- positive label: the consequent is true by the attached satisfying assignment;
- negative label: substitute the assignment variables y into the attached EF-refutation of x to obtain a proof of (
eg SAT_n(x,y)), then derive the implication.

The table (D={(x,y_x):xin A}) is explicit, polynomial-size, and functional.

## 4. Why this matters for APC1/APX1

The direct payoff ([C(x)
e SAT_n(x)]) is a (Delta_2^P/P^{NP}) predicate, so direct APC1 counting is not justified. The certificate-lifted payoff (e(C,z)) is PV. Thus the finite game can be represented as a succinct PV matrix, which is the right input type for approximate counting over PV-defined predicates.

This is a *representation-level improvement*, not a proof that APC1 or APX1 proves the needed MinMax theorem. The following still need proof:
1. polynomial-precision MinMax for the succinct PV matrix in APC1 or APX1;
2. exact synchronization of N, s, t, u and the canonical-pair refutation bound;
3. translation into the propositional proof system required by KPS;
4. a short proof of the universal antichecker tautology (lb_A(SAT,s)) and the full KPS transfer implication;
5. a feasible selector, not merely a nonuniform support.

KPS explicitly note that nonuniform anticheckers exist by Lipton–Young. No novelty is claimed for that existence theorem. The new angle is to encode canonical-pair membership certificates into the MinMax column domain so the payoff itself is PV.

## 5. Scope cautions

- This construction assumes **canonical-pair hardness** for (U_n,V_{n,w}), not merely SAT (
otin P/poly).
- It does not show canonical-pair hardness for EF.
- It does not prove the KPS condition-2 EF proofs of the universal antichecker statement.
- APC1-provability does not imply APX1-provability.
- No unconditional P ≠ NP proof is obtained.

## Sources

- Khaniki–Pich–Sokolov, *Efficient Adversaries*, Theorem 11, Remark 12, and proof discussion: https://doi.org/10.4230/LIPIcs.CCC.2026.8
- Pich–Santhanam, *Towards P ≠ NP from Extended Frege lower bounds*: https://arxiv.org/abs/2312.08163
- Müller–Pich, *Feasibly Constructive Proofs of Succinct Weak Circuit Lower Bounds*, Theorem 4.12: https://eccc.weizmann.ac.il/report/2017/144/download/
- Lipton–Young, *Simple Strategies for Large Zero-Sum Games with Applications to Complexity Theory*: https://arxiv.org/abs/cs/0205035
