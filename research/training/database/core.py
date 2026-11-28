"""Database internals: B-trees, hash indexes, relational algebra.

Stdlib-only. Pure computation, no external dependencies.

Core concepts:
- B-tree: balanced search tree for sorted data and range queries
- B+ tree variant with leaf linking
- Hash index: open addressing and separate chaining
- Relational algebra: select, project, join, union, difference, intersection
- Simple query planner and execution
"""

from __future__ import annotations

import hashlib


# ===========================================================================
# B-tree
# ===========================================================================

class BTreeNode:
    """A node in a B-tree. Stores (key, value) pairs."""

    def __init__(self, leaf: bool = True):
        self.keys: list = []
        self.values: list = []
        self.children: list["BTreeNode"] = []
        self.leaf = leaf
        self.parent: "BTreeNode | None" = None

    def is_leaf(self) -> bool:
        return self.leaf


class BTree:
    """B-tree with minimum degree t >= 2.

    - Each node has at most 2t-1 keys
    - Each non-root node has at least t-1 keys
    - All leaves are at the same depth
    """

    def __init__(self, t: int = 3):
        if t < 2:
            raise ValueError("Minimum degree must be >= 2")
        self.t = t
        self.root = BTreeNode(leaf=True)

    def search(self, key) -> object | None:
        """Search for a key. Returns the value or None."""
        node = self.root
        while node is not None:
            i = 0
            while i < len(node.keys) and key > node.keys[i]:
                i += 1
            if i < len(node.keys) and key == node.keys[i]:
                return node.values[i]
            if node.is_leaf():
                return None
            node = node.children[i]
        return None

    def insert(self, key, value=None) -> None:
        """Insert a key-value pair into the B-tree."""
        root = self.root
        if len(root.keys) == 2 * self.t - 1:
            new_root = BTreeNode(leaf=False)
            new_root.children.append(root)
            root.parent = new_root
            self._split_child(new_root, 0)
            self.root = new_root

        self._insert_non_full(self.root, key, value)

    def _split_child(self, parent: BTreeNode, i: int) -> None:
        """Split the i-th child of parent."""
        t = self.t
        child = parent.children[i]

        mid_idx = t - 1
        mid_key = child.keys[mid_idx]
        mid_value = child.values[mid_idx]

        right = BTreeNode(leaf=child.is_leaf())
        right.parent = parent

        # Copy right half
        right.keys = child.keys[mid_idx + 1 :]
        right.values = child.values[mid_idx + 1 :]

        # Move children if not leaf
        if not child.is_leaf():
            right.children = child.children[t:]
            for c in right.children:
                c.parent = right

        # Shrink child
        child.keys = child.keys[:mid_idx]
        child.values = child.values[:mid_idx]
        if not child.is_leaf():
            child.children = child.children[:t]

        # Insert middle into parent
        parent.keys.insert(i, mid_key)
        parent.values.insert(i, mid_value)
        parent.children.insert(i + 1, right)

    def _insert_non_full(self, node: BTreeNode, key, value) -> None:
        """Insert into a node that is not full."""
        if node.is_leaf():
            # Check for duplicate key
            for i, k in enumerate(node.keys):
                if k == key:
                    node.values[i] = value
                    return
            # Insert in sorted position
            i = len(node.keys) - 1
            while i >= 0 and key < node.keys[i]:
                i -= 1
            node.keys.insert(i + 1, key)
            node.values.insert(i + 1, value)
            return

        # Find the child to descend into
        i = len(node.keys) - 1
        while i >= 0 and key < node.keys[i]:
            i -= 1
        i += 1

        # If child is full, split it
        if len(node.children[i].keys) == 2 * self.t - 1:
            self._split_child(node, i)
            if key > node.keys[i]:
                i += 1

        self._insert_non_full(node.children[i], key, value)

    def range_search(self, low, high) -> list:
        """Return all keys in [low, high]."""
        result: list = []
        self._range_search_node(self.root, low, high, result)
        return result

    def _range_search_node(
        self, node: BTreeNode, low, high, result: list
    ) -> None:
        # In-order traversal with pruning
        for i, key in enumerate(node.keys):
            if not node.is_leaf():
                self._range_search_node(node.children[i], low, high, result)
            if key > high:
                return
            if key >= low:
                result.append(key)
        if not node.is_leaf():
            self._range_search_node(node.children[-1], low, high, result)

    def in_order_traversal(self) -> list:
        """Return all keys in sorted order."""
        result: list = []
        self._in_order(self.root, result)
        return result

    def _in_order(self, node: BTreeNode, result: list) -> None:
        for i, key in enumerate(node.keys):
            if not node.is_leaf():
                self._in_order(node.children[i], result)
            result.append(key)
        if not node.is_leaf():
            self._in_order(node.children[-1], result)


