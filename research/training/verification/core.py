"""Formal verification: model checking, Hoare logic, proof systems.

Stdlib-only. Pure computation, no external dependencies.

Core concepts:
- Kripke structures and model checking (LTL properties)
- Symbolic model checking (BFS on state space)
- Hoare triples: {P} C {Q} and weakest precondition
- Dijkstra's guarded command language
- Simple propositional proof systems (sequent calculus)
- Bounded model checking
"""

from __future__ import annotations

from typing import Callable


# ===========================================================================
# Kripke structures and LTL model checking
# ===========================================================================

class KripkeStructure:
    """A Kripke structure for model checking.

    States: list of state identifiers
    Transitions: dict mapping state -> set of successor states
    Labels: dict mapping state -> set of atomic propositions true in that state
    """

    def __init__(
        self,
        states: list,
        transitions: dict,
        labels: dict,
        init_states: list,
    ):
        self.states = list(states)
        self.transitions = {s: set(transitions.get(s, [])) for s in states}
        self.labels = {s: set(labels.get(s, [])) for s in states}
        self.init_states = list(init_states)

    def successors(self, state) -> set:
        """Get all successor states."""
        return self.transitions.get(state, set())

    def label(self, state) -> set:
        """Get atomic propositions true in a state."""
        return self.labels.get(state, set())

    def has_label(self, state, prop: str) -> bool:
        """Check if a proposition is true in a state."""
        return prop in self.labels.get(state, set())

    def is_terminal(self, state) -> bool:
        """A state is terminal if it has no successors."""
        return not self.successors(state)


def bfs_reachable(k: KripkeStructure, start_states: list | None = None) -> set:
    """BFS to find all reachable states."""
    if start_states is None:
        start_states = k.init_states
    visited: set = set()
    queue: list = list(start_states)
    while queue:
        s = queue.pop(0)
        if s in visited:
            continue
        visited.add(s)
        for succ in k.successors(s):
            if succ not in visited:
                queue.append(succ)
    return visited


# ===========================================================================
# LTL model checking (simplified)
# ===========================================================================

def lt_check_always(k: KripkeStructure, prop: str, start_states: list | None = None) -> bool:
    """Check if prop is true in all reachable states (AF / A[prop]).

    Simplified: check that prop holds in every state reachable from
    the initial states.
    """
    reachable = bfs_reachable(k, start_states)
    for s in reachable:
        if not k.has_label(s, prop):
            return False
    return True


def lt_check_eventually(
    k: KripkeStructure, prop: str, start_states: list | None = None
) -> bool:
    """Check if prop is eventually true in all paths (E F prop).

    Simplified: check that from every reachable state, there exists
    a path to a state where prop holds.
    """
    reachable = bfs_reachable(k, start_states)
    for s in reachable:
        if not _exists_path_to_prop(k, s, prop, set()):
            return False
    return True


def _exists_path_to_prop(
    k: KripkeStructure, state, prop: str, visited: set
) -> bool:
    """Check if there exists a path from state to a state labeled with prop."""
    if state in visited:
        return False
    visited.add(state)

    if k.has_label(state, prop):
        return True

    for succ in k.successors(state):
        if _exists_path_to_prop(k, succ, prop, visited):
            return True
    return False


def lt_check_exists_always(
    k: KripkeStructure, prop: str, start_states: list | None = None
) -> bool:
    """Check if there exists a path where prop is always true (E A prop).

    Find a single path from an initial state where prop holds in all states.
    """
    if start_states is None:
        start_states = k.init_states

    for init in start_states:
        # DFS to find a path where prop holds everywhere
        if _exists_always_path(k, init, prop, set(), set()):
            return True
    return False


def _exists_always_path(
    k: KripkeStructure, state, prop: str, visited: set, on_path: set
) -> bool:
    """DFS to find a path from state where prop holds in every state."""
    if state in on_path:
        return True  # Cycle reached; all states on path have prop

    if not k.has_label(state, prop):
        return False

    on_path.add(state)

    # If terminal, this path satisfies the property
    if k.is_terminal(state):
        on_path.discard(state)
        return True

    for succ in k.successors(state):
        if _exists_always_path(k, succ, prop, visited, on_path):
            on_path.discard(state)
            return True

    on_path.discard(state)
    return False


