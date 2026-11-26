# R66: lifting the direct decision anti-checker to APC₃

## Executive finding

R64's definability obstruction is real for APC₂, but it is not an absolute obstruction to relative approximate counting. Jeřábek's hierarchy relativizes: APC₂ counts Σᵇ₁-definable sets, while APC₃ counts Σᵇ₂-definable sets with relative (Sipser-style) precision. The decision-error fibre is Δᵇ₂, hence in particular Σᵇ₂. Therefore the direct R49 decision anti-checker is a plausible candidate for an APC₃ formalization.

The price is proof-theoretic strength. The relevant system is
APC₃ = T²₂ + sWPHP(PV₃) ⊆ T⁴₂,
not the APC₂ / T¹₂ + sWPHP(PV₂) setting used in the R56/R62 search route. This does not automatically give the S¹₂ proof or EF proof-size consequence required by Pich–Santhanam and KPS.

This corrects the overly broad reading of R64: “not countable by the current APC₂ Σᵇ₁ machinery” is justified; “not countable by relative approximate counting at any level” is not.

## 1. Primary-source hierarchy

Primary sources:
- Emil Jeřábek, *Approximate counting by hashing in bounded arithmetic*: https://users.math.cas.cz/~jerabek/papers/hash.pdf
- Emil Jeřábek, *Approximate counting in bounded arithmetic*, Constructive Complexity Theory 2025 slides: https://users.math.cas.cz/~jerabek/talks/stoc2025.pdf

Jeřábek's relativization discussion says that the counting machinery relativizes. Specializing the oracle predicate α to Σᵇᵢ formulas gives:
- APCᵢ₊₁ = Tᵢ₂ + sWPHP(PVᵢ₊₁) ⊆ Tᵢ₊₂;
- APCᵢ₊₁ can count Σᵇᵢ-definable sets with relative precision;
- additive-error counting at that level can also handle Δᵇᵢ₊₁ sets.

Thus APC₂ counts Σᵇ₁ sets, while APC₃ counts Σᵇ₂ sets. This is exactly the level shift relevant to the direct decision-error relation.

Theorem 2.1 in the 2009 paper generalizes as:
Sᵢ₊₁₂(α)+BBΣᵇᵢ₊₂(α)+sWPHP(PVᵢ₊₁(α))
is ∀Σᵇᵢ₊₁(α)-conservative over
Tᵢ₂(α)+rWPHP(PVᵢ₊₁(α)).
For i=2, this is a ∀Σᵇ₃ conservation result over T²₂+rWPHP(PV₃), not a descent to S¹₂.

## 2. Decision-error fibre is Σᵇ₂

For a fixed formula x and decision circuit C, define:
Err(C,x) :=
(C(x)=0 ∧ ∃w<2ⁿ SATₙ(x,w))
∨
(C(x)=1 ∧ ∀w<2ⁿ ¬SATₙ(x,w)).

This says exactly C(x)≠SATₙ(x). It is a Boolean combination of Σᵇ₁ predicates, hence Δᵇ₂, and can be written explicitly as a Σᵇ₂ formula:
∃b,z<2ⁿ ∀w<2ⁿ [
 (b=0 ∧ C(x)=0 ∧ SATₙ(x,z))
 ∨
 (b=1 ∧ C(x)=1 ∧ ¬SATₙ(x,w))
].
If b=0, z is a satisfying witness and C answers 0. If b=1, C answers 1 and every witness fails. The formula is therefore equivalent to the decision-error predicate.

The survivor predicate after history H=((x₀,...,x_{i−1})) is:
S_H(C) := C∈C_{n,s} ∧ ∧_{j<i} ¬Err(C,x_j).
A polynomial-length conjunction of these Δᵇ₂ conditions remains Δᵇ₂ / Σᵇ₂. The tuple bad-majority predicate is also Σᵇ₂. Thus the relevant universe, survivor, fibre, and incidence predicates can all be represented at the Σᵇ₂ level.

## 3. R64 weighted-tag construction can be lifted one level

