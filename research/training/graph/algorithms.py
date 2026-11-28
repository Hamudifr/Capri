"""Graph theory deep dive study modules.

Implements advanced graph algorithms beyond the basics: minimum
spanning trees, maximum flow, shortest paths with negative weights,
and related concepts.
Pure stdlib, no dependencies.

Topics covered:
- Minimum Spanning Tree: Kruskal's and Prim's algorithms
- Union-Find (Disjoint Set Union) data structure
- Maximum Flow: Ford-Fulkerson with BFS (Edmonds-Karp)
- Shortest paths with negative weights: Bellman-Ford
- Negative cycle detection
- Strongly Connected Components (Kosaraju's algorithm)
- Graph coloring (greedy)
- All-pairs shortest paths (Floyd-Warshall)
- Bipartite graph checking
- Graph representation utilities
"""

from __future__ import annotations

from collections import deque


# ===========================================================================
# Union-Find (Disjoint Set Union)
# ===========================================================================

class UnionFind:
    """Union-Find (Disjoint Set Union) data structure.

    Supports efficient union and find operations with path
    compression and union by rank. Used by Kruskal's algorithm
    and many other graph algorithms.
    """

    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        """Find the root of x with path compression."""
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x: int, y: int) -> bool:
        """Union the sets containing x and y. Returns True if they
        were in different sets (i.e., a merge happened)."""
        root_x = self.find(x)
        root_y = self.find(y)
        if root_x == root_y:
            return False

        if self.rank[root_x] < self.rank[root_y]:
            self.parent[root_x] = root_y
        elif self.rank[root_x] > self.rank[root_y]:
            self.parent[root_y] = root_x
        else:
            self.parent[root_y] = root_x
            self.rank[root_x] += 1
        return True

    def connected(self, x: int, y: int) -> bool:
        """Check if x and y are in the same set."""
        return self.find(x) == self.find(y)

    def components(self) -> int:
        """Count the number of disjoint sets."""
        return len({self.find(i) for i in range(len(self.parent))})


# ===========================================================================
# Minimum Spanning Tree
# ===========================================================================

def kruskal(edges: list[tuple[int, int, float]], num_nodes: int) -> list[tuple[int, int, float]]:
    """Kruskal's algorithm for Minimum Spanning Tree.

    edges: list of (u, v, weight)
    Returns the edges of the MST, sorted by weight.
    """
    # Sort edges by weight
    sorted_edges = sorted(edges, key=lambda e: e[2])

    uf = UnionFind(num_nodes)
    mst = []

    for u, v, w in sorted_edges:
        if uf.union(u, v):
            mst.append((u, v, w))
            if len(mst) == num_nodes - 1:
                break

    return mst


def kruskal_total_weight(edges: list[tuple[int, int, float]],
                         num_nodes: int) -> float:
    """Total weight of the MST using Kruskal's algorithm."""
    mst = kruskal(edges, num_nodes)
    return sum(w for _, _, w in mst)


def prim(adjacency: list[list[tuple[int, float]]],
         start: int = 0) -> list[tuple[int, int, float]]:
    """Prim's algorithm for Minimum Spanning Tree.

    adjacency: adjacency list, adjacency[u] = list of (v, weight)
    Returns the edges of the MST.
    """
    n = len(adjacency)
    if n == 0:
        return []

    visited = [False] * n
    mst: list[tuple[int, int, float]] = []

    # Min-heap: (weight, from_node, to_node)
    # Using a list-based approach since we can't use heapq easily
    # with the tuple ordering we need
    candidates: list[tuple[float, int, int]] = []
    visited[start] = True

    for v, w in adjacency[start]:
        candidates.append((w, start, v))

    while candidates and len(mst) < n - 1:
        # Find the minimum weight edge to an unvisited node
        candidates.sort()
        w, u, v = candidates.pop(0)
        if visited[v]:
            continue
        visited[v] = True
        mst.append((u, v, w))
        for neighbor, edge_w in adjacency[v]:
            if not visited[neighbor]:
                candidates.append((edge_w, v, neighbor))

    return mst


def prim_total_weight(adjacency: list[list[tuple[int, float]]],
                      start: int = 0) -> float:
    """Total weight of the MST using Prim's algorithm."""
    mst = prim(adjacency, start)
    return sum(w for _, _, w in mst)


# ===========================================================================
# Shortest Paths with Negative Weights
# ===========================================================================

