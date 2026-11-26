# R70: Sigma-3 survivor step and bounded-induction route

## Purpose

R70 uses Jeřábek's Theorem 3.17 to convert the R69 incidence contradiction into the exact successor statement needed for a history induction: not merely “some error fibre is large,” but “some next survivor set has a certified approximate upper bound.”

This repairs an important formula-class issue. The one-step conclusion can be written as an existential Sigma-b-3 statement, making S^3_2 a plausible induction theory. The complete history proof is not yet formalized, and no P≠NP or EF conclusion is claimed.

Primary source: Emil Jeřábek, *Approximate counting by hashing in bounded arithmetic*, https://users.math.cas.cz/~jerabek/papers/hash.pdf, especially Theorem 3.17, Theorem 3.19, Theorem 3.21, and Theorem 2.1.

## 1. Survivor partition and Theorem 3.17

Fix a current survivor set S of size-s decision circuits and a formula x. Partition it into:
- F_x = { C in S : C(x) != SAT_n(x) }, the erroneous circuits;
- G_x = { C in S : C(x) = SAT_n(x) }, the agreeing circuits and next survivor set.

Both predicates are Sigma-b-2 when the SAT decision predicate is represented by a Sigma-b-1 oracle alpha. The decision-error predicate is Delta-b-2, so the partition map C -> (C, Err(C,x)) is PV_3(alpha).

Run Theorem 3.21 with enumeration precision epsilon_0 = delta = 1/(1000r). In the large branch, s_0 >= 100r, its ceiling gives M/s_0 <= 1 + delta + 1/s_0 <= 1 + kappa, where kappa = 1/(50r). The PV_3 surjection [M] -> S supplied by Theorem 3.21 gives S <=_delta M directly by Corollary 3.5, at the same precision used by the incidence argument.

The partition map is a PV_3 bijection between S and the tagged disjoint union F_x dotcup G_x. Corollary 3.11 transfers the approximate upper bound through this bijection. Use
M_sharp = ceil(M(1+delta))
as the disjoint-union upper parameter.

Jeřábek Theorem 3.17 says that if X dotcup Y <=_delta s+t+1, then
- X <=_delta ceil(s(1+2delta)), or
- Y <=_delta ceil(t(1+2delta)).

Set:
- theta = 1/2 - 1/(2m);
- q = floor(theta*s_0/(1+delta));
- s_F = floor(q/(1+2delta));
- t_G = M_sharp - s_F - 1;
- A = ceil(t_G(1+2delta)).

Then s_F+t_G+1=M_sharp and ceil(s_F(1+2delta))<=q. Therefore Theorem 3.17 gives, for every x:
F_x <=_delta q OR G_x <=_delta A.

The R69 global incidence contradiction proves that the first alternative cannot hold for every x. If every F_x <=_delta q, the mixed-radix/tagged-fibre argument produces a tuple whose majority decides SAT, contradicting the assumed size-s^3 SAT circuit lower bound. Hence:
**There exists x with G_x <=_delta A.**

This is the desired next-survivor statement. It is materially better than concluding only that F_x is not approximately small: G_x <= A is itself a positive approximate-size certificate.

## 2. Quantitative survivor shrink

In the large branch s_0 >= 100r, Theorem 3.21 gives s_0 <= |S| <= M and M/s_0 <= 1+kappa, with delta=1/(1000r), kappa=1/(50r), r >= m^3(n ln 2+12), and m >= 4.

From the definitions:
A <= M_sharp(1+2delta)-q+1
  <= M(1+delta)(1+2delta)+3-q.
Also:
q >= theta*s_0/(1+delta)-1
  >= theta*M/((1+kappa)(1+delta))-1.

Since theta >= 3/8, this gives:
A/M <= 5/8 + 3delta + 2delta^2
       + (3/8)(kappa+delta+kappa*delta) + 4/M
     < 0.626 < 0.63.
The bound uses M >= 100r and r >= 4^3(ln 2+12) > 800. Thus A <= 0.63M.

To propagate the upper parameter without assuming a minimality property, use Theorem 3.21's lower section/retraction pair for G_x. If its lower parameter is a_next, Theorem 3.8 applied to G_x <=_delta A gives a PV_3 surjection [d]^c -> G_x^c with d=ceil(A(1+delta)). Compose with the retraction G_x^c -> [a_next]^c. sWPHP(PV_3) forces a_next<=d. Theorem 3.21 then gives M_next<=ceil(a_next(1+delta))<=ceil(ceil(A(1+delta))(1+delta))<=0.64M. The extra multiplicative loss and both ceilings fit well inside the 0.64 target for M>=100r.

### Small branch

If s_0 < 100r, Theorem 3.21 gives M <= 100r+2 and a PV_3 enumeration of S with at most M entries. Deduplicate to obtain the distinct survivor circuits. If no x had G_x <=_delta floor(M/2), then |G_x|>M/2>=|S|/2 for every x. The majority of the distinct S circuits would decide SAT. Its size is O(Ms)=O(rs)<=s^3, contradicting circuit hardness. Therefore some x has:
G_x <=_delta floor(M/2).

