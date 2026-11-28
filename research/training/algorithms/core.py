"""Algorithms and data structures: sorting, advanced trees, and algorithms.

Stdlib-only. Pure computation, no external dependencies.

Core concepts:
- Sorting: quicksort, mergesort, heapsort with complexity analysis
- Data structures: Fenwick tree (BIT), segment tree, treap
- String algorithms: Rabin-Karp, KMP, suffix array
- Dynamic programming: matrix chain multiplication, optimal BST, edit distance
- Graph algorithms: Dijkstra with priority queue, A* search
"""

from __future__ import annotations

import heapq
import random


# ===========================================================================
# Sorting algorithms
# ===========================================================================

def quicksort(arr: list) -> list:
    """Quicksort (Lomuto partition, in-place wrapper)."""
    result = list(arr)
    _quicksort(result, 0, len(result) - 1)
    return result


def _quicksort(arr: list, low: int, high: int) -> None:
    if low < high:
        pivot_idx = _partition(arr, low, high)
        _quicksort(arr, low, pivot_idx - 1)
        _quicksort(arr, pivot_idx + 1, high)


def _partition(arr: list, low: int, high: int) -> int:
    pivot = arr[high]
    i = low - 1
    for j in range(low, high):
        if arr[j] <= pivot:
            i += 1
            arr[i], arr[j] = arr[j], arr[i]
    arr[i + 1], arr[high] = arr[high], arr[i + 1]
    return i + 1


def mergesort(arr: list) -> list:
    """Mergesort (stable, top-down)."""
    if len(arr) <= 1:
        return list(arr)
    mid = len(arr) // 2
    left = mergesort(arr[:mid])
    right = mergesort(arr[mid:])
    return _merge(left, right)


def _merge(left: list, right: list) -> list:
    result = []
    i = j = 0
    while i < len(left) and j < len(right):
        if left[i] <= right[j]:
            result.append(left[i])
            i += 1
        else:
            result.append(right[j])
            j += 1
    result.extend(left[i:])
    result.extend(right[j:])
    return result


