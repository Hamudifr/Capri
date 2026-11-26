# R67: APC₃ formalization audit — sparse survivors, tagged fibres, and induction strength

## Executive result

R66 identified the correct hierarchy level for decision-error predicates, but left two important formalization questions underdeveloped:

1. Can the direct decision route count relative to a survivor set S that may be exponentially sparse inside the full circuit universe?
2. What theory actually supports iteration of the one-step theorem, whose selected hard formula is obtained through a higher-complexity approximate-counting statement?

The first issue has a plausible source-backed repair: apply Jeřábek's Theorem 3.21 to the Σᵇ₂ survivor set itself. It supplies near-cardinality parameters s₀≤t₀≤⌈s₀(1+ε)⌉ and PV₃ retraction pairs, so the proof need not compare sparse survivor fibres to the ambient circuit universe. The second issue is more serious: after relativization to Σᵇ₁ predicates, the relevant counting conclusions are ∀Σᵇ₃, and the natural iteration belongs in S³₂ + sWPHP(PV₃), with a conservation route to T²₂+rWPHP(PV₃), not in S¹₂/EF.

This is a more precise APC₃ proof blueprint, not a completed formalization.

## 1. Source-verified hierarchy and the right theorem levels

Primary source:
Emil Jeřábek, *Approximate counting by hashing in bounded arithmetic*:
https://users.math.cas.cz/~jerabek/papers/hash.pdf

Jeřábek's relativization discussion states that substituting Σᵇᵢ formulas for the oracle predicate α in the Σᵇ₁(α) counting machinery yields counting for Σᵇᵢ₊₁ sets. The corresponding theories shift as:
- APC₂: T¹₂ + sWPHP(PV₂), relative counting for Σᵇ₁ sets.
- APC₃: T²₂ + sWPHP(PV₃), relative counting for Σᵇ₂ sets.
- The proof of the Σᵇ₂ relativized counting statements is naturally carried out in S³₂ + sWPHP(PV₃), with the corresponding ∀Σᵇ₃ conservation route to T²₂ + rWPHP(PV₃), using BBΣᵇ₄ as in the generalization of Jeřábek's Theorem 2.1.

Relevant original results:
- Theorem 3.19: relative counting for a uniformly described family of fibres.
- Theorem 3.20: fibre-selection dichotomy; its rounding term is ⌈t(1+2ε)⌉, so t=1 gives two.
- Theorem 3.21: approximate increasing enumeration/retraction pairs for any Σᵇ₁(α)-definable set, with parameters s≤t≤⌈s(1+ε)⌉ and nondecreasing PV₂(α) functions; after substitution α:=Σᵇ₁, this applies to Σᵇ₂ survivors with PV₃ functions.

Jeřábek's 2025 slides independently summarize APCᵢ₊₁ as Tᵢ₂+sWPHP(PVᵢ₊₁), counting Σᵇᵢ sets, and distinguish this from additive-error counting for Δᵇᵢ₊₁ sets:
https://users.math.cas.cz/~jerabek/talks/stoc2025.pdf

## 2. Explicit complexity of decision error

For fixed decision circuit C and formula x, define:
Err(C,x) :=
(C(x)=0 ∧ ∃z<2ⁿ SATₙ(x,z))
∨
(C(x)=1 ∧ ∀w<2ⁿ ¬SATₙ(x,w)).

Equivalently:
∃b,z<2ⁿ ∀w<2ⁿ [
 (b=0 ∧ C(x)=0 ∧ SATₙ(x,z))
 ∨
 (b=1 ∧ C(x)=1 ∧ ¬SATₙ(x,w))
].

This is Σᵇ₂ and also Πᵇ₂ (Δᵇ₂). Its complement is also Σᵇ₂. For a history H=(x₀,…,xᵢ₋₁), the survivor predicate
S_H(C):=C∈C_{n,s} ∧ ∧_{j<i} ¬Err(C,xⱼ)
is Δᵇ₂/Σᵇ₂. The tuple bad-majority predicate is likewise Σᵇ₂ after bundling the polynomially many witness/branch bits into the existential block and the unsatisfiability checks into the universal block.

Thus the survivor set, correct/error fibres, tagged-copy sets, and bad-incidence relation are all eligible for APC₃ relative counting. This is the definability gain over APC₂.

