"""SAT solving: 2-SAT in linear time and CDCL with watch literals.

Stdlib-only. Pure computation, no external dependencies.

Core concepts:
- 2-SAT: linear-time algorithm using implication graphs + SCC
- CDCL: Conflict-Driven Clause Learning SAT solver
- Watch literals, BCP (boolean constraint propagation)
- VSIDS-style variable ordering, clause learning with assertion levels
"""

from __future__ import annotations

from collections import defaultdict


# ===========================================================================
# Variable and clause representation
# ===========================================================================
# A literal is an integer: positive for true, negative for false.
# E.g., 1 = variable 1 is true, -2 = variable 2 is false.


def var_of(literal: int) -> int:
    """Absolute value of a literal (the variable index)."""
    return abs(literal)


def neg(literal: int) -> int:
    """Negation of a literal."""
    return -literal


def to_clause_str(clause: list[int]) -> str:
    """Format a clause for display."""
    return "(" + " OR ".join(str(l) for l in clause) + ")"


# ===========================================================================
# 2-SAT: linear-time via implication graph
# ===========================================================================

def solve_2sat(clauses: list[list[int]]) -> dict[int, bool] | None:
    """Solve a 2-SAT instance in linear time.

    Each clause is a list of exactly 2 literals.
    Returns a satisfying assignment as {var: bool} or None if unsatisfiable.
    """
    n = _max_var(clauses)
    # Build implication graph: 2n nodes (2 per variable)
    # Node 2v = literal v (v positive), Node 2v+1 = literal -v
    # For clause (a OR b), add edges: ~a -> b and ~b -> a
    adj: dict[int, list[int]] = defaultdict(list)

    for clause in clauses:
        if len(clause) == 1:
            # Handle unit clause: (a) means a must be true.
            # Add edge ~a -> a
            a = clause[0]
            adj[_node(neg(a))].append(_node(a))
        elif len(clause) == 2:
            a, b = clause
            adj[_node(neg(a))].append(_node(b))
            adj[_node(neg(b))].append(_node(a))
        else:
            raise ValueError(f"2-SAT clause must have 1 or 2 literals: {clause}")

    # Find SCCs (Kosaraju)
    order = _dfs_finish_order(adj, 2 * n)
    transpose: dict[int, list[int]] = defaultdict(list)
    for u, neighbors in adj.items():
        for v in neighbors:
            transpose[v].append(u)

    comp = [-1] * (2 * n)
    comp_id = 0
    for node in reversed(order):
        if comp[node] == -1:
            _dfs_component(transpose, node, comp_id, comp)
            comp_id += 1

    # Check satisfiability
    assignment: dict[int, bool] = {}
    for v in range(1, n + 1):
        if comp[_node(v)] == comp[_node(neg(v))]:
            return None  # unsatisfiable
        assignment[v] = comp[_node(v)] > comp[_node(neg(v))]
    return assignment


def _node(literal: int) -> int:
    """Map a literal to a graph node index."""
    v = var_of(literal)
    return 2 * (v - 1) if literal > 0 else 2 * (v - 1) + 1


