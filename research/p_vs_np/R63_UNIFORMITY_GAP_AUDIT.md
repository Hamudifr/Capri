# R63: uniformity gap between approximate-counting existence and feasible anticheckers

## Executive finding

R62's corrected incidence argument is compatible with Jeřábek's Theorems 3.19 and 3.20. Theorem 3.19 genuinely handles a large uniformly described family of fibres; it does not require an explicit polynomial-length list of one certificate per formula. The remaining major gap is now sharper:

**The bounded-arithmetic existence argument is not a polynomial-time anti-checker generator.**

Jeřábek's machinery is carried out in theories using PV₂ functions and sWPHP(PV₂). PV₂ corresponds to FP^NP. The relevant theorems establish existence statements and use higher-level counting/induction; they do not supply a PV₁ (ordinary polynomial-time) function that, on input 1^n, outputs the anti-checker set and valid assignment labels required by Pich–Santhanam.

This is not a cosmetic implementation detail. Pich–Santhanam's feasible-antichecker theorem explicitly requires a p-time function f and an S¹₂ proof that f(1^n) outputs either a globally correct search circuit or the anti-checker objects with assignment labels. Their KPT discussion explains why replacing that function by existential quantifiers is not automatic: KPT yields a constant adaptive list of functions, and later outputs depend on earlier challenges.

## 1. What the primary sources actually establish

### Jeřábek Theorem 3.19

Primary source: Emil Jeřábek, *Approximate counting by hashing in bounded arithmetic* (2008/2009), pp. 17–18:
https://users.math.cas.cz/~jerabek/papers/hash.pdf

Theorem 3.19 states: for Σᵇ₁-definable X,Y,Z with Z⊆X×Y, if X≼εs and every fibre Z_x={y∈Y:(x,y)∈Z} satisfies Z_x≼εt, then Z≼ceil(st(1+4ε)).

Its proof partitions the first coordinate's ambient interval into dyadic subintervals and controls the corresponding incidence slices. The naive proof needs Πᵇ₂-LIND and is not itself a ∀Σᵇ₂ statement. Jeřábek then replaces the naive induction by a PV₂-computed interval-search function and a lower-complexity induction. This is precisely why R58's literal certificate-packing objection is not a necessary obstacle: the theorem handles a uniformly defined family of exponentially many fibres.

Theorem 3.19 is available as an internal lemma in a sufficiently strong theory containing its stated T¹₂(α)+sWPHP(PV₂(α)) proof. Its non-∀Σᵇ₂ status still matters for standalone conservation, but does not prohibit its internal use in a proof of a different low-complexity conclusion.

### Jeřábek Theorem 3.20

Same primary source, pp. 18–19. The theorem states:
If Z⊆X×Y and Z≼ε st, then either X≼s−1 or some x∈X has fibre size approximately at most ceil(t(1+2ε)).

The proof is formalized in S²₂(α)+sWPHP(PV₂(α)); its result is ∀Σᵇ₂ and therefore transfers to T¹₂(α)+rWPHP(PV₂(α)) by Theorem 2.1. For t=1, the bound is 2, not 1. R62 correctly repaired this by appending at most two circuits.

### PV₂ is not PV₁

Jeřábek's preliminaries identify PV_{i+1} functions with FP^{ΣP_i}; therefore PV₂ corresponds to FP^NP. Theorems 3.19 and 3.20 rely on PV₂ machinery and weak pigeonhole principles for PV₂ functions. The fact that their formal conclusions are true and provable does not yield a uniform polynomial-time construction in PV₁.

## 2. Exact Pich–Santhanam requirement

Primary source: Ján Pich and Rahul Santhanam, *Towards P≠NP from Extended Frege lower bounds*, ECCC TR23-199 / arXiv:2312.08163:
https://users.ox.ac.uk/~coml0742/papers/eopt.pdf

Theorem 7 (paper pp. 18–19) assumes a **p-time function f** such that S¹₂ proves that, on input 1^n, f outputs either:
1. a polynomial-size search circuit B solving SAT_n; or
2. anti-checker sets A, A' and a relation D, all of polynomial size, where A' contains valid assignment labels y_x for the formulas x∈A, the relation uniquely associates labels to formulas, and every n^k-size decision circuit C is wrong on at least one labelled formula.

