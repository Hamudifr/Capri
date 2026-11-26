# R72: uniform Sigma-b-2(alpha) successor proof

## Purpose

R72 assembles the R69 incidence arithmetic and R70 partition dichotomy into one uniform one-step proof, with every set class and function interface identified. The target is a successor lemma for arbitrary history-defined survivor sets, provable in:

S^2_2(alpha) + BB-Sigma-b-3(alpha) + sWPHP(PV_2(alpha)).

After substituting the SAT Sigma-b-1 predicate for alpha, this becomes:

S^3_2 + BB-Sigma-b-4 + sWPHP(PV_3).

This note is a proof blueprint with explicit parameters. It is not yet a line-by-line formal derivation in the theory.

Primary source: Jeřábek, *Approximate counting by hashing in bounded arithmetic*, https://users.math.cas.cz/~jerabek/papers/hash.pdf. Relevant source statements: Corollaries 3.5 and 3.11; Theorems 3.8, 3.13, 3.16, 3.17, 3.19, 3.21; Theorem 2.1.

## 1. Uniform input and target

Let S be the current set of size-s decision circuits, defined by a polynomial-length history H. Relative to the SAT decision predicate alpha, S is Sigma-b-1(alpha). For a formula x define:
- F_x = {C in S : C(x) != alpha(x)};
- G_x = {C in S : C(x) = alpha(x)}.

These are Sigma-b-1(alpha) sets. The error predicate and its negation are both quantifier-free in alpha. The target successor statement is:

There exists x such that G_x <=_delta A.

For a Sigma-b-1(alpha) set, approximate size <=_delta A is Sigma-b-2(alpha), so this is a positive Sigma-b-2(alpha) statement.

Fix:
- m=ceil(s^(1/3))>=4;
- r the least odd integer >=m^3(n ln 2+12);
- delta=epsilon_0=1/(1000r);
- kappa=1/(50r).

Assume Hard(n,s): every size-s^3 decision circuit has an n-bit counterexample.

## 2. Near-cardinality parameters and partition

Apply Theorem 3.21 to S at precision delta. Let a<=b be its lower/upper parameters, with b<=ceil(a(1+delta)). Its PV_2(alpha) surjection [b]->S gives S<=_delta b by Corollary 3.5. If a>=100r, then b/a<=1+kappa.

For each x, the map C -> (C,Err(C,x)) is a PV_2(alpha) bijection between S and the tagged disjoint union F_x dotcup G_x. Corollary 3.11 gives:
M_sharp=ceil(b(1+delta))
as an approximate upper parameter for F_x dotcup G_x.

By Theorem 3.8 soundness, F_x<=_delta q implies |F_x|<=q(1+delta)<=theta*a<=theta*|S|. Thus the finite tag universe has size |T_x|=m|S|+4|F_x|<=(m+2-2/m)|S|, which is the exact coefficient used in the tail ratio below.

Put:
- theta=1/2-1/(2m);
- q=floor(theta*a/(1+delta));
- s_F=floor(q/(1+2delta));
- t_G=M_sharp-s_F-1;
- A=ceil(t_G(1+2delta)).

Then s_F+t_G+1=M_sharp and ceil(s_F(1+2delta))<=q. Jeřábek Theorem 3.17 gives, for every x:
F_x<=_delta q OR G_x<=_delta A.

If no x has G_x<=_delta A, then F_x<=_delta q for every x. We show this is impossible.

## 3. Uniform tagged-fibre bound

For each x, define:
T_x=(S×[m]) dotcup (F_x×[4]),
with disjoint tag ranges. From S<=_delta b and F_x<=_delta q, Corollary 3.12 and Theorem 3.13 give:
H=ceil((1+2delta)(ceil(mb(1+delta)^2)+ceil(4q(1+delta)^2)))
as an upper parameter for T_x.

Corollary 3.18(ii) gives:
U_0=ceil((1+delta)^(r+1) H^r)
as an upper parameter for T_x^r.

