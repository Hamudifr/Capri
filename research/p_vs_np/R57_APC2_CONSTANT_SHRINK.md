# R57: APC2 theory compatibility and constant-factor shrink

## Theory compatibility

APC2 is T1_2+sWPHP(PV2). Jeřábek Theorems 3.20 and 3.21 are stated over T1_2+rWPHP(PV2), while Theorem 3.19 and Corollary 3.18 use sWPHP. Chapter II, Section 2 states that rWPHP(f,g) follows from either sWPHP(f) or iWPHP(g). Thus sWPHP(PV2) supplies the required rWPHP(PV2) instances.

## Candidate single-step theorem

Let S be a nonempty PV survivor set of size-s SAT search circuits. Theorem 3.21 gives a<=b<=a(1+eta), with [a] injecting into S and [b] mapping onto S. Set r=6n, U=S^r, and Q={(x,w):R(x,w)=1}. For F_x={C in S:R(x,C(x))=0}, assume for contradiction F_x is approximately bounded by 3b/4 for every satisfying pair.

Corollary 3.18(ii) bounds F_x^r. Theorem 3.19 bounds the bad incidence relation by approximately
(1+4eps) 2^(2n)(1+eps)^(r+1)(3b/4)^r.
Relative to a^r this is at most
(729/1024)^n (1+eta)^r (1+eps)^(r+1)(1+4eps),
which has a large constant margin below 3/4 for inverse-linear error parameters.

The injection [a^r]->U and a choice s0 near 3a^r/4 let Theorem 3.20 with t=1 produce a tuple with at most one bad satisfying pair. The contrary hypothesis and a<=b<=a(1+eta) ensure an additional successful circuit exists for that formula. Append it; a tuple of at most 6n+1 search circuits covers every satisfiable formula. A first-valid-output selector decides SAT, contradicting SAT_n notin SIZE(s^3) under explicit selector-size slack.

## Constant-factor survivor shrink

The contradiction yields x with F_x not approximately bounded by 3b/4. Theorem 3.17 applied to S=F_x disjoint union G_x, with split parameters near 3b/4 and 0.3a, should force G_x to be approximately bounded by 0.31a. This gives a candidate geometric invariant for repeated greedy selection.

## Remaining proof obligations

- Exact nested error and rounding derivation.
- Internal proof that the extra successful circuit exists.
- Exact Theorem 3.17 split parameters.
- Σb2 history-dependent induction.
- Selector size and verifier bounds.
- Deterministic generator and KPS/EF bridge.

Status: detailed APC2 route, not a completed formal proof. P != NP remains open.
Source: https://users.math.cas.cz/~jerabek/papers/dsc.pdf
