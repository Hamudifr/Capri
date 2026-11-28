"""Tests for the computational complexity training module."""

from __future__ import annotations

import unittest

from research.training.complexity import (
    COMPLEXITY_CLASSES,
    graph_coloring_3_coloring,
    hamiltonian_cycle,
    is_3sat_satisfiable,
    knapsack_bruteforce,
    knapsack_dp,
    max_clique,
    set_cover_approximation,
    sat_to_vertex_cover,
    subset_sum_meet_in_the_middle,
    traveling_salesman_2opt,
    traveling_salesman_nearest_neighbor,
    vertex_cover_approximation,
    vertex_cover_decision,
    vertex_cover_kernel,
)


class TestComplexityClasses(unittest.TestCase):
    def test_complexity_classes_defined(self):
        for cls in ["P", "NP", "NP-complete", "NP-hard", "co-NP", "PSPACE", "EXPTIME"]:
            self.assertIn(cls, COMPLEXITY_CLASSES)
            self.assertIsInstance(COMPLEXITY_CLASSES[cls], str)
            self.assertGreater(len(COMPLEXITY_CLASSES[cls]), 0)


class Test3SAT(unittest.TestCase):
    def test_3sat_satisfiable(self):
        # (x1 ∨ x2 ∨ x3) ∧ (¬x1 ∨ ¬x2 ∨ x3)
        clauses = [[1, 2, 3], [-1, -2, 3]]
        self.assertTrue(is_3sat_satisfiable(clauses))

    def test_3sat_unsatisfiable(self):
        # (x1) ∧ (¬x1)
        clauses = [[1], [-1]]
        self.assertFalse(is_3sat_satisfiable(clauses))

    def test_3sat_simple_satisfiable(self):
        clauses = [[1, 2, 3]]
        self.assertTrue(is_3sat_satisfiable(clauses))

    def test_3sat_empty(self):
        self.assertTrue(is_3sat_satisfiable([]))


class TestReductions(unittest.TestCase):
    def test_sat_to_vertex_cover(self):
        clauses = [[1, 2, 3], [-1, 2, -3]]
        edges, k = sat_to_vertex_cover(clauses)
        self.assertGreater(len(edges), 0)
        self.assertGreater(k, 0)

    def test_vertex_cover_decision_small(self):
        # Triangle graph: edges (0,1), (1,2), (0,2)
        edges = [(0, 1), (1, 2), (0, 2)]
        # Need at least 2 vertices to cover a triangle
        self.assertFalse(vertex_cover_decision(edges, 1))
        self.assertTrue(vertex_cover_decision(edges, 2))

    def test_vertex_cover_decision_path(self):
        # Path: 0-1-2
        edges = [(0, 1), (1, 2)]
        self.assertTrue(vertex_cover_decision(edges, 1))  # vertex 1 covers all

    def test_vertex_cover_approximation(self):
        edges = [(0, 1), (1, 2), (2, 3), (3, 4)]
        cover = vertex_cover_approximation(edges)
        # Should cover all edges
        for u, v in edges:
            self.assertTrue(u in cover or v in cover)


