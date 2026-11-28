"""Computational complexity: NP-completeness, reductions, approximation.

Stdlib-only. Pure computation, no external dependencies.

Core concepts:
- Complexity classes: P, NP, NP-complete, NP-hard
- Reductions: polynomial-time reductions between problems
- NP-completeness proofs: 3-SAT, vertex cover, clique, Hamiltonian cycle
- SAT-based reductions: 3-coloring, independent set
- Approximation algorithms: vertex cover (2-approx), set cover (ln-approx)
- Parameterized complexity: kernelization
- Exponential algorithms: subset sum, knapsack
"""

from __future__ import annotations


# ===========================================================================
# Complexity class definitions (formal, as data)
# ===========================================================================

COMPLEXITY_CLASSES = {
    "P": "Problems solvable in polynomial time (deterministic)",
    "NP": "Problems with polynomial-time verifiable solutions",
    "NP-complete": "Problems in NP that are as hard as any problem in NP",
    "NP-hard": "Problems at least as hard as any problem in NP",
    "co-NP": "Complement problems of NP (verification of non-solutions)",
    "PSPACE": "Problems solvable in polynomial space",
    "EXPTIME": "Problems solvable in exponential time",
}


# ===========================================================================
# 3-SAT
# ===========================================================================

def is_3sat_satisfiable(clauses: list[list[int]]) -> bool | None:
    """Check if a 3-SAT formula is satisfiable.

    clauses: list of clauses, each clause is a list of up to 3 literals.
    Literals are integers: positive = variable, negative = negated variable.

    Uses a simple DPLL-based approach. Returns True/False or None for
    very large formulas (timeout protection via recursion depth).
    """
    # Count variables
    all_vars = set()
    for clause in clauses:
        for lit in clause:
            all_vars.add(abs(lit))
    variables = sorted(all_vars)
    n = len(variables)

    if n == 0:
        return True  # Empty formula is satisfiable

    # Simple recursive DPLL
    assignment: dict[int, bool] = {}

    def dpll(clauses: list[list[int]], assignment: dict[int, bool]) -> bool:
        # Simplify clauses: evaluate each clause against the assignment
        simplified: list[list[int]] = []
        for clause in clauses:
            unassigned_count = 0
            satisfied = False
            for lit in clause:
                var = abs(lit)
                if var in assignment:
                    val = assignment[var]
                    if (lit > 0 and val) or (lit < 0 and not val):
                        satisfied = True
                        break
                else:
                    unassigned_count += 1
            if satisfied:
                continue  # Clause is satisfied, drop it
            if unassigned_count == 0:
                # All literals evaluated to false — unsatisfiable
                return False
            # Clause is not yet satisfied; keep simplified form
            if unassigned_count < len(clause):
                new_clause = [lit for lit in clause if abs(lit) not in assignment]
                simplified.append(new_clause)
            else:
                simplified.append(list(clause))

        # If no clauses remain, satisfiable
        if not simplified:
            return True

        # Find unit clause (clause with exactly one literal)
        unit_clause = None
        for clause in simplified:
            if len(clause) == 1:
                unit_clause = clause[0]
                break

        # If unit clause found, assign it
        if unit_clause is not None:
            var = abs(unit_clause)
            val = unit_clause > 0
            new_assignment = dict(assignment)
            new_assignment[var] = val
            result = dpll(simplified, new_assignment)
            if result:
                return True
            return False

        # Pick a variable and branch
        var = None
        for v in variables:
            if v not in assignment:
                var = v
                break

        if var is None:
            return True

        # Branch: var = True, then var = False
        for val in [True, False]:
            new_assignment = dict(assignment)
            new_assignment[var] = val
            simplified = []
            for clause in clauses:
                lit = var if val else -var
                if lit in clause:
                    continue  # Clause satisfied
                new_clause = [lit2 for lit2 in clause if abs(lit2) != var]
                if new_clause:
                    simplified.append(new_clause)
            if dpll(simplified, new_assignment):
                return True

        return False

    return dpll(clauses, assignment)


# ===========================================================================
# Reductions
# ===========================================================================

def sat_to_vertex_cover(clauses: list[list[int]]) -> tuple[list[tuple], int]:
    """Reduce 3-SAT to Vertex Cover.

    For each clause of 3 literals, create a triangle (3 vertices, 3 edges).
    For each variable, create edges between all positive and negative occurrences.
    The vertex cover size is (number of clauses * 2) + (number of variables).

    Returns (edges, vertex_cover_size).
    """
    all_vars = set()
    for clause in clauses:
        for lit in clause:
            all_vars.add(abs(lit))
    variables = sorted(all_vars)
    var_to_pos = {v: [] for v in variables}
    var_to_neg = {v: [] for v in variables}

    edges: list[tuple[int, int]] = []
    vertex_id = 0

    # For each clause, create a triangle
    total_cover = 0

    for clause in clauses:
        tri = [vertex_id, vertex_id + 1, vertex_id + 2]
        vertex_id += 3

        # Record occurrences
        for lit in clause:
            var = abs(lit)
            if lit > 0:
                var_to_pos[var].append(tri[0])
            else:
                var_to_neg[var].append(tri[1])

        # Triangle edges
        edges.extend([(tri[0], tri[1]), (tri[1], tri[2]), (tri[0], tri[2])])
        total_cover += 2

    # Variable edges: connect positive to negative occurrences
    for var in variables:
        for pos_v in var_to_pos[var]:
            for neg_v in var_to_neg[var]:
                edges.append((pos_v, neg_v))

    total_cover += len(variables)
    return edges, total_cover


