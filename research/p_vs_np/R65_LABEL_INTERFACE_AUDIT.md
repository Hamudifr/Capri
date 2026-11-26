# R65: exact Pich–Santhanam label interface and the remaining Δ₂ barrier

## Executive correction

The direct R49 decision-circuit anti-checker already has the correct *nonuniform object shape* required by Pich–Santhanam Theorem 7. It does not need to be converted from the R51 search anti-checker.

What is missing is feasible generation and an S¹₂ proof of correctness. In particular, the assignment labels must be generated so that every satisfiable formula in the selected anti-checker set receives a satisfying assignment; unsatisfiable formulas may receive arbitrary labels. The finite nonuniform proof can choose these labels after the formula set is known, but that choice is not yet a polynomial-time generator.

This sharpens R63/R64: search-to-decision conversion is not needed to match the *nonuniform target*. The unresolved issue is the feasible/ bounded-arithmetic realization of the decision anti-checker.

## 1. Exact Theorem 7 interface

Primary source: Ján Pich and Rahul Santhanam, *Towards P≠NP from Extended Frege lower bounds*, arXiv:2312.08163 / ECCC TR23-199:
https://users.ox.ac.uk/~coml0742/papers/eopt.pdf

Theorem 7 requires a p-time function f such that S¹₂ proves that f(1ⁿ) outputs either:
- a polynomial-size search circuit B solving SATₙ; or
- sets A⊆{0,1}ⁿ, A′⊆{0,1}ⁿ, and D⊆A×A′ of polynomial size, where each x∈A has a unique associated label yₓ∈A′, the label is valid whenever x is satisfiable, and every target decision circuit C errs on at least one labelled x.

The label condition is:
∀x∈A [∃yₓ∈A′, (x,yₓ)∈D ∧ uniqueness]
and
∀x∈A ∀y [SATₙ(x,y)→SATₙ(x,yₓ)].
The anti-checker condition is:
∀C ∃x∈A, SATₙ(x,yₓ)≠C(x).

The relation D makes the labels a uniquely associated polynomial-size table. The universal implication says that yₓ must be satisfying if x has any satisfying assignment. If x is unsatisfiable, every yₓ satisfies this implication vacuously, and SATₙ(x,yₓ)=0.

The complete correctness statement is ∀Πᵇ₁, which is why an S¹₂ proof gives polynomial-size EF proofs of its propositional translations.

## 2. R49 matches the nonuniform combinatorial object

R49 assumes SATₙ has no circuit of size s³ and considers a nonempty set S of size-s decision circuits.

If every x had fewer than (1/2−δ)|S| erroneous circuits, δ=1/√s, sample
t=ceil((n ln2+1)/(2δ²))=O(ns)
circuits independently. Hoeffding plus a union bound over all 2ⁿ inputs gives a fixed tuple whose majority decides SATₙ. The majority circuit has size O(ns²)≤s³ for sufficiently large s≥Kn, contradiction.

Thus some x has at least (1/2−δ)|S| erroneous circuits. Retain the circuits agreeing with SATₙ(x), shrinking S by at most 1/2+δ≤3/4. Repeating O(s log(n+s)) times gives a polynomial-size formula set A defeating every size-s decision circuit.

After A is fixed, choose one label yₓ for each x∈A:
- if x is satisfiable, choose a satisfying assignment;
- if x is unsatisfiable, choose any n-bit string.

Then the label condition holds, and each circuit C is wrong on at least one selected formula relative to SATₙ(x,yₓ)=SATₙ(x). Set D to the graph of this finite label map. Thus the R49 object has exactly the nonuniform shape of Theorem 7.

This does not make the construction feasible. The sequence of selected formulas and labels is existential/nonuniform.

## 3. Why the Δ₂ obstacle remains

For a fixed formula x and a candidate label y, define:

Label(x,y) := ∀w<2ⁿ [SATₙ(x,w)→SATₙ(x,y)].

This is a Πᵇ₁ condition. It is equivalent to “if x is satisfiable, then y is satisfying.” The error relation for a circuit C can be written using Label(x,y) together with the polynomial-time bit inequality SATₙ(x,y)≠C(x).

But the relation of valid labels is not Σᵇ₁ in general. The universal quantifier over all candidate witnesses is essential: it rules out choosing an invalid y for a satisfiable x. The finite fact that every x has some valid label follows by classical case distinction (if satisfiable choose a witness, otherwise choose anything), but a uniform polynomial-time algorithm producing such labels for all x would solve SAT search.

The direct decision-majority argument needs to reason about the correct SAT bit for every formula in the full 2ⁿ-input universe before it has constructed the polynomial-size set A. It cannot simply assume a valid label table for all x: that would be a global SAT search function. Labels only for the final polynomial-size A are harmless nonuniformly, but the current fibre-counting proof needs the SAT bit over the entire universe.

Thus the R64 Δ₂ definability issue is not removed by observing that the final anti-checker labels are polynomially many. The obstacle lies earlier, in the global majority-error fibres.

## 4. Search anti-checker route remains distinct

The R51/R56/R62 search anti-checker counts success/failure using the PV witness verifier. Its fibres are Σᵇ₁-definable, so Jeřábek's relative counting framework applies. But it only defeats search circuits: a decision circuit C can be transformed into a search circuit by self-reduction, yet the queried restricted formulas depend on C's answers. A fixed support containing every possible restriction can be exponential.

Therefore:
- R49: correct nonuniform decision anti-checker shape, but direct bounded-arithmetic formalization encounters Δ₂ fibres.
- R51/R56/R62: Σᵇ₁-friendly search anti-checker route, but no polynomial-support conversion to the decision anti-checker has been found.
- Pich–Santhanam feasible anti-checker: requires a single p-time generator and S¹₂ proof, not merely either nonuniform object.

## 5. Refined research targets

1. **Direct Δ₂ relative counting:** Find a Sipser-style relative counting theorem for the relevant Δ₂/Boolean-combination fibres at polynomial precision, with a theory/proof strength compatible with the intended EF consequence.
2. **Label-first reformulation:** Find a way to make the decision-error relation Σᵇ₁ using only polynomially many labels, without assuming a global label function over all formulas.
3. **Feasible construction:** Construct a PV₁ generator for the R49-style anti-checker set and labels, or prove an appropriate conditional generator theorem. It must compute the next hard formula without enumerating all candidate circuits or querying SAT.
4. **Do not conflate targets:** A nonuniform decision anti-checker, an existential bounded-arithmetic anti-checker, and a feasible anti-checker generator are three different achievements.

A useful test for any proposed label-first approach: state the formula defining the bad fibre, give its exact bounded-quantifier class, and identify how its relative cardinality is proved. If the definition silently quantifies over all SAT witnesses or assumes labels for every input, the original obstruction has not been removed.

## Status

- R49 finite nonuniform decision anti-checker: conditional proof established.
- R49 output shape vs Pich–Santhanam Theorem 7: exact match at the nonuniform object level.
- Polynomial-size final label table: exists nonuniformly by finite choice.
- PV₁ generator for formulas and labels: not constructed.
- S¹₂ proof of generator correctness: not obtained.
- Direct relative counting for Δ₂ decision-error fibres: open.
- R51/R56/R62 search route: separate, Σᵇ₁-friendly, but decision conversion open.
- KPS EF transfer certificates: open.
- P≠NP: not proved.

R65 corrects the diagnosis of the interface. It does not close the feasible-generation or Δ₂ counting gaps.
