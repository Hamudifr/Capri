# R62: corrected disjunctive survivor step, formula classes, and fibre rounding

## Executive summary

R62 corrects an overstatement in R58 and two concrete defects in the later R59/R61 notes.

1. **R58 overstates the fibre-certificate problem.** Literal storage of one hash certificate per formula would indeed be exponential, but R56 does not need to store them. Under the no-shrink assumption, Theorem 3.17 gives the required bound for every fibre; Theorem 3.19 is then invoked as an internal theorem of the bounded-arithmetic theory. Its not being a direct forall-Sigma^b_2 statement does not prevent this use.
2. **Theorem 3.20's t=1 rounding is two, not one.** The conclusion is bounded by ceil(t(1+2epsilon)); with t=1 and epsilon>0 this is 2. R59's later use of floor(1+2epsilon)=1 is incorrect. The earlier R56 repair (append at most two circuits) is the correct repair.
3. **R61's global-search alternative D is Sigma^b_2, not Sigma^b_1.** Its universal quantification over all n-bit formulas and witnesses is not sharply bounded. The disjunctive induction still has the desired Sigma^b_2 complexity because both D and the history invariant are Sigma^b_2.

The route is now better aligned: prove a local disjunction “global small search circuit OR one-step shrink,” use Sigma^b_2 length induction, and transfer the final forall-Sigma^b_2 statement by Jeřábek's conservation theorem. The exact single-step arithmetic and full formal derivation remain to be completed.

## 1. Correction to R58: no exponential certificate packing is required

R58 correctly observed that a literal list of separate fibre certificates for all q=(x,w) could have exponential total length. It incorrectly treated this as a necessary part of the R56 proof.

The actual proof can reason at the level of definable families:

- Let S be the current survivor set and split it, for each satisfiable x, into G_x (circuits that output a valid witness) and F_x (circuits that fail).
- Theorem 3.17 gives G_x ≼_epsilon A or F_x ≼_epsilon B, because G_x and F_x form a disjoint partition of S and S ≼_epsilon M.
- Under the contrary assumption that no satisfiable x has G_x ≼_epsilon A, the second alternative follows for every satisfying formula x.
- Corollary 3.18(ii) and Theorem 3.19 are applied to the uniformly definable incidence relation. Theorem 3.19 is precisely a theorem about a universally described family of fibres; it does not require the proof to write down a separate certificate string for each fibre.
- Theorem 3.20 then selects a tuple with a small exceptional fibre.

Theorem 3.19 is stated and proved in T^1_2(alpha)+sWPHP(PV_2(alpha)); Theorem 3.20 is stated in T^1_2(alpha)+rWPHP(PV_2(alpha)). Since rWPHP follows from sWPHP and T^1_2 is contained in S^2_2, these are available as internal lemmas in S^2_2(alpha)+sWPHP(PV_2(alpha)).

The source's warning that Theorem 3.19 is not itself a direct forall-Sigma^b_2 statement matters when transferring that theorem by conservativity as a standalone statement. It does **not** prevent using the theorem inside a derivation of a different low-complexity conclusion. Formula complexity belongs to the final one-step disjunction, not to every intermediate lemma separately.

Primary source: Jeřábek, *Bounded Arithmetic and Complexity*, Theorems 3.17–3.20:
https://users.math.cas.cz/~jerabek/papers/dsc.pdf

## 2. Corrected local one-step disjunction

Fix n and a search-circuit size parameter s. Let R_n(x,w) be the deterministic SAT witness verifier, and let S(H) be the circuits that solve every formula/witness pair already recorded in history H.

Define a global search-circuit alternative with an explicit size bound L(n,s):

D(n,s) := exists search circuit C of size at most L(n,s), such that
for every n-bit formula x and n-bit witness w,
R_n(x,w)=1 implies R_n(x,C(x))=1.

If D holds, the verifier applied to C(x) decides SAT_n: satisfiable formulas have at least one valid witness w, while unsatisfiable formulas have none. Choose L so that L(n,s)+V(n)≤s^3, where V(n)=O(n) is the verifier circuit overhead.

For a nonempty survivor set S(H), the intended local statement is:

D(n,s) OR exists satisfying pair (x,w) such that
G_x = {C in S(H): R_n(x,C(x))=1}
has approximate size at most 0.31 a(H),

where a(H) is the lower approximate-size parameter supplied by Theorem 3.21.