Let B_x⊆S^r consist of tuples whose majority circuit errs on x. For u∈B_x, at least half its coordinates are erroneous. Each correct coordinate has m tags; each erroneous coordinate has m+4 tags. Thus the product of tag radices is at least [m(m+4)]^(r/2). With L=floor([m(m+4)]^(r/2)), mixed-radix coding gives an injection:
B_x×[L] -> T_x^r.

The injection and inverse-on-image are PV_2(alpha): query the r error bits in parallel, then perform mixed-radix arithmetic. If B_x is nonempty, totalize the inverse by a default element of B_x×[L]. A default can be found by prefix self-reduction with the Sigma-b-1(alpha) predicate B_x, using polynomially many alpha-oracle queries. The resulting map T_x^r -> B_x×[L] is a PV_2(alpha) surjection with a PV_2(alpha) coretraction. If B_x is empty, its upper bound is trivial.

Corollary 3.11 gives:
B_x×[L] <=_delta P, where P=ceil(U_0(1+delta)).

Set:
t*=floor(L/(1+4delta)),
s*=ceil(P/t*).
By monotonicity, B_x×[L] <=_delta s*t*. Theorem 3.16 gives:
B_x <=_delta ceil(s*(1+delta))
OR
[L] <=_delta ceil(t*(1+delta)).

The interval alternative is impossible. Theorem 3.8 soundness would imply:
L <= ceil(t*(1+delta))(1+delta)
  <= L(1+delta)^2/(1+4delta)+(1+delta)
  < L,
for delta<=1/100 and L>=2/delta. Therefore:
B_x <=_delta K,
where K=ceil(ceil(P/t*)(1+delta)).

All sets used here are Sigma-b-1(alpha), and all functions are PV_2(alpha). This is the exact relativized level required by the APC_2-style counting theorems before substituting SAT.

## 4. Global incidence contradiction

Let Q=[2^n], U=S^r, and E⊆Q×U be the majority-error relation:
(x,u)∈E iff u∈B_x.
This is Sigma-b-1(alpha). Every fibre B_x has upper parameter K, so Theorem 3.19 gives:
E <=_delta E_0, where E_0=ceil(2^n K(1+4delta)).

Write:
c_m=m+2-2/m,
D_m=sqrt(m(m+4)),
rho=c_m/D_m.
The exact tag algebra gives:
1-rho^2 = 4(2m-1)/(m^3(m+4)) >= 7/(2m^3),
so rho<=exp(-7/(4m^3)).

The nested ceiling calculation from R69 yields, in the large branch a>=100r:
E_0/a^r <= 2^n * 2 * rho^r * (1+kappa)^r * exp(0.026)
         <= 2exp(-(3/4)n ln2-20.95)
         < 1/4.

Theorem 3.21 supplies a PV_2(alpha) retraction S-> [a]. Coordinatewise, U=S^r retracts onto [a^r]. If U<=_delta floor(a^r/2), Theorem 3.8 gives a PV_2(alpha) surjection [d]^c -> U^c with d=ceil(floor(a^r/2)(1+delta))<a^r. Compose with U^c -> [a^r]^c, contradicting sWPHP(PV_2(alpha)). Thus U is not approximately bounded by floor(a^r/2).

Under Hard(n,s), every tuple u∈U has a majority circuit of size O(rs)<=s^3 and therefore some counterexample x. Hence the projection E->U is surjective. A PV_2(alpha) section chooses the lexicographically first x by prefix self-reduction on the Sigma-b-1(alpha) predicate E(x,u), using polynomially many alpha queries. Corollary 3.11 transfers E<=_delta E_0 to U<=_delta ceil(E_0(1+delta)), which is below floor(a^r/2). Contradiction.

Therefore some tuple has a majority circuit correct on every n-bit input. Its size is O(rs)=O(ns^2)<=s^3 for sufficiently large s>=Kn, contradicting Hard(n,s). Thus the assumption that every F_x<=q was false.