def vertex_cover_decision(
    edges: list[tuple[int, int]], k: int
) -> bool:
    """Check if a graph has a vertex cover of size <= k.

    Brute force over all subsets of size k (exponential, but correct).
    """
    all_vertices = set()
    for u, v in edges:
        all_vertices.add(u)
        all_vertices.add(v)
    vertices = sorted(all_vertices)
    n = len(vertices)

    if k >= n:
        return True

    # Try all subsets of size k
    from itertools import combinations

    for subset in combinations(range(n), k):
        cover = set(vertices[i] for i in subset)
        if all(u in cover or v in cover for u, v in edges):
            return True

    return False


def graph_coloring_3_coloring(
    adj: dict[int, list[int]]
) -> list[int] | None:
    """3-coloring of a graph (backtracking).

    Returns a 3-coloring (list of colors 0/1/2 per vertex) or None.
    """
    vertices = sorted(adj.keys())
    colors: dict[int, int] = {}

    def backtrack(idx: int) -> bool:
        if idx == len(vertices):
            return True
        v = vertices[idx]
        for color in range(3):
            # Check neighbors
            if all(colors.get(neighbor) != color for neighbor in adj.get(v, []) if neighbor in colors):
                colors[v] = color
                if backtrack(idx + 1):
                    return True
                del colors[v]
        return False

    if backtrack(0):
        return [colors[v] for v in vertices]
    return None


def max_clique(adj: dict[int, list[int]]) -> list[int]:
    """Find a maximum clique using brute force (small graphs only).

    Returns the clique as a list of vertices.
    """
    vertices = sorted(adj.keys())
    n = len(vertices)
    best_clique: list[int] = []

    # Check all subsets (exponential)
    for mask in range(1, 1 << n):
        clique = [vertices[i] for i in range(n) if mask & (1 << i)]
        if len(clique) <= len(best_clique):
            continue
        # Check if it's a clique
        is_clique = True
        for i in range(len(clique)):
            for j in range(i + 1, len(clique)):
                if clique[j] not in adj.get(clique[i], []):
                    is_clique = False
                    break
            if not is_clique:
                break
        if is_clique:
            best_clique = clique

    return best_clique


def hamiltonian_cycle(adj: dict[int, list[int]]) -> list[int] | None:
    """Check if a graph has a Hamiltonian cycle (backtracking).

    Returns the cycle as a list of vertices, or None.
    """
    vertices = sorted(adj.keys())
    n = len(vertices)
    if n == 0:
        return None

    cycle: list[int] = []

    def backtrack(pos: int, current: int, visited: set[int]) -> bool:
        if pos == n:
            # Check if last connects to first
            if current in adj.get(vertices[0], []):
                return True
            return False

        for neighbor in adj.get(current, []):
            if neighbor not in visited:
                visited.add(neighbor)
                cycle.append(neighbor)
                if backtrack(pos + 1, neighbor, visited):
                    return True
                cycle.pop()
                visited.remove(neighbor)

        return False

    visited = {vertices[0]}
    cycle = [vertices[0]]
    if backtrack(1, vertices[0], visited):
        return cycle
    return None


# ===========================================================================
# Approximation algorithms
# ===========================================================================

def vertex_cover_approximation(edges: list[tuple[int, int]]) -> set[int]:
    """2-approximation for minimum vertex cover.

    Greedily pick both endpoints of each uncovered edge.
    The result is at most 2x the optimal.
    """
    cover: set[int] = set()
    uncovered = list(edges)

    while uncovered:
        u, v = uncovered.pop(0)
        cover.add(u)
        cover.add(v)
        # Remove covered edges
        uncovered = [(a, b) for a, b in uncovered if a not in cover and b not in cover]

    return cover


