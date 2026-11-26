# R69: APC₃ tagged-fibre transfer via division and pullback

## Purpose and status

R69 revisits the exact gap left by R68. The key result is a source-backed transfer route: the mixed-radix injection can be converted into an approximate-size bound using Jeřábek's Corollary 3.11 (surjection/pullback) and Theorem 3.16 (product division). This is more precise than saying that an injection automatically divides cardinalities.

The transfer is now a **conditional lemma with an explicit construction and parameter schedule**. The global incidence ceiling is bounded explicitly at the parameter level; the uniform bounded-formula proof and S³₂ survivor-history induction remain open. R69 does not claim an APC₃ anti-checker theorem, an EF result, or P≠NP.

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

If Bₓ is nonempty, totalize the inverse map Tₓʳ→Bₓ×[L] by sending points outside the image to one fixed element of Bₓ×[L]. A default element can be found by lexicographic prefix self-reduction with the Σᵇ₂ predicate Bₓ, using polynomially many Σ₂-oracle queries; this is PV₃, not an exponential scan. The totalized map is a PV₃(α) surjection with ιₓ as a PV₃ coretraction. If Bₓ is empty, the desired fibre upper bound is immediate.

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
- Run Theorem 3.21 with enumeration precision ε₀=δ. In the large branch s₀≥100r, its ceiling gives t₀/s₀≤1+δ+1/s₀≤1+κ, where κ=1/(50r). The PV₃ surjection [t₀]→S supplied by Theorem 3.21 gives S≼δM directly by Corollary 3.5, at the same precision used by the incidence argument.

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

## 5. Global incidence comparison with explicit ceilings

Let Q=[2ⁿ], U=Sʳ, and E⊆Q×U be the majority-error incidence relation. It is Σᵇ₂. From Sections 2–3, every fibre has Bₓ≼δK, where
- A=m+2−2/m and D=√(m(m+4));
- L=⌊Dʳ⌋;
- H=⌈(1+2δ)(⌈mM(1+δ)²⌉+⌈4q(1+δ)²⌉)⌉;
- U₀=⌈(1+δ)ʳ⁺¹Hʳ⌉;
- P=⌈U₀(1+δ)⌉;
- t*=⌊L/(1+4δ)⌋;
- K=⌈⌈P/t*⌉(1+δ)⌉.

Theorem 3.19 gives
E≼δ E₀, where E₀=⌈2ⁿK(1+4δ)⌉.

Here is an explicit ceiling envelope in the large branch. We have M≥s₀≥100r, A≥m≥4, and δ=1/(1000r). Therefore AM≥400r and
H≤AM(1+2δ)(1+δ)²+4
 ≤ AM(1+2δ)(1+δ)²(1+4/(AM)).
Using 1+u≤eᵘ,
Hʳ≤(AM)ʳ exp(r(4δ+4/(AM)))≤(AM)ʳe^0.014.
Also (1+δ)ʳ⁺¹≤e^0.002. The ceiling in U₀ contributes less than e^0.001 because its argument is at least (400r)ʳ. Hence U₀≤(AM)ʳe^0.017, and P≤(AM)ʳe^0.022.

Since L≥2/δ, t*≥L/(1+5δ). Also A/D≥1/2, so
P/L≥(AM/D)ʳ≥(M/2)ʳ≥(50r)ʳ.
The two ceilings in K, together with (1+5δ)(1+δ), contribute less than e^0.002; thus K≤(P/L)e^0.002. The final ceiling and factor (1+4δ) contribute less than e^0.001. Combining these conservative bounds gives
E₀ ≤ 2ⁿ(AM)ʳ/L · e^0.026
   ≤ 2ⁿ·2ρʳ Mʳ e^0.026,
where ρ=A/D. Since M/s₀≤1+κ and κr=1/50,
E₀/s₀ʳ ≤ 2ⁿ·2ρʳe^0.046
          ≤ 2exp(−(3/4)n ln2−20.95)
          < 2e^(−20.95) < 1/4.
All ceiling estimates above use r≥m³(n ln2+12), m≥4, and s₀≥100r; the additive +1 terms are absorbed by the displayed lower bounds (in particular L≥2/δ and P/L≥(50r)ʳ).

To turn this into a contradiction, use the Theorem 3.21 retraction pair S↔[s₀], coordinatewise on r-tuples. Put a=s₀ʳ. If U=Sʳ≼δ⌊a/2⌋, Theorem 3.8 would give a PV₃ surjection [d]^c↠U^c with d=⌈⌊a/2⌋(1+δ)⌉<a. Compose it with the retraction U^c→[a]^c. This would give a surjection from a smaller interval power onto [a]^c, contradicting sWPHP(PV₃). Hence U≰δ⌊a/2⌋.

If every tuple had a majority error on some x, the projection E→U would be surjective. A PV₃ section can choose the lexicographically first such x by prefix self-reduction with the Σᵇ₂ incidence predicate, using polynomially many Σ₂-oracle queries. Corollary 3.11 therefore transfers E≼δE₀ to U≼δ⌈E₀(1+δ)⌉. The ratio bound above makes this parameter strictly below ⌊a/2⌋, contradiction. Thus some tuple has a majority circuit correct on every input. Its circuit size is O(rs)=O(ns²)≤s³ for sufficiently large s≥Kn, contradicting the assumed SAT circuit lower bound.

Consequently, not every fibre Fₓ can satisfy Fₓ≼δq. There is an x with Fₓ not≼δq, hence |Fₓ|>q≥(1/2−1/m)|S|. Retaining the agreeing circuits shrinks the survivor set by at least 3/4.

**Quantitative status:** the nested-ceiling and lower-interval comparison is now explicitly bounded at the parameter level. The remaining issue is not a missing finite counting factor; it is to formalize this entire implication with the correct bounded formula classes and induction/collection strength.

## 6. Status and remaining obligations

### Closed or source-backed
- The approximate-size definition and its soundness direction.
- The surjection/coretraction pullback in Corollary 3.11, relativized to Σᵇ₂/PV₃.
- The product-division step from Theorem 3.16, including an explicit way to rule out the interval factor.
- A PV₃ mixed-radix inverse/surjection route, using the Δᵇ₂ error predicate and a batch of error-bit queries.
- A revised finite tail with m=⌈s^(1/3)⌉, r=O(ns), and a stronger e^(−21) union-bound margin.

### Still open
1. Formalize the now-explicit one-step incidence contradiction with the correct bounded formula classes and induction/collection strength; in particular, verify the uniform-family use of Theorem 3.19 and the PV₃ least-witness section.
2. Complete the S³₂ survivor-history induction and BBΣᵇ₄ collection obligations.
3. Verify the precise ∀Σᵇ₃ conservation transfer to T²₂+rWPHP(PV₃).
4. Find a descent to PV₁/S¹₂ and the Pich–Santhanam/KPS EF certificate target, or establish that this APC₃ route does not reach it.

No uniform PV₁ generator, S¹₂ proof, KPS EF transfer certificate, EF lower bound, or P≠NP result is claimed.
