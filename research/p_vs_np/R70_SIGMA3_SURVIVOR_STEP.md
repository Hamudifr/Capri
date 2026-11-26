# R70: Σᵇ₃ survivor step and bounded-induction route

## Purpose

R70 uses Jeřábek's Theorem 3.17 to convert the R69 incidence contradiction into the exact kind of successor statement needed for a history induction: not “some error fibre is large,” but “some next survivor set has a certified approximate upper bound.”

This repairs an important formula-class issue. The one-step conclusion can be written as an existential Σᵇ₃ statement, making (S^3_2) a plausible induction theory. The complete history proof is not yet formalized, and no P≠NP or EF conclusion is claimed.

Primary source: Emil Jeřábek, *Approximate counting by hashing in bounded arithmetic*, https://users.math.cas.cz/~jerabek/papers/hash.pdf, especially Theorem 3.17, Theorem 3.19, Theorem 3.21, and Theorem 2.1.

## 1. Survivor partition and Theorem 3.17

Fix a current survivor set (S) of size-s decision circuits and a formula (x). Partition it into:
- (F_x={Cin S:C(x)
e SAT_n(x)}), the erroneous circuits;
- (G_x=S\setminus F_x), the agreeing circuits and next survivor set.

Both predicates are Σᵇ₂ when the SAT decision predicate is represented by a Σᵇ₁ oracle α. The decision-error predicate is Δᵇ₂, so the partition map (C\mapsto(C,mathrm{Err}(C,x))) is PV₃(α).

If (S\preceq_\delta M), Corollary 3.11 transfers this bound through the PV₃ bijection between (S) and the tagged disjoint union (F_x\dot\cup G_x). Use
(M^\sharp=\lceil M(1+\delta)\rceil)
as the disjoint-union upper parameter.

Jeřábek Theorem 3.17 says that if (X\dot\cup Y\preceq_\delta s+t+1), then
(X\preceq_\delta\lceil s(1+2\delta)\rceil)
or
(Y\preceq_\delta\lceil t(1+2\delta)\rceil).

Set
- (q=\lfloor \theta s_0/(1+\delta)\rfloor), where (\theta=1/2-1/(2m));
- (s_F=\lfloor q/(1+2\delta)\rfloor);
- (t_G=M^\sharp-s_F-1);
- (A=\lceil t_G(1+2\delta)\rceil).

Then (s_F+t_G+1=M^\sharp) and
\(\lceil s_F(1+2\delta)\rceil\le q\).
Therefore Theorem 3.17 gives, for every x,
(F_x\preceq_\delta q\) or (G_x\preceq_\delta A\).

The R69 global incidence contradiction proves that the first alternative cannot hold for every x: if every (F_x\preceq_\delta q), then the mixed-radix/tagged-fibre argument produces a tuple whose majority decides SAT, contradicting the assumed size-s³ SAT circuit lower bound. Hence:
**There exists x with (G_x\preceq_\delta A).**

This is the desired next-survivor statement. It is materially better than concluding only that (F_x) is not approximately small: (G_x\preceq A) is itself a positive approximate-size certificate.

## 2. Quantitative survivor shrink

In the large branch (s_0\ge100r), Theorem 3.21 gives
(s_0\le |S|\le M\) and (M/s_0\le1+\kappa), with
(\delta=1/(1000r)), (\kappa=1/(50r)), (r\ge m^3(n\ln2+12)), and (m\ge4).

From the definitions:
[
A\le M^\sharp(1+2\delta)-q+1
\le M(1+\delta)(1+2\delta)+3-q.
]
Also
[
q\ge \frac{\theta s_0}{1+\delta}-1
\ge \frac{\theta M}{(1+\kappa)(1+\delta)}-1.
]
Since (\theta\ge3/8), this gives
[
\frac AM
\le \frac58+3\delta+2\delta^2
+\frac38(\kappa+\delta+\kappa\delta)+\frac3M
<0.626<0.63.
]
The bound uses (M\ge100r), (r\ge4^3(\ln2+12)>800). Thus (A\le0.63M).

Applying Theorem 3.21 to (G_x), with enumeration precision (\epsilon_0=1/(100r)), gives
(M_{next}\le\lceil A(1+\epsilon_0)\rceil\le0.64M).

