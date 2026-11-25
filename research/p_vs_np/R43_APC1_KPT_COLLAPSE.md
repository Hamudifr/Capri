# R43: APC1 KPT witnesses become uniform under P = NP

**Status:** Conditional theorem only. It does not prove the existential antichecker statement or P != NP unconditionally.

## 1. KPT theorem for APC1

Pich–Santhanam, *Strong co-nondeterministic lower bounds for NP cannot be proved feasibly* (STOC 2021), §2.1, Theorems 3–4, defines
[
T_{APC_1}=T_{PV}+dWPHP(PV),
]
where (T_{PV}) is the true universal theory of polynomial-time functions. This theory extends (APC_1=PV_1+dWPHP(PV)).

Skolemizing the dual weak pigeonhole principle introduces witness functions (h_e) satisfying, for inputs ((a,b)),
[
h_e(a,b)<a(|b|+1),qquad
orall u<a|b|, e(u)
e h_e(a,b).
]
KPT applied to the witnessed universal theory yields finitely many adaptive terms (t_1,ldots,t_c), built from PV functions and the (h_e) symbols. The KPT disjunction holds for every challenge tuple and every interpretation of the (h_e) functions satisfying these axioms.

The paper's Theorem 4 also gives randomized KPT functions and, for the parameter-free (T^0_{APC_1}) variant, nonuniform circuits with advice. R43 does not rely on either version: it uses the exact witnessed-theory KPT terms.

## 2. Uniformizing each dWPHP witness under P = NP

For a fixed PV function e and explicit parameters (	heta), define
[
R_e(	heta,a,b,v) :=
[v<a(|b|+1)]land
[orall u<a|b|, e(	heta,u)
e v].
]

- The witness v has polynomial length in the bit length of the inputs.
- The first condition is polynomial-time.
- The second condition is coNP: a counterexample u is a polynomial-length witness that (e(	heta,u)=v).
- The relation is total by the finite pigeonhole principle: the range of e on a|b| inputs has at most a|b| elements, while the codomain has a(|b|+1) elements.

If P=NP, then coNP=P. Hence (R_e) is polynomial-time decidable. The search problem for v is in FNP and therefore in FP under P=NP. In particular, choose the lexicographically least valid v. This defines a uniform polynomial-time function (h_e^*(	heta,a,b)) satisfying the dWPHP witness axiom for every input.

This handles the full parameterized dWPHP principle. All hidden parameters of e are included explicitly in (	heta); no parameter-free restriction is needed.

## 3. Conditional APC1 theorem

**Theorem (derived conditional implication).** If APC1 proves the existential SAT-antichecker statement (S_K) for every sufficiently large fixed exponent K, then P != NP.

**Proof.**
1. Assume P=NP.
2. Since APC1 is contained in (T_{APC_1}), each APC1 proof of (S_K) is also a (T_{APC_1}) proof. Apply the witnessed KPT construction. Interpret each (h_e) by the uniform polynomial-time function (h_e^*) above. The resulting standard structure satisfies the witnessed theory, so the KPT disjunction holds for every challenge tuple.
3. Each KPT term (t_i) is now a uniform polynomial-time function, being a fixed composition of PV functions and the P-time functions (h_e^*).
4. Run the R40 path selector. Its three query types are NP: a counterexample to (B_i)'s search correctness, a falsifier of (D'_i), and a size-(n^K) circuit evading (Q_i). Under P=NP all are in P. Because the KPT disjunction holds for every tuple, the selector halts with either a correct SAT-search circuit B or a valid antichecker package Q.
5. For each search exponent k, choose K large enough that (D_C(x)=SAT_n(x,C(x))) for every size-(n^k) search circuit C belongs to the package's size-(n^K) decision-circuit class. Define (f^k(C)) as in R40: if the selector returns B, output any pair; if it returns Q, scan the finite support for a mismatch. Package validity rules out a false positive, so the mismatch supplies a satisfying witness where C fails.
6. Thus, for every k>1, there is a polynomial-time (f^k) such that Pich–Santhanam's (w_n^k(f^k)) is a tautology for all sufficiently large n. Their JACM 2026 Corollary 1 implies (NP\not\subseteq SIZE[n^\ell]) for every ℓ, contradicting P=NP.

Therefore, the assumed family of APC1 proofs implies P != NP.

## 4. Why this avoids the APC1 randomized-KPT issue

The randomized functions in Pich–Santhanam Theorem 4 have an inverse-polynomial success guarantee for each fixed challenge tuple. That guarantee alone cannot be union-bounded over the adaptively selected KPT history.

Instead, the witnessed theory introduces exact functions (h_e) satisfying dWPHP. Under P=NP, each missing-range search is in FP, so we can interpret the exact KPT terms by deterministic P-time functions. The KPT disjunction then holds for all histories, not merely with per-tuple probability.

The parameter-free (T^0_{APC_1}) nonuniform-advice construction is unnecessary for this argument.

## 5. Scope and open obligations

- This is conditional on APC1 proving (S_K) for all sufficiently large K.
- It does not prove (S_K), the canonical-pair hardness premise, or an unconditional P != NP result.
- It does not produce short EF proofs of the selected package's universal antichecker property.
- R42 is a separate KPS route for the length-bounded canonical pair (SAT, short-P-refutable UNSAT). It does not directly prove the unconditional Pich–Santhanam S_K, because unsatisfiable formulas without short P-refutations are not represented. The direct S_K route still needs to handle all negative SAT labels; its APC1 MinMax proof remains open.
- The KPT path selector is not a deterministic P-time selector without the temporary assumption P=NP.

## Sources

- Pich–Santhanam, *Strong co-nondeterministic lower bounds for NP cannot be proved feasibly*, STOC 2021, §2.1, Theorems 3–4: https://users.ox.ac.uk/~coml0742/papers/stoc-final.pdf
- Pich–Santhanam, *Towards P != NP from Extended Frege lower bounds*, Theorem 7 / §3 and Corollary 1: https://arxiv.org/abs/2312.08163
- Published JACM version: https://doi.org/10.1145/3801091