## 3. Repair for sparse survivor sets: apply Theorem 3.21 to S

A survivor set S may be exponentially sparse in the full circuit-description universe. Comparing its fibres only against the ambient universe would lose the relative factor needed by the Chernoff/tagging argument.

Instead, apply Theorem 3.21 to S itself, viewed as a Σᵇ₂ set after relativization. For any ε with ε⁻¹ logarithmically bounded, it supplies parameters s₀,t₀ and PV₃ retraction pairs with:
s₀ ≤ t₀ ≤ ⌈s₀(1+ε)⌉,
a surjection [t₀]→S, and a surjection S→[s₀].
In the standard finite interpretation, these give:
s₀ ≤ |S| ≤ t₀ ≤ s₀(1+ε)+1.
The maps are part of the formal certificate; the argument does not enumerate S or use rejection sampling.

This gives a near-cardinality scale for S even when S is very sparse in the ambient universe. Products Sʳ can then be bounded relative to s₀ʳ and t₀ʳ, while the actual survivor/error predicates remain Σᵇ₂. Avoid pulling the Σᵇ₂ incidence relation back through PV₃ maps unless needed: such a pullback may rise to Δᵇ₃ and would forfeit the relative Σᵇ₂ counting advantage.

## 4. Explicit tagged-fibre injection

Fix x and partition S into Fₓ={C∈S:Err(C,x)} and Gₓ=S\Fₓ. Assume for contradiction:
|Fₓ| ≤ (1/2−1/m)|S|, for every x, with m≥4.

For each C∈S, define its tag radix:
ℓ(C,x)=m+4 if Err(C,x), and m otherwise.
Let Tₓ={(C,j): C∈S and j<ℓ(C,x)}. This is Σᵇ₂-definable, because Err and its complement are Σᵇ₂. Its exact finite cardinality is:
|Tₓ|=m|S|+4|Fₓ|≤(m+2−4/m)|S|.

Let r be odd. For u=(C₁,…,Cᵣ)∈Sʳ with at least r/2 errors, the number of tag vectors above u is:
∏ᵢ ℓ(Cᵢ,x) ≥ [m(m+4)]^{r/2}.

To avoid nonintegral lower bounds, put
L=floor([m(m+4)]^{r/2}).
For each bad u, the first L mixed-radix integers encode distinct tag vectors. The map
Badₓ×[L] → Tₓʳ
that retains u and decodes its second coordinate in the radices ℓ(Cᵢ,x) is injective. Its evaluation is PV₃, because it queries the Σᵇ₂ error predicate to obtain the radices. Injectivity is checked by forgetting tags to recover u and re-encoding the mixed-radix digits to recover the integer.

Hence the finite cardinality inequality is:
L·|Badₓ| ≤ |Tₓ|ʳ,
and therefore
|Badₓ|/|S|ʳ ≤ ρʳ up to the harmless floor factor, where
ρ=(m+2−4/m)/sqrt(m(m+4)).
Exact algebra gives:
1−ρ² = 4(m²+4m−4)/(m³(m+4)) ≥ 2/m²  (m≥4),
so ρ≤exp(−1/m²).

This is a concrete injection, not merely an appeal to a probabilistic tail bound. The remaining formal task is to derive its cardinality consequence using APC₃'s relative counting and weak-pigeonhole principles, with explicit approximation losses.

## 5. Global incidence bound with explicit slack

Let Q=[2ⁿ] be all formula encodings, U=Sʳ, and
E={(x,u)∈Q×U : u has majority error on x}.
The relation E is Σᵇ₂. Theorem 3.19's relativized form can count this uniformly described family of Σᵇ₂ fibres.

Use Theorem 3.21 parameters s₀,t₀ for S, and choose η≤1/(100r) for the relative-counting approximations. The tag injection and the near-cardinality bounds give, up to controlled approximation factors:
|E|/|U| ≤ 2ⁿ · 2 · exp(−r/m²) · (1+η)^{O(r)}.

Take m=⌈√s⌉ and choose r odd with:
r ≥ m²(n ln2+12).
Then 2ⁿ·2·exp(−r/m²)≤2e⁻¹². With η≤1/(100r), the remaining (1+η)^{O(r)} factor can be kept below a fixed constant close to one by making the hidden constant in η explicit. The resulting ratio is strictly below one, so some tuple u∈Sʳ has no majority error on any x.

