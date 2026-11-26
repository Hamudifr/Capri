# R52: APC₁ precision audit and search-to-decision interface

## 1. Correction and precision of the R51 APC₁ claim

R51 correctly identified an ambient-additive-error problem, but its wording must be precise: APC₁ does have a sophisticated approximate-cardinality framework for circuit-definable sets. It is incorrect to say that APC₁ simply cannot count sparse sets.

Pich–Santhanam §2.3 defines approximate comparison by efficiently witnessed surjections. For definable (X,Y\subseteq 2^n), (X\preceq_\epsilon Y) is witnessed by a circuit mapping (v\times(Y\cup \epsilon 2^n)) onto (v\times X). The error is additive relative to the ambient universe (2^n), not multiplicative relative to (|Y|). Their Proposition 3 provides comparison, complement, union, and disjoint-union laws with accumulated additive errors.

In the search-survivor construction, let (U=\mathcal C_{n,s}), with (|U|=2^m) up to encoding conventions. After (i) successful halving stages,
[
|S_i|\le 2^{-i}|U|=2^{m-i}.
]
To infer a constant-factor statement such as (|F_i|\ge |S_i|/2) from ambient-additive approximations with error (epsilon 2^m), one needs (epsilon 2^m\ll |S_i|), hence (epsilon\ll 2^{-i}). At (i=\Theta(m)), this requires exponentially small additive error in the circuit-description length. APC₁'s standard polynomial-precision regime does not provide that by direct application.

This is a limitation of the **direct ambient-counting implementation** of the R51 proof, not an impossibility theorem about APC₁ proving the desired statement. A new representation, sampler, weighting, or counting argument could avoid the direct requirement.

The rejection-sampling intuition makes the obstacle concrete: sampling uniformly from (S_i\subseteq U) by rejection from (U) has expected cost (|U|/|S_i|\ge 2^i), exponential in the late-stage index. No PV sampler for the survivor set has been constructed.

## 2. Source-verified formulation in Pich–Santhanam

The primary paper explicitly says (Section 1.1.3, §2.3, §3):
- APC₁ is (PV_1+dWPHP(PV)).
- Approximate comparison (X\preceq_\epsilon Y) is witnessed by a surjection from (v\times(Y\cup\epsilon 2^n)) onto (v\times X).
- The error is ambient-additive; comparison and union operations accumulate the errors.
- The authors say that a MinMax proof using only polynomial-precision APC₁ counting, together with a successful replacement of the polynomial-time witnessing function by existential quantifiers, could yield anticheckers in APC₁.
- Their Theorem 7's antichecker is a decision-circuit antichecker with a structured assignment-label relation (D), not merely a search-circuit anti-checker.
- Replacing the polynomial-time witnessing function by existential quantifiers produces a ∀Σᵇ₂ statement. KPT witnessing yields a constant adaptive list; later outputs depend on earlier challenges, preventing the immediate extraction of one fixed efficient SAT-search circuit.

## 3. Search-to-decision conversion audit

R51 constructs a nonuniform list of satisfiable formulas (F_i) with witnesses (w_i), such that every size-(s) search circuit fails to output a valid witness on at least one (F_i).

A tempting conversion is: given a decision circuit (C), run SAT self-reduction using (C) to build a search circuit (G_C). If (C) answers every restricted formula correctly, (G_C) finds a satisfying assignment.

But the restrictions queried by (G_C) depend on the answers of (C). To make a fixed support defeat every decision circuit, a direct closure construction must include all possible restriction nodes. For an (n)-variable formula, the full binary self-reduction tree has (2^{n+1}-1) nodes (up to encoding/padding). This destroys the polynomial-size support bound.

Including only restrictions consistent with one preselected witness does not suffice: a decision circuit may guide self-reduction down a different branch. Including only one path per circuit is also not a fixed support of polynomial size, since the number of circuit descriptions is exponential in their size.

Therefore the naive search-to-decision conversion is **not established**. This does not rule out a more efficient universal restriction family, a different reduction, or a direct decision anti-checker construction.

## 4. Consequence for the research plan

The R51 search anti-checker is a valid separate combinatorial result, but it does not yet instantiate Pich–Santhanam Theorem 7 or KPS's decision anti-checker premise. Two interfaces must be solved independently:

1. **Formal counting:** prove the search survivor halving theorem in APC₁ without demanding exponentially fine ambient-additive precision on late sparse survivor sets.
2. **Object conversion:** obtain a polynomial-support decision anti-checker with the required valid assignment labels, or prove a different reduction from the search anti-checker to the exact decision/transfer statement.

Potential directions to test, not results:
- Reparameterize the game so that the survivor set is never exponentially sparse, perhaps via a fixed family of weighted strata.
- Replace rejection sampling with a PV-computable sampler or a provably dense encoding of survivor circuits.
- Use a direct decision payoff with an explicit valid-label relation rather than passing through search circuits.
- Investigate whether a one-shot global minimax argument avoids sequential survivor sparsity altogether, while remaining formalizable with APC₁'s polynomial-precision counting.

## 5. Status

- R51 search-circuit survivor lemma: **proved combinatorially**, conditional on the explicit decision-circuit hardness and selector-size assumptions.
- APC₁ approximate counting: **available**, but its direct ambient-additive precision does not automatically resolve exponentially sparse late survivor sets.
- APC₁ proof of the R51 relative-halving statement: **open**.
- Polynomial-size search-to-decision conversion: **not established**; naive full restriction closure is exponential.
- Pich–Santhanam Theorem 7 / KPS decision anti-checker interface: **open**.
- Uniform polynomial-time generator and short EF transfer certificates: **open**.
- (P\ne NP): **open**; no separation proof is claimed.

## Sources

- Pich–Santhanam, *Towards P ≠ NP from Extended Frege lower bounds*, especially §1.1.3, §2.2–2.3, and §3: https://users.ox.ac.uk/~coml0742/papers/eopt.pdf
- ECCC record: https://eccc.weizmann.ac.il/report/2023/199/
- Jeřábek, *Approximate counting in bounded arithmetic*: https://doi.org/10.2178/jsl/1191333850
