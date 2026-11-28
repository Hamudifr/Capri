"""Formal logic study modules."""

from research.training.logic.propositional import (
    var, negate, conjoin, disjoin, imply, biconditional,
    TRUE, FALSE, variables, evaluate, truth_table,
    to_cnf, cnf_clauses, dpll_sat, resolve, resolution_refute,
    const, fvar, func, substitute, occurs_in, unify,
)

__all__ = [
    "var", "negate", "conjoin", "disjoin", "imply", "biconditional",
    "TRUE", "FALSE", "variables", "evaluate", "truth_table",
    "to_cnf", "cnf_clauses", "dpll_sat", "resolve", "resolution_refute",
    "const", "fvar", "func", "substitute", "occurs_in", "unify",
]
