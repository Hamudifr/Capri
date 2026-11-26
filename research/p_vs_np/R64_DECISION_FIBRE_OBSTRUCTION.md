# R64: direct decision anti-checker formalization and the Δ₂/sparsity obstruction

## Executive summary

R49's greedy-survivor proof gives a direct nonuniform **decision-circuit** anti-checker, which is closer to Pich–Santhanam's required object than the R51 search anti-checker. I explored whether its majority-sampling proof can be formalized by lifting survivor sets with Jeřábek Theorem 3.21 and applying approximate counting.

A useful weighted Chernoff encoding exists at the finite combinatorial level. However, the direct decision-error fibres are not generally Σᵇ₁-definable: deciding whether C(x) is wrong requires both SAT and UNSAT cases. They are Boolean combinations of Σᵇ₁ predicates (at the Δ₂/P^NP level). Jeřábek's relative Sipser-style counting theorems in Chapter II are for Σᵇ₁ sets, while the older ambient-additive counting framework can handle Δ₂ sets but loses precision on the exponentially sparse majority-error fibres.

This is a genuine obstacle to directly formalizing R49 with the current tools. It does not refute the nonuniform decision anti-checker theorem.

## 1. R49's external combinatorial argument

Let S be a nonempty set of size-s decision circuits for SAT_n. Put δ≈1/√s. If every input x had fewer than (1/2−δ)|S| erroneous circuits, then a uniformly sampled circuit errs on each x with probability below 1/2−δ. Sampling r=O(n/δ²)=O(ns) circuits and taking their majority gives, by Hoeffding plus a union bound over 2^n inputs, a fixed tuple whose majority decides SAT_n. The majority circuit has size O(rs)=O(ns²), below s³ for s≥Kn.

Contrapositively, some x has at least (1/2−δ)|S| erroneous circuits. Retain the circuits agreeing with SAT_n(x); the survivor set shrinks by a factor at most 1/2+δ. Repeating O(s log(n+s)) times gives a polynomial-size list of formulas defeating every size-s decision circuit. For each selected formula choose a valid witness if satisfiable, or any assignment if unsatisfiable. This yields exactly the *shape* of the nonuniform labelled decision anti-checker required by Pich–Santhanam.

This is an external finite proof. It does not give a feasible generator.

## 2. Weighted Chernoff encoding (finite combinatorics)

There is a compact way to express the majority-error tail without enumerating all 2^r error patterns.

Assume for a fixed x that F_x is the error subset of S and |F_x|/|S|≤1/2−1/m, where m≥4. Let G_x=S\F_x. Make a tagged set T_x consisting of m copies of each element of G_x and m+4 copies of each element of F_x.

For a tuple u∈S^r with at least r/2 error coordinates, the number of tag-lift preimages in T_x^r is at least

(m(m+4))^(r/2).

Because G_x and F_x partition S,

|T_x| = m|G_x|+(m+4)|F_x|
      = m|S|+4|F_x|
      ≤ (m+2−4/m)|S|.

Therefore the fraction of bad tuples is at most

ρ^r, where ρ=(m+2−4/m)/sqrt(m(m+4)).

For m≥4,

ρ² = 1 − (4+16/m−16/m²)/(m²+4m)
    ≤ 1 − 2/m²,

so ρ≤exp(−1/m²). Taking odd r≥m²(n ln 2+2) makes the bad-tuple fraction at most exp(−n ln 2−2), enough for a union bound over 2^n inputs.

The tag-lift is explicit: for a tuple with k error coordinates, its number of tag assignments is (m+4)^k m^(r−k). A mixed-radix encoding injects a fixed interval of length (m(m+4))^(r/2) into those tags whenever k≥r/2.

This is a potentially useful formalization of the Chernoff step, but it does not yet solve the definability problem below.

## 3. Why the fibre is not Σᵇ₁

For a fixed formula x, the decision-error fibre is

F_x={C∈S : C(x)≠SAT_n(x)}.