Keep the R64 finite combinatorial inequality. Let F_x be the erroneous circuits and G_x the correct circuits. Suppose:
|F_x|/|S| ≤ 1/2−1/m, m≥4.

Define a tagged copy set:
T_x = {(C,j): C∈G_x and j<m} ∪ {(C,j): C∈F_x and j<m+4}.

Then:
|T_x| = m|G_x|+(m+4)|F_x|
      = m|S|+4|F_x|
      ≤ (m+2−4/m)|S|.

For a tuple u∈S^r with at least r/2 errors, the forgetful map T_x^r→S^r has at least (m(m+4))^(r/2) preimages over u. The tag choices are explicit mixed-radix strings. Since membership in F_x is Σᵇ₂, a PV₃ function can use the corresponding Σᵇ₂ oracle to compute the tag radices and canonical tag assignments.

Consequently:
|Bad_x|/|S|^r ≤ ρ^r,
ρ=(m+2−4/m)/sqrt(m(m+4)),
and ρ²≤1−2/m², so ρ≤exp(−1/m²).

Choose odd r≥m²(n ln2+2). Then each formula's bad-majority tuple fraction is at most exp(−n ln2−2). Summing over all 2ⁿ formulas gives total bad-tuple fraction below e⁻²<1/4. Hence there exists a tuple whose majority decides SATₙ on every input, contradicting the assumed size-s³ decision-circuit lower bound when the majority circuit size O(rs) is ≤s³.

This is the finite proof plus a candidate formalization plan. A full APC₃ proof still needs explicit PV₃ maps and exact relative-counting inequalities for the tagged fibres, products, and union over all x.

## 4. What this might establish, and what it does not

If the tagged-fibre counting and survivor iteration are fully formalized, APC₃ may prove the R49 nonuniform decision anti-checker existence statement, with polynomially many formulas and a finite assignment-label table.

This would be a meaningful improvement over R64: it would move the direct decision route from “not expressible in APC₂'s Σᵇ₁ counting language” to “candidate formalizable one level higher.”

It does not automatically give:
- a PV₁ generator for the anti-checker set;
- an S¹₂ proof of generator correctness;
- polynomial-size EF proofs of the relevant tautologies;
- KPS EF transfer certificates;
- P≠NP.

The theory level is now T²₂+sWPHP(PV₃), with a ∀Σᵇ₃ conservativity route to T²₂+rWPHP(PV₃). This is substantially stronger than the S¹₂ target. Pich–Santhanam's generalization to stronger theories also changes the associated propositional proof system; non-p-boundedness of EF does not imply non-p-boundedness of an arbitrary stronger system.

## 5. Exact open obligations

1. Write the weighted tag-lift injection as an explicit PV₃ function on the Σᵇ₂ error relation; prove injectivity and range conditions in APC₃.
2. Formalize the relative bound |Bad_x|≤ρʳ|S|ʳ with all ceilings and approximation losses explicit.
3. Apply the Σᵇ₂ version of Theorem 3.19 to the uniform family indexed by all 2ⁿ formulas and prove the global bad tuple set is strictly smaller than Sʳ.
4. Formalize the survivor update S_{i+1}={C∈S_i:C(x_i)=SATₙ(x_i)} as a Σᵇ₂ history predicate and bound the iteration length.
5. Extract the final nonuniform label table and prove the Pich–Santhanam label conditions.
6. Separately investigate whether the resulting ∀Σᵇ₃ statement has any conservativity route down to an EF-relevant theory. Do not assume one.

## Status

- R49 finite decision anti-checker: conditional combinatorial proof.
- Decision-error predicate as Σᵇ₂: explicit formula given.
- APC₃ relative counting for Σᵇ₂ sets: source-verified hierarchy.
- Weighted tag-lift within APC₃: plausible formalization, not yet proved.
- Full APC₃ survivor anti-checker: open.
- Descent to S¹₂ / EF: no route established.
- Pich–Santhanam feasible generator: not constructed.
- KPS EF transfer and P≠NP: open.

R66 is a new higher-level formalization route, not a proof of an anti-checker theorem or P≠NP.