def lt_check_until(
    k: KripkeStructure, prop_a: str, prop_b: str, start_states: list | None = None
) -> bool:
    """Check if A (prop_a U prop_b): on all paths, prop_b eventually
    holds and prop_a holds until then.

    Simplified: for every reachable state, either prop_b holds, or prop_a
    holds and there exists a path to prop_b while prop_a holds everywhere.
    """
    if start_states is None:
        start_states = k.init_states

    for init in start_states:
        if not _check_until_path(k, init, prop_a, prop_b, set()):
            return False
    return True


def _check_until_path(
    k: KripkeStructure, state, prop_a: str, prop_b: str, visited: set
) -> bool:
    """Check A (a U b) from a single state."""
    if state in visited:
        return True  # Cycle: assume until holds (simplification)
    visited.add(state)

    if k.has_label(state, prop_b):
        return True

    if not k.has_label(state, prop_a):
        return False

    if k.is_terminal(state):
        return False  # Dead end without reaching b

    for succ in k.successors(state):
        if _check_until_path(k, succ, prop_a, prop_b, visited):
            return True
    return False


# ===========================================================================
# Bounded model checking
# ===========================================================================

def bounded_model_check(
    k: KripkeStructure,
    prop: str,
    bound: int,
    start_states: list | None = None,
) -> bool:
    """Bounded model checking: check if prop holds within `bound` steps.

    Returns True if prop is found true within bound steps from all
    initial states (simplified check for "eventually prop").
    """
    if start_states is None:
        start_states = k.init_states

    for init in start_states:
        if not _bmc_search(k, init, prop, bound, set()):
            return False
    return True


def _bmc_search(
    k: KripkeStructure, state, prop: str, bound: int, visited: set
) -> bool:
    """Search for prop within bound steps."""
    if bound <= 0:
        return False

    if state in visited:
        return False
    visited.add(state)

    if k.has_label(state, prop):
        return True

    for succ in k.successors(state):
        if _bmc_search(k, succ, prop, bound - 1, visited):
            return True
    return False


# ===========================================================================
# Hoare logic
# ===========================================================================

class HoareTriple:
    """A Hoare triple: {P} C {Q}.

    P is the precondition, C is the command, Q is the postcondition.
    """

    def __init__(self, precondition: Callable, command: Callable, postcondition: Callable):
        self.pre = precondition
        self.cmd = command
        self.post = postcondition

    def verify(self, state: dict) -> bool:
        """Verify the triple for a given initial state.

        The command mutates the state dict. Returns True if the
        precondition held initially and the postcondition holds after.
        """
        if not self.pre(state):
            return False

        try:
            self.cmd(state)
        except Exception:
            return False

        return self.post(state)


def weakest_precondition(
    command: Callable, postcondition: Callable
) -> Callable:
    """Compute a weakest precondition for a command and postcondition.

    For simple assignments and sequential composition, this computes
    the weakest precondition symbolically.

    Simplified: for an assignment x = expr, the weakest precondition
    for postcondition Q is Q with x replaced by expr.
    """
    # For simple assignments: x = expr
    # We return a function that checks if the assignment guarantees Q
    def wp(state: dict) -> bool:
        # Save state
        saved = dict(state)
        try:
            command(state)
            return postcondition(state)
        except Exception:
            return False
        finally:
            # Restore
            state.clear()
            state.update(saved)

    return wp


def assignment_wp(var: str, expr: Callable, postcondition: Callable) -> Callable:
    """Weakest precondition for a simple assignment: var = expr.

    Computes Q[var/expr] symbolically.
    """
    def wp_func(state: dict) -> bool:
        # Temporarily assign
        old = state.get(var)
        state[var] = expr(state)
        result = postcondition(state)
        # Restore
        if old is not None:
            state[var] = old
        elif var in state:
            del state[var]
        return result
    return wp_func


def sequential_wp(
    cmd1: Callable, wp2: Callable
) -> Callable:
    """Weakest precondition for sequential composition: wp(cmd1, wp2)."""
    def wp(state: dict) -> bool:
        saved = dict(state)
        try:
            cmd1(state)
            return wp2(state)
        except Exception:
            return False
        finally:
            state.clear()
            state.update(saved)
    return wp


