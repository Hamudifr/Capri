# R46: dWPHP label-shift obstruction and APC2 MinMax formalization gap

**Status:** Source audit and failed reduction. No proof of the required APC2 MinMax theorem and no P-vs-NP proof.

## 1. APC1 succinct circuit hierarchy is not a SAT antichecker theorem

Carmosino–Kabanets–Kolokolova–Oliveira–Tsintsilidas, *Provability of the Circuit Size Hierarchy and Its Consequences* (ITCS 2025), Theorem 9, proves in APC1 the succinct circuit-size hierarchy:

```
there is a labelled sample F_y of size n^a such that
for every circuit C of size n^b, C disagrees with some label in F_y.
```

The proof is direct dWPHP. Given a circuit description C of length r = O(n^b log n), a PV function outputs its complete evaluation table on n^a fixed inputs. Since n^a > r, dWPHP supplies a string y outside the image.

This is a legitimate APC1 proof of an arbitrary hard labelled sample. It does **not** make y the SAT truth table on its support, and it does not supply satisfying assignments for the positive labels. It therefore does not prove Pich–Santhanam's feasible-antichecker statement.

## 2. A tempting SAT-specific dWPHP shift, and why it fails

Fix a polynomial-size support A = {x_1,...,x_m}. Using an NP oracle, define

```
E_C = (C(x_i) XOR SAT(x_i))_{i <= m}.
```

This is computable from C in FP^NP. If dWPHP gives a missing vector e outside all E_C, then the labels SAT(x_i) XOR e_i defeat every circuit C in the source circuit class.

But these are not SAT labels unless e = 0. One might try to convert an arbitrary circuit D into C = D XOR M_e, where M_e is a lookup circuit taking value e_i on x_i. Then E_C = e would contradict the missing-vector property if D agreed with SAT. The conversion is circular in the size parameters:

- an arbitrary m-bit mask e on m designated points requires, in the worst case, a circuit of size Ω(m/log m), by counting the number of circuits of size q (at most 2^{O(q log q)}) against the 2^m possible masks;
- its ordinary circuit description therefore has length Ω(m);
- the dWPHP map would need an input length at least the description length of D XOR M_e, but its output length is only m.

So the output length cannot exceed the input length as required by dWPHP. Padding the dWPHP output does not help: if the extra bits are fixed, a missing string may differ only in those padding bits, leaving the projected mask inside the image. This is a failed reduction, not a proof that every alternative dWPHP construction is impossible.

**Consequence:** The generic APC1 SCSH proof cannot be converted to true SAT labels by a simple XOR-shift. This explains why arbitrary labelled-example hardness is weaker than a SAT antichecker with valid witnesses.

## 3. Refined APC2 finite-game formalization target

R45's game remains combinatorially sound:

- columns are all pairs (x,y);
- Valid(x,y) := forall y' [SAT(x,y') -> SAT(x,y)], equivalently SAT(x,y) OR UNSAT(x);
- payoff M(C,(x,y)) := Valid(x,y) AND [SAT(x,y) != C(x)], and zero on invalid pairs.

For every x at least one valid y exists; every valid y has the true SAT bit. The R45 majority argument therefore proves, by ordinary finite minimax, that if SAT has no size-s^3 circuit then the game value is at least 1/2 - 1/sqrt(s), for sufficiently large s >= c n. Sampling O(s log s) columns from a maximin distribution gives a valid mixed-label antichecker.

The formalization gap is sharper than “APC2 can count coNP predicates”:

