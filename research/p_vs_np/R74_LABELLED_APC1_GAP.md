# R74: the labelled anti-checker is the APC1 bottleneck

## Purpose

R74 compares the three anti-checker routes and isolates the exact obstacle between the lower-level search route and the higher-level decision route. The target is not merely a list of hard satisfiable formulas. Pich–Santhanam require a labelled decision anti-checker that catches both false negatives and false positives.

Primary source: Pich–Santhanam, *Towards P≠NP from Extended Frege Lower Bounds*, https://users.ox.ac.uk/~coml0742/papers/eopt.pdf, Theorem 7 and §§1.1.3, 2.3, 3.

## 1. Exact labelled object

For an n-bit formula x and assignment y, define:
Lab(x,y) iff for every assignment z, R(x,z)=1 implies R(x,y)=1.

Consequences:
- If x is satisfiable, Lab(x,y) holds exactly when y is a satisfying assignment.
- If x is unsatisfiable, Lab(x,y) holds for every y.
- For every x there is at least one valid label y.
- The relation gives a unique label once a canonical choice, such as lexicographically least satisfying assignment (or 0^n when unsatisfiable), is selected.

A labelled anti-checker consists of polynomially many pairs (x,y_x) such that every size-s decision circuit C is wrong on at least one labelled bit R(x,y_x). This catches both:
- false negatives: x satisfiable, C(x)=0, and y_x is a satisfying witness;
- false positives: x unsatisfiable, C(x)=1, and any label y_x gives R(x,y_x)=0.

Pich–Santhanam Theorem 7 requires this labelled decision object, not just a set of satisfiable formulas with witnesses.

## 2. Why the search anti-checker is insufficient

The R51/R55 search-circuit route uses the PV_1 verifier:
Good(C,x,y) iff R(x,C(x))=1.
Its survivor, success, failure, and incidence predicates can be kept PV_1 when selected formula/witness pairs are explicit.

This is attractive for APC_1. But its support consists of satisfiable formulas with witnesses. It only guarantees that every small search circuit fails on at least one satisfiable formula.

A decision circuit C with false positives can be converted by SAT self-reduction into a search circuit that fails on a satisfiable input because it follows a false-positive restriction. But the search anti-checker only says that the induced search circuit fails on some support formula; it does not identify a decision error of C on that formula. The false-positive restriction that caused the failure may lie outside the fixed support. Converting that failure into a fixed labelled decision counterexample requires a universal restriction family, and the naive family of all restrictions is exponential. Therefore the search anti-checker does not by itself imply the labelled decision anti-checker required by Theorem 7.

Naive repairs fail:
- Add arbitrary (x,y) pairs: a satisfiable x with an invalid y has R(x,y)=0 and can falsely label it unsatisfiable.
- Restrict to satisfying pairs R(x,y)=1: all unsatisfiable formulas disappear, so false positives remain uncaught.
- Include a witness for every satisfiable x: this is a global SAT search function, far stronger than the finite labelled anti-checker output.

## 3. Why the direct decision route rises to APC3

The direct decision-error predicate is:
Err(C,x) iff C(x) != SAT(x).

Without a valid label y_x, this predicate combines:
- C(x)=0 and SAT(x)=1, an NP condition;
- C(x)=1 and SAT(x)=0, a coNP condition.

It is Delta-b-2 in the ordinary language. Relative to the SAT Sigma-b-1 oracle alpha, it becomes quantifier-free in alpha, so Jeřábek's relative counting hierarchy can handle it as a Sigma-b-1(alpha) set. But substituting SAT for alpha raises the theory to the APC3/PV3 level:
S^3_2+BB-Sigma-b-4+sWPHP(PV_3),
with conservation to T^2_2+rWPHP(PV_3).

R69-R73 develop this direct route and obtain a candidate decision anti-checker / solver disjunction, but the proof strength is too high for the S^1_2 / EF target. The missing step is a descent from APC3/PV3 to APC1/PV1.

## 4. The precise APC1 MinMax target

Pich–Santhanam §1.1.3 explicitly identify a feasible MinMax theorem using only polynomial-precision APC1 counting as a route to proving anti-checkers in APC1 after replacing the p-time generator by existential quantifiers.

The relevant game should use formula-label pairs (x,y) satisfying Lab(x,y), with payoff:
Payoff(C,(x,y)) = 1 iff C(x) != R(x,y).

The challenge is that Lab(x,y) is Pi-b-1, not PV_1:
Lab(x,y) = forall z (R(x,z) -> R(x,y)).
Counting the payoff relation while enforcing valid labels is therefore not the same as counting a PV_1 failure relation. A successful APC1 MinMax formalization must handle this label-validity condition without:
- computing a global SAT witness selector;
- counting Delta_2 decision-error fibres at APC3;
- allowing invalid labels for satisfiable formulas.

This is the most direct formulation of the remaining lower-level obstacle.

## 5. Candidate research directions (unproved)

1. **Existentially packed labels:** formulate the MinMax game so each selected formula carries a label y, and the proof obligation Lab(x,y) is kept in the final universal block rather than queried by the counting function.
2. **Two-sided payoff decomposition:** split false-negative and false-positive errors, then prove a single APC1 dichotomy that handles the coNP label-validity side without requiring a global selector.
3. **KPT-aware construction:** allow a constant adaptive list of candidate labels/anti-checkers, but prove that the adaptive dependence can be eliminated or made EF-provable.
4. **PV_1 sampler/MinMax:** replace PV_2 interval search and APC3 fibre selection by a PV_1-computable sampler or a polynomial-precision PV_1 MinMax theorem.
5. **Proof-system descent:** if APC1 cannot establish the labelled object, identify the weakest stronger theory that can and the exact propositional proof system it corresponds to; do not call it EF.

## 6. Route status

| Route | Error / success predicate | Natural counting level | Output | Main gap |
|---|---|---|---|---|
| Search anti-checker | PV_1 witness verification | APC_1 candidate | Satisfiable formulas with witnesses | Does not catch false positives of decision circuits |
| Direct decision anti-checker | Delta_2 error; Sigma_1(alpha) relativized | APC_3 / PV_3 | Labelled decision anti-checker | Too strong for S^1_2 / EF |
| Labelled APC_1 MinMax | Pi_1 label validity plus PV payoff | APC_1 target | Correct two-sided labelled anti-checker | Feasible MinMax with valid-label constraint is missing |

R74's conclusion: the main bottleneck is not merely “search-to-decision conversion.” It is the **valid-label constraint for unsatisfiable formulas**. The search route avoids coNP by restricting to satisfiable inputs, but then loses false-positive coverage. The decision route handles both sides by querying SAT, but pays the APC3 cost. The APC1 route must bridge this exact gap.

No APC1 MinMax theorem, PV_1 generator, S^1_2 proof, KPS EF transfer, or P≠NP result is established here.