# ===========================================================================
# Hash index
# ===========================================================================

class HashIndex:
    """Hash index using separate chaining."""

    def __init__(self, buckets: int = 16):
        self.buckets = buckets
        self.table: list[list[tuple]] = [[] for _ in range(buckets)]

    def _hash(self, key) -> int:
        """Compute hash bucket for a key."""
        key_str = str(key)
        h = int(hashlib.md5(key_str.encode()).hexdigest(), 16)
        return h % self.buckets

    def insert(self, key, value) -> None:
        """Insert a key-value pair."""
        bucket = self._hash(key)
        for i, (k, v) in enumerate(self.table[bucket]):
            if k == key:
                self.table[bucket][i] = (key, value)
                return
        self.table[bucket].append((key, value))

    def get(self, key):
        """Get value for a key, or None if not found."""
        bucket = self._hash(key)
        for k, v in self.table[bucket]:
            if k == key:
                return v
        return None

    def delete(self, key) -> bool:
        """Delete a key. Returns True if found and deleted."""
        bucket = self._hash(key)
        for i, (k, _) in enumerate(self.table[bucket]):
            if k == key:
                self.table[bucket].pop(i)
                return True
        return False

    def keys(self) -> list:
        """Return all keys in the index."""
        result = []
        for bucket in self.table:
            for k, _ in bucket:
                result.append(k)
        return result

    def load_factor(self) -> float:
        """Current load factor of the hash table."""
        total = sum(len(b) for b in self.table)
        return total / self.buckets if self.buckets > 0 else 0.0


class OpenAddressingHash:
    """Hash index using open addressing with linear probing."""

    def __init__(self, capacity: int = 16):
        self.capacity = capacity
        self.keys: list = [None] * capacity
        self.values: list = [None] * capacity
        self.count = 0

    def _hash(self, key) -> int:
        key_str = str(key)
        h = int(hashlib.md5(key_str.encode()).hexdigest(), 16)
        return h % self.capacity

    def _probe(self, key) -> int:
        """Find the slot for a key (insert or lookup)."""
        idx = self._hash(key)
        for i in range(self.capacity):
            j = (idx + i) % self.capacity
            if self.keys[j] is None or self.keys[j] == key:
                return j
        return -1  # Table full

    def insert(self, key, value) -> None:
        """Insert a key-value pair."""
        idx = self._probe(key)
        if idx == -1:
            raise Exception("Hash table is full")
        if self.keys[idx] is not None and self.keys[idx] != key:
            # Replace existing
            self.values[idx] = value
            return
        self.keys[idx] = key
        self.values[idx] = value
        self.count += 1

    def get(self, key):
        """Get value for a key, or None."""
        idx = self._probe(key)
        if idx == -1 or self.keys[idx] is None:
            return None
        return self.values[idx]

    def delete(self, key) -> bool:
        """Delete a key using tombstones."""
        idx = self._hash(key)
        for i in range(self.capacity):
            j = (idx + i) % self.capacity
            if self.keys[j] is None:
                return False
            if self.keys[j] == key:
                self.keys[j] = None
                self.values[j] = None
                self.count -= 1
                return True
        return False


# ===========================================================================
# Relational algebra
# ===========================================================================