The statement is ∀Πᵇ₁ so its propositional translation has polynomial-size EF proofs. If SAT had polynomial-size circuits for all large n, the anti-checker branch would be falsified, forcing the generated B to solve SAT; this self-provability yields the proof-complexity consequence.

Pich–Santhanam explicitly discuss replacing the p-time function by existential quantifiers. Their KPT extraction gives a constant list f₁,…,f_c with adaptive dependence: f₂ depends on the first challenge, f₃ on previous challenges, etc. They explain that this does not immediately yield a single fixed generator or a short proof that one of those functions produces a SAT solver. Thus the exact uniformity/witnessing obstacle is already identified in the primary literature.

## 3. What R62 can and cannot contribute

The intended R62 local disjunction is D(n,s) OR shrink, where D is existence of a globally correct search circuit of size L(n,s), and shrink is existence of a satisfying formula/witness pair whose success fibre is approximately small.

Under the assumed SAT decision-circuit lower bound, D is impossible because a globally correct search circuit plus the polynomial-time witness verifier yields a SAT decision circuit of size at most s³. Thus the local disjunction conditionally gives a shrink witness.

Iterating the shrink can produce an existential polynomial-size history H whose labelled formulas defeat every size-s search circuit. This is a nonuniform anti-checker existence statement, provided the formal induction and parameter propagation are completed.

However:
- A proof in S²₂+sWPHP(PV₂), followed by ∀Σᵇ₂ conservation to T¹₂+rWPHP(PV₂), does not give an S¹₂ proof.
- T¹₂/PV₂ resources are FP^NP-level, not ordinary P-time.
- The history H is existentially quantified. No PV₁ algorithm generating H has been constructed.
- The final object must also be converted to the Pich–Santhanam decision anti-checker with its structured, unique assignment-label relation D. The current search anti-checker has explicit witnesses, but the exact conversion to their object is still open.
- Even a completed existential anti-checker theorem is therefore not yet a feasible anti-checker theorem in the Pich–Santhanam sense.

## 4. A possible but unproved route to close the uniformity gap

The next target should be stronger than “there exists a history H”:

Find a single PV₁ function G(1^n) which outputs a polynomial-size history H_n and its witness labels, and prove in S¹₂ that:
- every formula in H_n is satisfiable with its supplied label;
- for every size-s search circuit C, some formula in H_n defeats C;
- the encoding/label relation has the uniqueness and totality properties required by Pich–Santhanam.

Possible directions, none established:

1. **PV₁-computable approximate counting:** replace the PV₂ hashing/selection steps by an APC₁-level construction with polynomial precision. Pich–Santhanam explicitly identify a feasible MinMax theorem using only APC₁-counting as a missing ingredient.
2. **Direct constructive anti-checker algorithm:** derive a polynomial-time algorithm that builds the survivor-eliminating list without asking NP-oracle approximate-size questions. This must avoid exponential enumeration and must be proved under the circuit-hardness hypothesis.
3. **KPT adaptive-to-static compression:** show that the adaptive list produced from a bounded-arithmetic proof can be compressed into one fixed generator using the special monotonicity/selector structure of SAT anti-checkers. Pich–Santhanam explain why the generic KPT output does not do this.
4. **Stronger conclusion with explicit function:** redesign the induction invariant so that the shrink formula and witness are output by a PV₁ function rather than merely existentially selected. No such selector is currently known.

A useful falsification test for every proposed route: if it claims to output H_n in polynomial time, identify exactly how it computes each next formula x_i without evaluating an exponentially large survivor set or using an NP oracle.

## 5. Status after R63

| Component | Status |
|---|---|
| R56/R62 finite incidence and rounding skeleton | Corrected conditional argument; formal proof still open |
| Jeřábek Theorem 3.19 handles large fibre families | Source-verified |
| Theorem 3.20 exceptional fibre t=1 | At most two; source-verified |
| Local D OR shrink disjunction | Candidate formal lemma |
| Iterated existential nonuniform search anti-checker | Candidate, formal induction open |
| PV₁ polynomial-time anti-checker generator | Not constructed |
| S¹₂ proof required by Pich–Santhanam | Not obtained |
| Search-to-decision conversion and unique label relation | Open |
| KPS EF transfer certificates | Open |
| P≠NP | Not proved |

R63 is a source-grounded diagnosis of the uniformity/witnessing gap, not a proof of an anti-checker theorem or P≠NP.