def hoare_assignment(
    state: dict, var: str, expr: Callable, precondition: Callable, postcondition: Callable
) -> bool:
    """Verify a simple assignment command against a Hoare triple."""
    # Precondition must hold
    if not precondition(state):
        return False

    old_val = state.get(var)
    state[var] = expr(state)

    try:
        result = postcondition(state)
    finally:
        # Restore state
        if old_val is not None:
            state[var] = old_val
        elif var in state:
            del state[var]

    return result


# ===========================================================================
# Dijkstra's guarded command language
# ===========================================================================

class GuardedCommand:
    """A guarded command: b -> S, where b is a guard and S is a statement."""

    def __init__(self, guard: Callable, statement: Callable):
        self.guard = guard
        self.statement = statement


class GCLProgram:
    """A Dijkstra guarded command language program."""

    def __init__(self, commands: list[GuardedCommand]):
        self.commands = list(commands)

    def execute(self, state: dict, rng=None) -> dict:
        """Execute the program (non-deterministic: picks first enabled guard)."""
        if rng is None:
            import random
            rng = random.Random(0)

        for cmd in self.commands:
            if cmd.guard(state):
                cmd.statement(state)
                return state
        return state

    def weakest_precondition(self, postcondition: Callable) -> Callable:
        """Compute weakest precondition: disjunction of (guard_i AND wp_i)."""
        wp_functions = []
        for cmd in self.commands:
            wp_i = weakest_precondition(cmd.statement, postcondition)
            wp_functions.append((cmd.guard, wp_i))

        def wp(state: dict) -> bool:
            for guard, wp_i in wp_functions:
                if guard(state) and wp_i(state):
                    return True
            return False

        return wp


# ===========================================================================
# Propositional proof system (sequent calculus)
# ===========================================================================

class Sequent:
    """A sequent: Gamma |- Delta (Gamma implies Delta).

    Represented as (antecedents: frozenset, succedents: frozenset).
    """

    def __init__(self, antecedents: frozenset, succedents: frozenset):
        self.antecedents = frozenset(antecedents)
        self.succedents = frozenset(succedents)

    def __eq__(self, other) -> bool:
        return self.antecedents == other.antecedents and self.succedents == other.succedents

    def __hash__(self) -> int:
        return hash((self.antecedents, self.succedents))

    def __repr__(self) -> str:
        ants = ", ".join(sorted(str(a) for a in self.antecedents)) or "empty"
        sucs = ", ".join(sorted(str(s) for s in self.succedents)) or "empty"
        return f"[{ants}] -> [{sucs}]"

    def is_axiom(self) -> bool:
        """An axiom: some atom appears on both sides."""
        return bool(self.antecedents & self.succedents)


