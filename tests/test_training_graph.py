"""Tests for the graph theory deep dive training module."""

import unittest

from research.training.graph.algorithms import (
    UnionFind, kruskal, kruskal_total_weight,
    prim, prim_total_weight,
    bellman_ford, bellman_ford_path,
    floyd_warshall, floyd_warshall_has_negative_cycle,
    edmonds_karp, min_cut_edges,
    kosaraju_scc, greedy_graph_coloring, chromatic_number,
    is_bipartite,
)


class TestUnionFind(unittest.TestCase):

    def test_find(self):
        uf = UnionFind(5)
        self.assertEqual(uf.find(0), 0)
        uf.union(0, 1)
        self.assertEqual(uf.find(1), 0)

    def test_union(self):
        uf = UnionFind(5)
        self.assertTrue(uf.union(0, 1))
        self.assertTrue(uf.union(2, 3))
        self.assertFalse(uf.union(0, 1))  # Already connected

    def test_connected(self):
        uf = UnionFind(5)
        uf.union(0, 1)
        self.assertTrue(uf.connected(0, 1))
        self.assertFalse(uf.connected(0, 2))

    def test_components(self):
        uf = UnionFind(4)
        uf.union(0, 1)
        uf.union(2, 3)
        self.assertEqual(uf.components(), 2)

    def test_path_compression(self):
        uf = UnionFind(10)
        for i in range(9):
            uf.union(i, i + 1)
        # All should have the same root
        root = uf.find(0)
        for i in range(10):
            self.assertEqual(uf.find(i), root)


class TestMST(unittest.TestCase):

    def test_kruskal_basic(self):
        # 4-node graph
        edges = [
            (0, 1, 1),
            (0, 2, 4),
            (0, 3, 3),
            (1, 2, 2),
            (1, 3, 5),
            (2, 3, 6),
        ]
        mst = kruskal(edges, 4)
        self.assertEqual(len(mst), 3)
        # MST should have total weight 1 + 2 + 3 = 6
        total = sum(w for _, _, w in mst)
        self.assertEqual(total, 6)

    def test_kruskal_total_weight(self):
        edges = [
            (0, 1, 1),
            (1, 2, 2),
            (2, 3, 3),
            (0, 3, 10),
        ]
        self.assertEqual(kruskal_total_weight(edges, 4), 6)

    def test_prim_basic(self):
        adjacency = [
            [(1, 1), (2, 4), (3, 3)],
            [(0, 1), (2, 2), (3, 5)],
            [(0, 4), (1, 2), (3, 6)],
            [(0, 3), (1, 5), (2, 6)],
        ]
        mst = prim(adjacency, 0)
        self.assertEqual(len(mst), 3)
        total = sum(w for _, _, w in mst)
        self.assertEqual(total, 6)

    def test_prim_total_weight(self):
        adjacency = [
            [(1, 1), (2, 4), (3, 3)],
            [(0, 1), (2, 2), (3, 5)],
            [(0, 4), (1, 2), (3, 6)],
            [(0, 3), (1, 5), (2, 6)],
        ]
        self.assertEqual(prim_total_weight(adjacency, 0), 6)

    def test_mst_disconnected(self):
        # Two separate components
        edges = [(0, 1, 1), (2, 3, 2)]
        mst = kruskal(edges, 4)
        # Can only connect within each component
        self.assertEqual(len(mst), 2)


class TestBellmanFord(unittest.TestCase):

    def test_bellman_ford_basic(self):
        edges = [
            (0, 1, 4),
            (0, 2, 5),
            (1, 2, -3),
            (1, 3, 2),
            (2, 3, 1),
        ]
        dist = bellman_ford(edges, 4, 0)
        self.assertIsNotNone(dist)
        self.assertEqual(dist[0], 0.0)
        self.assertEqual(dist[1], 4.0)
        # 0→1→2 = 4-3 = 1
        self.assertEqual(dist[2], 1.0)
        # 0→1→2→3 = 4-3+1 = 2
        self.assertEqual(dist[3], 2.0)

    def test_bellman_ford_no_path(self):
        edges = [(0, 1, 1)]
        dist = bellman_ford(edges, 3, 0)
        self.assertEqual(dist[2], float("inf"))

    def test_bellman_ford_negative_cycle(self):
        edges = [
            (0, 1, 1),
            (1, 2, -1),
            (2, 0, -1),  # Negative cycle: 0→1→2→0 = 1-1-1 = -1
        ]
        dist = bellman_ford(edges, 3, 0)
        self.assertIsNone(dist)

    def test_bellman_ford_path(self):
        edges = [
            (0, 1, 4),
            (0, 2, 5),
            (1, 2, -3),
            (1, 3, 2),
            (2, 3, 1),
        ]
        result = bellman_ford_path(edges, 4, 0, 3)
        self.assertIsNotNone(result)
        path, dist = result
        self.assertEqual(path, [0, 1, 2, 3])
        self.assertEqual(dist, 2.0)

    def test_bellman_ford_no_path_returns_none(self):
        edges = [(0, 1, 1)]
        result = bellman_ford_path(edges, 3, 0, 2)
        self.assertIsNone(result)