def heapsort(arr: list) -> list:
    """Heapsort (in-place, O(n log n))."""
    result = list(arr)
    n = len(result)

    # Build max heap
    for i in range(n // 2 - 1, -1, -1):
        _heapify(result, n, i)

    # Extract elements
    for i in range(n - 1, 0, -1):
        result[0], result[i] = result[i], result[0]
        _heapify(result, i, 0)

    return result


def _heapify(arr: list, n: int, i: int) -> None:
    largest = i
    l = 2 * i + 1
    r = 2 * i + 2
    if l < n and arr[l] > arr[largest]:
        largest = l
    if r < n and arr[r] > arr[largest]:
        largest = r
    if largest != i:
        arr[i], arr[largest] = arr[largest], arr[i]
        _heapify(arr, n, largest)


def _is_sorted(arr: list) -> bool:
    return all(arr[i] <= arr[i + 1] for i in range(len(arr) - 1))


# ===========================================================================
# Fenwick Tree (Binary Indexed Tree)
# ===========================================================================

class FenwickTree:
    """Fenwick tree / Binary Indexed Tree for prefix sums.

    - build: O(n)
    - point update: O(log n)
    - prefix query: O(log n)
    """

    def __init__(self, size: int | None = None, initial: list[int] | None = None):
        if initial is not None:
            size = len(initial)
            self.n = size
            self.tree = [0] * (size + 1)
            for i in range(size):
                self._update(i + 1, initial[i])
        elif size is not None:
            self.n = size
            self.tree = [0] * (size + 1)
        else:
            self.n = 0
            self.tree = [0]

    def _update(self, idx: int, delta: int) -> None:
        while idx <= self.n:
            self.tree[idx] += delta
            idx += idx & (-idx)

    def update(self, index: int, delta: int) -> None:
        """Add delta to element at index (0-based)."""
        self._update(index + 1, delta)

    def prefix_sum(self, index: int) -> int:
        """Sum of elements [0, index] (0-based, inclusive)."""
        idx = index + 1
        total = 0
        while idx > 0:
            total += self.tree[idx]
            idx -= idx & (-idx)
        return total

    def range_sum(self, left: int, right: int) -> int:
        """Sum of elements [left, right] (0-based, inclusive)."""
        if left == 0:
            return self.prefix_sum(right)
        return self.prefix_sum(right) - self.prefix_sum(left - 1)

    def total(self) -> int:
        """Sum of all elements."""
        return self.prefix_sum(self.n - 1)


# ===========================================================================
# Segment Tree
# ===========================================================================

class SegmentTree:
    """Segment tree for range queries and point updates.

    Supports range sum, range min, range max queries.
    """

    def __init__(self, data: list, op: str = "sum"):
        self.n = len(data)
        self.op = op
        self.size = 1
        while self.size < self.n:
            self.size *= 2
        self.tree = [0] * (2 * self.size)

        if op == "sum":
            self.identity = 0
        elif op == "min":
            self.identity = float("inf")
        elif op == "max":
            self.identity = float("-inf")
        else:
            raise ValueError(f"Unknown operation: {op}")

        # Fill leaves
        for i in range(self.n):
            self.tree[self.size + i] = data[i]
        for i in range(self.n, self.size):
            self.tree[self.size + i] = self.identity

        # Build tree
        for i in range(self.size - 1, 0, -1):
            self.tree[i] = self._apply(self.tree[2 * i], self.tree[2 * i + 1])

    def _apply(self, a, b) -> float:
        if self.op == "sum":
            return a + b
        elif self.op == "min":
            return min(a, b)
        elif self.op == "max":
            return max(a, b)

    def update(self, index: int, value) -> None:
        """Update element at index (0-based)."""
        pos = self.size + index
        self.tree[pos] = value
        pos //= 2
        while pos > 0:
            self.tree[pos] = self._apply(self.tree[2 * pos], self.tree[2 * pos + 1])
            pos //= 2

    def query(self, left: int, right: int) -> float:
        """Query range [left, right] (0-based, inclusive)."""
        left += self.size
        right += self.size
        result = self.identity
        while left <= right:
            if left % 2 == 1:
                result = self._apply(result, self.tree[left])
                left += 1
            if right % 2 == 0:
                result = self._apply(result, self.tree[right])
                right -= 1
            left //= 2
            right //= 2
        return result


# ===========================================================================
# Treap (Randomized BST)
# ===========================================================================

class TreapNode:
    """A node in a treap."""

    def __init__(self, key, value=None):
        self.key = key
        self.value = value if value is not None else key
        self.priority = random.random()
        self.left: "TreapNode | None" = None
        self.right: "TreapNode | None" = None


class Treap:
    """Treap: a Cartesian tree combining BST and heap properties.

    - Expected O(log n) for insert, delete, search
    - Uses random priorities to maintain balance
    """

    def __init__(self):
        self.root: TreapNode | None = None

    def _rotate_right(self, y: TreapNode) -> TreapNode:
        x = y.left  # type: ignore
        if x is None:
            return y
        T2 = x.right
        x.right = y
        y.left = T2
        return x

    def _rotate_left(self, x: TreapNode) -> TreapNode:
        y = x.right  # type: ignore
        if y is None:
            return x
        T2 = y.left
        y.left = x
        x.right = T2
        return y

    def insert(self, key, value=None) -> None:
        """Insert a key-value pair."""
        self.root = self._insert(self.root, TreapNode(key, value))

    def _insert(self, node: TreapNode | None, new_node: TreapNode) -> TreapNode:
        if node is None:
            return new_node

        if new_node.key < node.key:
            node.left = self._insert(node.left, new_node)
            if node.left.priority > node.priority:  # type: ignore
                node = self._rotate_right(node)
        else:
            node.right = self._insert(node.right, new_node)
            if node.right.priority > node.priority:  # type: ignore
                node = self._rotate_left(node)

        return node

    def search(self, key):
        """Search for a key. Returns value or None."""
        node = self.root
        while node is not None:
            if key == node.key:
                return node.value
            elif key < node.key:
                node = node.left
            else:
                node = node.right
        return None

    def delete(self, key) -> bool:
        """Delete a key. Returns True if found."""
        found = [False]
        self.root = self._delete(self.root, key, found)
        return found[0]

    def _delete(self, node: TreapNode | None, key, found: list) -> TreapNode | None:
        if node is None:
            return None

        if key == node.key:
            found[0] = True
            # Merge left and right subtrees
            return self._merge(node.left, node.right)

        elif key < node.key:
            node.left = self._delete(node.left, key, found)
        else:
            node.right = self._delete(node.right, key, found)

        return node

    def _merge(self, left: TreapNode | None, right: TreapNode | None) -> TreapNode | None:
        if left is None:
            return right
        if right is None:
            return left

        if left.priority > right.priority:
            left.right = self._merge(left.right, right)
            return left
        else:
            right.left = self._merge(left, right.left)
            return right

    def in_order(self) -> list:
        """Return all keys in sorted order."""
        result = []
        self._in_order(self.root, result)
        return result

    def _in_order(self, node: TreapNode | None, result: list) -> None:
        if node is None:
            return
        self._in_order(node.left, result)
        result.append(node.key)
        self._in_order(node.right, result)


# ===========================================================================
# String algorithms
# ===========================================================================

def rabin_karp_search(text: str, pattern: str) -> list[int]:
    """Rabin-Karp string search. Returns list of match positions."""
    if not pattern:
        return []
    n = len(text)
    m = len(pattern)
    if m > n:
        return []

    d = 256  # alphabet size
    q = 101  # prime modulus

    h = pow(d, m - 1, q)
    p_hash = 0
    t_hash = 0

    # Compute initial hash
    for i in range(m):
        p_hash = (d * p_hash + ord(pattern[i])) % q
        t_hash = (d * t_hash + ord(text[i])) % q

    matches = []
    for i in range(n - m + 1):
        if p_hash == t_hash and text[i : i + m] == pattern:
            matches.append(i)

        if i < n - m:
            t_hash = (d * (t_hash - ord(text[i]) * h) + ord(text[i + m])) % q
            if t_hash < 0:
                t_hash += q

    return matches


def kmp_search(text: str, pattern: str) -> list[int]:
    """KMP (Knuth-Morris-Pratt) string search. Returns list of match positions."""
    if not pattern:
        return []
    n = len(text)
    m = len(pattern)

    # Build failure function (partial match table)
    lps = [0] * m
    length = 0
    i = 1
    while i < m:
        if pattern[i] == pattern[length]:
            length += 1
            lps[i] = length
            i += 1
        else:
            if length != 0:
                length = lps[length - 1]
            else:
                lps[i] = 0
                i += 1

    # Search
    matches = []
    i = 0  # index for text
    j = 0  # index for pattern
    while i < n:
        if pattern[j] == text[i]:
            i += 1
            j += 1
        if j == m:
            matches.append(i - j)
            j = lps[j - 1]
        elif i < n and pattern[j] != text[i]:
            if j != 0:
                j = lps[j - 1]
            else:
                i += 1

    return matches


def suffix_array(text: str) -> list[int]:
    """Build suffix array using doubling algorithm. O(n log^2 n)."""
    n = len(text)
    sa = list(range(n))
    rank = [ord(c) for c in text]
    new_rank = [0] * n
    k = 1

    while k < n:
        # Sort by (rank[i], rank[i+k])
        sa.sort(key=lambda i: (rank[i], rank[i + k] if i + k < n else -1))

        # Recompute rank
        new_rank[sa[0]] = 0
        for i in range(1, n):
            prev = sa[i - 1]
            curr = sa[i]
            prev_key = (rank[prev], rank[prev + k] if prev + k < n else -1)
            curr_key = (rank[curr], rank[curr + k] if curr + k < n else -1)
            new_rank[curr] = new_rank[prev] if prev_key == curr_key else i

        rank = list(new_rank)
        if rank[sa[-1]] == n - 1:
            break
        k *= 2

    return sa


# ===========================================================================
# Dynamic programming
# ===========================================================================

def matrix_chain_multiply(dims: list[int]) -> int:
    """Minimum number of scalar multiplications to multiply a chain of matrices.

    dims: [d0, d1, d2, ..., dn] where matrix i has dimensions dims[i] x dims[i+1]
    """
    n = len(dims) - 1  # number of matrices
    if n < 2:
        return 0

    # dp[i][j] = min multiplications for matrices i..j
    dp = [[0] * n for _ in range(n)]

    for length in range(2, n + 1):
        for i in range(n - length + 1):
            j = i + length - 1
            dp[i][j] = float("inf")
            for k in range(i, j):
                cost = dp[i][k] + dp[k + 1][j] + dims[i] * dims[k + 1] * dims[j + 1]
                dp[i][j] = min(dp[i][j], cost)

    return dp[0][n - 1]


def optimal_bst(keys: list, freq: list) -> int:
    """Optimal binary search tree cost (minimum expected search cost).

    keys: sorted keys
    freq: frequency of each key (and dummy keys between/around)
    """
    n = len(keys)
    # freq has n + 1 entries (including dummy keys)
    if n == 0:
        return 0

    dp = [[0] * (n + 1) for _ in range(n + 1)]

    for length in range(1, n + 1):
        for i in range(n - length + 1):
            j = i + length
            dp[i][j] = float("inf")
            for k in range(i, j):
                cost = dp[i][k] + dp[k + 1][j] + sum(freq[i : j + 1])
                dp[i][j] = min(dp[i][j], cost)

    return dp[0][n]


def edit_distance(s1: str, s2: str) -> int:
    """Levenshtein edit distance between two strings."""
    m = len(s1)
    n = len(s2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]

    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if s1[i - 1] == s2[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])

    return dp[m][n]


