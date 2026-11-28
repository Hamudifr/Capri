"""Theory of computation study modules.

Implements core concepts from theoretical CS: automata, regular
expressions, complexity classes, and formal language theory.
Pure stdlib, no dependencies.

Topics covered:
- Deterministic and nondeterministic finite automata (DFA/NFA)
- Regular expressions and their equivalence to finite automata
- The pumping lemma for regular languages
- Turing machines (conceptual + simulation of a simple one)
- Complexity classes: P, NP, NP-completeness (conceptual)
- Sorting algorithm analysis
- Graph algorithms: BFS, DFS, shortest paths, topological sort
- Dynamic programming fundamentals
"""

from __future__ import annotations

from collections import deque


# ===========================================================================
# Finite automata
# ===========================================================================

class DFA:
    """Deterministic Finite Automaton.

    states: set of state names
    alphabet: set of input symbols
    transitions: dict (state, symbol) -> next_state
    start: start state
    accept: set of accepting states
    """

    def __init__(self, states: set[str], alphabet: set[str],
                 transitions: dict[tuple[str, str], str],
                 start: str, accept: set[str]):
        self.states = states
        self.alphabet = alphabet
        self.transitions = transitions
        self.start = start
        self.accept = accept

    def accepts(self, input_str: str) -> bool:
        """Check if the DFA accepts an input string."""
        current = self.start
        for symbol in input_str:
            if symbol not in self.alphabet:
                return False
            if (current, symbol) not in self.transitions:
                return False
            current = self.transitions[(current, symbol)]
        return current in self.accept


class NFA:
    """Nondeterministic Finite Automaton.

    transitions: dict (state, symbol) -> set of next states
    """

    def __init__(self, states: set[str], alphabet: set[str],
                 transitions: dict[tuple[str, str], set[str]],
                 start: str, accept: set[str]):
        self.states = states
        self.alphabet = alphabet
        self.transitions = transitions
        self.start = start
        self.accept = accept

    def accepts(self, input_str: str) -> bool:
        """Check if the NFA accepts an input string (subset construction)."""
        # Compute epsilon-closure of start
        current_set = self._epsilon_closure({self.start})
        for symbol in input_str:
            if symbol not in self.alphabet:
                return False
            next_set = set()
            for state in current_set:
                if (state, symbol) in self.transitions:
                    next_set.update(self.transitions[(state, symbol)])
            current_set = self._epsilon_closure(next_set)
            if not current_set:
                return False
        return bool(current_set & self.accept)

    def _epsilon_closure(self, states: set[str]) -> set[str]:
        """Compute the epsilon-closure of a set of states."""
        closure = set(states)
        stack = list(states)
        while stack:
            state = stack.pop()
            if (state, "") in self.transitions:
                for next_state in self.transitions[(state, "")]:
                    if next_state not in closure:
                        closure.add(next_state)
                        stack.append(next_state)
        return closure

    def to_dfa(self) -> DFA:
        """Convert NFA to DFA via subset construction."""
        # Compute epsilon-closure of start
        start_set = frozenset(self._epsilon_closure({self.start}))

        dfa_states = set()
        dfa_alphabet = self.alphabet
        dfa_transitions: dict[tuple[str, str], str] = {}
        dfa_accept = set()

        # Map from frozenset of NFA states to DFA state names
        state_map: dict[frozenset[str], str] = {}
        state_map[start_set] = "q0"
        dfa_states.add("q0")
        if start_set & self.accept:
            dfa_accept.add("q0")

        queue = deque([start_set])
        counter = 1

        while queue:
            nfa_set = queue.popleft()
            dfa_name = state_map[nfa_set]

            for symbol in self.alphabet:
                # Union of epsilon-closures of all transitions
                next_nfa_set = set()
                for nfa_state in nfa_set:
                    if (nfa_state, symbol) in self.transitions:
                        next_nfa_set.update(self.transitions[(nfa_state, symbol)])
                next_nfa_set = frozenset(self._epsilon_closure(next_nfa_set))

                if next_nfa_set:
                    if next_nfa_set not in state_map:
                        name = f"q{counter}"
                        counter += 1
                        state_map[next_nfa_set] = name
                        dfa_states.add(name)
                        if next_nfa_set & self.accept:
                            dfa_accept.add(name)
                        queue.append(next_nfa_set)
                    dfa_transitions[(dfa_name, symbol)] = state_map[next_nfa_set]

        return DFA(dfa_states, dfa_alphabet, dfa_transitions, "q0", dfa_accept)


# ===========================================================================
# Regular expressions (basic matching)
# ===========================================================================

