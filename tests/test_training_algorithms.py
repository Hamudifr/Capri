"""Tests for the algorithms training module."""

from __future__ import annotations

import unittest

from research.training.algorithms import (
    FenwickTree,
    SegmentTree,
    Treap,
    astar_search,
    dijkstra_pq,
    edit_distance,
    heapsort,
    kmp_search,
    matrix_chain_multiply,
    mergesort,
    optimal_bst,
    quicksort,
    rabin_karp_search,
    suffix_array,
)


class TestSorting(unittest.TestCase):
    def test_quicksort(self):
        import random
        rng = random.Random(42)
        arr = [rng.randint(-100, 100) for _ in range(50)]
        result = quicksort(arr)
        self.assertEqual(result, sorted(arr))

    def test_mergesort(self):
        import random
        rng = random.Random(42)
        arr = [rng.randint(-100, 100) for _ in range(50)]
        result = mergesort(arr)
        self.assertEqual(result, sorted(arr))

    def test_heapsort(self):
        import random
        rng = random.Random(42)
        arr = [rng.randint(-100, 100) for _ in range(50)]
        result = heapsort(arr)
        self.assertEqual(result, sorted(arr))

    def test_mergesort_stable(self):
        # Mergesort should be stable
        items = [(3, "a"), (1, "b"), (3, "c"), (1, "d"), (2, "e")]
        result = mergesort(items)
        # The two 3s should maintain relative order (a before c)
        threes = [item for item in result if item[0] == 3]
        self.assertEqual(threes, [(3, "a"), (3, "c")])


class TestFenwickTree(unittest.TestCase):
    def test_fenwick_prefix_sum(self):
        ft = FenwickTree(initial=[1, 2, 3, 4, 5])
        self.assertEqual(ft.prefix_sum(0), 1)
        self.assertEqual(ft.prefix_sum(2), 6)
        self.assertEqual(ft.prefix_sum(4), 15)

    def test_fenwick_range_sum(self):
        ft = FenwickTree(initial=[1, 2, 3, 4, 5])
        self.assertEqual(ft.range_sum(1, 3), 9)
        self.assertEqual(ft.range_sum(0, 0), 1)

    def test_fenwick_update(self):
        ft = FenwickTree(initial=[1, 2, 3, 4, 5])
        ft.update(2, 10)  # Add 10 to index 2
        self.assertEqual(ft.prefix_sum(2), 16)  # 1 + 2 + 13

    def test_fenwick_total(self):
        ft = FenwickTree(initial=[1, 2, 3, 4, 5])
        self.assertEqual(ft.total(), 15)


class TestSegmentTree(unittest.TestCase):
    def test_segment_tree_sum(self):
        st = SegmentTree([1, 2, 3, 4, 5], op="sum")
        self.assertEqual(st.query(0, 4), 15)
        self.assertEqual(st.query(1, 3), 9)

    def test_segment_tree_min(self):
        st = SegmentTree([3, 1, 4, 1, 5], op="min")
        self.assertEqual(st.query(0, 4), 1)
        self.assertEqual(st.query(1, 3), 1)

    def test_segment_tree_max(self):
        st = SegmentTree([3, 1, 4, 1, 5], op="max")
        self.assertEqual(st.query(0, 4), 5)

    def test_segment_tree_update(self):
        st = SegmentTree([1, 2, 3, 4, 5], op="sum")
        st.update(2, 10)
        self.assertEqual(st.query(0, 4), 22)


class TestTreap(unittest.TestCase):
    def test_treap_insert_search(self):
        import random
        rng = random.Random(42)
        treap = Treap()
        keys = list(range(20))
        rng.shuffle(keys)
        for k in keys:
            treap.insert(k, k * 10)

        for k in keys:
            self.assertEqual(treap.search(k), k * 10)

    def test_treap_delete(self):
        treap = Treap()
        for k in range(10):
            treap.insert(k, k)

        self.assertTrue(treap.delete(5))
        self.assertIsNone(treap.search(5))
        self.assertFalse(treap.delete(5))

    def test_treap_in_order(self):
        import random
        rng = random.Random(42)
        treap = Treap()
        keys = list(range(20))
        rng.shuffle(keys)
        for k in keys:
            treap.insert(k)
        result = treap.in_order()
        self.assertEqual(result, sorted(keys))


class TestStringAlgorithms(unittest.TestCase):
    def test_rabin_karp(self):
        matches = rabin_karp_search("ABABDABACDABABCABAB", "ABABCABAB")
        self.assertEqual(matches, [10])

    def test_rabin_karp_no_match(self):
        matches = rabin_karp_search("ABCDEFG", "XYZ")
        self.assertEqual(matches, [])

    def test_kmp(self):
        matches = kmp_search("ABABDABACDABABCABAB", "ABABCABAB")
        self.assertEqual(matches, [10])

    def test_kmp_no_match(self):
        matches = kmp_search("ABCDEFG", "XYZ")
        self.assertEqual(matches, [])

    def test_suffix_array(self):
        text = "banana"
        sa = suffix_array(text)
        # Verify the suffix array is correct
        for i in range(len(sa) - 1):
            s1 = text[sa[i]:]
            s2 = text[sa[i + 1]:]
            self.assertLessEqual(s1, s2)


class TestDynamicProgramming(unittest.TestCase):
    def test_matrix_chain(self):
        # (10, 30, 5, 60) -> matrices 10x30, 30x5, 5x60
        # Optimal: 10*5*60 + 10*30*60 = 3000 + 18000 = 21000
        result = matrix_chain_multiply([10, 30, 5, 60])
        self.assertEqual(result, 4500)  # Actually (10*30*5) + (10*5*60) = 1500+3000=4500

    def test_edit_distance(self):
        self.assertEqual(edit_distance("kitten", "sitting"), 3)
        self.assertEqual(edit_distance("", "abc"), 3)
        self.assertEqual(edit_distance("abc", "abc"), 0)

    def test_optimal_bst(self):
        # keys = [10, 20, 30], freq = [3, 5, 1, 1] (with dummy keys)
        # This is a standard example
        result = optimal_bst([10, 20, 30], [3, 5, 1, 1])
        # Should be a positive integer
        self.assertGreater(result, 0)


class TestGraphAlgorithms(unittest.TestCase):
    def test_dijkstra_pq(self):
        graph = {
            0: [(1, 4), (2, 1)],
            1: [(3, 1)],
            2: [(1, 2), (3, 5)],
            3: [],
        }
        distances, _ = dijkstra_pq(graph, 0)
        self.assertEqual(distances[0], 0.0)
        self.assertEqual(distances[1], 3.0)  # 0->2->1 = 1+2
        self.assertEqual(distances[3], 4.0)  # 0->2->1->3 = 1+2+1

    def test_astar_search(self):
        graph = {
            0: [(1, 1), (2, 4)],
            1: [(3, 1)],
            2: [(3, 2)],
            3: [],
        }
        # Heuristic: distance to goal (3)
        def h(n):
            return {0: 2, 1: 1, 2: 2, 3: 0}.get(n, 0)

        path = astar_search(graph, 0, 3, h)
        self.assertIsNotNone(path)
        self.assertEqual(path[0], 0)
        self.assertEqual(path[-1], 3)


if __name__ == "__main__":
    unittest.main()