class TestFloydWarshall(unittest.TestCase):

    def test_floyd_warshall_basic(self):
        INF = float("inf")
        adj = [
            [0, 3, INF, INF],
            [INF, 0, 1, INF],
            [INF, INF, 0, 7],
            [INF, INF, INF, 0],
        ]
        dist = floyd_warshall(adj)
        self.assertEqual(dist[0][1], 3)
        self.assertEqual(dist[0][2], 4)  # 0→1→2
        self.assertEqual(dist[0][3], 11)  # 0→1→2→3

    def test_floyd_warshall_negative_cycle(self):
        INF = float("inf")
        # 0→1 (1), 1→2 (-3), 2→0 (1): total -1 < 0
        adj = [
            [0, 1, INF],
            [INF, 0, -3],
            [1, INF, 0],
        ]
        self.assertTrue(floyd_warshall_has_negative_cycle(adj))

    def test_floyd_warshall_no_negative_cycle(self):
        INF = float("inf")
        adj = [
            [0, 1, INF],
            [INF, 0, 2],
            [INF, INF, 0],
        ]
        self.assertFalse(floyd_warshall_has_negative_cycle(adj))


class TestMaxFlow(unittest.TestCase):

    def test_edmonds_karp_basic(self):
        # Classic example: max flow = 4
        capacities = [
            [0, 3, 0, 0],
            [0, 0, 2, 2],
            [0, 0, 0, 1],
            [0, 0, 0, 0],
        ]
        # Source=0, sink=3
        flow = edmonds_karp(capacities, 0, 3)
        self.assertEqual(flow, 3)

    def test_edmonds_karp_simple(self):
        # Direct edge: 0→1 with capacity 5
        capacities = [
            [0, 5],
            [0, 0],
        ]
        flow = edmonds_karp(capacities, 0, 1)
        self.assertEqual(flow, 5)

    def test_edmonds_karp_no_flow(self):
        capacities = [
            [0, 0, 0],
            [0, 0, 0],
            [0, 0, 0],
        ]
        flow = edmonds_karp(capacities, 0, 2)
        self.assertEqual(flow, 0)

    def test_min_cut_edges(self):
        capacities = [
            [0, 3, 0, 0],
            [0, 0, 2, 2],
            [0, 0, 0, 1],
            [0, 0, 0, 0],
        ]
        cut = min_cut_edges(capacities, 0, 3)
        self.assertIsInstance(cut, set)
        # The cut should have some edges
        self.assertGreater(len(cut), 0)


class TestSCC(unittest.TestCase):

    def test_kosaraju_single_scc(self):
        # 3-node cycle: all in one SCC
        adj = [[1], [2], [0]]
        sccs = kosaraju_scc(adj)
        self.assertEqual(len(sccs), 1)
        self.assertEqual(set(sccs[0]), {0, 1, 2})

    def test_kosaraju_multiple_sccs(self):
        # 0→1→0 (SCC), 2→3→2 (SCC): two SCCs
        adj = [[1], [0], [3], [2]]
        sccs = kosaraju_scc(adj)
        self.assertEqual(len(sccs), 2)

    def test_kosaraju_empty(self):
        sccs = kosaraju_scc([])
        self.assertEqual(sccs, [])


class TestGraphColoring(unittest.TestCase):

    def test_greedy_coloring(self):
        # Triangle graph needs 3 colors
        adj = [[1, 2], [0, 2], [0, 1]]
        colors = greedy_graph_coloring(adj)
        self.assertEqual(len(colors), 3)
        # No adjacent nodes share a color
        for i, neighbors in enumerate(adj):
            for j in neighbors:
                self.assertNotEqual(colors[i], colors[j])

    def test_chromatic_number_path(self):
        # Path graph: 2 colors
        adj = [[1], [0, 2], [1, 3], [2]]
        chromatic = chromatic_number(adj)
        self.assertLessEqual(chromatic, 2)

    def test_chromatic_number_triangle(self):
        adj = [[1, 2], [0, 2], [0, 1]]
        chromatic = chromatic_number(adj)
        self.assertEqual(chromatic, 3)


class TestBipartite(unittest.TestCase):

    def test_bipartite_path(self):
        # Path: 0-1-2-3 is bipartite
        adj = [[1], [0, 2], [1, 3], [2]]
        self.assertTrue(is_bipartite(adj))

    def test_bipartite_odd_cycle(self):
        # Triangle: not bipartite
        adj = [[1, 2], [0, 2], [0, 1]]
        self.assertFalse(is_bipartite(adj))

    def test_bipartite_even_cycle(self):
        # Square: 0-1-2-3-0 is bipartite
        adj = [[1, 3], [0, 2], [1, 3], [0, 2]]
        self.assertTrue(is_bipartite(adj))

    def test_bipartite_disconnected(self):
        adj = [[1], [0], [3], [2]]
        self.assertTrue(is_bipartite(adj))


if __name__ == "__main__":
    unittest.main()