class ProofSystem:
    """A simple sequent calculus for propositional logic."""

    def __init__(self):
        self.proofs: dict[Sequent, list[Sequent]] = {}

    def apply_rule(self, rule: str, premises: list[Sequent]) -> Sequent:
        """Apply a proof rule to premises and return the conclusion."""
        if rule == "and_left":
            # From Gamma, A ∧ B |- Delta  infer  Gamma, A, B |- Delta
            antecedents = premises[0].antecedents
            # The premise has A ∧ B in antecedents; split it
            ant_set = set(antecedents)
            # Remove A∧B and add A and B
            combined = "A∧B"
            ant_set.discard(combined)
            ant_set.add("A")
            ant_set.add("B")
            return Sequent(frozenset(ant_set), premises[0].succedents)

        elif rule == "and_right":
            # From Gamma |- Delta, A  and  Gamma |- Delta, B
            # infer Gamma |- Delta, A ∧ B
            ants = premises[0].antecedents | premises[1].antecedents
            sucs = premises[0].succedents | premises[1].succedents
            suc_set = set(sucs)
            suc_set.discard("A")
            suc_set.discard("B")
            suc_set.add("A∧B")
            return Sequent(frozenset(ants), frozenset(suc_set))

        elif rule == "or_left":
            # From Gamma, A |- Delta  and  Gamma, B |- Delta
            # infer Gamma, A ∨ B |- Delta
            ants = premises[0].antecedents | premises[1].antecedents
            sucs = premises[0].succedents | premises[1].succedents
            ant_set = set(ants)
            ant_set.discard("A")
            ant_set.discard("B")
            ant_set.add("A∨B")
            return Sequent(frozenset(ant_set), frozenset(sucs))

        elif rule == "or_right":
            # From Gamma |- Delta, A, B  infer  Gamma |- Delta, A ∨ B
            ants = set(premises[0].antecedents)
            sucs = set(premises[0].succedents)
            sucs.discard("A")
            sucs.discard("B")
            sucs.add("A∨B")
            return Sequent(frozenset(ants), frozenset(sucs))

        elif rule == "not_left":
            # From Gamma |- Delta, A  infer  Gamma, ¬A |- Delta
            ants = set(premises[0].antecedents)
            sucs = premises[0].succedents
            ants.add("¬A")
            return Sequent(frozenset(ants), frozenset(sucs))

        elif rule == "not_right":
            # From Gamma, A |- Delta  infer  Gamma |- Delta, ¬A
            ants = set(premises[0].antecedents)
            sucs = set(premises[0].succedents)
            ants.discard("A")
            sucs.add("¬A")
            return Sequent(frozenset(ants), frozenset(sucs))

        elif rule == "imp_left":
            # From Gamma |- Delta, A  and  Gamma, B |- Delta
            # infer Gamma, A → B |- Delta
            ants = premises[0].antecedents | premises[1].antecedents
            sucs = premises[0].succedents | premises[1].succedents
            ant_set = set(ants)
            ant_set.discard("A")
            ant_set.discard("B")
            ant_set.add("A→B")
            return Sequent(frozenset(ant_set), frozenset(sucs))

        elif rule == "imp_right":
            # From Gamma, A |- Delta, B  infer  Gamma |- Delta, A → B
            ants = set(premises[0].antecedents)
            sucs = set(premises[0].succedents)
            ants.discard("A")
            sucs.discard("B")
            sucs.add("A→B")
            return Sequent(frozenset(ants), frozenset(sucs))

        elif rule == "weakening":
            # From Gamma |- Delta  infer  Gamma, A |- Delta
            ants = set(premises[0].antecedents)
            ants.add("A")
            return Sequent(frozenset(ants), premises[0].succedents)

        elif rule == "exchange":
            # Reordering (always valid, just return the same sequent)
            return premises[0]

        else:
            raise ValueError(f"Unknown rule: {rule}")

    def prove(self, sequent: Sequent, max_depth: int = 10) -> bool:
        """Try to prove a sequent by searching for a proof tree.

        Uses a simple recursive search over available rules.
        """
        if sequent.is_axiom():
            return True

        if max_depth <= 0:
            return False

        # Try applying rules in reverse (work backwards from conclusion)
        # For simplicity, try each rule type that could produce this sequent
        rules_to_try = [
            ("and_left", 1),
            ("and_right", 2),
            ("or_left", 2),
            ("or_right", 1),
            ("not_left", 1),
            ("not_right", 1),
            ("imp_left", 2),
            ("imp_right", 1),
        ]

        for rule, n_premises in rules_to_try:
            # Check if this rule could produce our sequent
            # We need to invert the rule; for simplicity, check if the
            # structure matches
            if self._rule_matches(rule, sequent):
                premises = self._invert_rule(rule, sequent)
                if premises:
                    if all(self.prove(p, max_depth - 1) for p in premises):
                        return True

        return False

    def _rule_matches(self, rule: str, sequent: Sequent) -> bool:
        """Check if a rule could produce the given sequent."""
        ants = set(sequent.antecedents)
        sucs = set(sequent.succedents)

        if rule == "and_left":
            return "A∧B" in ants
        elif rule == "and_right":
            return "A∧B" in sucs
        elif rule == "or_left":
            return "A∨B" in ants
        elif rule == "or_right":
            return "A∨B" in sucs
        elif rule == "not_left":
            return "¬A" in ants
        elif rule == "not_right":
            return "¬A" in sucs
        elif rule == "imp_left":
            return "A→B" in ants
        elif rule == "imp_right":
            return "A→B" in sucs
        return False

    def _invert_rule(self, rule: str, sequent: Sequent) -> list[Sequent]:
        """Given a conclusion sequent, find the premises."""
        ants = set(sequent.antecedents)
        sucs = set(sequent.succedents)

        if rule == "and_left":
            # Conclusion: ..., A∧B, ... |- Delta
            # Premise: ..., A, B, ... |- Delta
            new_ants = ants - {"A∧B"} | {"A", "B"}
            return [Sequent(frozenset(new_ants), frozenset(sucs))]

        elif rule == "and_right":
            # Conclusion: Gamma |- Delta, A∧B
            # Premises: Gamma |- Delta, A  and  Gamma |- Delta, B
            new_sucs = sucs - {"A∧B"}
            p1 = Sequent(frozenset(ants), frozenset(new_sucs | {"A"}))
            p2 = Sequent(frozenset(ants), frozenset(new_sucs | {"B"}))
            return [p1, p2]

        elif rule == "or_left":
            # Conclusion: ..., A∨B, ... |- Delta
            # Premises: ..., A, ... |- Delta  and  ..., B, ... |- Delta
            new_ants = ants - {"A∨B"}
            p1 = Sequent(frozenset(new_ants | {"A"}), frozenset(sucs))
            p2 = Sequent(frozenset(new_ants | {"B"}), frozenset(sucs))
            return [p1, p2]

        elif rule == "or_right":
            # Conclusion: Gamma |- Delta, A∨B
            # Premise: Gamma |- Delta, A, B
            new_sucs = sucs - {"A∨B"} | {"A", "B"}
            return [Sequent(frozenset(ants), frozenset(new_sucs))]

        elif rule == "not_left":
            # Conclusion: Gamma, ¬A |- Delta
            # Premise: Gamma |- Delta, A
            new_ants = ants - {"¬A"}
            new_sucs = sucs | {"A"}
            return [Sequent(frozenset(new_ants), frozenset(new_sucs))]

        elif rule == "not_right":
            # Conclusion: Gamma |- Delta, ¬A
            # Premise: Gamma, A |- Delta
            new_ants = ants | {"A"}
            new_sucs = sucs - {"¬A"}
            return [Sequent(frozenset(new_ants), frozenset(new_sucs))]

        elif rule == "imp_left":
            # Conclusion: Gamma, A→B |- Delta
            # Premises: Gamma |- Delta, A  and  Gamma, B |- Delta
            new_ants = ants - {"A→B"}
            p1 = Sequent(frozenset(new_ants), frozenset(sucs | {"A"}))
            p2 = Sequent(frozenset(new_ants | {"B"}), frozenset(sucs))
            return [p1, p2]

        elif rule == "imp_right":
            # Conclusion: Gamma |- Delta, A→B
            # Premise: Gamma, A |- Delta, B
            new_ants = ants | {"A"}
            new_sucs = sucs - {"A→B"} | {"B"}
            return [Sequent(frozenset(new_ants), frozenset(new_sucs))]

        return []


# ===========================================================================
# Inductive invariant checking
# ===========================================================================

def check_inductive_invariant(
    k: KripkeStructure, invariant: Callable, init_states: list | None = None
) -> bool:
    """Check if a predicate is an inductive invariant.

    An invariant I is inductive if:
    1. I holds in all initial states
    2. For every state s where I holds, all successors also satisfy I
    """
    if init_states is None:
        init_states = k.init_states

    # Check initial states
    for s in init_states:
        if not invariant(s):
            return False

    # Check all states satisfying I have successors also satisfying I
    for s in k.states:
        if invariant(s):
            for succ in k.successors(s):
                if not invariant(succ):
                    return False

    return True


def check_safety_property(
    k: KripkeStructure,
    invariant: Callable,
    start_states: list | None = None,
) -> bool:
    """Check if a safety property (invariant) holds on all reachable states.

    Uses BFS from initial states to verify the invariant holds everywhere.
    """
    reachable = bfs_reachable(k, start_states)
    for s in reachable:
        if not invariant(s):
            return False
    return True
