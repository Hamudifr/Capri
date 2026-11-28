"""Tests for the database internals training module."""

from __future__ import annotations

import unittest

from research.training.database import (
    BTree,
    HashIndex,
    OpenAddressingHash,
    Relation,
    SimpleDB,
)


class TestBTree(unittest.TestCase):
    def test_btree_insert_search(self):
        tree = BTree(t=2)
        for i in range(10):
            tree.insert(i, i * 10)
        # Search for existing keys
        for i in range(10):
            self.assertEqual(tree.search(i), i * 10)
        # Search for missing key
        self.assertIsNone(tree.search(100))

    def test_btree_in_order(self):
        tree = BTree(t=2)
        import random
        rng = random.Random(42)
        keys = list(range(50))
        rng.shuffle(keys)
        for k in keys:
            tree.insert(k, k)
        result = tree.in_order_traversal()
        self.assertEqual(result, sorted(keys))

    def test_btree_range_search(self):
        tree = BTree(t=2)
        for i in range(20):
            tree.insert(i, i)
        result = tree.range_search(5, 10)
        self.assertEqual(result, [5, 6, 7, 8, 9, 10])

    def test_btree_range_search_empty(self):
        tree = BTree(t=2)
        for i in range(10):
            tree.insert(i, i)
        result = tree.range_search(50, 60)
        self.assertEqual(result, [])

    def test_btree_large_insert(self):
        tree = BTree(t=3)
        keys = list(range(100))
        for k in keys:
            tree.insert(k, k)
        # All keys should be findable
        for k in keys:
            self.assertEqual(tree.search(k), k)

    def test_btree_duplicate_key(self):
        tree = BTree(t=2)
        tree.insert(5, "a")
        tree.insert(5, "b")
        # Should have the latest value
        self.assertEqual(tree.search(5), "b")


class TestHashIndex(unittest.TestCase):
    def test_hash_insert_get(self):
        idx = HashIndex(buckets=8)
        idx.insert("name", "Alice")
        idx.insert("age", 30)
        self.assertEqual(idx.get("name"), "Alice")
        self.assertEqual(idx.get("age"), 30)

    def test_hash_missing_key(self):
        idx = HashIndex()
        self.assertIsNone(idx.get("nonexistent"))

    def test_hash_delete(self):
        idx = HashIndex()
        idx.insert("key1", "val1")
        self.assertTrue(idx.delete("key1"))
        self.assertIsNone(idx.get("key1"))
        self.assertFalse(idx.delete("key1"))

    def test_hash_update(self):
        idx = HashIndex()
        idx.insert("key", "old")
        idx.insert("key", "new")
        self.assertEqual(idx.get("key"), "new")

    def test_hash_load_factor(self):
        idx = HashIndex(buckets=10)
        for i in range(5):
            idx.insert(f"k{i}", i)
        lf = idx.load_factor()
        self.assertAlmostEqual(lf, 0.5)

    def test_hash_keys(self):
        idx = HashIndex()
        idx.insert("a", 1)
        idx.insert("b", 2)
        keys = idx.keys()
        self.assertIn("a", keys)
        self.assertIn("b", keys)


class TestOpenAddressing(unittest.TestCase):
    def test_open_addressing_insert_get(self):
        h = OpenAddressingHash(capacity=8)
        h.insert("x", 100)
        h.insert("y", 200)
        self.assertEqual(h.get("x"), 100)
        self.assertEqual(h.get("y"), 200)

    def test_open_addressing_missing(self):
        h = OpenAddressingHash()
        self.assertIsNone(h.get("nope"))

    def test_open_addressing_delete(self):
        h = OpenAddressingHash(capacity=8)
        h.insert("a", 1)
        h.insert("b", 2)
        self.assertTrue(h.delete("a"))
        self.assertIsNone(h.get("a"))
        # "b" should still be findable after deletion of "a"
        self.assertEqual(h.get("b"), 2)


