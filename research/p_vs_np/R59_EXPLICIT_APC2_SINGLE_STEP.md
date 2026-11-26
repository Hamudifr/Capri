# R59: explicit APC2 single-step constants and small-survivor case

## Incidence constants

Use r=6n and ε₁=ε₂=η=1/(1000r). From Corollary 3.18(ii), Theorem 3.19, and b≤a(1+η), the bad incidence upper parameter relative to a^r is bounded by

(729/1024)^n · (1+η)^r · (1+ε₁)^(r+1) · (1+4ε₂).

A direct numerical bound gives <0.714 for every n≥1. Choose s₀=floor(0.74a^r).

## Lower bound for U

Theorem 3.21 gives a PV₂ injection [a]→S with a PV₂ left inverse. Taking r-fold products gives [a^r]→U=S^r. If U were approximately bounded by s₀−1, Theorem 3.8 would yield a PV₂ surjection from a smaller-power interval onto a corresponding power of U. Composing with U→[a^r] contradicts rWPHP, since s₀≈0.74a^r.

## One-element fibre and repair

Theorem 3.20 with t=1 yields a tuple u whose bad-pair fibre is bounded by floor(1+2ε)=1. Corollary 3.10 converts this approximate upper bound into an actual sequence of length at most one, since 1≤ε^{-1} is logarithmically bounded.

Under the contrary hypothesis F_x ≼ε 3b/4 for all satisfying x, and b≤a(1+η), the failure set is strictly smaller than the lower size parameter a. Since [a] injects into S, a successful circuit exists. If the exceptional list contains one pair (x,w), append a circuit C*∈S that solves x. The enlarged tuple of at most 6n+1 circuits covers every satisfiable formula.

## Constant-factor survivor split for large a

The contradiction yields x with F_x not ≼ε 3b/4. For a≥21 choose
s_F=floor((3b/4)/(1+2ε)), s_G=floor(0.30a).
Because a≤b≤a(1+η), s_F+s_G+1≥b with floor slack. Theorem 3.17 gives either F_x ≼ε floor((1+2ε)s_F)≤3b/4, contradiction, or G_x ≼ε floor((1+2ε)s_G)≤0.31a.

## Small-a case

If a≤20, then b≤20 for the chosen η. Since b≤ε^{-1}, Corollary 3.10 gives an exact list of at most b elements covering S and exact short lists for F_x and G_x. The conclusion F_x not ≼ε floor(3b/4) implies |F_x|>floor(3b/4), so
|G_x|≤b-floor(3b/4)-1≤0.25b≤0.251a≤0.30a.
Thus the same shrink holds without applying Theorem 3.17 with too-small parameters.

## Remaining

- Fully formalize nested errors and floors.
- Write the history-dependent Σᵇ₂ induction over O(s log(n+s)) stages.
- Verify selector size O((6n+1)(s+V(n)))≤s³ for a sufficiently large fixed polynomial exponent.
- Uniform anti-checker generator, Pich–Santhanam decision anti-checker, KPS EF certificates remain open.
- No P≠NP proof.

Source: Jeřábek, *Bounded Arithmetic and Complexity*, Chapter II, Theorems 3.8, 3.10, 3.17–3.21:
https://users.math.cas.cz/~jerabek/papers/dsc.pdf