### Small branch

If (s_0<100r), then Theorem 3.21 gives (M\le100r+2) and a PV₃ enumeration of S with at most M entries. Deduplicate the list to obtain the distinct survivor circuits. If no x had (G_x\preceq\lfloor M/2\rfloor), then (|G_x|>M/2\ge|S|/2) for every x. The majority of the distinct S circuits would decide SAT. Its size is (O(Ms)=O(rs)\le s^3), contradicting the circuit-hardness hypothesis. Therefore some x has
(G_x\preceq\lfloor M/2\rfloor),
and the next Theorem 3.21 upper parameter is at most (0.51M) (for the stated large r).

Thus every nonterminal round shrinks the upper survivor parameter by at least a factor 0.64. The process terminates after (O(\log M_0)) rounds.

## 3. Formula class and induction target

For a Σᵇ₂-definable set, Jeřábek's approximate-size predicate is Σᵇ₃ after relativization. The positive conclusion
(\exists x\;(G_x\preceq_\delta A))
remains Σᵇ₃: the bounded existential x can be included in the leading existential block of the hash-isolation certificate.

This avoids the worse-looking formula (\exists x\neg(F_x\preceq q)), whose quantifier complexity is not the right induction target.

The natural bounded-arithmetic route is:
1. Relativize Jeřábek's counting toolbox to Σᵇ₂ sets, using PV₃ and (T^2_2+sWPHP(PV_3)).
2. Use Theorem 3.17 for the positive Σᵇ₃ successor statement. Its proof uses (BB\Sigma^b_3(\alpha)); after the Σᵇ₁ substitution this becomes (BB\Sigma^b_4).
3. Encode the history of selected formulas and each stage's approximate-size/hash certificate in one polynomial-length string.
4. Use (S^3_2+sWPHP(PV_3)), which supports Σᵇ₃ length induction and (BB\Sigma^b_4), to iterate the successor step for (O(\log M_0)) rounds.
5. Check whether the resulting universal closure is within the exact ∀Σᵇ₃ conservation scope of Theorem 2.1, yielding a statement in (T^2_2+rWPHP(PV_3)).

The initial circuit universe has at most (2^{O(s\log(n+s))}) descriptions, so (\log M_0=O(s\log(n+s))). Each round adds one n-bit formula and polynomially many hash-matrix bits; the total history remains polynomial length.

## 4. What this would and would not establish

If the uniform one-step implication and history invariant are fully formalized, the result would be a bounded-arithmetic proof of a polynomial-size **nonuniform labelled decision anti-checker**, conditional on the absence of size-s³ SAT circuits. For each selected formula, attach a satisfying assignment if satisfiable and any assignment if unsatisfiable; every size-s circuit is wrong on at least one selected formula.

This still does not provide:
- a PV₁ / polynomial-time generator;
- an S¹₂ proof of the generator's correctness;
- an unconditional SAT circuit lower bound;
- the Pich–Santhanam feasible-function hypothesis;
- KPS short EF transfer certificates;
- an EF lower bound or P≠NP.

In particular, the anti-checker is conditional on the same circuit-hardness premise; the argument does not eliminate the SAT-solver branch under P=NP.

## 5. Exact open obligations

1. Write the R69 incidence contradiction as a uniform theorem with survivor-history parameters and the correct Σᵇ₂(α) set definitions.
2. Verify the PV₃ partition bijection (S\leftrightarrow F_x\dot\cup G_x) and its use in Corollary 3.11, including the exact (M^\sharp) ceiling.
3. Prove the large-branch A/M inequality with all ceilings, and verify the small-branch enumeration/deduplication circuit bound.
4. Write the exact Σᵇ₃ history invariant, including the stage hash certificates and Theorem 3.21 parameter maps.
5. Verify the (S^3_2+sWPHP(PV_3)) induction and (BB\Sigma^b_4) collection step.
6. Check the precise ∀Σᵇ₃ conservation statement; do not assume the existential anti-checker conclusion transfers automatically.
7. Investigate PV₁/S¹₂ descent and the KPS/EF bridge separately.

R70 is an induction blueprint with a positive Σᵇ₃ successor target, not a completed bounded-arithmetic anti-checker theorem.
