# R57: a Sigma-2 induction blueprint for survivor iteration

## Objective

R56 repaired the one-step incidence argument and produced a constant-factor approximate survivor reduction. R57 investigates whether the history-dependent iteration can be formalized by the same bounded-induction mechanism Jeřábek uses in his tournament principle.

This is a proof blueprint, not a completed theorem. The main insight is that the approximate-size relation itself has the right formula complexity for a Sigma-2 induction, provided all certificates and the survivor history are packed into one polynomial-length string.

## 1. Source facts

Jeřábek's Definition 3.1 and Remark 3.2 state that if X is Sigma^b_1-definable, then X <=_epsilon s is Sigma^b_2. (The relation is defined using a polynomial-size family of hash matrices that isolates X^c.)

Theorem 4.2 (tournament principle) is proved by Sigma^b_2-LIND on a history-dependent sequence. At each step it:
- defines the current survivor set from the previous selected vertices;
- maintains an approximate-size upper bound;
- uses Theorem 3.17 to split a product relation;
- uses Theorem 3.20 to select the next vertex with a small fibre.

This is the right proof-theoretic template for our repeated survivor reduction. It is not automatically applicable; our one-step transition has to be written in the same formula class.

## 2. Survivor history and invariant

Fix n, circuit size s, r=n+1, epsilon=1/(1000r), and let C_{n,s} be the finite family of size-s search circuits.

For a history
H_i = ((x_0,w_0),...,(x_{i-1},w_{i-1})),
define

S_i(C) iff C in C_{n,s} and for every j<i, R(x_j,w_j)=1 and R(x_j,C(x_j))=1.

For fixed H_i this is a PV predicate (the history is a polynomial-length parameter and the verifier is polynomial time).

The intended invariant stores:
1. the history H_i and valid witnesses R(x_j,w_j)=1;
2. an approximate-size certificate S_i <=_epsilon b_i;
3. a Theorem 3.21 lower/upper pair a_i<=b_i<=ceil(a_i(1+epsilon)), with the section/retraction data for S_i;
4. the recurrence bound on b_i.

Because S_i is PV-definable, S_i <=_epsilon b_i is Sigma^b_2 by Remark 3.2. The hash certificates for all earlier stages can be packed into H_i, and their universal isolation checks combined into one bounded universal block. This is the intended way to keep the induction formula Sigma^b_2 rather than raising the alternation at every stage.

## 3. One-step transition

Assume S_i is nonempty and apply Theorem 3.21 with error epsilon, obtaining a_i,b_i and section/retraction maps.

### Large branch: a_i >= 100r

Set M_i=b_i,
A_i=ceil(ceil(3M_i/4)(1+2epsilon)).

R56's corrected incidence argument, using Theorems 3.17–3.20, gives a satisfiable formula x_i and witness w_i such that

R(x_i,w_i)=1, and
G_{i,x_i} <=_epsilon A_i,

where G_{i,x_i}={C in S_i:R(x_i,C(x_i))=1}.

Set S_{i+1}=G_{i,x_i}. Theorem 3.21 applied to S_{i+1} yields a lower parameter a_{i+1} no greater than A_i (using the minimality property in its proof), and an upper parameter

b_{i+1} <= ceil(A_i(1+epsilon)).

### Small branch: a_i < 100r

Then b_i<=ceil(a_i(1+epsilon))<=100r. Since 100r<=epsilon^{-1}, Corollary 3.10 gives an actual list of at most 100r circuits covering S_i.

If every satisfiable formula had a successful circuit in S_i, a first-valid-output selector running all circuits in this list would decide SAT with circuit size O(ns+n^2), contradicting SAT_n notin SIZE(s^3) under the fixed s>=Kn slack.

Therefore there exists a satisfiable x_i with G_{i,x_i}=empty, and S_{i+1}=empty. The iteration terminates.

## 4. Explicit recurrence and round bound

For the large branch,

A_i <= (3M_i/4)(1+2epsilon)+2+2epsilon,
b_{i+1} <= A_i(1+epsilon)+1.

Therefore

b_{i+1}/b_i
 <= (3/4)(1+2epsilon)(1+epsilon)
    + ((2+2epsilon)(1+epsilon)+1)/b_i.

For r>=2, epsilon=1/(1000r), and b_i>=a_i>=100r, the right side is <0.77. Thus every large step shrinks the upper parameter by at least a factor 0.77.

Initially b_0 can be chosen at most 2^(m+1), where m=O(s log(n+s)) is the circuit-description length: S_0 is contained in the 2^m possible descriptions, and Theorem 3.21's upper parameter adds only a factor 1+epsilon plus rounding. Hence at most

