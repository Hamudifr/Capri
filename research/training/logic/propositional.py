"""Formal logic study modules.

Implements propositional logic, SAT solving, resolution, and
first-order logic concepts. Pure stdlib, no dependencies.

Topics covered:
- Propositional variables and well-formed formulas
- Truth tables and evaluation
- Clauses, CNF, and SAT solving (DPLL)
- Resolution refutation
- First-order logic: terms, substitution, unification
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Propositional logic: AST for formulas
# ---------------------------------------------------------------------------

# A propositional formula is one of:
#   ("var", name)                 — a propositional variable
#   ("not", sub)                  — negation
#   ("and", [sub, ...])          — conjunction
#   ("or", [sub, ...])           — disjunction
#   ("imp", a, b)                — implication  (a -> b)
#   ("bicond", a, b)             — biconditional
#   ("true",)                    — constant true
#   ("false",)                   — constant false

Formula = tuple


def var(name: str) -> Formula:
    return ("var", name)


def negate(f: Formula) -> Formula:
    return ("not", f)


def conjoin(*formulas: Formula) -> Formula:
    return ("and", list(formulas))


def disjoin(*formulas: Formula) -> Formula:
    return ("or", list(formulas))


def imply(a: Formula, b: Formula) -> Formula:
    return ("imp", a, b)


def biconditional(a: Formula, b: Formula) -> Formula:
    return ("bicond", a, b)


TRUE: Formula = ("true",)
FALSE: Formula = ("false",)


def variables(formula: Formula) -> list[str]:
    """Collect all propositional variable names in a formula."""
    kind = formula[0]
    if kind == "var":
        return [formula[1]]
    if kind in ("not",):
        return variables(formula[1])
    if kind in ("and", "or"):
        out: list[str] = []
        for sub in formula[1]:
            out.extend(variables(sub))
        return out
    if kind in ("imp", "bicond"):
        return variables(formula[1]) + variables(formula[2])
    if kind == "true" or kind == "false":
        return []
    return []


def evaluate(formula: Formula, assignment: dict[str, bool]) -> bool:
    """Evaluate a formula under a variable assignment.

    Unassigned variables default to False.
    """
    kind = formula[0]
    if kind == "var":
        return assignment.get(formula[1], False)
    if kind == "not":
        return not evaluate(formula[1], assignment)
    if kind == "and":
        return all(evaluate(s, assignment) for s in formula[1])
    if kind == "or":
        return any(evaluate(s, assignment) for s in formula[1])
    if kind == "imp":
        return (not evaluate(formula[1], assignment)) or evaluate(formula[2], assignment)
    if kind == "bicond":
        return evaluate(formula[1], assignment) == evaluate(formula[2], assignment)
    if kind == "true":
        return True
    if kind == "false":
        return False
    raise ValueError(f"Unknown formula kind: {kind}")


def truth_table(formula: Formula) -> list[tuple[dict[str, bool], bool]]:
    """Generate the full truth table for a formula.

    Returns a list of (assignment, result) pairs.
    """
    vars_list = sorted(set(variables(formula)))
    rows: list[tuple[dict[str, bool], bool]] = []
    n = len(vars_list)
    for i in range(2 ** n):
        assignment = {v: bool(i & (1 << (n - 1 - j))) for j, v in enumerate(vars_list)}
        rows.append((assignment, evaluate(formula, assignment)))
    return rows


# ---------------------------------------------------------------------------
# CNF conversion and SAT solving
# ---------------------------------------------------------------------------

def to_cnf(formula: Formula) -> Formula:
    """Convert a formula to Conjunctive Normal Form (CNF).

    Uses Tseitin-style expansion for XOR/biconditional and
    De Morgan + distribution for the rest.
    """
    # Step 1: eliminate implications and biconditionals
    f = _eliminate_implications(formula)
    # Step 2: push negations inward (De Morgan)
    f = _nnf(f)
    # Step 3: distribute OR over AND
    f = _distribute(f)
    return f


def _eliminate_implications(f: Formula) -> Formula:
    kind = f[0]
    if kind == "imp":
        return _eliminate_implications(("or", [("not", _eliminate_implications(f[1])),
                                                _eliminate_implications(f[2])]))
    if kind == "bicond":
        a = _eliminate_implications(f[1])
        b = _eliminate_implications(f[2])
        return ("and", [_eliminate_implications(("or", [("not", a), b])),
                        _eliminate_implications(("or", [a, ("not", b)]))])
    if kind == "not":
        return ("not", _eliminate_implications(f[1]))
    if kind in ("and", "or"):
        return (kind, [_eliminate_implications(s) for s in f[1]])
    return f


def _nnf(f: Formula) -> Formula:
    """Push negations to the literal level (Negation Normal Form)."""
    kind = f[0]
    if kind == "not":
        sub = f[1]
        sub_kind = sub[0]
        if sub_kind == "not":
            return _nnf(sub[1])
        if sub_kind == "and":
            return _nnf(("or", [("not", s) for s in sub[1]]))
        if sub_kind == "or":
            return _nnf(("and", [("not", s) for s in sub[1]]))
        if sub_kind in ("imp", "bicond"):
            return _nnf(_eliminate_implications(("not", _eliminate_implications(sub))))
        return ("not", _nnf(sub))
    if kind in ("and", "or"):
        return (kind, [_nnf(s) for s in f[1]])
    return f


def _distribute(f: Formula) -> Formula:
    """Distribute OR over AND to reach CNF."""
    kind = f[0]
    if kind == "or":
        # If any disjunct is an AND, distribute
        and_clauses = [s for s in f[1] if s[0] == "and"]
        if not and_clauses:
            return ("or", [_distribute(s) for s in f[1]])
        # Pick the first AND and distribute
        first_and = and_clauses[0]
        rest = [s for s in f[1] if s is not first_and]
        results = []
        for clause in first_and[1]:
            new_or = ("or", [_distribute(clause)] + [_distribute(s) for s in rest])
            results.append(_distribute(new_or))
        return _distribute(("and", results))
    if kind == "and":
        return ("and", [_distribute(s) for s in f[1]])
    return f


def cnf_clauses(cnf: Formula) -> list[list[tuple[str, bool]]]:
    """Extract clauses (ORs of literals) from a CNF formula.

    Each clause is a list of (variable_name, is_positive) tuples.
    """
    def extract(f: Formula) -> list[list[tuple[str, bool]]]:
        kind = f[0]
        if kind == "and":
            clauses: list[list[tuple[str, bool]]] = []
            for sub in f[1]:
                clauses.extend(extract(sub))
            return clauses
        if kind == "or":
            lits: list[tuple[str, bool]] = []
            for sub in f[1]:
                if sub[0] == "var":
                    lits.append((sub[1], True))
                elif sub[0] == "not" and sub[1][0] == "var":
                    lits.append((sub[1][1], False))
                else:
                    # Nested — shouldn't happen in proper CNF, but handle
                    lits.append(("__compound__", True))
            return [lits]
        # Single literal
        if kind == "var":
            return [[(f[1], True)]]
        if kind == "not" and f[1][0] == "var":
            return [[(f[1][1], False)]]
        return []

    return extract(cnf)


def dpll_sat(clauses: list[list[tuple[str, bool]]],
             variables: list[str]) -> dict[str, bool] | None:
    """DPLL SAT solver.

    Returns a satisfying assignment or None if unsatisfiable.
    """
    def solve(clauses: list[list[tuple[str, bool]]],
              assignment: dict[str, bool],
              unassigned: list[str]) -> dict[str, bool] | None:
        # Unit propagation
        unit_changed = True
        while unit_changed:
            unit_changed = False
            for clause in clauses:
                unassigned_lits = []
                assigned_true = False
                for lit in clause:
                    name, pos = lit
                    if name in assignment:
                        if assignment[name] == pos:
                            assigned_true = True
                            break
                    else:
                        unassigned_lits.append(lit)
                if not assigned_true and len(unassigned_lits) == 1:
                    # Unit clause
                    name, pos = unassigned_lits[0]
                    assignment[name] = pos
                    unit_changed = True
                    # Restart clause scan
                    break
                if not assigned_true and len(unassigned_lits) == 0:
                    return None  # Empty clause → unsat

        if all(v in assignment for v in unassigned):
            # All assigned, check satisfaction
            if all(_clause_sat(c, assignment) for c in clauses):
                return assignment
            return None

        # Pick first unassigned variable
        var = unassigned[0]
        remaining = [v for v in unassigned if v != var]

        # Try True
        assignment[var] = True
        result = solve(clauses, assignment, remaining)
        if result is not None:
            return result

        # Try False
        assignment[var] = False
        result = solve(clauses, assignment, remaining)
        return result

    return solve(clauses, {}, list(variables))


def _clause_sat(clause: list[tuple[str, bool]], assignment: dict[str, bool]) -> bool:
    for name, pos in clause:
        if name in assignment and assignment[name] == pos:
            return True
    return False


# ---------------------------------------------------------------------------
# Resolution refutation
# ---------------------------------------------------------------------------

def resolve(clause1: list[tuple[str, bool]],
            clause2: list[tuple[str, bool]]) -> list[tuple[str, bool]] | None:
    """Resolve two clauses on a complementary pair of literals.

    Returns the resolvent, or None if no complementary pair exists.
    """
    for lit1 in clause1:
        for lit2 in clause2:
            if lit1[0] == lit2[0] and lit1[1] != lit2[1]:
                resolvent = [l for l in clause1 if l != lit1] + [l for l in clause2 if l != lit2]
                # Remove duplicates
                seen = set()
                deduped = []
                for lit in resolvent:
                    if lit not in seen:
                        seen.add(lit)
                        deduped.append(lit)
                return deduped
    return None


def resolution_refute(clauses: list[list[tuple[str, bool]]],
                      max_iterations: int = 1000) -> bool:
    """Check if a set of clauses is unsatisfiable via resolution.

    Returns True if the set is unsatisfiable (empty clause derived).
    """
    current = [list(c) for c in clauses]
    for _ in range(max_iterations):
        new_clauses = list(current)
        for i in range(len(current)):
            for j in range(i + 1, len(current)):
                resolvent = resolve(current[i], current[j])
                if resolvent is not None:
                    if len(resolvent) == 0:
                        return True
                    # Check if already present
                    if resolvent not in new_clauses:
                        new_clauses.append(resolvent)
        if new_clauses == current:
            break
        current = new_clauses
    return False


# ---------------------------------------------------------------------------
# First-order logic: terms, substitution, unification
# ---------------------------------------------------------------------------

# Terms: ("const", name) | ("var", name) | ("func", name, [terms])
Term = tuple


def const(name: str) -> Term:
    return ("const", name)


def fvar(name: str) -> Term:
    return ("var", name)


def func(name: str, *args: Term) -> Term:
    return ("func", name, list(args))


def substitute(term: Term, substitution: dict[str, Term]) -> Term:
    """Apply a substitution to a term."""
    kind = term[0]
    if kind == "var":
        name = term[1]
        if name in substitution:
            return substitute(substitution[name], substitution)
        return term
    if kind == "const":
        return term
    if kind == "func":
        return ("func", term[1], [substitute(a, substitution) for a in term[2]])
    raise ValueError(f"Unknown term kind: {kind}")


def occurs_in(name: str, term: Term) -> bool:
    """Check if a variable occurs in a term."""
    kind = term[0]
    if kind == "var":
        return term[1] == name
    if kind == "const":
        return False
    if kind == "func":
        return any(occurs_in(name, a) for a in term[2])
    return False


def unify(t1: Term, t2: Term) -> dict[str, Term] | None:
    """Unify two terms. Returns a substitution dict or None if not unifiable."""
    if t1 == t2:
        return {}

    kind1 = t1[0]
    kind2 = t2[0]

    if kind1 == "var":
        if occurs_in(t1[1], t2):
            return None
        return {t1[1]: t2}
    if kind2 == "var":
        if occurs_in(t2[1], t1):
            return None
        return {t2[1]: t1}

    if kind1 == "const" and kind2 == "const":
        return {} if t1[1] == t2[1] else None

    if kind1 == "func" and kind2 == "func":
        if t1[1] != t2[1] or len(t1[2]) != len(t2[2]):
            return None
        combined: dict[str, Term] = {}
        for a, b in zip(t1[2], t2[2]):
            sub = unify(a, b)
            if sub is None:
                return None
            # Compose: apply sub to combined, then merge
            combined = _compose_subs(combined, sub)
        return combined

    return None


def _compose_subs(s1: dict[str, Term], s2: dict[str, Term]) -> dict[str, Term]:
    """Compose two substitutions: apply s2 to s1's values, then merge."""
    result = {}
    for var, term in s1.items():
        result[var] = substitute(term, s2)
    for var, term in s2.items():
        if var not in result:
            result[var] = term
    return result


def apply_substitution(term: Term, sub: dict[str, Term]) -> Term:
    """Apply a substitution to a term (alias for substitute)."""
    return substitute(term, sub)



def __all__() -> list[str]:
    return [
        "var", "negate", "conjoin", "disjoin", "imply", "biconditional",
        "TRUE", "FALSE", "variables", "evaluate", "truth_table",
        "to_cnf", "cnf_clauses", "dpll_sat", "resolve", "resolution_refute",
        "const", "fvar", "func", "substitute", "occurs_in", "unify",
        "apply_substitution",
    ]
