# R37: OPS anti-checker selector route

## 1. Why this is a separate route

The Pich–Santhanam KPT route asks for a polynomial-time function of 1^n that outputs a proof-certified anti-checker. A different route from Oliveira–Pich–Santhanam (OPS), *Hardness Magnification Near State-of-the-Art Lower Bounds*, works with a circuit whose input is the full truth table of the target function. It trades the uniform selector problem for a near-linear circuit upper bound under NP ⊆ Circuit[poly], then asks for a superlinear lower bound against that selector / the associated Gap-MCSP problem.

Let N = 2^n. OPS Lemma 4.1 says that if NP ⊆ Circuit[poly], then for every sufficiently small constant β > 0 there is a circuit of size at most 2^(n+kβn) = N^(1+kβ) which takes tt(f) as input and outputs t = 2^(10βn) query points. If f has circuit complexity greater than 2^(βn), every circuit of size at most s = 2^(βn)/(10n) disagrees with f on at least one selected point.

Theorem 1.4 then gives the hardness-magnification implication: if for some ε > 0 and every sufficiently small β > 0, Gap-MCSP[2^(βn)/(c n), 2^(βn)] requires circuits of size greater than N^(1+ε), then NP ⊄ Circuit[poly], hence P ≠ NP.

## 2. Selector construction mechanics

For a partial sample a = ((y_1,f(y_1)),...,(y_i,f(y_i))), let R_i be the set of all size-s circuits consistent with the sample.

1. Use relative approximate counting to estimate |R_i|. Under NP ⊆ Circuit[poly], the relevant approximate-counting computations can be implemented by nonuniform circuits.
2. While at least 4n² circuits remain, choose a point y_{i+1} that removes at least a 1/(2n) fraction of the consistent circuits. The existence proof uses a majority of n consistent circuits: if no point makes enough of them disagree, their majority would compute f with size at most 2^(βn), contradicting hardness.
3. After 2^(O(βn)) rounds, only polynomially many consistent circuits remain. Enumerate them using NP ⊆ Circuit[poly], then add one disagreement point for each remaining circuit.

The key distinction from KPT is the scale and input: this selector is a circuit on the entire 2^n-bit truth table, not a P-time generator on 1^n. It is near-linear in N for small β, but still superlinear by N^(kβ).

## 3. What the Anti-Checker Hypothesis result does and does not say

Chen–Hirahara–Oliveira–Pich–Rajgopal–Santhanam, *Beyond Natural Proofs: Hardness Magnification and Locality*, Corollary 61, disproves the Anti-Checker Hypothesis. That hypothesis asks for a fixed, relatively small family of sample sets, independent of f, such that one set in the family anti-checks every hard f.

This does not refute the OPS selector: its output set depends on the entire truth table f. Fixed-family anti-checkers and an input-dependent selector are different objects. The same paper's locality barrier warns that some lower-bound techniques for weak models continue to work even with small-fan-in oracle gates, limiting direct hardness-magnification attempts.

## 4. Independent Lean workbench and the current gap

A public independent research workbench, *P vs NP Lean proofs and research* (Joshua Christl), reports:
- a formalized extensional anti-checker selector interface;
- a linear gate lower bound for shared selector circuits, of the form 2^n ≤ 2·size + qn + q + description-length;
- several failed attempts to amplify this to a superlinear bound;
- an open direct-selector superlinear target.

I could not retrieve its Lean source repository or independently compile those declarations in this session. Treat these as author-reported research status, not as independently verified formal results. The useful lesson is that information/support arguments appear to stop at a linear gate lower bound; a superlinear selector lower bound needs a genuinely stronger idea.

## 5. Recent MCSP lower-bound benchmark

A November 2026 manuscript by J. A. Wittcop reports Lean-checked lower bounds around 2N for MCSP thresholds n−1, n, and n+1, with the strongest result at n−1 being 2N − O(N/log N). Its own abstract explicitly says these results do not address thresholds s = N^ε needed by the OPS hardness-magnification theorem. This is a useful near-linear benchmark, not a solution to the required superlinear Gap-MCSP bound. The n and n+1 results also rely on small EQ circuit bounds checked by exhaustive computation rather than a checked certificate.

## 6. Finite toy experiment

The accompanying toy code uses the concept class of all functions depending only on the first k input bits. A target outside this class must vary inside some fiber of the projection onto those k bits. Two points in that fiber with opposite target labels refute every candidate function at once.

Conversely, any fixed sample S with fewer than 2^n points can be defeated: choose an unqueried point z and let f be 1 only at z. Then the constant-zero candidate agrees with f on S, while f is not constant on its projection fiber. This demonstrates why a target-dependent selector can succeed while a fixed sample cannot.

