# R69: APC₃ tagged-fibre transfer via division and pullback

## Purpose and status

R69 revisits the exact gap left by R68. The key result is a source-backed transfer route: the mixed-radix injection can be converted into an approximate-size bound using Jeřábek's Corollary 3.11 (surjection/pullback) and Theorem 3.16 (product division). This is more precise than saying that an injection automatically divides cardinalities.

The transfer is now a **conditional lemma with an explicit construction and parameter schedule**. The full global incidence ceiling calculation and the S³₂ survivor-history induction still need a formal line-by-line proof. R69 does not claim an APC₃ anti-checker theorem, an EF result, or P≠NP.

## 1. Primary-source facts

Use Emil Jeřábek, *Approximate counting by hashing in bounded arithmetic*:

- Definition 3.1 defines X ≼ε s by a sequence of hash matrices isolating X^c; Remark 3.2 says this relation is Σᵇ₂ when X is Σᵇ₁(α).
- Corollary 3.11: if X ≼ε s and a PV₂(α) function gives a smooth surjection r×X^d ↠ r×Y^d, then Y ≼ε ⌈s(1+ε)⌉. A surjection with a PV₂ coretraction is smooth (Observation 2.2).
- Theorem 3.16: if X×Y ≼ε st, then X ≼ε ⌈s(1+ε)⌉ or Y ≼ε ⌈t(1+ε)⌉. This is the division principle needed below.
- Theorem 3.8 gives a PV₂ surjection from a power of ⌈s(1+ε)⌉ onto X^c when X ≼ε s. In the standard finite model this entails the soundness bound |X| ≤ s(1+ε).
- Section 2 explicitly says the counting results relativize: replacing Σᵇ₁(α) by Σᵇᵢ predicates raises PV₂ to PVᵢ₊₁ and T¹₂ to Tᵢ₂. Thus the relevant versions for Σᵇ₂ sets use PV₃ and APC₃.

Primary source: https://users.math.cas.cz/~jerabek/papers/hash.pdf (Definition 3.1, Remark 3.2, Observation 2.2, Corollary 3.11, Theorems 3.8 and 3.16, and the relativization discussion in Section 2).

## 2. The transfer lemma

Fix a formula x and a survivor set S of decision circuits. Let Fₓ be the erroneous circuits and let Bₓ⊆Sʳ be the r-tuples with majority error on x. Put
- Tₓ = (S×[m]) ⊔ (Fₓ×[4]), with disjoint tag ranges;
- L = ⌊[m(m+4)]^(r/2)⌋.

For every u∈Bₓ, at least half its coordinates are erroneous. The mixed-radix product of available tags is therefore at least [m(m+4)]^(r/2). Hence there is an injective map
ιₓ:Bₓ×[L]→Tₓʳ.

### 2.1 Complexity of the map

The decision-error predicate
Err(C,x) := (C(x)=0 ∧ SAT(x)) ∨ (C(x)=1 ∧ ¬SAT(x))
is Δᵇ₂: both it and its negation have Σᵇ₂ definitions. All r error bits can be queried in parallel. Given those bits, mixed-radix digit extraction and rank computation are ordinary polynomial-time arithmetic.

Consequently, the mixed-radix injection and its inverse-on-image are PV₃(α) procedures, with α representing the Σᵇ₁ SAT-witness predicate. The sets S, Fₓ, Bₓ, Tₓʳ and Bₓ×[L] are Σᵇ₂-definable. The graph of a general PV₃ function need not itself be Σᵇ₂; the proof uses the PV₃ function interface in Corollary 3.11, not an unjustified claim that every PV₃ graph is Σᵇ₂.

If Bₓ is nonempty, totalize the inverse map Tₓʳ→Bₓ×[L] by sending points outside the image to one fixed element of Bₓ×[L]. This is a PV₃(α) surjection with ιₓ as a PV₃ coretraction. If Bₓ is empty, the desired fibre upper bound is immediate.

### 2.2 Pull back the approximate upper bound

Suppose Tₓʳ ≼δ U. Apply the Σᵇ₂-relativized Corollary 3.11 with d=1 and r=1 to the totalized surjection:
Bₓ×[L] ≼δ P, where P = ⌈U(1+δ)⌉.

This is the missing formal step that an injection alone did not supply. It uses the actual theorem's surjection-plus-coretraction hypothesis.

### 2.3 Divide out the tag interval

Let
t* = ⌊L/(1+4δ)⌋ and s* = ⌈P/t*⌉.

By monotonicity and s*t*≥P, we have Bₓ×[L] ≼δ s*t*. The Σᵇ₂-relativized Theorem 3.16 gives either
- Bₓ ≼δ ⌈s*(1+δ)⌉, or
- [L] ≼δ ⌈t*(1+δ)⌉.

The second alternative is impossible for δ≤1/100 and L≥2/δ. Indeed, Theorem 3.8's soundness gives
L ≤ ⌈t*(1+δ)⌉(1+δ)
  ≤ L(1+δ)²/(1+4δ) + (1+δ)
  < L.
Thus
**Bₓ ≼δ K**, where
K = ⌈⌈P/t*⌉(1+δ)⌉.

This proves the abstract tagged-fibre transfer, conditional only on the stated approximate upper bound for Tₓʳ. It replaces the invalid shortcut “injection implies division” with two named bounded-arithmetic theorems.

## 3. Obtaining the tagged-universe upper bound

Assume S ≼δ M and Fₓ ≼δ q. The tag universe is a disjoint union:
Tₓ = (S×[m]) ⊔ (Fₓ×[4]).