def bellman_ford(edges: list[tuple[int, int, float]],
                 num_nodes: int,
                 source: int) -> list[float] | None:
    """Bellman-Ford algorithm: shortest paths from source with
    negative edge weights.

    edges: list of (u, v, weight)
    Returns distance list, or None if a negative cycle is detected.
    """
    dist = [float("inf")] * num_nodes
    dist[source] = 0.0

    # Relax all edges V-1 times
    for _ in range(num_nodes - 1):
        updated = False
        for u, v, w in edges:
            if dist[u] != float("inf") and dist[u] + w < dist[v]:
                dist[v] = dist[u] + w
                updated = True
        if not updated:
            break

    # Check for negative cycles
    for u, v, w in edges:
        if dist[u] != float("inf") and dist[u] + w < dist[v]:
            return None  # Negative cycle detected

    return dist


def bellman_ford_path(edges: list[tuple[int, int, float]],
                      num_nodes: int,
                      source: int,
                      target: int) -> tuple[list[int], float] | None:
    """Bellman-Ford with path reconstruction.

    Returns (path, distance) or None if no path or negative cycle.
    """
    dist = [float("inf")] * num_nodes
    parent: list[int | None] = [None] * num_nodes
    dist[source] = 0.0

    for _ in range(num_nodes - 1):
        for u, v, w in edges:
            if dist[u] != float("inf") and dist[u] + w < dist[v]:
                dist[v] = dist[u] + w
                parent[v] = u

    # Check negative cycle
    for u, v, w in edges:
        if dist[u] != float("inf") and dist[u] + w < dist[v]:
            return None

    if dist[target] == float("inf"):
        return None

    # Reconstruct path
    path = []
    current = target
    while current is not None:
        path.append(current)
        current = parent[current]
    path.reverse()
    return path, dist[target]


# ===========================================================================
# All-Pairs Shortest Paths
# ===========================================================================

def floyd_warshall(adjacency: list[list[float]]) -> list[list[float]]:
    """Floyd-Warshall algorithm: all-pairs shortest paths.

    adjacency: matrix where adjacency[i][j] = weight of edge i→j,
    or inf if no direct edge. diagonal = 0.
    Returns the distance matrix with shortest paths between all pairs.
    """
    n = len(adjacency)
    dist = [row[:] for row in adjacency]

    for k in range(n):
        for i in range(n):
            for j in range(n):
                if dist[i][k] != float("inf") and dist[k][j] != float("inf"):
                    if dist[i][j] > dist[i][k] + dist[k][j]:
                        dist[i][j] = dist[i][k] + dist[k][j]

    return dist


def floyd_warshall_has_negative_cycle(adjacency: list[list[float]]) -> bool:
    """Check for negative cycles using Floyd-Warshall."""
    dist = floyd_warshall(adjacency)
    n = len(adjacency)
    for i in range(n):
        if dist[i][i] < 0:
            return True
    return False


# ===========================================================================
# Maximum Flow (Edmonds-Karp)
# ===========================================================================

def edmonds_karp(capacities: list[list[float]],
                 source: int, sink: int) -> float:
    """Edmonds-Karp algorithm for maximum flow.

    capacities: adjacency matrix where capacities[u][v] = capacity.
    Returns the maximum flow value from source to sink.
    """
    n = len(capacities)
    # Create residual graph
    residual = [row[:] for row in capacities]

    def bfs_find_path() -> list[int] | None:
        """BFS to find an augmenting path. Returns the path or None."""
        parent = [-1] * n
        visited = [False] * n
        queue = deque([source])
        visited[source] = True

        while queue:
            u = queue.popleft()
            for v in range(n):
                if not visited[v] and residual[u][v] > 0:
                    visited[v] = True
                    parent[v] = u
                    queue.append(v)
                    if v == sink:
                        # Reconstruct path
                        path = []
                        current = sink
                        while current != -1:
                            path.append(current)
                            current = parent[current]
                        path.reverse()
                        return path
        return None

    max_flow = 0.0
    path = bfs_find_path()
    while path is not None:
        # Find bottleneck capacity along the path
        bottleneck = float("inf")
        for i in range(len(path) - 1):
            u, v = path[i], path[i + 1]
            bottleneck = min(bottleneck, residual[u][v])

        # Update residual capacities
        for i in range(len(path) - 1):
            u, v = path[i], path[i + 1]
            residual[u][v] -= bottleneck
            residual[v][u] += bottleneck

        max_flow += bottleneck
        path = bfs_find_path()

    return max_flow


