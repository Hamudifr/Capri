# R36: finite-game audit for P-vs-NP anticheckers

This directory contains a deliberately isolated research experiment. It is not imported by Capri runtime code and adds no runtime dependency.

## What is tested

- A finite zero-sum payoff LP for direct input-example games.
- The identity-matrix transcript counterexample: pointwise coverage alone can have value 1/M.
- Mutual information for deterministic finite response maps.
- A synthetic constant-round causal KPT game.
- Exhaustive enumeration of all 16,384 three-round causal package strategies over a two-element challenge universe. Every strategy satisfying the all-sequences KPT property has a terminal package covering the whole universe.

## Run

Requires Python 3, NumPy, and SciPy.

    python -m pip install numpy scipy
    python minimax_audit.py
    python -m unittest -v

## Mathematical status

The KPT terminal-package lemma recorded in R36 is a derived adversarial-path unpacking of the exact KPT predicate in Pich–Santhanam, *Towards P != NP from Extended Frege lower bounds*, preprint §3. At each round, the KPT function outputs its package before the current circuit challenge. If no output search circuit is globally correct, choose a witness that falsifies the search branch. If the bounded validity predicate has a falsifying input, choose it; otherwise choose a circuit that evades the package unless the package already refutes every circuit. Continuing for all constant-many rounds would falsify every KPT disjunct, contradiction.

This is the Student–Teacher interpretation: the KPT functions are the Student; the previous circuits, formula/witness pairs, and auxiliary inputs are the Teacher's counterexamples. Ježil–Tsintsilidas (2026), Theorems 1.6–1.8, classify PV1-provable forall-exists-forall statements as constant-round, one-query-per-round Student–Teacher games. Their adaptivity/parallelism separations are general results and do not prove this SAT-specific selector impossible.

This is a nonuniform existence argument. It does not construct the history in deterministic polynomial time, prove P != NP, prove SAT not in P/poly, or provide a PV1/S1_2-provably correct selector.

The Python tests are finite sanity checks only. They do not prove the asymptotic KPT lemma.

## Sources

- Pich–Santhanam preprint: https://users.ox.ac.uk/~coml0742/papers/eopt.pdf
- Published version: https://doi.org/10.1145/3801091
- Ježil–Tsintsilidas, *Parallelism and Adaptivity in Student-Teacher Witnessing* (2026): https://arxiv.org/abs/2602.19934
- Chen–Li–Oliveira–Williams, APX1: https://arxiv.org/abs/2602.09302


# R37: OPS selector and verified Lean kernel

## Additional artifacts

- OPS_SELECTOR_ROUTE.md: OPS Lemma 4.1 / Theorem 1.4 hardness-magnification route, the fixed-family versus input-dependent anti-checker distinction, the APC1 relative-counting obstruction, and the soft-weight floor experiment.
- ops_selector_toy.py and test_ops_selector_toy.py: finite adaptive-selector example; 3 tests.
- soft_weights_floor_test.py and test_soft_weights_floor_test.py: finite counterexample to naive raw-weight floor in multiplicative weights; 2 tests.
- formalization/: Lean 4.24.0 proof of the abstract finite causal-game terminal-package lemma. GitHub Actions run 45696083281 passed; axiom audit checked five declarations under the allowlist propext, Classical.choice, Quot.sound.

## R37 mathematical status

OPS gives a near-linear-in-truth-table-length selector under NP ⊆ Circuit[poly]. Its construction uses relative approximate counting of the circuits still consistent with the growing sample. This does not directly transfer to APC1's polynomial-precision additive counting, because late survivor sets can be exponentially sparse. A naive raw-weight floor also fails in a finite expert game: a polynomial floor destroys concentration, while a normalized floor is exponentially small per expert.

The Lean result formalizes only the abstract causal-game terminal lemma. It does not formalize the bounded-arithmetic KPT theorem, SAT-specific package predicates, the search-circuit branch, or EF translation. No P-vs-NP proof is claimed.

All five Python tests pass. Main remains untouched; the R37 work is isolated on this research branch.


# R40–R41: KPT selector collapse under P = NP

See [R40–R41 conditional KPT selector analysis](R40_KPT_COLLAPSE_CONDITIONAL.md).