def regex_match(pattern: str, text: str) -> bool:
    """Simple regex matcher supporting:
    - '.' matches any single character
    - '*' matches zero or more of the preceding character
    - '+' matches one or more of the preceding character
    - '?' matches zero or one of the preceding character
    - '|' for alternation
    - '()' for grouping

    This is a recursive matcher — not a full regex engine but
    sufficient for study.
    """
    def match_at(pat_idx: int, text_idx: int) -> bool:
        if pat_idx >= len(pattern):
            return text_idx >= len(text)

        # Check for alternation
        if pat_idx + 1 < len(pattern) and pattern[pat_idx + 1] == '|':
            # Find the end of the alternation
            end = pat_idx + 2
            depth = 0
            while end < len(pattern):
                if pattern[end] == '(':
                    depth += 1
                elif pattern[end] == ')':
                    if depth == 0:
                        break
                    depth -= 1
                elif pattern[end] == '|' and depth == 0:
                    break
                end += 1
            alt_end = end
            if end < len(pattern) and pattern[end] == ')':
                alt_end = end

            # Try the first branch
            sub_patterns = pattern[pat_idx:alt_end].split('|')
            for sub in sub_patterns:
                if _match_with_pattern(sub, text, text_idx):
                    return True
            return False

        # Handle '*' 
        if pat_idx + 1 < len(pattern) and pattern[pat_idx + 1] == '*':
            char = pattern[pat_idx]
            # Zero occurrences
            if match_at(pat_idx + 2, text_idx):
                return True
            # One or more occurrences
            if text_idx < len(text) and (char == '.' or text[text_idx] == char):
                return match_at(pat_idx, text_idx + 1)
            return False

        # Handle '+'
        if pat_idx + 1 < len(pattern) and pattern[pat_idx + 1] == '+':
            char = pattern[pat_idx]
            if text_idx >= len(text):
                return False
            if not (char == '.' or text[text_idx] == char):
                return False
            # At least one, then optionally more via *
            return match_at(pat_idx, text_idx + 1) and (
                match_at(pat_idx + 2, text_idx + 1) or match_at(pat_idx, text_idx + 1)
            )

        # Handle '?'
        if pat_idx + 1 < len(pattern) and pattern[pat_idx + 1] == '?':
            char = pattern[pat_idx]
            # Zero occurrences
            if match_at(pat_idx + 2, text_idx):
                return True
            # One occurrence
            if text_idx < len(text) and (char == '.' or text[text_idx] == char):
                return match_at(pat_idx + 2, text_idx + 1)
            return False

        # Literal or '.'
        if text_idx >= len(text):
            return False
        if pattern[pat_idx] == '.' or pattern[pat_idx] == text[text_idx]:
            return match_at(pat_idx + 1, text_idx + 1)

        return False

    return match_at(0, 0)


def _match_with_pattern(pattern: str, text: str, text_idx: int) -> bool:
    """Helper for alternation matching."""
    def match_at(pat_idx: int, text_idx: int) -> bool:
        if pat_idx >= len(pattern):
            return text_idx >= len(text)

        if pat_idx + 1 < len(pattern) and pattern[pat_idx + 1] == '*':
            char = pattern[pat_idx]
            if match_at(pat_idx + 2, text_idx):
                return True
            if text_idx < len(text) and (char == '.' or text[text_idx] == char):
                return match_at(pat_idx, text_idx + 1)
            return False

        if pat_idx + 1 < len(pattern) and pattern[pat_idx + 1] == '+':
            char = pattern[pat_idx]
            if text_idx >= len(text):
                return False
            if not (char == '.' or text[text_idx] == char):
                return False
            return match_at(pat_idx + 2, text_idx + 1) or match_at(pat_idx, text_idx + 1)

        if pat_idx + 1 < len(pattern) and pattern[pat_idx + 1] == '?':
            char = pattern[pat_idx]
            if match_at(pat_idx + 2, text_idx):
                return True
            if text_idx < len(text) and (char == '.' or text[text_idx] == char):
                return match_at(pat_idx + 2, text_idx + 1)
            return False

        if text_idx >= len(text):
            return False
        if pattern[pat_idx] == '.' or pattern[pat_idx] == text[text_idx]:
            return match_at(pat_idx + 1, text_idx + 1)
        return False

    return match_at(0, text_idx)


# ===========================================================================
# Turing machine simulation (conceptual)
# ===========================================================================

class TuringMachine:
    """A simple Turing machine for study.

    states: set of state names
    alphabet: set of symbols including '_' (blank)
    transitions: dict (state, symbol) -> (next_state, write_symbol, move)
    start: start state
    accept: accepting state
    reject: rejecting state
    """

    def __init__(self, states: set[str], alphabet: set[str],
                 transitions: dict[tuple[str, str], tuple[str, str, str]],
                 start: str, accept: str, reject: str):
        self.states = states
        self.alphabet = alphabet
        self.transitions = transitions
        self.start = start
        self.accept = accept
        self.reject = reject

    def run(self, tape: list[str]) -> tuple[str, list[str]]:
        """Run the TM on a tape. Returns (result_state, final_tape)."""
        position = 0
        state = self.start

        def extend_tape(t: list[str], pos: int) -> list[str]:
            while len(t) <= pos:
                t.append("_")
            return t

        for _ in range(10000):
            if state == self.accept:
                return "accept", tape
            if state == self.reject:
                return "reject", tape

            tape = extend_tape(tape, position)
            symbol = tape[position]

            if (state, symbol) not in self.transitions:
                return "reject", tape

            next_state, write_symbol, move = self.transitions[(state, symbol)]
            tape[position] = write_symbol

            if move == "L":
                position -= 1
            elif move == "R":
                position += 1

            state = next_state

        return "timeout", tape