L = O(log(2^m/(100r))) = O(m)

large steps occur before the small branch is reached. If s is polynomial in n, L is polynomial in n. The final support contains at most L+1 satisfiable formulas with explicit witnesses.

## 5. Formula-complexity audit

The desired one-step statement is:

For every history H_i and valid approximate-size certificate for S_i, either S_i is empty, or there exist x,w such that
R(x,w)=1 and G_{i,x} <=_epsilon A_i,
under the formal SAT circuit-hardness hypothesis.

The conclusion is Sigma^b_2:
- x,w and the approximate-size hash certificate are existentially bounded;
- the isolation condition is universally bounded;
- all verifier and survivor predicates are PV.

The hardness hypothesis can be expressed as a universal family of Sigma^b_2 counterexample statements: for every decision circuit D of size at most s^3, there is an input z on which D disagrees with SAT. The disagreement predicate is Sigma^b_2 because a wrong positive answer has a satisfying witness, while a wrong negative answer asserts that no witness exists.

If the one-step lemma is established uniformly as a Sigma^b_2 consequence of this hardness hypothesis, Sigma^b_2-LIND in S^2_2(alpha)+sWPHP(PV2(alpha)) is a plausible way to construct the entire history. Jeřábek's Theorem 4.2 demonstrates this induction strength for a closely related repeated approximate-shrink process.

The final statement can be kept Sigma^b_2 by existentially packing the whole history and all per-stage approximate-size certificates into one string, then universally checking the certificates and that no circuit survives the final history. Do not write it as an unstructured nested sequence of separate Sigma^b_2 existential statements; that risks an unnecessary alternation increase.

## 6. Exact unresolved proof obligations

1. **One-step theorem statement:** Write the R56 contradiction argument as a uniform Sigma^b_2 implication with the history H_i as a parameter. Carefully formalize the selector circuit and the instantiation of the circuit-hardness hypothesis.
2. **Theorem 3.21 minimality:** Show from the proof's binary-search definition of its lower parameter that G_{i,x} <=_epsilon A_i implies a_{i+1}<=A_i. The theorem statement alone only displays the section/retraction bounds; the minimality fact is in its proof.
3. **Certificate packing:** Give an explicit polynomial bound on all hash-matrix certificates across O(m) rounds, and show their combined verification remains Sigma^b_2.
4. **Induction formula:** Write the exact Sigma^b_2 formula for a length-i history, including nonempty survivor set, selected SAT witnesses, approximate-size certificates, and recurrence.
5. **Terminal extraction:** Prove that the small-branch parallel selector contradiction yields a final satisfiable x with no successful circuit in S_i, in the same formula class.
6. **Theory transfer:** Verify the complete proof in S^2_2(alpha)+sWPHP(PV2(alpha)); then state exactly which ∀Sigma^b_2 consequence transfers to T^1_2(alpha)+rWPHP(PV2(alpha)).

## 7. What this would and would not establish

If completed, R57 would turn the R56 one-step result into a bounded-arithmetic proof of a polynomial-size nonuniform **search anti-checker**: a polynomial-size list of satisfiable formulas with valid witnesses such that every size-s search circuit fails on at least one listed formula.

It would still not automatically provide:
- a polynomial-time uniform generator for the anti-checker list;
- the Pich–Santhanam decision-circuit anti-checker with its structured assignment-label relation;
- KPS's short EF transfer certificates;
- a proof of P != NP.

The search-to-decision interface and the EF proof-certificate gap remain separate.

## Primary sources

- Jeřábek, *Bounded Arithmetic and Complexity*, Definition 3.1 and Remark 3.2 (PDF p. 70): https://users.math.cas.cz/~jerabek/papers/dsc.pdf
- Jeřábek, Theorem 3.20 (PDF p. 80), explicit PV2 interval-search construction.
- Jeřábek, Theorem 3.21 (PDF pp. 80–82), approximate enumeration and section/retraction maps.
- Jeřábek, Theorem 4.2 (PDF pp. 84–85), tournament principle using Sigma^b_2-LIND.

## Status

- Sigma^b_2 complexity of approximate-size relation: source-verified.
- Theorem 4.2 as a history-dependent induction template: source-verified.
- Survivor history and recurrence: derived as a candidate.
- Full one-step Sigma^b_2 theorem: not yet formalized.
- Certificate packing and exact induction invariant: open.
- Bounded-arithmetic search anti-checker: not yet proved.
- Uniform generator, decision anti-checker, KPS EF transfer, P != NP: open.