The new conditional implication is: if the existential SAT-antichecker statements are provable in PV1 (or, separately, APX1) for every sufficiently large fixed circuit exponent, then P != NP. The proof uses a constant-round KPT path selector in FP^NP; under P = NP, this selector becomes uniform polynomial time and yields the witness functions required by Pich–Santhanam Corollary 1.

This is not an unconditional P-vs-NP proof. The main open obligation remains proving the existential antichecker statement in the required bounded-arithmetic theory. The APX1 Refuter(Yao) theorem does not directly witness the higher-quantifier selector.


# R42: certificate-lifted canonical-pair MinMax

See [certificate-lifted canonical-pair MinMax analysis](R42_CERTIFICATE_LIFTED_MINMAX.md).

The key representation change is to use certified encodings z=(formula, label, witness-or-refutation) as the MinMax column domain. The payoff valid(z) AND (C(formula) != label) is a total PV predicate, unlike the direct SAT-disagreement payoff. Under canonical-pair hardness, majority amplification gives a constant-error, polynomial-support antichecker if the SAT circuit-hardness premise holds.

This is a formalization route, not a proof of canonical-pair hardness or of the APC1/APX1 MinMax theorem. The universal antichecker proof and full KPS transfer implication remain open.


# R43: APC1 KPT uniformization under P = NP

See [APC1 KPT uniformization conditional theorem](R43_APC1_KPT_COLLAPSE.md).

The new conditional implication is: if APC1 proves the existential SAT-antichecker statement S_K for every sufficiently large fixed exponent, then P != NP. The key is the witnessed dWPHP form of the APC1 KPT theorem. Under P = NP, each missing-range witness function h_e can be computed in P by searching for a value outside the range of a polynomial-time function; the KPT terms then become uniform P-time, and the R40 path selector yields the witness functions needed by Pich–Santhanam Corollary 1.

This does not prove S_K in APC1 or P != NP unconditionally. R42 is a separate KPS canonical-pair route: it covers only unsatisfiable formulas with short P-refutations, not every negative SAT instance. The direct S_K MinMax problem remains open.


# R44–R45: validity-constrained SAT labels and APC2 game

- R44 identifies the label-validity predicate Valid(x,y) := forall y' [SAT(x,y') -> SAT(x,y)] and shows why unrestricted formula-assignment pairs create false anticheckers.
- R45 constructs the full-SAT valid-pair game. Its payoff is coNP/Delta2, and ordinary finite minimax plus majority amplification yields a constant-error, polynomial-support antichecker if the SAT circuit lower-bound premise holds.
- The APC2 formalization is still open: counting a Delta2 payoff does not by itself prove a mixed minimax theorem for the exponentially large succinct matrix or produce the polynomial-size sampled support in the theory.

See the canonical Notion workpaper for the full derivation and quantifier audit.


# R46: dWPHP label-shift obstruction and APC2 MinMax gap

See [R46 dWPHP label-shift and APC2 MinMax audit](R46_DWPHP_LABEL_SHIFT_AND_APC2_MINIMAX.md).

CKKOT ITCS 2025 Theorem 9 proves arbitrary succinct hard labelled samples in APC1 by dWPHP, but does not force the labels to be true SAT labels or provide satisfying witnesses. A proposed XOR-shift conversion fails because an arbitrary m-bit mask may require an ordinary circuit description of length Ω(m), so the dWPHP output length cannot exceed the transformed input description length. This is a failed route, not a general impossibility theorem.

R45's full-SAT validity-constrained game remains combinatorially sound. The remaining proof obligation is a polynomial-precision, succinct mixed-MinMax/strategy-existence theorem in APC2, followed by the exact Pich–Santhanam S_K translation and proof-system certification. No P-vs-NP proof is claimed.


# R47: APC2 semantic witnessing audit

See [R47 APC2 semantic witnessing audit](R47_APC2_SEMANTIC_WITNESSING_AUDIT.md).

CKKO21 distinguishes ordinary KPT from the semantic randomized witnessing needed for dWPHP-extended theories. Its VAPC2 boundary confirms a randomized NP-oracle / LEARN-uniform character, but does not itself give the exact S_K selector. The possible collapse under P=NP remains conditional on checking formula class, rounds, success verification, and the semantic Skolem-function assignments.