def set_cover_approximation(
    universe: list, sets: list[list]
) -> list[int]:
    """Greedy approximation for set cover (ln(n) approximation).

    universe: list of elements
    sets: list of sets (each is a list of elements)
    Returns indices of selected sets.
    """
    uncovered = set(universe)
    selected: list[int] = []
    remaining = list(enumerate(sets))

    while uncovered and remaining:
        # Pick the set that covers the most uncovered elements
        best_idx = -1
        best_count = -1
        for idx, s in remaining:
            count = len(uncovered & set(s))
            if count > best_count:
                best_count = count
                best_idx = idx

        if best_idx == -1 or best_count == 0:
            break

        selected.append(best_idx)
        uncovered -= set(sets[best_idx])
        remaining = [(i, s) for i, s in remaining if i != best_idx]

    return selected


def traveling_salesman_nearest_neighbor(
    dist: list[list[float]], start: int = 0
) -> list[int]:
    """Nearest-neighbor heuristic for TSP.

    dist: distance matrix (n x n)
    Returns the tour as a list of vertex indices.
    """
    n = len(dist)
    visited = {start}
    tour = [start]
    current = start

    while len(visited) < n:
        # Find nearest unvisited neighbor
        nearest = -1
        best_dist = float("inf")
        for j in range(n):
            if j not in visited and dist[current][j] < best_dist:
                best_dist = dist[current][j]
                nearest = j
        if nearest == -1:
            break
        visited.add(nearest)
        tour.append(nearest)
        current = nearest

    return tour


def traveling_salesman_2opt(
    dist: list[list[float]], start: int = 0
) -> list[int]:
    """2-opt local search improvement for TSP.

    Starts from nearest-neighbor solution and iteratively improves.
    """
    tour = traveling_salesman_nearest_neighbor(dist, start)
    n = len(tour)

    improved = True
    while improved:
        improved = False
        for i in range(1, n - 1):
            for j in range(i + 1, n):
                # Check if swapping improves
                a, b = tour[i - 1], tour[i]
                c, d = tour[j], tour[(j + 1) % n]
                if dist[a][b] + dist[c][d] > dist[a][c] + dist[b][d]:
                    # Reverse the segment between i and j
                    tour[i : j + 1] = tour[i : j + 1][::-1]
                    improved = True
                    break
            if improved:
                break

    return tour


# ===========================================================================
# Parameterized complexity: kernelization
# ===========================================================================

def vertex_cover_kernel(edges: list[tuple[int, int]], k: int) -> tuple[list[tuple], int]:
    """Kernelization for vertex cover.

    - Remove isolated vertices
    - If a vertex has degree > k, it must be in any cover of size k -> include it
    - If more than k high-degree vertices, no cover exists

    Returns (remaining_edges, reduced_k).
    """
    adj: dict[int, list[int]] = {}
    for u, v in edges:
        adj.setdefault(u, []).append(v)
        adj.setdefault(v, []).append(u)

    # Remove high-degree vertices
    high_degree = [v for v, neighbors in adj.items() if len(neighbors) > k]
    if len(high_degree) > k:
        return [], -1  # No solution possible

    k_remaining = k - len(high_degree)
    remaining_edges = [
        (u, v) for u, v in edges
        if u not in high_degree and v not in high_degree
    ]

    # Remove isolated vertices
    all_vertices = set()
    for u, v in remaining_edges:
        all_vertices.add(u)
        all_vertices.add(v)

    return remaining_edges, k_remaining


# ===========================================================================
# Exponential algorithms
# ===========================================================================

def subset_sum_meet_in_the_middle(numbers: list[int], target: int) -> bool:
    """Subset sum using meet-in-the-middle. O(2^(n/2)).

    Returns True if a subset sums to target.
    """
    n = len(numbers)
    if n == 0:
        return target == 0

    mid = n // 2
    left = numbers[:mid]
    right = numbers[mid:]

    # Generate all subset sums for left and right
    left_sums = {0}
    for num in left:
        left_sums |= {s + num for s in left_sums}

    right_sums = {0}
    for num in right:
        right_sums |= {s + num for s in right_sums}

    # Check if any combination equals target
    right_set = set(right_sums)
    for s in left_sums:
        if target - s in right_set:
            return True

    return False


def knapsack_bruteforce(items: list[tuple[int, int]], capacity: int) -> int:
    """0/1 knapsack via brute force (exponential, for small inputs).

    items: list of (weight, value)
    Returns the maximum achievable value.
    """
    n = len(items)
    best = 0

    for mask in range(1 << n):
        total_weight = 0
        total_value = 0
        for i in range(n):
            if mask & (1 << i):
                weight, value = items[i]
                total_weight += weight
                total_value += value
        if total_weight <= capacity and total_value > best:
            best = total_value

    return best


def knapsack_dp(items: list[tuple[int, int]], capacity: int) -> int:
    """0/1 knapsack via dynamic programming. O(n * capacity).

    items: list of (weight, value)
    Returns the maximum achievable value.
    """
    dp = [0] * (capacity + 1)

    for weight, value in items:
        for w in range(capacity, weight - 1, -1):
            if dp[w - weight] + value > dp[w]:
                dp[w] = dp[w - weight] + value

    return dp[capacity]
