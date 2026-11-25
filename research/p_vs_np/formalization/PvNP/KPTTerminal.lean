import Std

/-!
# A finite causal-game kernel for KPT terminal packages

`Wins Q n h` says that from history `h`, every next challenge is either
already covered by the current package `Q h`, or leaves a winning game with
one fewer round. The theorem `wins_has_terminal` proves that a winning
finite-horizon game has some reachable history whose package covers every
challenge.

This formalizes the abstract terminal-package lemma only. It does not
formalize Pich–Santhanam's bounded-arithmetic formula, its search-circuit
branch, or the translation to Extended Frege.
-/

namespace PvNP.KPTTerminal

variable {α : Type}

/-- The recursive winning condition for a causal challenge/package game. -/
def Wins (Q : List α → α → Prop) : Nat → List α → Prop
  | 0, _ => False
  | n + 1, h => ∀ x, Q h x ∨ Wins Q n (h ++ [x])

/-- A winning causal game has a reachable history with a universal package. -/
theorem wins_has_terminal (Q : List α → α → Prop) :
    ∀ n h, Wins Q n h →
      ∃ p : List α, p.length < n ∧ ∀ x, Q (h ++ p) x := by
  classical
  intro n
  induction n with
  | zero =>
      intro h hwin
      exact False.elim hwin
  | succ n ih =>
      intro h hwin
      by_cases hroot : ∀ x, Q h x
      · exact ⟨[], by simp, by simpa using hroot⟩
      · obtain ⟨x, hx⟩ := Classical.not_forall.mp hroot
        have hnext : Wins Q n (h ++ [x]) := (hwin x).resolve_left hx
        obtain ⟨p, hp, hterm⟩ := ih (h ++ [x]) hnext
        refine ⟨x :: p, ?_, ?_⟩
        · simpa using Nat.succ_lt_succ hp
        · simpa [List.append_assoc] using hterm

end PvNP.KPTTerminal