R45's APC2 conditional P != NP route is therefore marked **not closed**. R40 (PV1) and R43 (APC1) remain separate conditional implications. No unconditional P-vs-NP proof is claimed.


# R51: search-circuit survivor anti-checker

See [R51 search-circuit survivor anti-checker](R51_SEARCH_SURVIVOR_ANTICHECKER.md).

A separate greedy construction for search circuits: if every satisfiable formula is solved by more than half of the current survivor set, (n+1) independent samples contain a solver for every satisfiable (n)-bit formula with positive probability. A first-valid-output selector then yields a SAT decision circuit, contradicting the chosen circuit-hardness premise. Thus a satisfiable formula defeats at least half the survivors; retaining only circuits that solve each selected formula halves the set at every step.

This gives a polynomial-size **nonuniform search anti-checker** with explicit satisfying witnesses. Its survivor and failure predicates are PV, avoiding the coNP-valid-label issue of arbitrary decision labels. The APC₁ relative-counting formalization, uniform generator, exact bridge to KPS's decision anti-checker, and EF transfer certificates remain open. No P-vs-NP proof is claimed.


# R52: APC2 relative-counting search survivor

See [R52 APC2 relative-counting search survivor](R52_APC2_RELATIVE_COUNTING_SEARCH_SURVIVOR.md).

R52 strengthens the R51 search-survivor argument by counting formula/witness pairs. With r=2n+2 candidate search circuits, the bad-pair set has size at most |S|^r/4 if every satisfiable formula is solved by more than half of the survivors. Its projection cannot cover S^r, so some tuple contains a valid solver for every satisfiable formula. This gives a first-valid-output SAT decision circuit and hence a halving witness under the stated circuit-size slack.

The formalization target is now APC2, not APC1: the survivor and bad-pair sets are PV / Sigma^b_1, and APC2 supplies relative counting for sparse sets plus parameterized-family averaging. The exact APC2 derivation and polynomial iteration remain open. The anti-checker is still nonuniform; the Pich-Santhanam feasible generator and KPS EF transfer certificates are not obtained. No P-vs-NP proof is claimed.


# R53: APC2 empty-fibre route

See [R53 APC2 empty-fibre route](R53_APC2_EMPTY_FIBRE.md).

R53 applies Jeřábek's Theorem 3.20 to the R52 bad-pair incidence relation, with candidate search-circuit tuples as the first coordinate and satisfying formula/witness pairs as the second. Together with Theorems 3.19 and 3.21, the constant 1/4 incidence gap appears to force an empty fibre, giving the APC2 single-step survivor lemma. Theorem 4.2 supplies a close template for the greedy iteration, but its adaptation is not complete.

The search-to-decision bridge remains open because SAT self-reduction is adaptive and its full query tree can be exponential. No deterministic generator, KPS EF transfer certificate, or P-vs-NP proof is claimed.


# R54: one-element APC2 fibre repair

See [R54 one-element APC2 fibre repair](R54_ONE_ELEMENT_APC2_REPAIR.md).

R54 corrects R53: Jeřábek Theorem 3.20 with t=1 gives a fibre of size at most one, not necessarily zero. A finite combinatorial repair appends one additional surviving search circuit that solves the sole remaining formula, yielding a tuple of at most 2n+3 circuits covering every satisfiable formula. The APC2 derivation is not complete: the key missing step is deriving per-fibre approximate size bounds from the formalized contrary hypothesis. The tournament principle is only an induction template, not a direct application. No P-vs-NP proof is claimed.


# R55: robust APC2 fibre dichotomy

See [R55 robust APC2 fibre dichotomy](R55_APC2_ROBUST_FIBRE_DICHOTOMY.md).

R55 uses Jeřábek's disjoint-union dichotomy to repair the per-fibre counting gap in R54. For each satisfiable formula, either the successful survivor set is approximately at most 3/4 of S, giving the desired constant-factor survivor reduction, or the failure set is approximately at most 1/4 of S. In the latter case, product counting and the parameterized averaging theorem make the bad tuple incidence set small; the empty-fibre theorem leaves at most one uncovered formula/witness pair, repaired by appending one successful circuit. With r=n+1 the target incidence ratio is below 0.255 including the outer ceiling for the stated small relative error and large-parameter branch. The interval lower-bound comparison and small-survivor exact-counting branch now have explicit proof routes, though their formal composition remains to be written. The small-survivor case has a separate exact-list treatment using Theorem 3.21's polynomial-length enumeration.