In this branch the filtered, deduplicated enumeration gives an exact list of the next survivors. Its next upper parameter can be taken to be |G_x|<=floor(M/2), avoiding a rounding stall when M is very small.

Thus every nonterminal round shrinks the upper survivor parameter by at least a factor 0.64. The process terminates after O(log M_0) rounds.

## 3. Formula class and induction target

For a Sigma-b-2-definable set, Jeřábek's approximate-size predicate is Sigma-b-3 after relativization. The positive conclusion:
there exists x such that G_x <=_delta A
remains Sigma-b-3: the bounded existential x can be included in the leading existential block of the hash-isolation certificate.

This avoids the worse-looking formula “there exists x such that NOT(F_x <= q),” whose quantifier complexity is not the right induction target.

The natural bounded-arithmetic route is:
1. Relativize Jeřábek's counting toolbox to Sigma-b-2 sets, using PV_3 and T^2_2+sWPHP(PV_3).
2. Use Theorem 3.17 for the positive Sigma-b-3 successor statement. Its proof uses BB-Sigma-b-3(alpha); after the Sigma-b-1 substitution this becomes BB-Sigma-b-4.
3. Encode the history of selected formulas and each stage's approximate-size/hash certificate in one polynomial-length string.
4. Use S^3_2+BB-Sigma-b-4+sWPHP(PV_3) to iterate the successor step for O(log M_0) rounds.
5. Check whether the resulting universal closure is within the exact forall-Sigma-b-3 conservation scope of Theorem 2.1, yielding a statement in T^2_2+rWPHP(PV_3).

At parameter 0, Definition 3.1 explicitly stipulates S_T <=_delta 0 iff S_T is empty; it is not a hash-matrix certificate. This does not raise the final formula beyond Sigma-b-3: S_T(C) is Sigma-b-1(alpha), so emptiness forall C not-in-S_T(C) is Pi-b-1(alpha). The stage hash-isolation verifications are also Pi-b-1(alpha). Pack the history and all stage hash matrices into one leading existential string, then combine the universal verifications and terminal emptiness into one Pi-b-1(alpha) block. The resulting history-existence statement is Sigma-b-2(alpha), hence Sigma-b-3 after alpha is instantiated by SAT. This is the correct terminal encoding; do not describe S_T <=_delta 0 as a positive hash certificate.

### Conservation-formula check

Let Hard(n,s) be the assertion that every size-s^3 decision circuit has an n-bit counterexample. Since Err(C,x) is Delta-b-2, Hard is Pi-b-3; its negation is Sigma-b-3. If the packed history certificate Cert(n,s,H) is Sigma-b-3 as above, then Hard -> exists H Cert is equivalent to not-Hard OR exists H Cert, also Sigma-b-3. Its universal closure over n,s is therefore a candidate forall-Sigma-b-3 statement. Jeřábek Theorem 2.1 with i=1, followed by substituting the SAT Sigma-b-1 predicate for alpha, gives exactly the conservation route from S^3_2+BB-Sigma-b-4+sWPHP(PV_3) to T^2_2+rWPHP(PV_3). This matches the target class; the remaining task is to prove that the fully packed history certificate really has the stated Sigma-b-3 form and that S^3_2 proves it.

The initial circuit universe has at most 2^(O(s log(n+s))) descriptions, so log M_0=O(s log(n+s)). Each round adds one n-bit formula and polynomially many hash-matrix bits; the total history remains polynomial length.

## 4. What this would and would not establish

If the uniform one-step implication and history invariant are fully formalized, the result would be a bounded-arithmetic proof of a polynomial-size **nonuniform labelled decision anti-checker**, conditional on the absence of size-s^3 SAT circuits. For each selected formula, attach a satisfying assignment if satisfiable and any assignment if unsatisfiable; every size-s circuit is wrong on at least one selected formula.

This still does not provide:
- a PV_1 / polynomial-time generator;
- an S^1_2 proof of the generator's correctness;
- an unconditional SAT circuit lower bound;
- the Pich-Santhanam feasible-function hypothesis;
- KPS short EF transfer certificates;
- an EF lower bound or P≠NP.

In particular, the anti-checker is conditional on the same circuit-hardness premise; the argument does not eliminate the SAT-solver branch under P=NP.

## 5. Exact open obligations

1. Write the R69 incidence contradiction as a uniform theorem with survivor-history parameters and the correct Sigma-b-2(alpha) set definitions.
2. Verify the PV_3 partition bijection S <-> F_x dotcup G_x and its use in Corollary 3.11, including the exact M_sharp ceiling.
3. Prove the large-branch A/M inequality with all ceilings, and verify the small-branch enumeration/deduplication circuit bound.
4. Write the exact Sigma-b-3 history invariant, including the stage hash certificates and Theorem 3.21 parameter maps.
5. Verify the S^3_2+BB-Sigma-b-4+sWPHP(PV_3) induction and collection step.
6. Complete the packed history certificate and verify its universal closure is genuinely forall-Sigma-b-3; then apply Theorem 2.1's i=1 conservation theorem after substituting SAT for alpha.
7. Investigate PV_1/S^1_2 descent and the KPS/EF bridge separately.

R70 is an induction blueprint with a positive Sigma-b-3 successor target, not a completed bounded-arithmetic anti-checker theorem.