# ===========================================================================
# Graph algorithms with priority queue
# ===========================================================================

def dijkstra_pq(
    graph: dict, start: int
) -> tuple[dict[int, float], dict[int, int | None]]:
    """Dijkstra's algorithm using a priority queue.

    graph: adjacency list {node: [(neighbor, weight), ...]}
    Returns (distances, predecessors).
    """
    distances = {start: 0.0}
    predecessors: dict[int, int | None] = {start: None}
    pq = [(0.0, start)]
    visited: set[int] = set()

    while pq:
        dist_u, u = heapq.heappop(pq)
        if u in visited:
            continue
        visited.add(u)

        for v, weight in graph.get(u, []):
            if v not in distances or dist_u + weight < distances[v]:
                distances[v] = dist_u + weight
                predecessors[v] = u
                heapq.heappush(pq, (distances[v], v))

    return distances, predecessors


def astar_search(
    graph: dict,
    start: int,
    goal: int,
    heuristic: "callable | None" = None,  # noqa: F821
) -> list[int] | None:
    """A* search with a heuristic function.

    graph: adjacency list {node: [(neighbor, weight), ...]}
    heuristic: function h(node) -> float, must be admissible
    Returns the path as a list of nodes, or None if no path.
    """
    if heuristic is None:
        heuristic = lambda n: 0.0

    g_scores = {start: 0.0}
    f_scores = {start: heuristic(start)}
    open_set = [(f_scores[start], 0, start)]  # (f, tie-breaker, node)
    counter = 1
    came_from: dict[int, int | None] = {}

    while open_set:
        _, _, current = heapq.heappop(open_set)

        if current == goal:
            # Reconstruct path
            path = []
            while current is not None:
                path.append(current)
                current = came_from.get(current)
            return list(reversed(path))

        for neighbor, weight in graph.get(current, []):
            tentative_g = g_scores[current] + weight
            if neighbor not in g_scores or tentative_g < g_scores[neighbor]:
                came_from[neighbor] = current
                g_scores[neighbor] = tentative_g
                f = tentative_g + heuristic(neighbor)
                f_scores[neighbor] = f
                counter += 1
                heapq.heappush(open_set, (f, counter, neighbor))

    return None