class TestRelationalAlgebra(unittest.TestCase):
    def test_project(self):
        rel = Relation("people", ["name", "age"])
        rel.add_row({"name": "Alice", "age": 30})
        rel.add_row({"name": "Bob", "age": 25})
        projected = rel.project(["name"])
        self.assertEqual(len(projected.rows), 2)
        self.assertEqual(projected.columns, ["name"])

    def test_select(self):
        rel = Relation("t", ["x"])
        rel.add_row({"x": 1})
        rel.add_row({"x": 2})
        rel.add_row({"x": 3})
        selected = rel.select(lambda r: r["x"] > 1)
        self.assertEqual(len(selected.rows), 2)

    def test_union(self):
        r1 = Relation("a", ["x"])
        r1.add_row({"x": 1})
        r2 = Relation("b", ["x"])
        r2.add_row({"x": 2})
        result = r1.union(r2)
        self.assertEqual(len(result.rows), 2)

    def test_union_dedup(self):
        r1 = Relation("a", ["x"])
        r1.add_row({"x": 1})
        r2 = Relation("b", ["x"])
        r2.add_row({"x": 1})
        r2.add_row({"x": 2})
        result = r1.union(r2)
        self.assertEqual(len(result.rows), 2)

    def test_intersect(self):
        r1 = Relation("a", ["x"])
        r1.add_row({"x": 1})
        r1.add_row({"x": 2})
        r2 = Relation("b", ["x"])
        r2.add_row({"x": 2})
        r2.add_row({"x": 3})
        result = r1.intersect(r2)
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["x"], 2)

    def test_difference(self):
        r1 = Relation("a", ["x"])
        r1.add_row({"x": 1})
        r1.add_row({"x": 2})
        r2 = Relation("b", ["x"])
        r2.add_row({"x": 2})
        result = r1.difference(r2)
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["x"], 1)

    def test_natural_join(self):
        r1 = Relation("emp", ["id", "dept_id"])
        r1.add_row({"id": 1, "dept_id": 1})
        r1.add_row({"id": 2, "dept_id": 2})

        r2 = Relation("dept", ["dept_id", "budget"])
        r2.add_row({"dept_id": 1, "budget": 100})
        r2.add_row({"dept_id": 2, "budget": 200})

        result = r1.natural_join(r2)
        # Joined on dept_id
        self.assertEqual(len(result.rows), 2)

    def test_theta_join(self):
        r1 = Relation("a", ["x", "y"])
        r1.add_row({"x": 1, "y": 10})
        r2 = Relation("b", ["x", "z"])
        r2.add_row({"x": 1, "z": 100})

        result = r1.theta_join(r2, lambda r: r["y"] < r["z"])
        self.assertEqual(len(result.rows), 1)


class TestSimpleDB(unittest.TestCase):
    def test_create_and_insert(self):
        db = SimpleDB()
        db.create_table("users", ["id", "name"])
        db.insert("users", {"id": 1, "name": "Alice"})
        db.insert("users", {"id": 2, "name": "Bob"})

    def test_query_select(self):
        db = SimpleDB()
        db.create_table("t", ["x"])
        db.insert("t", {"x": 1})
        db.insert("t", {"x": 2})
        db.insert("t", {"x": 3})
        result = db.query("t", condition=lambda r: r["x"] > 1)
        self.assertEqual(len(result.rows), 2)

    def test_query_project(self):
        db = SimpleDB()
        db.create_table("t", ["x", "y"])
        db.insert("t", {"x": 1, "y": 10})
        db.insert("t", {"x": 2, "y": 20})
        result = db.query("t", columns=["x"])
        self.assertEqual(result.columns, ["x"])
        self.assertEqual(len(result.rows), 2)

    def test_join_query(self):
        db = SimpleDB()
        db.create_table("emp", ["id", "dept_id"])
        db.create_table("dept", ["dept_id", "name"])
        db.insert("emp", {"id": 1, "dept_id": 1})
        db.insert("emp", {"id": 2, "dept_id": 2})
        db.insert("dept", {"dept_id": 1, "name": "Eng"})
        db.insert("dept", {"dept_id": 2, "name": "Sales"})

        result = db.join("emp", "dept")
        self.assertEqual(len(result.rows), 2)

    def test_table_names(self):
        db = SimpleDB()
        db.create_table("a", ["x"])
        db.create_table("b", ["y"])
        names = db.table_names()
        self.assertIn("a", names)
        self.assertIn("b", names)


if __name__ == "__main__":
    unittest.main()
