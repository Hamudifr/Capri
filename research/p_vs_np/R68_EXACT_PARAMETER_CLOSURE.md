# R68: exact finite parameters and the missing APC₃ transfer lemma

## Purpose

R68 closes the finite combinatorial constants in R67 and isolates the exact bounded-arithmetic lemma still needed. It deliberately does not pretend that the finite cardinality argument automatically yields a Jeřábek approximate-size comparison.

## 1. Exact finite tagged-tail estimate

Let S be a nonempty finite set of decision circuits. For each formula x, let Fₓ⊆S be circuits that err on SATₙ(x), and Gₓ=S\Fₓ.

Fix integer m≥4 and suppose:
|Fₓ|≤(1/2−1/m)|S|.

Give each C∈Gₓ exactly m tags and each C∈Fₓ exactly m+4 tags. Thus:
|Tₓ|=m|Gₓ|+(m+4)|Fₓ|
=m|S|+4|Fₓ|
≤(m+2−4/m)|S|.

For odd r, a tuple u∈Sʳ with majority error has k≥(r+1)/2 erroneous coordinates, so its number of tag lifts is at least:
m^(r−k)(m+4)^k ≥ [m(m+4)]^(r/2).

Set L=⌊[m(m+4)]^(r/2)⌋. Since m≥4 and r≥1, the quantity inside the floor is at least 2, hence L≥[m(m+4)]^(r/2)/2.

Mixed-radix encoding gives an explicit injection Badₓ×[L]→Tₓʳ. Therefore:
|Badₓ|/|S|ʳ ≤ 2ρʳ,
where
ρ=(m+2−4/m)/√(m(m+4)).

Exact algebra:
1−ρ²=4(m²+4m−4)/(m³(m+4)).
For m≥4, this is at least 2/m². Hence:
ρ≤exp(−1/m²),
and
|Badₓ|/|S|ʳ ≤ 2exp(−r/m²).

This is a finite-set inequality with explicit floor loss.

## 2. Concrete circuit parameters

Choose:
m=⌈√s⌉,
r = the least odd integer ≥ m²(n ln2+12).

Then:
2ⁿ·2exp(−r/m²) ≤ 2e⁻¹² < 1.

Thus, in the exact finite setting, the union of all 2ⁿ bad-majority fibres occupies strictly less than the whole product Sʳ. Some tuple has a majority circuit correct on every n-bit input.

The majority circuit has size O(rs)=O(ns²), because m²=O(s) and r=O(ns). For a sufficiently large fixed K, s≥Kn ensures O(ns²)≤s³.

After finding a hard formula x, retain the circuits agreeing with SATₙ(x). Their number is at most:
(1/2+1/m)|S|≤3|S|/4.
After O(log|C_{n,s}|)=O(s log(n+s)) rounds, no circuit remains.

This closes the finite combinatorial parameter calculation, conditional on the size-s³ SAT circuit lower bound.

## 3. Sparse survivor normalization and the small branch

Apply Jeřábek Theorem 3.21 to the Σᵇ₂ survivor set S after relativization. It gives s₀≤t₀≤⌈s₀(1+ε₀)⌉ and PV₃ retraction pairs, with maps [t₀]→S and S→[s₀].

Choose ε₀=1/(100r).

- If s₀<100r, then t₀=O(r). In the standard finite interpretation S has O(r) circuits. If every formula had fewer than (1/2−1/m) errors in S, the majority of this explicit finite list would decide SATₙ. Its size is O(rs)≤s³ for sufficiently large s≥Kn, contradiction. Therefore a formula with the required error fraction exists.
- If s₀≥100r, the ceiling gives t₀/s₀≤1+ε₀+1/s₀≤1+2/(100r). This is the large branch where relative counting is used.

The small-branch majority is over the whole survivor list, not a first-correct-circuit selector. A single correct circuit per input would not suffice; the strict majority guarantee is essential.

## 4. Explicit target for the APC₃ incidence estimate

Let Q=[2ⁿ], U=Sʳ, and E⊆Q×U be the majority-error incidence relation. All defining predicates are Σᵇ₂ after substituting Σᵇ₁ formulas for Jeřábek's oracle predicate α.

The desired one-step formal lemma is:

**Tagged-fibre transfer lemma.** Under the hypothesis that every x∈Q has
|Fₓ|≤(1/2−1/m)|S|,
the mixed-radix injection, the APC₃ relative product/counting laws, and Theorem 3.21's near-cardinality parameters imply a uniform approximate-size bound on each fibre Eₓ sufficient for the Σᵇ₂-relativized Theorem 3.19 to yield:
E is strictly smaller than U.

The finite target ratio, before bounded-arithmetic approximation losses, is:
2ⁿ·2exp(−r/m²)≤2e⁻¹².

The available slack is large. For example, with ε₀=ε=1/(100r), the enumeration ceiling contributes at most (1+2/(100r))ʳ, while Theorem 3.19 contributes its stated factor (1+ε)ʳ⁺¹(1+4ε), in addition to the product/tag comparison losses that must be derived from the exact hypotheses of Theorems 3.13, 3.17, and 3.19. These displayed factors alone are bounded by a small absolute constant (<e^0.1); the e⁻¹² margin is ample. Do not silently assume that the product/tag comparison contributes no further loss.

The exact missing proof is to derive, inside APC₃, the approximate comparison:
Badₓ ≼ε T
from the PV₃ injection Badₓ×[L]→Tₓʳ and the approximate upper bound on Tₓʳ, with all relative errors and ceilings explicit. Then apply the uniform-fibre theorem. This is the key technical lemma for the direct decision route.

## 5. Formalization strength

The relevant Σᵇ₂ set-counting theorem is obtained by relativizing Jeřábek's Σᵇ₁(α) machinery to Σᵇ₁ predicates. The resulting approximate-size statements are generally Σᵇ₃. Thus:
- the counting hierarchy is APC₃ = T²₂+sWPHP(PV₃);
- the natural proof of the ∀Σᵇ₃ counting statements uses S³₂+sWPHP(PV₃) and the associated BBΣᵇ₄ collection;
- the generalized conservation route is to T²₂+rWPHP(PV₃), not S¹₂.

The polynomial-length survivor history can be encoded in one bounded string, but the complete S³₂ induction formula and its collection obligations are not yet written. This remains a separate proof obligation after the one-step tagged-fibre transfer lemma.

## 6. Status

### Established in the finite setting
- Exact tagged-tail inequality including floor loss: |Badₓ|/|S|ʳ≤2e^(−r/m²).
- Explicit parameters m=⌈√s⌉ and odd r≥m²(n ln2+12).
- Union bound strictly below one.
- Majority circuit size O(ns²), within s³ for s≥Kn.
- Survivor shrink factor at most 3/4.
- Small/large survivor branch using Theorem 3.21's near-cardinality scale.

### Source-backed but not fully formalized
- APC₃ relative counting for Σᵇ₂ fibres.
- Theorem 3.21 normalization for Σᵇ₂ survivors.
- Mixed-radix injection is a PV₃-computable map.

### Still open
1. Prove the tagged-fibre transfer lemma inside APC₃ with exact approximation losses.
2. Instantiate the product and union laws without hidden constants.
3. Complete the S³₂ history induction and BBΣᵇ₄ collection.
4. Verify the ∀Σᵇ₃ conservation transfer.
5. Find a descent to S¹₂/EF or a different proof route.

No APC₃ anti-checker theorem, PV₁ generator, EF lower bound, KPS transfer, or P≠NP proof is claimed.