class Relation:
    """A relation (table) with columns and rows."""

    def __init__(self, name: str, columns: list[str]):
        self.name = name
        self.columns = list(columns)
        self.rows: list[dict[str, object]] = []

    def add_row(self, row: dict[str, object]) -> None:
        """Add a row (dict mapping column names to values)."""
        self.rows.append(dict(row))

    def project(self, cols: list[str]) -> "Relation":
        """Project onto a subset of columns."""
        result = Relation(self.name + "_proj", cols)
        for row in self.rows:
            new_row = {c: row.get(c) for c in cols}
            result.add_row(new_row)
        return result

    def select(self, condition=None) -> "Relation":
        """Select rows satisfying a condition."""
        result = Relation(self.name + "_sel", self.columns)
        if condition is None:
            for row in self.rows:
                result.add_row(row)
        else:
            for row in self.rows:
                if condition(row):
                    result.add_row(row)
        return result

    def union(self, other: "Relation") -> "Relation":
        """Union of two relations (must have same columns)."""
        if self.columns != other.columns:
            raise ValueError("Relations must have same columns for union")
        result = Relation(self.name + "_union", self.columns)
        # Deduplicate
        seen: set[tuple] = set()
        for row in self.rows:
            t = tuple(row.get(c) for c in self.columns)
            if t not in seen:
                seen.add(t)
                result.add_row(row)
        for row in other.rows:
            t = tuple(row.get(c) for c in other.columns)
            if t not in seen:
                seen.add(t)
                result.add_row(row)
        return result

    def intersect(self, other: "Relation") -> "Relation":
        """Intersection of two relations."""
        if self.columns != other.columns:
            raise ValueError("Relations must have same columns for intersect")
        result = Relation(self.name + "_int", self.columns)
        other_tuples = {tuple(row.get(c) for c in other.columns) for row in other.rows}
        seen: set[tuple] = set()
        for row in self.rows:
            t = tuple(row.get(c) for c in self.columns)
            if t in other_tuples and t not in seen:
                seen.add(t)
                result.add_row(row)
        return result

    def difference(self, other: "Relation") -> "Relation":
        """Difference (self - other)."""
        if self.columns != other.columns:
            raise ValueError("Relations must have same columns for difference")
        result = Relation(self.name + "_diff", self.columns)
        other_tuples = {tuple(row.get(c) for c in other.columns) for row in other.rows}
        seen: set[tuple] = set()
        for row in self.rows:
            t = tuple(row.get(c) for c in self.columns)
            if t not in other_tuples and t not in seen:
                seen.add(t)
                result.add_row(row)
        return result

    def natural_join(self, other: "Relation") -> "Relation":
        """Natural join on common columns."""
        common = [c for c in self.columns if c in other.columns]
        if not common:
            # Cartesian product
            all_cols = list(self.columns) + [c for c in other.columns if c not in self.columns]
            result = Relation(self.name + "_x", all_cols)
            for r1 in self.rows:
                for r2 in other.rows:
                    merged = dict(r1)
                    for c in other.columns:
                        if c not in merged:
                            merged[c] = r2.get(c)
                    result.add_row(merged)
            return result

        result_cols = list(dict.fromkeys(self.columns + other.columns))
        result = Relation(self.name + "_join", result_cols)

        for r1 in self.rows:
            for r2 in other.rows:
                if all(r1.get(c) == r2.get(c) for c in common):
                    merged = dict(r1)
                    for c in other.columns:
                        if c not in merged:
                            merged[c] = r2.get(c)
                    result.add_row(merged)
        return result

    def theta_join(
        self, other: "Relation", condition=None  # noqa: F821
    ) -> "Relation":
        """Theta join with an arbitrary condition."""
        all_cols = list(dict.fromkeys(self.columns + other.columns))
        result = Relation(self.name + "_theta", all_cols)

        for r1 in self.rows:
            for r2 in other.rows:
                merged = dict(r1)
                for c in other.columns:
                    if c not in merged:
                        merged[c] = r2.get(c)
                if condition is None or condition(merged):
                    result.add_row(merged)
        return result

    def count(self) -> int:
        """Number of rows."""
        return len(self.rows)

    def __repr__(self) -> str:
        return f"Relation({self.name}, cols={self.columns}, rows={len(self.rows)})"


# ===========================================================================
# Simple query execution
# ===========================================================================

class SimpleDB:
    """A minimal in-memory database with tables and query execution."""

    def __init__(self):
        self.tables: dict[str, Relation] = {}

    def create_table(self, name: str, columns: list[str]) -> None:
        """Create a new table."""
        self.tables[name] = Relation(name, columns)

    def insert(self, table: str, row: dict[str, object]) -> None:
        """Insert a row into a table."""
        self.tables[table].add_row(row)

    def query(self, table: str, condition=None, columns=None) -> Relation:
        """Run a select-project query."""
        rel = self.tables[table]
        rel = rel.select(condition)
        if columns:
            rel = rel.project(columns)
        return rel

    def join(self, table1: str, table2: str, condition=None) -> Relation:
        """Run a join query between two tables."""
        r1 = self.tables[table1]
        r2 = self.tables[table2]
        if condition is None:
            return r1.natural_join(r2)
        return r1.theta_join(r2, condition)

    def table_names(self) -> list[str]:
        """Return names of all tables."""
        return list(self.tables.keys())