Proof by contradiction:
- Assume not D and assume no satisfying x has G_x ≼ 0.31a.
- Theorem 3.17 forces the failure side F_x to be approximately small for every satisfying x.
- Corollary 3.18(ii) and Theorem 3.19 bound the global bad-incidence relation.
- Theorem 3.20 yields a tuple with at most two exceptional formula/witness pairs.
- Under the no-shrink assumption, each exceptional formula has a successful survivor circuit. Append one such circuit per distinct exceptional formula, at most two circuits.
- The resulting first-valid-output selector is a globally correct search circuit of size at most L(n,s), contradicting not D.

Thus the local disjunction is the desired result. The finite incidence argument and selector repair are not invalidated by R58.

## 3. Correct formula complexity of D and the induction invariant

R61 labelled D as Sigma^b_1 because its quantifiers are bounded and its matrix is PV. This misses the distinction between sharply bounded and ordinary bounded quantifiers.

The quantifiers over all n-bit formula/witness pairs range up to 2^n, so they are not sharply bounded. Therefore

D(n,s) = exists C forall x,w [R_n(x,w)=1 -> R_n(x,C(x))=1]

is Sigma^b_2, not Sigma^b_1.

The nonuniform anti-checker alternative also has Sigma^b_2 form:

exists polynomial-length history H
forall size-s search circuits C
exists sharply bounded i < length(H):
R_n(x_i,C(x_i))=0.

The current-history invariant P(k), which existentially stores H and asserts an approximate-size bound on the PV-definable survivor set S(H), is Sigma^b_2 by Definition 3.1 / Remark 3.2.

Consequently I(k):=D(n,s) OR P(k) remains Sigma^b_2. The correction to D's classification does not break the disjunctive induction.

## 4. Corrected R59 fibre rounding

Jeřábek Theorem 3.20 gives a fibre bound ceil(t(1+2delta)). With t=1 and delta>0:

ceil(1+2delta)=2,

not 1. Corollary 3.10 therefore gives an actual list of at most two exceptional formula/witness pairs. There may be one or two distinct exceptional formulas. Append one successful circuit for each distinct formula, at most two circuits total.

For R59's r=6n tuple, the selector therefore uses at most 6n+2 circuits, not 6n+1. Its size remains

O((6n+2)(s+V(n))) = O(n(s+n)),

which is at most s^3 for s≥K n with sufficiently large fixed K.

## 5. A conservative exact-parameter repair for R59's 3/4-to-0.31 split

Use r=6n and set eta=epsilon=1/(1000r). Theorem 3.21 gives integer parameters a≤b≤ceil(a(1+eta)), hence b≤a(1+eta)+1.

The R59 incidence estimate is

E/a^r ≤ (729/1024)^n (1+eta)^r (1+epsilon)^(r+1) (1+4epsilon).

With eta=epsilon=1/(6000n), use 1+x≤exp(x):

(1+eta)^r(1+epsilon)^(r+1)(1+4epsilon)
≤ exp((12n+1)/(6000n)+4/(6000n))
≤ exp(0.002834).

Since 729/1024=0.7119140625, the product is below 0.714 for every n≥1. Retain the outer integer ceiling as an additive +1. For a≥100r, this remains strictly below s0=floor(0.74a^r).

For the survivor split, take

s_F = floor(floor(3b/4)/(1+2epsilon)),
s_G = floor(0.29a).

Then ceil(s_F(1+2epsilon))≤floor(3b/4), so the F-branch contradicts F_x not ≼ floor(3b/4).

Also ceil(s_G(1+2epsilon))≤0.29a+0.00058a+1≤0.31a for a≥100r.

The split condition s_F+s_G+1≥b follows from

s_F+s_G+1
≥ (0.75b-1)/(1+2epsilon)+0.29a-1,

and the difference between the right side and b is

[0.29a-0.25b-2-2epsilon(b+1-0.29a)]/(1+2epsilon).

Using b≤a(1+eta)+1, eta=epsilon=1/(1000r), and a≥100r≥600, the numerator is positive with ample slack. Thus Theorem 3.17 yields G_x ≼ 0.31a.

This is deliberately more conservative than R59's a≥21 threshold. It avoids the lost unit caused by the ceiling in Theorem 3.17 and restores a clean margin.

### Small-survivor branch

If a<100r, then a≤100r−1 and

b≤ceil(a(1+eta))≤100r,

because (100r−1)(1+eta)<100r. Corollary 3.10 gives an actual list of at most 100r survivor circuits. If every satisfiable formula has a successful circuit in S, a selector running this list decides SAT. Otherwise some satisfiable formula has G_x empty, giving immediate shrinkage.