Combined with Theorem 3.17's dichotomy, this proves the target:
there exists x such that G_x<=_delta A.

## 5. Survivor shrink and parameter propagation

The R70 ceiling calculation gives A/b<0.626<0.63. To propagate the next Theorem 3.21 lower parameter a_next, do not assume a_next<=A. Instead:
- G_x<=_delta A gives, by Theorem 3.8, a PV_3 surjection [d]^c -> G_x^c with d=ceil(A(1+delta)).
- Theorem 3.21 gives a PV_3 retraction G_x^c -> [a_next]^c.
- Compose and use sWPHP(PV_3): a_next<=d.
- Then b_next<=ceil(a_next(1+delta))<=ceil(ceil(A(1+delta))(1+delta))<=0.64b.

Small branch a<100r:
- Theorem 3.21 gives b<=100r+2 and a PV_3 enumeration [b]->S.
- Deduplicate to the exact survivor list and let N=|S|. If N=0, terminate.
- If every formula had |G_x|>N/2, the majority of the distinct S circuits would decide SAT. Hence some x has |G_x|<=floor(N/2).
- Filtering the exact list gives G_x<=_delta floor(N/2), and the exact next count N_next=|G_x|<=floor(N/2)<=b/2.

Thus every nonterminal round shrinks the upper parameter by at least 16/25.

## 6. Formula class and theory

The successor conclusion G_x<=_delta A is Sigma-b-2(alpha). The proof uses:
- Theorem 3.19 internally in T^1_2(alpha)+sWPHP(PV_2(alpha)); its proof is not itself a forall-Sigma-b-2 theorem, but it can be used as an internal lemma in the stronger induction theory.
- Theorem 3.17, whose proof uses BB-Sigma-b-3(alpha) and sWPHP(PV_2(alpha)).
- Theorem 3.21 and Corollary 3.5.
- Theorem 3.8 and sWPHP(PV_2(alpha)) for the lower-parameter propagation.

The natural one-step proof theory is:
S^2_2(alpha)+BB-Sigma-b-3(alpha)+sWPHP(PV_2(alpha)).

The formula class is preserved: the bounded existential x is merged into the leading existential hash-matrix block of G_x<=A. The history invariant in R71 is Sigma-b-2(alpha), so S^2_2(alpha) can perform length induction; BB-Sigma-b-3(alpha) supplies the collection needed by Theorem 3.17 and the packed history.

The final conditional statement Hard(n,s)->exists H Cert(n,s,H) is Sigma-b-2(alpha). Its universal closure over n,s is forall-Sigma-b-2(alpha). Theorem 2.1 with i=1 gives the corresponding conservation to T^1_2(alpha)+rWPHP(PV_2(alpha)). Substituting SAT (Sigma-b-1) for alpha yields the forall-Sigma-b-3 statement in T^2_2+rWPHP(PV_3).

## 7. Exact remaining work

1. Turn the displayed uniform one-step derivation into a formal proof in S^2_2(alpha)+BB-Sigma-b-3(alpha)+sWPHP(PV_2(alpha)), checking every function is a PV_2(alpha) term and every set is Sigma-b-1(alpha).
2. Verify the default-element and incidence-section prefix searches are polynomial-time with the Sigma_1(alpha) oracle.
3. Recheck the global nested-ceiling bound after substituting the history-dependent parameters a,b.
4. Write the R71 induction invariant as a single Sigma-b-2(alpha) formula and prove the extension step.
5. Collect all stage hash certificates using BB-Sigma-b-3(alpha), then prove b_T=0 at the chosen T.
6. Apply Theorem 2.1 only after the final universal closure is verified to be forall-Sigma-b-2(alpha).
7. Keep the Pich-Santhanam/KPS EF generator requirement separate: this result is conditional nonuniform existence, not a PV_1 generator or P!=NP proof.

R72 is a uniform one-step proof blueprint, not a completed bounded-arithmetic proof.
