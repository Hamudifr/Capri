"""Tests for the logic training module."""

import unittest

from research.training.logic.propositional import (
    var, negate, conjoin, disjoin, imply, biconditional,
    TRUE, FALSE, variables, evaluate, truth_table,
    to_cnf, cnf_clauses, dpll_sat, resolve, resolution_refute,
    const, fvar, func, substitute, occurs_in, unify,
    apply_substitution,
)


class TestPropositionalLogic(unittest.TestCase):

    def test_variables_collection(self):
        f = conjoin(var("a"), disjoin(var("b"), negate(var("a"))))
        self.assertEqual(sorted(set(variables(f))), ["a", "b"])

    def test_evaluate_basic(self):
        a, b = var("a"), var("b")
        self.assertTrue(evaluate(conjoin(a, b), {"a": True, "b": True}))
        self.assertFalse(evaluate(conjoin(a, b), {"a": True, "b": False}))
        self.assertTrue(evaluate(disjoin(a, b), {"a": False, "b": True}))

    def test_evaluate_negation(self):
        a = var("a")
        self.assertTrue(evaluate(negate(a), {"a": False}))
        self.assertFalse(evaluate(negate(a), {"a": True}))

    def test_evaluate_implication(self):
        a, b = var("a"), var("b")
        # a -> b is False only when a=True, b=False
        self.assertFalse(evaluate(imply(a, b), {"a": True, "b": False}))
        self.assertTrue(evaluate(imply(a, b), {"a": True, "b": True}))
        self.assertTrue(evaluate(imply(a, b), {"a": False, "b": False}))

    def test_evaluate_biconditional(self):
        a, b = var("a"), var("b")
        self.assertTrue(evaluate(biconditional(a, b), {"a": True, "b": True}))
        self.assertFalse(evaluate(biconditional(a, b), {"a": True, "b": False}))

    def test_truth_table_size(self):
        f = conjoin(var("a"), var("b"))
        table = truth_table(f)
        self.assertEqual(len(table), 4)

    def test_truth_table_known_values(self):
        f = conjoin(var("a"), var("b"))
        table = truth_table(f)
        # Check the all-true assignment
        true_rows = [(a, r) for a, r in table if a["a"] and a["b"]]
        self.assertEqual(len(true_rows), 1)
        self.assertTrue(true_rows[0][1])

    def test_to_cnf_and_extract(self):
        # (a or b) and c
        f = conjoin(disjoin(var("a"), var("b")), var("c"))
        cnf = to_cnf(f)
        clauses = cnf_clauses(cnf)
        self.assertGreater(len(clauses), 0)

    def test_dpll_sat_satisfiable(self):
        # a or b is satisfiable
        f = disjoin(var("a"), var("b"))
        cnf = to_cnf(f)
        clauses = cnf_clauses(cnf)
        result = dpll_sat(clauses, ["a", "b"])
        self.assertIsNotNone(result)

    def test_dpll_sat_unsatisfiable(self):
        # a and not a is unsatisfiable
        f = conjoin(var("a"), negate(var("a")))
        cnf = to_cnf(f)
        clauses = cnf_clauses(cnf)
        result = dpll_sat(clauses, ["a"])
        self.assertIsNone(result)

    def test_resolve(self):
        c1 = [("a", True), ("b", True)]
        c2 = [("a", False), ("c", True)]
        resolvent = resolve(c1, c2)
        self.assertIsNotNone(resolvent)
        self.assertIn(("b", True), resolvent)
        self.assertIn(("c", True), resolvent)
        self.assertNotIn(("a", True), resolvent)
        self.assertNotIn(("a", False), resolvent)

    def test_constants(self):
        self.assertTrue(evaluate(TRUE, {}))
        self.assertFalse(evaluate(FALSE, {}))
        self.assertEqual(variables(TRUE), [])
        self.assertEqual(variables(FALSE), [])

    def test_apply_substitution_alias(self):
        t = func("f", fvar("x"), const("a"))
        sub = {"x": const("3")}
        result = apply_substitution(t, sub)
        self.assertEqual(result, func("f", const("3"), const("a")))

    def test_resolve_no_complement(self):
        c1 = [("a", True)]
        c2 = [("b", True)]
        self.assertIsNone(resolve(c1, c2))

    def test_resolution_refute_unsat(self):
        # {a}, {not a} -> empty clause
        clauses = [[("a", True)], [("a", False)]]
        self.assertTrue(resolution_refute(clauses))

    def test_resolution_refute_sat(self):
        # {a or b} is satisfiable
        clauses = [[("a", True), ("b", True)]]
        self.assertFalse(resolution_refute(clauses))


class TestFirstOrderLogic(unittest.TestCase):

    def test_substitute_var(self):
        t = fvar("x")
        sub = {"x": const("5")}
        self.assertEqual(substitute(t, sub), const("5"))

    def test_substitute_func(self):
        t = func("f", fvar("x"), const("a"))
        sub = {"x": const("3")}
        result = substitute(t, sub)
        self.assertEqual(result, func("f", const("3"), const("a")))

    def test_occurs_in(self):
        t = func("f", fvar("x"), const("a"))
        self.assertTrue(occurs_in("x", t))
        self.assertFalse(occurs_in("y", t))

    def test_unify_constants(self):
        self.assertEqual(unify(const("a"), const("a")), {})
        self.assertIsNone(unify(const("a"), const("b")))

    def test_unify_var_constant(self):
        result = unify(fvar("x"), const("a"))
        self.assertEqual(result, {"x": const("a")})

    def test_unify_var_var(self):
        result = unify(fvar("x"), fvar("y"))
        self.assertEqual(result, {"x": fvar("y")})

    def test_unify_func(self):
        t1 = func("f", const("a"))
        t2 = func("f", const("a"))
        self.assertEqual(unify(t1, t2), {})

    def test_unify_func_mismatch(self):
        t1 = func("f", const("a"))
        t2 = func("g", const("a"))
        self.assertIsNone(unify(t1, t2))

    def test_unify_occur_check(self):
        # x occurs in f(x) — should fail
        t1 = fvar("x")
        t2 = func("f", fvar("x"))
        self.assertIsNone(unify(t1, t2))


if __name__ == "__main__":
    unittest.main()