1. **Matrix entries:** M is coNP/Delta_2 and is within the Delta_2-definable counting scope of APC2's additive approximate counting. This part is syntactically plausible.
2. **No automatic minimax theorem:** APC2's counting toolbox (averaging, Chernoff, approximate cardinalities) does not by itself provide a uniform finite von Neumann minimax/LP-duality theorem for an exponentially large succinct Delta_2 payoff matrix. No source found so far establishes that exact theorem in APC2.
3. **Distribution representation:** A literal mixed strategy over all columns has exponentially many rational weights and is not a polynomial-length bounded-arithmetic object. The standard proof first obtains such a distribution by LP duality, then samples O(s log s) columns. To formalize this in APC2, one needs a proof that the short sampled support exists without assuming an unrepresentable full distribution, or a succinct/implicit strategy theorem.
4. **Validity preservation:** Invalid columns have payoff zero. Since the game value is bounded below by a positive constant, a positive-value maximin distribution has positive mass on valid columns. Conditioning on the valid part preserves or increases every circuit's expected payoff. However, the proof must formalize the weighted mass/conditioning operation at the required precision; it cannot simply count the valid domain as a dense subset.
5. **KPT complexity:** The final statement must be translated into the exact Pich–Santhanam bounded formula, with the original n-scale, polynomial support size, existential label table, and its universal validity condition. A truth-table input of length 2^n or an exponential-size mixed strategy does not meet the required selector parameters.

## 4. Related bounded-arithmetic results: what they do and do not supply

- Jeřábek's *Approximate Counting by Hashing in Bounded Arithmetic* (2009) develops multiplicative approximate counting for Sigma_1^b sets in T_2^1 + sWPHP(PV_2), and a toolbox of averaging, products/unions, and approximate enumeration. Its additive-error counterpart reaches Delta_2^b sets. This supports the matrix-predicate complexity diagnosis, not automatically minimax.
- Pudlák–Thapen, *Alternating Minima and Maxima, Nash Equilibria and Bounded Arithmetic* (2012), characterizes T_2^i by alternating minima/maxima and pure-strategy k-turn games. It does not state the mixed-strategy von Neumann minimax theorem for a succinct exponentially large matrix. The pure-strategy theorem should not be cited as if it were the missing mixed MinMax theorem.
- CKKOT ITCS 2025 Theorem 9 supplies the APC1 dWPHP proof of unrestricted SCSH, but labels are unconstrained.
- KPS CCC 2026 Theorem 11 still requires the separate proof-system statement: for each z, a short P-proof of not-lb_A(SAT,s)[B] AND SAT(z,y) -> SAT(z,F(z,B)). An abstract support-existence theorem alone does not produce this proof.

## 5. Updated status and next attack

**Established:** APC1 proves arbitrary succinct hard labelled samples by dWPHP; this does not yield SAT-consistent labels. The XOR-shift conversion fails because encoding an arbitrary missing mask costs at least its output-length scale. R45's validity-constrained game and constant-error combinatorial bound remain correct.

**Open:** Prove a polynomial-precision, succinct mixed-MinMax/strategy-existence theorem for the Delta_2 payoff matrix in APC2, including a polynomial-size sampled support with SAT-valid labels, and translate it to the exact S_K statement. Then separately prove the EF/APC2 certificate or KPT conditions required by the conditional P != NP route.

**No P != NP proof obtained.** No claim that APC2 proves this MinMax theorem.

## Sources

- Carmosino, Kabanets, Kolokolova, Oliveira, Tsintsilidas, *Provability of the Circuit Size Hierarchy and Its Consequences*, ITCS 2025, Theorem 9: https://doi.org/10.4230/LIPIcs.ITCS.2025.30 ; https://www.dcs.warwick.ac.uk/~igorcarb/documents/papers/CKKOT25.pdf
- Jeřábek, *Approximate Counting by Hashing in Bounded Arithmetic*: https://users.math.cas.cz/~jerabek/papers/hash.pdf
- Pudlák–Thapen, *Alternating Minima and Maxima, Nash Equilibria and Bounded Arithmetic*: https://doi.org/10.1016/j.apal.2011.06.014
- Khaniki–Pich–Sokolov, *Efficient Adversaries*, CCC 2026, Theorem 11: https://doi.org/10.4230/LIPIcs.CCC.2026.8
- Pich–Santhanam, *Towards P != NP from Extended Frege Lower Bounds*, JACM 2026: https://doi.org/10.1145/3801091