This avoids the fragile finite threshold-20 integer table in R59 and reuses the robust small-list method from R56.

## 6. Disjunctive Sigma^b_2 induction and conservation

Let N_s bound the number of size-s circuit descriptions, with log N_s=O(s log(n+s)). Let rho=0.4. Define P(k) to assert that there is a length-k history H whose survivor set S(H) has approximate size at most N_s rho^k, with a fixed sufficiently small relative error.

- Base: the empty history has S(H) contained in the full circuit-description universe N_s.
- Step: if D holds, I(k+1) is immediate. Otherwise P(k) supplies H. If S(H) is empty, pad H with a fixed satisfiable pair. If it is nonempty, the local disjunction gives either D or a shrink pair. Theorem 3.21's minimality/binary-search construction and the section/retraction maps must show that the next upper parameter is at most 0.35 times the previous invariant bound, after all rounding and approximation errors.
- Since 0.35<0.4, the invariant propagates.
- After K=O(log N_s)=O(s log(n+s)) stages, the upper bound is below 1, forcing S(H)=empty. The final disjunction is D(n,s) OR a polynomial-size nonuniform search anti-checker.

The induction formula I(k)=D∨P(k) is Sigma^b_2. Its universal closure over n,s is a candidate forall-Sigma^b_2 theorem.

Jeřábek Theorem 2.1 states that

S^2_2(alpha) + BBSigma^b_3(alpha) + sWPHP(PV_2(alpha))

is forall-Sigma^b_2-conservative over

T^1_2(alpha) + rWPHP(PV_2(alpha)).

If the final forall-Sigma^b_2 disjunction is proved in S^2_2(alpha)+sWPHP(PV_2(alpha)), it is automatically also proved in the stronger theory with BBΣ^b_3 added. The conservation theorem then transfers it. We do not need to prove BBΣ^b_3 inside S^2_2; it is an added axiom in the stronger conservative-extension theory.

This resolves the apparent BBΣ^b_3 bookkeeping issue in R61, provided the full derivation really is in S^2_2+sWPHP and the final formula is correctly shown to be forall-Sigma^b_2.

Primary source for Theorem 2.1: Jeřábek, *Approximate counting by hashing in bounded arithmetic*, pp. 3–4:
https://users.math.cas.cz/~jerabek/papers/hash.pdf

## 7. Exact remaining obligations

1. Write the R59 incidence argument as a formal derivation in S^2_2(alpha)+sWPHP(PV_2(alpha)), with E's orientation, all ceilings, and the two-exceptional-pair repair explicit.
2. Verify the small branch's selector size and the global D size bound L(n,s)+V(n)≤s^3.
3. Prove Theorem 3.21 parameter propagation: if G_x ≼ 0.31a(H), then the next lower parameter a(Hx)≤0.31a(H), and derive the next upper parameter with exact ceilings.
4. Choose a cumulative error schedule for K=O(s log(n+s)) stages and prove the 0.35-to-0.4 margin.
5. Write the exact Sigma^b_2 formula P(k), the local disjunction, and the length-induction instance.
6. Verify that the final disjunction is genuinely forall-Sigma^b_2 and apply Theorem 2.1 exactly as stated.
7. Only after the search anti-checker statement is established, return to the separate search-to-decision conversion and KPS EF transfer-certificate obligations.

## Status

- R58 literal certificate-packing concern: **retracted as a necessary obstacle**; it is not needed when Theorem 3.19 is used as an internal theorem.
- Theorem 3.19 not being a direct forall-Sigma^b_2 statement: **source-verified**, but not itself a barrier to its internal use.
- Theorem 3.20 t=1 fibre size: **at most two**, correction source-verified.
- R59's 6n+1 selector: **corrected to 6n+2**.
- R59's threshold-20 split: **replaced by conservative a≥100r / a<100r split**.
- Local D OR shrink formula: **candidate Sigma^b_2 statement**, proof skeleton given; full formal derivation open.
- D formula class: **Sigma^b_2**, not Sigma^b_1.
- Disjunctive Sigma^b_2 induction: **candidate**, parameter/error proof open.
- Bounded-arithmetic polynomial-size search anti-checker: not yet proved.
- Uniform generator, decision anti-checker, KPS EF transfer, P≠NP: open.

R62 is a corrected proof blueprint and source audit, not a completed P-vs-NP proof.