Its majority circuit decides SATₙ. Its size is O(rs)=O(ns²), which is at most s³ for s≥K n with sufficiently large fixed K. This contradicts the assumed SATₙ circuit lower bound.

Important: the preceding is a parameter blueprint. A formal proof must instantiate the exact constants in Jeřábek's Theorems 3.13, 3.17, 3.19 and the product/union approximation laws; the notation O(r) is not itself a formal certificate.

## 6. Survivor iteration and the actual induction level

Once the one-step result is available for every nonempty history-defined survivor S_H, choose xᵢ with at least (1/2−1/m)|Sᵢ| errors and set:
Sᵢ₊₁={C∈Sᵢ : ¬Err(C,xᵢ)}.
Then |Sᵢ₊₁|≤(1/2+1/m)|Sᵢ|≤3|Sᵢ|/4 for m≥4. The number of stages is O(log |C_{n,s}|)=O(s log(n+s)).

The survivor predicate remains Σᵇ₂, but the statement that a formula has a sufficiently large error fibre is expressed using the approximate-size relation for a Σᵇ₂ set, which is generally Σᵇ₃. Thus do not claim that the entire step is a Σᵇ₂ induction formula.

The natural formalization is:
- prove the one-step incidence/counting statement in the Σᵇ₂-relativized hierarchy;
- package the polynomial-length history, selected formulas, labels, and approximation certificates into one bounded string;
- use S³₂ + sWPHP(PV₃) (and the relevant BBΣ⁴ collection) for the Σᵇ₃ induction/collection work;
- state the resulting ∀Σᵇ₃ consequence and use the generalized Jeřábek conservation theorem to transfer it to T²₂+rWPHP(PV₃), if every hypothesis is verified.

This is still far above S¹₂. The transfer is not an EF descent.

## 7. Final labels and Pich–Santhanam interface

After the formula set A is fixed, for each x∈A choose yₓ such that:
∀w<2ⁿ [SATₙ(x,w)→SATₙ(x,yₓ)].
This is a Πᵇ₁ label-validity condition. If x is satisfiable, yₓ is a witness; if x is unsatisfiable, any yₓ works. The finite polynomial-size label table and its graph D meet the nonuniform object shape in Pich–Santhanam Theorem 7.

The APC₃ construction would still be a nonuniform/existential anti-checker theorem. It does not yield the single PV₁ generator f and S¹₂ proof required by Pich–Santhanam. Nor does it give KPS's short EF transfer certificates.

## 8. Status and proof obligations

### Improved / source-backed
- APC₃ relative counting is the correct hierarchy level for Σᵇ₂ decision-error fibres.
- Theorem 3.21 supplies a near-cardinality scale for sparse Σᵇ₂ survivor sets.
- The mixed-radix tag-lift has an explicit PV₃ injection description.
- The global incidence can be expressed as a uniformly described Σᵇ₂ family.
- Correct induction strength is S³₂ + sWPHP(PV₃), with a ∀Σᵇ₃ conservation route to T²₂+rWPHP(PV₃), not S¹₂.

### Still open
1. Formalize the exact mixed-radix injection and cardinality inequality in APC₃.
2. Instantiate every approximation loss and ceiling in the tag-fibre and global-incidence estimates.
3. Prove the Σᵇ₂ relativized Theorem 3.19 application with the chosen parameters and sparse-survivor normalization.
4. Write the full S³₂ history-induction formula, including bounded collection of labels and approximation certificates.
5. Verify the generalized conservation hypotheses and exact final ∀Σᵇ₃ statement.
6. Find a genuinely lower-strength route to S¹₂/EF, or abandon this route as insufficient for the EF objective.

## Conclusion

R67 repairs the sparse-survivor normalization in R66 and turns the weighted Chernoff idea into an explicit candidate PV₃ injection. It also exposes the true arithmetic cost: the iterative decision route naturally lives at the S³₂ / T²₂ level, not the S¹₂ level. This is a more concrete candidate theorem, but it is not yet a formal bounded-arithmetic proof, a feasible generator, an EF lower bound, or P≠NP.