This is a promising APC2 single-step proof route, not yet a completed formal derivation. The small-parameter exact-counting branch, interval lower-bound implication, bounded formula classes, and witness extraction still need explicit proofs. Greedy iteration, uniform generation, the Pich–Santhanam/KPS decision and EF-certificate bridge, and P != NP remain open.


# R56: empty-fibre rounding repair and selector audit

See [R56 empty-fibre rounding repair](R56_EMPTY_FIBRE_ROUNDING_REPAIR.md).

R56 corrects R55's use of Theorem 3.20: with t=1 the theorem's ceiling gives at most two exceptional formula/witness pairs, not one. Append one successful search circuit for each distinct exceptional formula, at most two circuits total. The selector then uses at most n+3 circuits and remains polynomial size under the standard O(n)-size SAT witness verifier and s≥Kn.

R56 also separates Theorem 3.20's internal precision delta from the outer approximation epsilon, records the source's exact Theorem 3.21 section/retraction maps, and gives a candidate recurrence for repeated survivor reduction. A stronger small-parameter repair now bypasses incidence counting entirely: if the lower parameter a<100(n+1), Theorem 3.21 and Corollary 3.10 enumerate S with O(n) circuits, and their parallel selector contradicts SAT circuit hardness unless one formula defeats every circuit. For a≥100(n+1), retaining both ceiling errors, the refined incidence ratio is below 0.29a^r, still below the half-size threshold. The recurrence and one-step arithmetic are promising, but full APC2 formula-class/witness extraction and history-dependent iteration remain unproved. No uniform generator, KPS EF transfer certificate, or P≠NP proof is claimed.


# R57: Sigma-2 survivor induction blueprint

See [R57 Sigma-2 survivor induction](R57_SIGMA2_SURVIVOR_INDUCTION.md).

R57 investigates formalizing repeated R56 survivor reduction by Sigma^b_2-LIND. Jeřábek's approximate-size relation is Sigma^b_2 for Sigma^b_1 sets, and Theorem 4.2 demonstrates history-dependent approximate shrinking by this induction pattern. The candidate invariant stores the satisfiable-formula history and all approximate-size certificates in one polynomial-length string. The large-step recurrence shrinks the upper parameter by <0.77 while it is at least 100(n+1); the small branch enumerates O(n) circuits and terminates by a selector contradiction.

This is not yet a bounded-arithmetic anti-checker theorem. The exact one-step Sigma^b_2 implication, certificate packing, induction invariant, and theory transfer remain to be formalized. If completed, it would yield a nonuniform search anti-checker, not the Pich–Santhanam decision anti-checker or KPS EF transfer certificates.


# R58: fibre-complexity audit

See [R58 fibre-complexity audit](R58_FIBRE_COMPLEXITY_AUDIT.md).

R58 identifies a specific gap in R57: packing the polynomially many *stage* certificates does not pack the exponentially many per-formula fibre certificates used by the R56 incidence bound. Jeřábek Theorem 3.19 requires a pointwise fibre-size premise and is explicitly not a direct forall-Sigma^b_2 statement; Theorem 3.20, by contrast, has an explicit forall-Sigma^b_2 formulation. Thus the finite incidence arithmetic remains conditional on its fibre bounds, but the uniform one-step survivor implication has not been shown to lie in Sigma^b_2. Candidate repairs are a uniform PV_2 fibre-certificate selector, a specialized forall-Sigma^b_2 incidence lemma, or a direct tournament/partial-colouring reformulation. No bounded-arithmetic anti-checker or P≠NP proof is claimed.

**R62 correction:** The literal exponential certificate list is not required: Theorem 3.19 can be invoked as an internal theorem on the universally defined fibre family. Its not being a direct forall-Sigma^b_2 statement does not block this internal use. R62 also corrects the t=1 rounding to at most two exceptional pairs, fixes the selector length to 6n+2 in the r=6n route, and corrects the global search-circuit alternative D to Sigma^b_2 (not Sigma^b_1). See R62 for the disjunctive local step and conservative parameter split.



