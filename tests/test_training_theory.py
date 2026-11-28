"""Tests for the theory of computation training module."""

import unittest

from research.training.theory.computation import (
    DFA, NFA, regex_match, TuringMachine,
    is_polynomial_time, bfs, dfs, dijkstra,
    topological_sort, fib_dp, longest_common_subsequence, knapsack,
)


class TestDFA(unittest.TestCase):

    def setUp(self):
        # DFA for binary strings ending in '1'
        self.dfa = DFA(
            states={"q0", "q1"},
            alphabet={"0", "1"},
            transitions={
                ("q0", "0"): "q0",
                ("q0", "1"): "q1",
                ("q1", "0"): "q0",
                ("q1", "1"): "q1",
            },
            start="q0",
            accept={"q1"},
        )

    def test_accepts_ending_in_one(self):
        self.assertTrue(self.dfa.accepts("1"))
        self.assertTrue(self.dfa.accepts("01"))
        self.assertTrue(self.dfa.accepts("101"))

    def test_rejects_ending_in_zero(self):
        self.assertFalse(self.dfa.accepts(""))
        self.assertFalse(self.dfa.accepts("0"))
        self.assertFalse(self.dfa.accepts("10"))

    def test_rejects_bad_symbol(self):
        self.assertFalse(self.dfa.accepts("x"))


class TestNFA(unittest.TestCase):

    def test_nfa_accepts(self):
        # NFA that accepts strings containing '1'
        nfa = NFA(
            states={"q0", "q1"},
            alphabet={"0", "1"},
            transitions={
                ("q0", "0"): {"q0"},
                ("q0", "1"): {"q0", "q1"},
                ("q1", "0"): {"q1"},
                ("q1", "1"): {"q1"},
            },
            start="q0",
            accept={"q1"},
        )
        self.assertTrue(nfa.accepts("01"))
        self.assertTrue(nfa.accepts("111"))
        self.assertFalse(nfa.accepts("000"))

    def test_nfa_epsilon(self):
        nfa = NFA(
            states={"q0", "q1"},
            alphabet={"0", "1"},
            transitions={
                ("q0", "0"): {"q0"},
                ("q0", "1"): {"q0"},
                ("q0", ""): {"q1"},
            },
            start="q0",
            accept={"q1"},
        )
        self.assertTrue(nfa.accepts(""))
        self.assertTrue(nfa.accepts("00"))

    def test_nfa_to_dfa(self):
        nfa = NFA(
            states={"q0", "q1"},
            alphabet={"0", "1"},
            transitions={
                ("q0", "0"): {"q0"},
                ("q0", "1"): {"q0", "q1"},
                ("q1", "0"): {"q1"},
                ("q1", "1"): {"q1"},
            },
            start="q0",
            accept={"q1"},
        )
        dfa = nfa.to_dfa()
        self.assertTrue(dfa.accepts("01"))
        self.assertTrue(dfa.accepts("1"))
        self.assertFalse(dfa.accepts("000"))


class TestRegex(unittest.TestCase):

    def test_regex_match_simple(self):
        self.assertTrue(regex_match("a*", "aaa"))
        self.assertTrue(regex_match("a*", ""))
        self.assertFalse(regex_match("a*", "b"))

    def test_regex_match_alternation(self):
        self.assertTrue(regex_match("a|b", "a"))
        self.assertTrue(regex_match("a|b", "b"))
        self.assertFalse(regex_match("a|b", "c"))

    def test_regex_match_sequence(self):
        self.assertTrue(regex_match("ab", "ab"))
        self.assertFalse(regex_match("ab", "ba"))
        self.assertFalse(regex_match("ab", "a"))


class TestTuringMachine(unittest.TestCase):

    def test_tm_accept(self):
        tm = TuringMachine(
            states={"q0", "q_accept"},
            alphabet={"0", "1", "_"},
            transitions={
                ("q0", "_"): ("q_accept", "_", "R"),
            },
            start="q0",
            accept="q_accept",
            reject="q_reject",
        )
        result_state, tape = tm.run(["_"])
        self.assertEqual(result_state, "accept")

    def test_tm_reject(self):
        tm = TuringMachine(
            states={"q0", "q_reject"},
            alphabet={"0", "1", "_"},
            transitions={
                ("q0", "0"): ("q_reject", "0", "R"),
            },
            start="q0",
            accept="q_accept",
            reject="q_reject",
        )
        result_state, tape = tm.run(["0"])
        self.assertEqual(result_state, "reject")


class TestComplexity(unittest.TestCase):

    def test_is_polynomial_time_true(self):
        # n^2 is polynomial
        self.assertTrue(is_polynomial_time(lambda n: sum(range(n ** 2)), [10, 20, 40]))

    def test_is_polynomial_time_linear(self):
        self.assertTrue(is_polynomial_time(lambda n: sum(range(n)), [10, 20, 40]))


class TestGraphAlgorithms(unittest.TestCase):

    def setUp(self):
        self.graph = {
            "A": ["B", "C"],
            "B": ["C", "D"],
            "C": ["D"],
            "D": [],
        }

    def test_bfs_visit_order(self):
        result = bfs(self.graph, "A")
        self.assertEqual(result[0], "A")
        self.assertIn("B", result)
        self.assertIn("C", result)
        self.assertIn("D", result)

    def test_bfs_visits_all(self):
        result = bfs(self.graph, "A")
        self.assertEqual(set(result), {"A", "B", "C", "D"})

    def test_dfs_visits_all(self):
        result = dfs(self.graph, "A")
        self.assertEqual(set(result), {"A", "B", "C", "D"})

    def test_dijkstra_weighted(self):
        weighted_graph = {
            "A": {"B": 1, "C": 4},
            "B": {"C": 2, "D": 5},
            "C": {"D": 1},
            "D": {},
        }
        distances = dijkstra(weighted_graph, "A")
        self.assertEqual(distances["A"], 0.0)
        self.assertEqual(distances["B"], 1.0)
        # A->B->C->D = 1+2+1 = 4
        self.assertEqual(distances["D"], 4.0)

    def test_topological_sort(self):
        graph = {"A": ["B", "C"], "B": ["D"], "C": ["D"], "D": []}
        order = topological_sort(graph)
        self.assertIsNotNone(order)
        self.assertEqual(order[0], "A")
        self.assertEqual(order[-1], "D")

    def test_topological_sort_cycle(self):
        graph = {"A": ["B"], "B": ["A"]}
        order = topological_sort(graph)
        self.assertIsNone(order)


class TestDP(unittest.TestCase):

    def test_fib_dp(self):
        self.assertEqual(fib_dp(0), 0)
        self.assertEqual(fib_dp(1), 1)
        self.assertEqual(fib_dp(10), 55)

    def test_longest_common_subsequence(self):
        self.assertEqual(longest_common_subsequence("ABC", "AXC"), "AC")
        # Both "ACT" and "AGT" are valid LCS of length 3
        lcs = longest_common_subsequence("AGCT", "ACGT")
        self.assertEqual(len(lcs), 3)
        self.assertEqual(longest_common_subsequence("", "ABC"), "")

    def test_knapsack(self):
        # weights, values, capacity
        weights = [10, 20, 30]
        values = [60, 100, 120]
        result = knapsack(weights, values, 50)
        # Best: items 2 and 3: 100+120=220 with weight 50
        self.assertEqual(result, 220)

    def test_knapsack_zero_capacity(self):
        result = knapsack([1, 2], [10, 20], 0)
        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