def _node_to_literal(node: int) -> int:
    """Map a graph node index back to a literal."""
    if node % 2 == 0:
        return node // 2 + 1
    return -(node // 2 + 1)


def _dfs_finish_order(adj: dict[int, list[int]], num_nodes: int) -> list[int]:
    visited = [False] * num_nodes
    order: list[int] = []

    for start in range(num_nodes):
        if not visited[start]:
            stack = [(start, 0)]
            while stack:
                node, idx = stack.pop()
                if idx == 0:
                    if visited[node]:
                        continue
                    visited[node] = True
                if idx < len(adj.get(node, [])):
                    stack.append((node, idx + 1))
                    stack.append((adj[node][idx], 0))
                else:
                    order.append(node)
    return order


def _dfs_component(
    transpose: dict[int, list[int]], start: int, comp_id: int, comp: list[int]
) -> None:
    stack = [start]
    comp[start] = comp_id
    while stack:
        node = stack.pop()
        for nb in transpose.get(node, []):
            if comp[nb] == -1:
                comp[nb] = comp_id
                stack.append(nb)


def _max_var(clauses: list[list[int]]) -> int:
    max_v = 0
    for clause in clauses:
        for lit in clause:
            max_v = max(max_v, abs(lit))
    return max_v


# ===========================================================================
# CDCL SAT solver with watch literals
# ===========================================================================

class CDCLSolver:
    """Conflict-Driven Clause Learning SAT solver.

    Features:
    - Watch literals with BCP (boolean constraint propagation)
    - Implication graph tracking with decision levels
    - Clause learning (1-UIP scheme)
    - VSIDS-style variable activity scoring
    - Phase saving (keep last assignment)
    """

    def __init__(self):
        self.clauses: list[list[int]] = []
        self.n_vars: int = 0
        # Assignment: literal -> True means assigned, value True/False
        self.assignment: dict[int, bool] = {}
        self.level: dict[int, int] = {}
        self.reason: dict[int, list[int]] = {}
        # Watch lists
        self.watches: dict[int, list[list[int]]] = defaultdict(list)
        # Activity scores for VSIDS
        self.activity: dict[int, float] = defaultdict(float)
        self.decision_level: int = 0
        self.implications: list[tuple[int, bool, int]] = []  # (lit, value, level)
        self.conflict: list[int] | None = None
        self.unsatisfiable: bool = False

    def add_clause(self, clause: list[int]) -> None:
        """Add a clause to the solver."""
        self.clauses.append(list(clause))
        for lit in clause:
            self.n_vars = max(self.n_vars, abs(lit))
        # Initialize watch lists
        if len(clause) >= 2:
            self.watches[clause[0]].append(self.clauses[-1])
            self.watches[clause[-1]].append(self.clauses[-1])
        else:
            # Unit clause - will be handled during BCP
            self.watches[clause[0]].append(self.clauses[-1])

    def solve(self) -> dict[int, bool] | None:
        """Run CDCL. Returns satisfying assignment or None."""
        self._init_unit_clauses()

        while not self.unsatisfiable:
            # BCP
            while True:
                conflict = self._bcp()
                if conflict is None:
                    break
                if conflict:
                    learnt = self._analyze_conflict(conflict)
                    if learnt is None:
                        self.unsatisfiable = True
                        return None
                    self._backtrack(self.decision_level - 1)
                    self.clauses.append(learnt)
                    # Watch the learnt clause
                    if len(learnt) >= 2:
                        self.watches[learnt[0]].append(learnt)
                        self.watches[learnt[-1]].append(learnt)
                    else:
                        self.watches[learnt[0]].append(learnt)
                    # Unit propagation of learnt clause
                    self._assign(learnt[0], True, 0, reason=learnt)
                    continue

            # Decision
            if len(self.assignment) == self.n_vars:
                return self.assignment

            var = self._select_branch_var()
            if var is None:
                return self.assignment

            self.decision_level += 1
            lit = var if self._get_phase(var) else -var
            if not self._assign(lit, True, self.decision_level, reason=None):
                # Decision caused immediate conflict
                self.unsatisfiable = True
                return None

        return None

    def _init_unit_clauses(self) -> None:
        for clause in self.clauses:
            if len(clause) == 1:
                lit = clause[0]
                var = abs(lit)
                if var in self.assignment:
                    # Already assigned - check for conflict
                    if self.assignment[var] != (lit > 0):
                        self.unsatisfiable = True
                        return
                else:
                    if not self._assign(lit, True, 0, reason=clause):
                        self.unsatisfiable = True
                        return

    def _get_phase(self, var: int) -> bool:
        return self.assignment.get(var, True)

    def _select_branch_var(self) -> int | None:
        """VSIDS: pick unassigned variable with highest activity."""
        best_var = None
        best_score = -1.0
        for var in range(1, self.n_vars + 1):
            if var not in self.assignment:
                score = self.activity[var]
                if score > best_score:
                    best_score = score
                    best_var = var
        return best_var

    def _assign(self, lit: int, value: bool, level: int, reason: list[int] | None) -> bool:
        """Assign a literal. Returns False if already assigned conflicting."""
        var = abs(lit)
        expected = lit > 0
        if var in self.assignment:
            if self.assignment[var] != expected:
                return False
            return True

        self.assignment[var] = expected
        self.level[var] = level
        if reason is not None:
            self.reason[var] = reason

        # Bump activity
        self.activity[var] += 1.0

        # Record implication
        self.implications.append((lit, expected, level))

        # Propagate watches
        if level == 0:
            return True

        # Watch propagation: process the watch list of the FALSIFIED literal (-lit)
        # When lit is assigned true, -lit becomes false, so clauses watching -lit
        # need to find a new watch or become unit/conflict
        falsified_lit = -lit
        watch_list = self.watches.get(falsified_lit, [])
        for clause in watch_list:
            if not self._propagate_watch(clause, falsified_lit):
                return False
        return True

    def _propagate_watch(self, clause: list[int], watch: int) -> bool:
        """Propagate implications from a watch literal. Returns False on conflict."""
        other_watch = clause[0] if clause[-1] == watch else clause[-1]

        # Check if other watch is already falsified
        other_var = abs(other_watch)
        other_val = other_watch > 0

        if other_var in self.assignment:
            if self.assignment[other_var] == other_val:
                return True  # Clause is satisfied
            if self.assignment[other_var] != other_val:
                pass  # Other watch is falsified, need to find new watch
        else:
            pass

        # Find a new watch
        if other_var not in self.assignment or self.assignment[other_var] != other_val:
            # Other watch is falsified, look for new watch
            new_watch = None
            for lit in clause:
                if lit == watch:
                    continue
                v = abs(lit)
                if v in self.assignment:
                    if (lit > 0) == self.assignment[v]:
                        new_watch = lit
                        break
                else:
                    new_watch = lit
                    break

            if new_watch is not None:
                # Update watch
                self.watches[watch].remove(clause)
                self.watches[new_watch].append(clause)
                clause[0] = new_watch if clause[0] == watch else clause[0]
                clause[-1] = new_watch if clause[-1] == watch else clause[-1]
                return True

        # No new watch found - check if clause is unit
        unassigned = [lit for lit in clause if abs(lit) not in self.assignment]
        satisfied = any(
            (lit > 0) == self.assignment.get(abs(lit), False)
            for lit in clause
            if abs(lit) in self.assignment
        )

        if satisfied:
            return True
        if len(unassigned) == 0:
            # Conflict
            return False
        if len(unassigned) == 1:
            # Unit propagation
            lit = unassigned[0]
            return self._assign(lit, lit > 0, self.decision_level, reason=clause)

        # If other watch is unassigned, this is a propagation
        if other_var not in self.assignment:
            return self._assign(other_watch, other_val, self.decision_level, reason=clause)

        return True

    def _bcp(self) -> list[int] | None:
        """Boolean constraint propagation. Returns conflict clause or None.

        Processes all implications: for each implied literal, check clauses
        watching the falsified negation.
        """
        queue = list(self.implications)
        while queue:
            lit, _, _ = queue.pop()
            falsified = -lit
            for clause in self.watches.get(falsified, []):
                if not self._propagate_watch(clause, falsified):
                    return clause
        return None

    def _analyze_conflict(self, conflict_clause: list[int]) -> list[int] | None:
        """1-UIP clause learning. Returns learnt clause or None if root."""
        # Build implication graph from current assignment
        # Track literals at current decision level
        current_level = self.decision_level
        seen: set[int] = set()
        learned: list[int] = []

        # Add conflict clause literals
        for lit in conflict_clause:
            seen.add(lit)

        # Resolve backwards until we hit the decision literal at current level
        while True:
            # Find a literal in seen at current level (not the decision)
            new_seen: set[int] = set()
            for lit in seen:
                var = abs(lit)
                if self.level.get(var, -1) == current_level:
                    # Resolve on this literal
                    reason = self.reason.get(var)
                    if reason is None:
                        # This is a decision literal - 1-UIP
                        continue
                    # Remove lit from seen, add reason clause
                    new_seen.add(lit)
                    for r_lit in reason:
                        if r_lit != lit and r_lit not in new_seen:
                            new_seen.add(r_lit)
                else:
                    new_seen.add(lit)

            if new_seen == seen:
                # No progress - we've reached the 1-UIP
                break
            seen = new_seen

        # Build learned clause
        learned = []
        for lit in seen:
            var = abs(lit)
            if var in self.assignment and (lit > 0) != self.assignment[var]:
                learned.append(lit)

        # Remove duplicates
        learned = list(dict.fromkeys(learned))

        if len(learned) == 0:
            return None
        return learned

    def _backtrack(self, target_level: int) -> None:
        """Backtrack to target decision level."""
        # Unassign all variables at levels > target_level
        to_unassign = []
        for var, lvl in self.level.items():
            if lvl > target_level:
                to_unassign.append(var)
        for var in to_unassign:
            del self.assignment[var]
            del self.level[var]
            if var in self.reason:
                del self.reason[var]
        self.decision_level = target_level
        self.implications = [(l, v, lvl) for l, v, lvl in self.implications if lvl <= target_level]


def solve_sat_cdcl(clauses: list[list[int]]) -> dict[int, bool] | None:
    """Solve a general CNF SAT instance using CDCL."""
    solver = CDCLSolver()
    for clause in clauses:
        solver.add_clause(clause)
    return solver.solve()


# ===========================================================================
# DPLL (simpler reference solver for comparison)
# ===========================================================================

def dpll_solve(clauses: list[list[int]]) -> dict[int, bool] | None:
    """Simple DPLL SAT solver (recursive, for comparison/reference)."""
    # Unit propagation
    units = [c[0] for c in clauses if len(c) == 1]
    if not units:
        return _dpll_recursive([list(c) for c in clauses], {}, 1)
    return _dpll_recursive([list(c) for c in clauses], {abs(units[0]): units[0] > 0}, 1)


def _dpll_recursive(
    clauses: list[list[int]], assignment: dict[int, bool], n_vars: int
) -> dict[int, bool] | None:
    # Simplify clauses with current assignment
    new_clauses: list[list[int]] = []
    for clause in clauses:
        simplified = []
        satisfied = False
        for lit in clause:
            var = abs(lit)
            if var in assignment:
                if (lit > 0) == assignment[var]:
                    satisfied = True
                    break
            else:
                simplified.append(lit)
        if not satisfied:
            if not simplified:
                return None  # Empty clause = conflict
            new_clauses.append(simplified)

    # Find unassigned variable
    unassigned = [v for v in range(1, n_vars + 1) if v not in assignment]
    if not unassigned:
        return assignment

    var = unassigned[0]

    # Try true
    assignment_true = dict(assignment)
    assignment_true[var] = True
    result = _dpll_recursive(new_clauses, assignment_true, n_vars)
    if result is not None:
        return result

    # Try false
    assignment_false = dict(assignment)
    assignment_false[var] = False
    return _dpll_recursive(new_clauses, assignment_false, n_vars)