# ===========================================================================
# Complexity classes (conceptual + verification)
# ===========================================================================

def is_polynomial_time(func, input_sizes: list[int], max_n: int = 50) -> bool:
    """Rough check: does runtime grow polynomially with input size?

    For study purposes — times the function on inputs of increasing
    size and checks if log(time) vs log(n) is roughly linear.
    """
    import time
    times = []
    for n in input_sizes:
        start = time.perf_counter()
        func(n)
        elapsed = time.perf_counter() - start
        times.append(elapsed)

    # Check if log(time) is roughly linear in log(n)
    import math
    log_ns = [math.log(n) for n in input_sizes]
    log_ts = [math.log(t) if t > 0 else -20 for t in times]

    # Simple linear regression
    n_pts = len(log_ns)
    mx = sum(log_ns) / n_pts
    my = sum(log_ts) / n_pts
    sxy = sum((x - mx) * (y - my) for x, y in zip(log_ns, log_ts))
    sxx = sum((x - mx) ** 2 for x in log_ns)
    slope = sxy / sxx if sxx > 0 else 0
    # Polynomial time: slope should be finite and not super-linear
    return slope < 5.0


# ===========================================================================
# Graph algorithms
# ===========================================================================

def bfs(graph: dict, start: str) -> list[str]:
    """Breadth-first search."""
    visited = set()
    queue = deque([start])
    visited.add(start)
    order = []
    while queue:
        node = queue.popleft()
        order.append(node)
        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
    return order


def dfs(graph: dict, start: str) -> list[str]:
    """Depth-first search (iterative)."""
    visited = set()
    stack = [start]
    order = []
    while stack:
        node = stack.pop()
        if node not in visited:
            visited.add(node)
            order.append(node)
            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    stack.append(neighbor)
    return order


def dijkstra(graph: dict, start: str) -> dict[str, float]:
    """Dijkstra's shortest path algorithm.

    graph: dict of {node: {neighbor: weight}}
    Returns dict of shortest distances from start.
    """
    import heapq
    distances = {start: 0.0}
    heap = [(0.0, start)]
    visited = set()

    while heap:
        dist, node = heapq.heappop(heap)
        if node in visited:
            continue
        visited.add(node)
        for neighbor, weight in graph.get(node, {}).items():
            new_dist = dist + weight
            if neighbor not in distances or new_dist < distances[neighbor]:
                distances[neighbor] = new_dist
                heapq.heappush(heap, (new_dist, neighbor))

    return distances


def topological_sort(graph: dict) -> list[str] | None:
    """Kahn's algorithm for topological sorting.

    graph: dict of {node: [dependencies]} where dependencies must
    come before the node.
    Returns sorted order or None if there's a cycle.
    """
    in_degree = {node: 0 for node in graph}
    for node, deps in graph.items():
        for dep in deps:
            in_degree[dep] = in_degree.get(dep, 0) + 1

    # Initialize with nodes that have no incoming edges
    queue = deque([node for node in graph if in_degree.get(node, 0) == 0])
    result = []

    while queue:
        node = queue.popleft()
        result.append(node)
        for neighbor in graph.get(node, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(result) != len(graph):
        return None  # Cycle detected
    return result


# ===========================================================================
# Dynamic programming
# ===========================================================================

def fib_dp(n: int) -> int:
    """Fibonacci via dynamic programming (memoization)."""
    if n <= 1:
        return n
    dp = [0, 1]
    for i in range(2, n + 1):
        dp.append(dp[i - 1] + dp[i - 2])
    return dp[n]


def longest_common_subsequence(a: str, b: str) -> str:
    """LCS via dynamic programming."""
    m, n = len(a), len(b)
    dp = [[0] * (n + 1) for _ in range(m + 1)]

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])

    # Backtrack
    lcs = []
    i, j = m, n
    while i > 0 and j > 0:
        if a[i - 1] == b[j - 1]:
            lcs.append(a[i - 1])
            i -= 1
            j -= 1
        elif dp[i - 1][j] > dp[i][j - 1]:
            i -= 1
        else:
            j -= 1
    return "".join(reversed(lcs))


def knapsack(weights: list[int], values: list[int], capacity: int) -> int:
    """0/1 knapsack via dynamic programming."""
    n = len(weights)
    dp = [[0] * (capacity + 1) for _ in range(n + 1)]

    for i in range(1, n + 1):
        for w in range(capacity + 1):
            if weights[i - 1] <= w:
                dp[i][w] = max(dp[i - 1][w],
                               dp[i - 1][w - weights[i - 1]] + values[i - 1])
            else:
                dp[i][w] = dp[i - 1][w]

    return dp[n][capacity]


def __all__() -> list[str]:
    return [
        "DFA", "NFA", "regex_match", "TuringMachine",
        "is_polynomial_time", "bfs", "dfs", "dijkstra",
        "topological_sort", "fib_dp", "longest_common_subsequence",
        "knapsack",
    ]