This is only a finite combinatorial analogy. It does not model the circuit-size bounds, approximate-counting subroutines, or superlinear lower bound in OPS.

## 7. Next research targets

1. Determine whether the OPS approximate-counting selector can be improved from N^(1+O(β)) to a smaller exponent or a sharper structural class.
2. Search for a superlinear lower bound on input-dependent anti-checker selector circuits that survives the fixed-family Anti-Checker Hypothesis counterexample.
3. Test whether the locality barrier applies to candidate selector lower-bound techniques, rather than assuming it does.
4. Investigate whether the recent near-2N MCSP[n−1] gate-elimination method can be generalized to any gap regime relevant to OPS. The immediate parameter mismatch is severe: n−1 = Θ(log N), whereas OPS needs s = N^β/Θ(log N).
5. Keep this route separate from the KPT/PV₁ route. A near-linear truth-table selector is not a uniform feasible generator on 1^n.

## Sources

- Oliveira, Pich, Santhanam, *Hardness Magnification Near State-of-the-Art Lower Bounds*, Theory of Computing 17(11), 2021: https://doi.org/10.4086/toc.2021.v017a011
- Chen et al., *Beyond Natural Proofs: Hardness Magnification and Locality*, JACM 69(4), 2022: https://doi.org/10.1145/3538391
- Ježil–Tsintsilidas, *Parallelism and Adaptivity in Student-Teacher Witnessing* (2026): https://arxiv.org/abs/2602.19934
- Wittcop, *2N Circuit Lower Bounds for the Minimum Circuit Size Problem* (November 2026 manuscript): https://www.academia.edu/180415409/2N_Circuit_Lower_Bounds_for_the_Minimum_Circuit_Size_Problem

# R37 APC1 transfer audit — relative counting is the obstacle

A tempting bridge to the Pich–Santhanam Open Problem 2 is to rescale the OPS greedy selector to polynomial circuit sizes. If the high hardness threshold is H=n^d and the low threshold is s=H/(10n), then the OPS majority argument has a polynomial number of rounds and a polynomial-size sample. For SAT, the sample can be augmented with one representative satisfying assignment for each satisfiable formula, producing the mixed-label package shape required by the KPS interface.

However, this does **not** by itself give an APC₁ proof.

The OPS selector does not merely need an additive approximation to the number of consistent circuits. At a late stage, its survivor set R_i may contain only 4n² circuits among a universe of 2^{poly(n)} descriptions. An additive approximation with error ε|U| for ε=1/poly(n) cannot distinguish |R_i|=4n² from |R_i|=0, because ε|U| is exponentially larger than 4n². OPS uses relative approximate counting of the NP relation “circuit description is consistent with the current sample”; under NP⊆Circuit[poly], this can be implemented nonuniformly. That relative-counting strength is not supplied merely by APC₁'s polynomial-precision additive counting.

The existence proof for a good next point is a combinatorial double-counting argument over n-subsets of R_i (OPS Lemma 4.7 / Claim 4.8). Formalizing it in APC₁ still requires handling the sparse definable set R_i. The fact that the set has at least 4n² elements does not make it a noticeable fraction of the full circuit-description universe.

**Conclusion:** OPS gives a constructive selector under the stronger nonuniform relative-counting assumption NP⊆P/poly. It is not yet a direct solution to the APC₁ MinMax bottleneck. A viable APC₁ proof must avoid conditioning on an exponentially sparse survivor set, or find a way to represent/count that set with only polynomial-precision additive counting.

Potential alternatives, not yet proved:
- a soft-weight potential over all circuits whose total mass has a polynomial lower bound;
- a direct minimax/duality proof that never conditions on the survivor set;
- a dense encoding or compressed representation of relevant circuits that preserves the disagreement relation;
- a proof that the special structure of circuit disagreement prevents the survivor set from becoming too sparse.

The naive soft-weight idea also has a warning: ordinary exponential weights can assign minimum mass exp(-poly(n)) after poly(n) rounds, again below APC₁'s additive precision. A polynomial floor may destroy the usual regret bound. This requires a genuine new lemma, not just replacing zero-one weights by clipped weights.

Parameter caveat: choosing β_n=Θ(log n/n) makes 2^(β_n n) polynomial in n and the OPS sample size polynomial, but the published hardness-magnification theorem states β as a fixed positive constant. The variable-β rescaling is an exploratory parameter substitution for the combinatorial selector lemma, not a published corollary of Theorem 1.4.