class TestGraphProblems(unittest.TestCase):
    def test_3_coloring(self):
        # Triangle needs 3 colors
        adj = {0: [1, 2], 1: [0, 2], 2: [0, 1]}
        colors = graph_coloring_3_coloring(adj)
        self.assertIsNotNone(colors)
        self.assertEqual(len(colors), 3)

    def test_3_coloring_bipartite(self):
        # Path is bipartite, needs 2 colors
        adj = {0: [1], 1: [0, 2], 2: [1]}
        colors = graph_coloring_3_coloring(adj)
        self.assertIsNotNone(colors)
        # Check valid coloring (colors is indexed by sorted vertex position)
        vertices = sorted(adj.keys())
        v_idx = {v: i for i, v in enumerate(vertices)}
        for v in adj:
            for neighbor in adj[v]:
                self.assertNotEqual(colors[v_idx[v]], colors[v_idx[neighbor]])

    def test_max_clique(self):
        # Triangle is a clique of size 3
        adj = {0: [1, 2], 1: [0, 2], 2: [0, 1]}
        clique = max_clique(adj)
        self.assertEqual(len(clique), 3)

    def test_hamiltonian_cycle(self):
        # Triangle has a Hamiltonian cycle
        adj = {0: [1, 2], 1: [0, 2], 2: [0, 1]}
        cycle = hamiltonian_cycle(adj)
        self.assertIsNotNone(cycle)
        self.assertEqual(len(cycle), 3)

    def test_hamiltonian_cycle_none(self):
        # Path (3 vertices in a line) has no Hamiltonian cycle
        adj = {0: [1], 1: [0, 2], 2: [1]}
        cycle = hamiltonian_cycle(adj)
        self.assertIsNone(cycle)


class TestApproximation(unittest.TestCase):
    def test_set_cover_approximation(self):
        universe = [1, 2, 3, 4, 5, 6]
        sets = [
            [1, 2, 3],
            [4, 5, 6],
            [1, 4],
            [2, 5],
            [3, 6],
        ]
        selected = set_cover_approximation(universe, sets)
        # Selected sets should cover the universe
        covered = set()
        for idx in selected:
            covered |= set(sets[idx])
        self.assertEqual(covered, set(universe))

    def test_tsp_nearest_neighbor(self):
        # Simple distance matrix
        dist = [
            [0, 1, 2],
            [1, 0, 1],
            [2, 1, 0],
        ]
        tour = traveling_salesman_nearest_neighbor(dist)
        self.assertEqual(len(tour), 3)
        self.assertEqual(tour[0], 0)

    def test_tsp_2opt(self):
        dist = [
            [0, 1, 2, 3],
            [1, 0, 1, 2],
            [2, 1, 0, 1],
            [3, 2, 1, 0],
        ]
        tour = traveling_salesman_2opt(dist)
        self.assertEqual(len(tour), 4)


class TestKernelization(unittest.TestCase):
    def test_vertex_cover_kernel(self):
        # Star graph: center 0 has degree 3, leaves have degree 1
        edges = [(0, 1), (0, 2), (0, 3)]
        # k = 1, vertex 0 has degree 3 > 1, so it must be in the cover
        remaining, k_remaining = vertex_cover_kernel(edges, 1)
        # Vertex 0 is included, k_remaining = 0
        self.assertEqual(k_remaining, 0)
        self.assertEqual(remaining, [])  # All edges covered by vertex 0


class TestExponentialAlgorithms(unittest.TestCase):
    def test_subset_sum(self):
        numbers = [3, 1, 4, 2]
        self.assertTrue(subset_sum_meet_in_the_middle(numbers, 5))  # 1+4
        self.assertFalse(subset_sum_meet_in_the_middle(numbers, 11))  # max sum is 10

    def test_knapsack_bruteforce(self):
        items = [(2, 3), (3, 4), (4, 5)]  # (weight, value)
        capacity = 5
        result = knapsack_bruteforce(items, capacity)
        # Best: items 1+2 (weight 2+3=5, value 3+4=7) or items 0+2 (weight 2+4=6 > 5)
        # Actually items 0+1: weight 5, value 7
        self.assertEqual(result, 7)

    def test_knapsack_dp(self):
        items = [(2, 3), (3, 4), (4, 5)]
        capacity = 5
        result = knapsack_dp(items, capacity)
        self.assertEqual(result, 7)

    def test_knapsack_dp_matches_bruteforce(self):
        items = [(2, 3), (3, 4), (4, 5), (1, 2)]
        capacity = 7
        self.assertEqual(knapsack_dp(items, capacity), knapsack_bruteforce(items, capacity))


if __name__ == "__main__":
    unittest.main()