# R62: corrected disjunctive survivor step and fibre rounding

See [R62 corrected disjunctive step and rounding audit](R62_DISJUNCTIVE_STEP_AND_ROUNDING_AUDIT.md).

R62 retracts R58's claim that the exponential family of per-formula fibre certificates must be explicitly packed. Theorem 3.19 can be used as an internal bounded-arithmetic lemma on the universally defined fibre family. R62 formulates the desired local result as a disjunction: either a globally correct small search circuit exists, or there is a formula causing a constant-factor survivor shrink. The global search-circuit alternative is Sigma^b_2, not Sigma^b_1, because its universal quantifiers range over all n-bit formulas and witnesses; the disjunctive induction invariant nevertheless remains Sigma^b_2.

R62 also restores Theorem 3.20's correct t=1 rounding: at most two exceptional pairs, repaired by appending at most two circuits. For the r=6n construction it replaces the fragile threshold-20 split by a conservative a≥100r / a<100r split and chooses parameters that absorb the ceiling in Theorem 3.17. The bounded-arithmetic search anti-checker is still not proved: exact formalization of the local disjunction, parameter propagation, cumulative error schedule, and conservativity transfer remain open. Moreover, even a completed D OR anti-checker dichotomy would not imply P≠NP: under P=NP the D branch can hold for sufficiently large polynomial s. A separate argument must eliminate D or prove the anti-checker statement unconditionally. No uniform generator, Pich–Santhanam decision anti-checker, KPS EF transfer, or P≠NP proof is claimed.


# R63: uniformity gap and feasible anti-checkers

See [R63 uniformity gap audit](R63_UNIFORMITY_GAP_AUDIT.md).

R63 confirms from Jeřábek's original Theorems 3.19–3.20 that the incidence method handles uniformly described large fibre families and that the t=1 exceptional fibre is at most two. The next major obstacle is uniformity: the bounded-arithmetic route uses PV₂/FP^NP resources and yields existential anti-checker objects, whereas Pich–Santhanam Theorem 7 requires a single p-time generator whose correctness is proved in S¹₂. Their KPT discussion shows that replacing the generator by existential quantifiers yields an adaptive constant list, not automatically one fixed generator. The current search anti-checker also still needs conversion to their decision anti-checker with unique assignment labels. No feasible anti-checker generator or P≠NP proof is claimed.


# R64: direct decision anti-checker fibre obstruction

See [R64 decision fibre obstruction](R64_DECISION_FIBRE_OBSTRUCTION.md).

R64 revisits the R49 majority-sampling anti-checker, which is the right nonuniform decision-circuit object for Pich–Santhanam. A weighted Chernoff/tagging inequality gives a compact finite combinatorial tail bound. But the decision-error fibre C(x)≠SAT(x) is generally BΣᵇ₁/Δ₂, not Σᵇ₁, because it includes the unsatisfiable case. Jeřábek's relative Sipser counting theorems require Σᵇ₁ sets. The older Δ₂ counting framework has ambient-additive precision, insufficient for the exponentially small majority-error fibres needed to union-bound over 2ⁿ formulas. Thus R49's external nonuniform proof remains sound, but this direct bounded-arithmetic formalization is blocked by both definability and sparsity. R51/R56/R62 search anti-checker remains the better APC₂ route, with the separate search-to-decision gap unresolved.


# R65: exact Pich–Santhanam label interface

See [R65 label interface audit](R65_LABEL_INTERFACE_AUDIT.md).

R65 checks the full statement of Pich–Santhanam Theorem 7. R49's direct nonuniform decision anti-checker already has the required object shape: a polynomial-size formula set plus one label per formula, valid whenever the formula is satisfiable, and defeating every target decision circuit. It does not need conversion from the search anti-checker. The missing step is feasible generation and an S¹₂ proof. The valid-label condition is Πᵇ₁ (∀w, SAT(x,w)→SAT(x,yₓ)); a final polynomial-size label table exists nonuniformly, but the R49 majority argument needs the SAT bit over all 2ⁿ formulas before constructing the final set. The global decision-error fibres remain Δ₂/Boolean-combination objects, outside Jeřábek's current Σᵇ₁ relative-counting theorems. Search and decision anti-checker routes remain distinct.