def min_cut_edges(capacities: list[list[float]],
                  source: int, sink: int) -> set[tuple[int, int]]:
    """Find the edges in the minimum cut after computing max flow.

    Uses the residual graph from Edmonds-Karp. Returns the set of
    (u, v) edges crossing the cut from the source side to the sink side.
    """
    n = len(capacities)
    residual = [row[:] for row in capacities]

    def bfs_find_path() -> list[int] | None:
        parent = [-1] * n
        visited = [False] * n
        queue = deque([source])
        visited[source] = True
        while queue:
            u = queue.popleft()
            for v in range(n):
                if not visited[v] and residual[u][v] > 0:
                    visited[v] = True
                    parent[v] = u
                    queue.append(v)
                    if v == sink:
                        path = []
                        current = sink
                        while current != -1:
                            path.append(current)
                            current = parent[current]
                        path.reverse()
                        return path
        return None

    # Run Edmonds-Karp to fill residual graph
    path = bfs_find_path()
    while path is not None:
        bottleneck = float("inf")
        for i in range(len(path) - 1):
            u, v = path[i], path[i + 1]
            bottleneck = min(bottleneck, residual[u][v])
        for i in range(len(path) - 1):
            u, v = path[i], path[i + 1]
            residual[u][v] -= bottleneck
            residual[v][u] += bottleneck
        path = bfs_find_path()

    # Find all nodes reachable from source in residual graph
    visited = [False] * n
    queue = deque([source])
    visited[source] = True
    while queue:
        u = queue.popleft()
        for v in range(n):
            if not visited[v] and residual[u][v] > 0:
                visited[v] = True
                queue.append(v)

    # Edges from reachable to non-reachable are in the min cut
    cut = set()
    for u in range(n):
        if visited[u]:
            for v in range(n):
                if not visited[v] and capacities[u][v] > 0:
                    cut.add((u, v))
    return cut


# ===========================================================================
# Strongly Connected Components (Kosaraju)
# ===========================================================================

def kosaraju_scc(adjacency: list[list[int]]) -> list[list[int]]:
    """Kosaraju's algorithm for Strongly Connected Components.

    adjacency: adjacency list, adjacency[u] = list of neighbors.
    Returns a list of SCCs, each a list of node indices.
    """
    n = len(adjacency)

    # Build reverse graph
    reverse: list[list[int]] = [[] for _ in range(n)]
    for u in range(n):
        for v in adjacency[u]:
            reverse[v].append(u)

    # First DFS: compute finish order
    visited = [False] * n
    finish_order = []

    def dfs1(u: int) -> None:
        visited[u] = True
        for v in adjacency[u]:
            if not visited[v]:
                dfs1(v)
        finish_order.append(u)

    for i in range(n):
        if not visited[i]:
            dfs1(i)

    # Second DFS on reverse graph, processing in reverse finish order
    visited = [False] * n
    sccs = []

    def dfs2(u: int, component: list[int]) -> None:
        visited[u] = True
        component.append(u)
        for v in reverse[u]:
            if not visited[v]:
                dfs2(v, component)

    for u in reversed(finish_order):
        if not visited[u]:
            component = []
            dfs2(u, component)
            sccs.append(component)

    return sccs


# ===========================================================================
# Graph coloring
# ===========================================================================

def greedy_graph_coloring(adjacency: list[list[int]]) -> list[int]:
    """Greedy graph coloring (sequential coloring).

    Assigns each node the smallest available color not used by its
    neighbors. Not optimal, but a good approximation.

    Returns a list where result[i] = color of node i.
    """
    n = len(adjacency)
    colors = [-1] * n

    for node in range(n):
        # Collect colors used by neighbors
        used_colors = set()
        for neighbor in adjacency[node]:
            if colors[neighbor] != -1:
                used_colors.add(colors[neighbor])

        # Assign the smallest available color
        color = 0
        while color in used_colors:
            color += 1
        colors[node] = color

    return colors


def chromatic_number(adjacency: list[list[int]]) -> int:
    """Estimate the chromatic number using greedy coloring.

    Returns the number of colors used (an upper bound on the
    true chromatic number).
    """
    colors = greedy_graph_coloring(adjacency)
    return max(colors) + 1 if colors else 0


# ===========================================================================
# Bipartite graph checking
# ===========================================================================

def is_bipartite(adjacency: list[list[int]]) -> bool:
    """Check if a graph is bipartite using 2-coloring (BFS).

    A graph is bipartite if its vertices can be colored with 2
    colors such that no two adjacent vertices share the same color.
    Equivalently, the graph has no odd-length cycles.
    """
    n = len(adjacency)
    colors = [-1] * n  # -1 = uncolored, 0 or 1 = color

    for start in range(n):
        if colors[start] != -1:
            continue

        colors[start] = 0
        queue = deque([start])

        while queue:
            u = queue.popleft()
            for v in adjacency[u]:
                if colors[v] == -1:
                    colors[v] = 1 - colors[u]
                    queue.append(v)
                elif colors[v] == colors[u]:
                    return False

    return True


def __all__() -> list[str]:
    return [
        "UnionFind", "kruskal", "kruskal_total_weight",
        "prim", "prim_total_weight",
        "bellman_ford", "bellman_ford_path",
        "floyd_warshall", "floyd_warshall_has_negative_cycle",
        "edmonds_karp", "min_cut_edges",
        "kosaraju_scc", "greedy_graph_coloring", "chromatic_number",
        "is_bipartite",
    ]
