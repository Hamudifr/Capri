"""Tests for the SAT solving training module."""

import unittest

from research.training.sat.solver import (
    CDCLSolver,
    solve_2sat, solve_sat_cdcl, dpll_solve,
    var_of, neg,
)


class TestLiterals(unittest.TestCase):

    def test_var_of(self):
        self.assertEqual(var_of(3), 3)
        self.assertEqual(var_of(-3), 3)

    def test_neg(self):
        self.assertEqual(neg(5), -5)
        self.assertEqual(neg(-5), 5)


class Test2SAT(unittest.TestCase):

    def test_satisfiable_basic(self):
        # (x1 OR x2) AND (NOT x1 OR x2)
        clauses = [[1, 2], [-1, 2]]
        result = solve_2sat(clauses)
        self.assertIsNotNone(result)
        self.assertEqual(result[1], True)  # x2 must be true

    def test_unsatisfiable(self):
        # (x1) AND (NOT x1)
        clauses = [[1], [-1]]
        result = solve_2sat(clauses)
        self.assertIsNone(result)

    def test_simple_true(self):
        # (x1 OR NOT x1) - always true
        clauses = [[1, -1]]
        result = solve_2sat(clauses)
        self.assertIsNotNone(result)

    def test_implication_chain(self):
        # x1 -> x2, x2 -> x3, NOT x3 -> NOT x1
        # Equivalent: (NOT x1 OR x2), (NOT x2 OR x3), (x3 OR NOT x1)
        clauses = [[-1, 2], [-2, 3], [3, -1]]
        result = solve_2sat(clauses)
        self.assertIsNotNone(result)

    def test_two_vars(self):
        # (x1 OR x2) AND (NOT x1 OR x2) AND (x1 OR NOT x2)
        # x1=true, x2=true is a solution
        clauses = [[1, 2], [-1, 2], [1, -2]]
        result = solve_2sat(clauses)
        self.assertIsNotNone(result)
        self.assertTrue(result[1])
        self.assertTrue(result[2])


class TestCDCL(unittest.TestCase):

    def test_trivial_satisfiable(self):
        # Single clause: (1 OR 2)
        solver = CDCLSolver()
        solver.add_clause([1, 2])
        result = solver.solve()
        self.assertIsNotNone(result)

    def test_trivial_unsatisfiable(self):
        # (1) AND (-1)
        solver = CDCLSolver()
        solver.add_clause([1])
        solver.add_clause([-1])
        result = solver.solve()
        self.assertIsNone(result)

    def test_two_clauses_satisfiable(self):
        solver = CDCLSolver()
        solver.add_clause([1, 2])
        solver.add_clause([-1, 2])
        result = solver.solve()
        self.assertIsNotNone(result)

    def test_solve_sat_cdcl(self):
        # (x1 OR x2) AND (NOT x1 OR x3) AND (NOT x2 OR x3)
        # Satisfiable: x1=True, x2=True, x3=True
        clauses = [[1, 2], [-1, 3], [-2, 3]]
        result = solve_sat_cdcl(clauses)
        self.assertIsNotNone(result)

    def test_solve_sat_cdcl_unsat(self):
        clauses = [[1], [-1]]
        result = solve_sat_cdcl(clauses)
        self.assertIsNone(result)

    def test_more_complex(self):
        # 3-SAT instance
        clauses = [
            [1, 2, 3],
            [1, -2, -3],
            [-1, 2, -3],
            [-1, -2, 3],
        ]
        result = solve_sat_cdcl(clauses)
        self.assertIsNotNone(result)


class TestDPLL(unittest.TestCase):

    def test_simple(self):
        clauses = [[1, 2], [-1, 2]]
        result = dpll_solve(clauses)
        self.assertIsNotNone(result)

    def test_unsat(self):
        clauses = [[1], [-1]]
        result = dpll_solve(clauses)
        self.assertIsNone(result)

    def test_three_vars(self):
        clauses = [[1, 2, 3], [-1, 2, -3], [-2]]
        result = dpll_solve(clauses)
        self.assertIsNotNone(result)


class Test2SATvsCDCL(unittest.TestCase):

    def test_consistent_results(self):
        # Both solvers should agree on satisfiability
        clauses = [[1, 2], [-1, 3], [-2, 3], [-3]]
        sat_2sat = solve_2sat(clauses)
        sat_cdcl = solve_sat_cdcl(clauses)
        self.assertEqual(sat_2sat is not None, sat_cdcl is not None)


if __name__ == "__main__":
    unittest.main()