Its predicate splits into two cases:

- C(x)=0 and SAT_n(x)=1: there exists a satisfying assignment, a Σᵇ₁ condition.
- C(x)=1 and SAT_n(x)=0: there is no satisfying assignment, a Πᵇ₁ condition.

Their disjunction is generally a Boolean combination of Σᵇ₁ predicates, not a Σᵇ₁ predicate. Consequently, Theorems 3.19 and 3.20 cannot simply be applied to this family: their hypotheses require Σᵇ₁-definable sets.

A selected anti-checker label y_x would make SAT_n(x,y_x) a polynomial-time bit for that selected x. But the majority argument needs the error fibre for every x in the entire 2^n-input universe before the small anti-checker set has been constructed. Supplying a valid y_x for every satisfiable formula would itself amount to a global SAT search function, which is precisely what is not available.

## 4. Why Theorem 3.21 plus old counting does not immediately repair it

Jeřábek explicitly distinguishes:
- the older ambient-additive counting framework, which can count P^NP/poly (Δ₂) sets;
- the newer Sipser-style relative counting framework, which handles NP/poly (Σᵇ₁) sets with error relative to the set's own size.

Theorem 3.21 gives an almost-bijective PV₂ enumeration of a Σᵇ₁ survivor set. Pulling a Δ₂ decision-error fibre back through that enumeration still gives a Δ₂ set. The older framework can count it, but only with additive error relative to the ambient interval.

The majority-error tuple fibre is exponentially sparse: its density must be about 2^(-n) to union-bound over all 2^n formulas. Polynomially small ambient-additive precision is far too coarse to distinguish such a fibre from the empty set. Lifting the survivor set makes the circuit universe dense, but it does not make the majority-error event dense.

Primary source: Jeřábek, *Approximate counting by hashing in bounded arithmetic*, introduction pp.1–2 and Theorem 3.21 pp.18–19:
https://users.math.cas.cz/~jerabek/papers/hash.pdf

## 5. What this tells us about the two routes

| Route | Definability | Counting precision | Current status |
|---|---|---|---|
| Search anti-checker (R51/R56/R62) | Success/failure via witness verifier is PV/Σᵇ₁ | Relative Sipser counting applies | Better fit for APC₂, but search-to-decision remains open |
| Direct decision anti-checker (R49/R64) | Error fibre is generally BΣᵇ₁ / Δ₂ | Relative theorem does not directly apply; old counting is ambient-additive | External nonuniform proof is sound; bounded-arithmetic formalization blocked |
| Pich–Santhanam feasible anti-checker | Needs explicit labels and p-time generator | Requires S¹₂-provable output correctness | Not obtained |

## 6. Candidate ways forward (unproved)

1. Find a relative approximate-counting theorem for the relevant Δ₂ fibres at polynomial precision, without escalating the theory beyond the proof-complexity target.
2. Reformulate decision errors using a Σᵇ₁ relation plus labelled witnesses, without requiring a global witness selector for all satisfiable formulas.
3. Prove a search-to-decision conversion using a polynomial-size universal restriction family, avoiding the full exponential self-reduction tree.
4. Use a stronger proof system/theory and state honestly the corresponding weaker or different conclusion; this does not solve the EF/S¹₂ target.

## Status

- R49 nonuniform decision anti-checker: finite combinatorial proof, conditional on circuit hardness.
- Weighted Chernoff/tagging inequality: finite combinatorial derivation.
- Direct Σᵇ₁ formalization of decision-error fibres: unavailable.
- Theorem 3.21 lift + old ambient counting: insufficient for exponentially sparse majority-error fibres.
- R51/R56/R62 search route: still the better bounded-arithmetic route, but does not automatically give the Pich–Santhanam decision object.
- PV₁ generator, S¹₂ proof, KPS EF transfer, P≠NP: open.

R64 records an attempted route and its precise obstruction; it is not a new proof of P≠NP.