Corollary 3.12 gives the product bounds, and Theorem 3.13 gives the union bound. One explicit safe parameter is
H = ⌈(1+2δ)(⌈mM(1+δ)²⌉ + ⌈4q(1+δ)²⌉)⌉,
so Tₓ ≼δ H.

Corollary 3.18(ii), applied to the r identical factors, gives
U = ⌈(1+δ)^(r+1) H^r⌉
as an upper parameter for Tₓʳ.

Combining Sections 2 and 3 yields the uniform fibre bound
Bₓ ≼δ ⌈⌈⌈U(1+δ)⌉ / ⌊L/(1+4δ)⌋⌉(1+δ)⌉.

All ceilings are retained. The bound is uniform in x; no exponentially long list of per-formula certificates is being assumed.

## 4. Parameter repair: leave room for approximation soundness

R68 used m≈√s and the finite threshold 1/2−1/m. For the formal route, it is cleaner to leave a factor-two margin between the approximate threshold and the final hard-formula threshold.

Choose:
- m = ⌈s^(1/3)⌉, with m≥4;
- r the least odd integer at least m³(n ln 2 + 12);
- δ = 1/(1000r);
- κ = 1/(50r), the large-branch bound t₀/s₀≤1+κ from Theorem 3.21.

For a large survivor set, let s₀≤|S|≤t₀=M and define
θ = 1/2−1/(2m),
q = ⌊θs₀/(1+δ)⌋.

If Fₓ ≼δ q, soundness gives |Fₓ|≤q(1+δ)≤θs₀≤θ|S|. Also q≤θM, so the tag-universe estimate has
mM+4q ≤ (m+2−2/m)M.

Conversely, in the large branch s₀≥100r, the inequalities κ+δ+2/s₀ < 1/m imply
q ≥ (1/2−1/m)t₀ ≥ (1/2−1/m)|S|.
Thus if some Fₓ is not approximately bounded by q, then |Fₓ|>q and this formula has error fraction greater than 1/2−1/m. Retaining the agreeing circuits shrinks S by at least the factor 1/2+1/m≤3/4.

For the weighted tail with θ=1/2−1/(2m), define
ρ = (m+2−2/m)/√(m(m+4)).
Direct algebra gives
1−ρ² = 4(2m−1)/(m³(m+4)) ≥ 7/(2m³), for m≥4.
Therefore ρ≤exp(−7/(4m³)). Including the floor loss L≥[m(m+4)]^(r/2)/2, the finite bound is
|Bₓ|/|S|ʳ ≤ 2exp(−7r/(4m³)).

With r≥m³(n ln2+12), the union-bound target is
2ⁿ·2exp(−7r/(4m³))
≤ 2exp(−(3/4)n ln2−21) < 1.

The majority circuit size is O(rs)=O(ns²), because m³=O(s) and r=O(ns). Hence it is at most s³ for sufficiently large s≥Kn.

The small-survivor branch remains separate: if s₀<100r, Theorem 3.21 enumerates O(r) survivors. If every formula had error fraction below 1/2−1/m, the majority of the entire survivor list would decide SAT, contradicting the size-s³ circuit lower bound. Thus a hard formula exists without using the large-branch incidence estimate.

## 5. Global incidence calculation: next proof checkpoint

Let Q=[2ⁿ], U=Sʳ, and E⊆Q×U be the majority-error incidence relation. It is Σᵇ₂. If every fibre has the bound Bₓ≼δK from Section 2, the Σᵇ₂-relativized Theorem 3.19 gives
E ≼δ ⌈2ⁿ K(1+4δ)⌉.

The remaining arithmetic is to compare this upper parameter with the lower near-cardinality scale s₀ʳ supplied by Theorem 3.21. The leading ratio is
2ⁿ (M/s₀)ʳ · 2ρʳ,
where M/s₀≤1+κ and ρʳ≤exp(−7r/(4m³)). The chosen r gives an e^(−21) margin before approximation losses. The displayed product/union/transfer/averaging losses are O(δr), while the enumeration loss is at most (1+κ)^r≤e^(1/50). The nested ceiling terms are negligible in the large branch because M≥100r and L grows as [m(m+4)]^(r/2).

This is a strong quantitative margin, but the final written proof must still turn those observations into one explicit inequality with every additive ceiling bounded. Do not mark the global incidence contradiction as closed until that calculation is written and checked independently.

## 6. Status and remaining obligations

### Closed or source-backed
- The approximate-size definition and its soundness direction.
- The surjection/coretraction pullback in Corollary 3.11, relativized to Σᵇ₂/PV₃.
- The product-division step from Theorem 3.16, including an explicit way to rule out the interval factor.
- A PV₃ mixed-radix inverse/surjection route, using the Δᵇ₂ error predicate and a batch of error-bit queries.
- A revised finite tail with m=⌈s^(1/3)⌉, r=O(ns), and a stronger e^(−21) union-bound margin.

### Still open
1. Finish the global incidence comparison with exact nested-ceiling inequalities and the Theorem 3.21 lower-bound contradiction.
2. Write the one-step statement as a uniform Σᵇ₃ implication with all parameters and formula classes explicit.
3. Complete the S³₂ survivor-history induction and BBΣᵇ₄ collection obligations.
4. Verify the precise ∀Σᵇ₃ conservation transfer to T²₂+rWPHP(PV₃).
5. Find a descent to PV₁/S¹₂ and the Pich–Santhanam/KPS EF certificate target, or establish that this APC₃ route does not reach it.

No uniform PV₁ generator, S¹₂ proof, KPS EF transfer certificate, EF lower bound, or P≠NP result is claimed.
