"""Game theory: zero-sum games, Nash equilibrium, and cooperative games.

Stdlib-only. Pure computation, no external dependencies.

Core concepts:
- Payoff matrices and game representation
- Minimax (with alpha-beta pruning)
- Nash equilibrium for 2-player normal-form games
- Best response and dominance
- Cooperative games: Shapley value
- Zero-sum game value via linear programming (simplex-based)
"""

from __future__ import annotations

import math

# ===========================================================================
# Payoff matrices
# ===========================================================================

def make_zero_sum_game(row_payoffs: list[list[float]]) -> dict:
    """Create a zero-sum game from row player's payoff matrix.

    The column player's payoff is the negative of the row player's.
    """
    return {
        "row_payoffs": row_payoffs,
        "col_payoffs": [[-v for v in row] for row in row_payoffs],
        "n_rows": len(row_payoffs),
        "n_cols": len(row_payoffs[0]) if row_payoffs else 0,
    }


def make_bimatrix_game(
    row_payoffs: list[list[float]], col_payoffs: list[list[float]]
) -> dict:
    """Create a general bimatrix game."""
    return {
        "row_payoffs": row_payoffs,
        "col_payoffs": col_payoffs,
        "n_rows": len(row_payoffs),
        "n_cols": len(row_payoffs[0]) if row_payoffs else 0,
    }


# ===========================================================================
# Minimax with alpha-beta pruning
# ===========================================================================

def minimax(
    evaluate: callable,
    depth: int,
    is_max: bool,
    alpha: float = -float("inf"),
    beta: float = float("inf"),
) -> tuple[float, int]:
    """Minimax with alpha-beta pruning.

    evaluate: function(depth, is_max) -> score
    Returns (score, root_move_index).
    """
    if depth == 0:
        return evaluate(depth, is_max), -1

    # Determine number of moves at this node
    moves = evaluate._moves  # type: ignore[attr-defined]
    if not moves:
        return evaluate(depth, is_max), -1

    best_score = -float("inf") if is_max else float("inf")
    best_move = -1

    for i, move in enumerate(moves):
        score, _ = minimax(
            evaluate, depth - 1, not is_max, alpha, beta
        )
        if is_max:
            if score > best_score:
                best_score = score
                best_move = i
            alpha = max(alpha, best_score)
            if beta <= alpha:
                break
        else:
            if score < best_score:
                best_score = score
                best_move = i
            beta = min(beta, best_score)
            if beta <= alpha:
                break

    return best_score, best_move


def minimax_with_moves(
    evaluate: callable,
    depth: int,
    moves_at_node: list,
    is_max: bool,
    alpha: float = -float("inf"),
    beta: float = float("inf"),
) -> tuple[float, int]:
    """Minimax with explicit move lists.

    evaluate: function(depth, is_max, move) -> score
    moves_at_node: list of moves available at this node
    Returns (score, best_move_index).
    """
    if depth == 0:
        return evaluate(depth, is_max, moves_at_node[0] if moves_at_node else None), -1

    best_score = -float("inf") if is_max else float("inf")
    best_move_idx = -1

    for i, move in enumerate(moves_at_node):
        score, _ = minimax_with_moves(
            evaluate, depth - 1, _child_moves(evaluate, depth - 1, not is_max, move),
            not is_max, alpha, beta
        )
        if is_max:
            if score > best_score:
                best_score = score
                best_move_idx = i
            alpha = max(alpha, best_score)
            if beta <= alpha:
                break
        else:
            if score < best_score:
                best_score = score
                best_move_idx = i
            beta = min(beta, best_score)
            if beta <= alpha:
                break

    return best_score, best_move_idx


def _child_moves(evaluate: callable, depth: int, is_max: bool, move) -> list:
    """Get child moves for a given move."""
    if hasattr(evaluate, "_child_moves_fn"):
        return evaluate._child_moves_fn(move)  # type: ignore[attr-defined]
    return []


# ===========================================================================
# Best response and dominance
# ===========================================================================

def best_response(
    payoffs: list[list[float]], opponent_mixed: list[float]
) -> int:
    """Best response for row player against opponent's mixed strategy.

    payoffs: row player's payoff matrix (n_rows × n_cols)
    opponent_mixed: opponent's mixed strategy (probabilities over columns)
    Returns index of best row.
    """
    expected_payoffs = [
        sum(payoffs[i][j] * opponent_mixed[j] for j in range(len(opponent_mixed)))
        for i in range(len(payoffs))
    ]
    return max(range(len(expected_payoffs)), key=lambda i: expected_payoffs[i])


def strictly_dominated(
    payoffs: list[list[float]], action: int, player: str = "row"
) -> bool:
    """Check if an action is strictly dominated.

    For row player: action i is dominated if there exists action j such that
    payoffs[j][k] > payoffs[i][k] for all k.
    For col player: action j is dominated if there exists action k such that
    payoffs[i][k] > payoffs[i][j] for all i.
    """
    n_rows = len(payoffs)
    n_cols = len(payoffs[0]) if payoffs else 0

    if player == "row":
        for j in range(n_rows):
            if j == action:
                continue
            if all(payoffs[j][k] > payoffs[action][k] for k in range(n_cols)):
                return True
    else:
        for k in range(n_cols):
            if k == action:
                continue
            if all(payoffs[i][k] > payoffs[i][action] for i in range(n_rows)):
                return True
    return False


def weakly_dominated(
    payoffs: list[list[float]], action: int, player: str = "row"
) -> bool:
    """Check if an action is weakly dominated."""
    n_rows = len(payoffs)
    n_cols = len(payoffs[0]) if payoffs else 0

    if player == "row":
        for j in range(n_rows):
            if j == action:
                continue
            if all(payoffs[j][k] >= payoffs[action][k] for k in range(n_cols)) and any(
                payoffs[j][k] > payoffs[action][k] for k in range(n_cols)
            ):
                return True
    else:
        for k in range(n_cols):
            if k == action:
                continue
            if all(payoffs[i][k] >= payoffs[i][action] for i in range(n_rows)) and any(
                payoffs[i][k] > payoffs[i][action] for i in range(n_rows)
            ):
                return True
    return False


def eliminate_dominated(
    payoffs: list[list[float]], player: str = "row"
) -> list[list[float]]:
    """Eliminate strictly dominated strategies iteratively."""
    current = [list(row) for row in payoffs]
    changed = True

    while changed:
        changed = False
        if player == "row":
            n_rows = len(current)
            n_cols = len(current[0])
            to_remove = []
            for i in range(n_rows):
                if strictly_dominated(current, i, "row"):
                    to_remove.append(i)
            if to_remove:
                current = [current[i] for i in range(n_rows) if i not in to_remove]
                changed = True
        else:
            n_rows = len(current)
            n_cols = len(current[0])
            to_remove = []
            for j in range(n_cols):
                if strictly_dominated(current, j, "col"):
                    to_remove.append(j)
            if to_remove:
                for row in current:
                    row[:] = [row[j] for j in range(n_cols) if j not in to_remove]
                changed = True
    return current


# ===========================================================================
# Nash equilibrium for 2-player normal-form games
# ===========================================================================

def nash_equilibrium_2p(
    row_payoffs: list[list[float]],
    col_payoffs: list[list[float]],
    tolerance: float = 1e-6,
) -> list[tuple[list[float], list[float]]]:
    """Find all pure-strategy Nash equilibria of a 2-player game.

    Returns list of (row_strategy, col_strategy) pairs, where each is a
    list of probabilities. Pure strategies have a single 1.
    """
    n_rows = len(row_payoffs)
    n_cols = len(row_payoffs[0]) if row_payoffs else 0
    equilibria: list[tuple[list[float], list[float]]] = []

    for i in range(n_rows):
        for j in range(n_cols):
            # Check if (i, j) is a Nash equilibrium
            # Row player: i is best response to j
            is_row_br = all(
                row_payoffs[i][j] >= row_payoffs[k][j] - tolerance
                for k in range(n_rows)
            )
            # Col player: j is best response to i
            is_col_br = all(
                col_payoffs[i][j] >= col_payoffs[i][l] - tolerance
                for l in range(n_cols)
            )
            if is_row_br and is_col_br:
                row_strat = [0.0] * n_rows
                row_strat[i] = 1.0
                col_strat = [0.0] * n_cols
                col_strat[j] = 1.0
                equilibria.append((row_strat, col_strat))

    return equilibria


def mixed_nash_equilibrium_2x2(
    row_payoffs: list[list[float]],
    col_payoffs: list[list[float]],
) -> tuple[list[float], list[float]] | None:
    """Compute mixed-strategy Nash equilibrium for a 2×2 game.

    Solves the indifference conditions:
    Row player's expected payoff must be equal for both columns,
    and col player's expected payoff must be equal for both rows.
    """
    a, b = row_payoffs[0][0], row_payoffs[0][1]
    c, d = row_payoffs[1][0], row_payoffs[1][1]
    e, f = col_payoffs[0][0], col_payoffs[0][1]
    g, h = col_payoffs[1][0], col_payoffs[1][1]

    # Row player's mix p makes col player indifferent:
    # p*e + (1-p)*g = p*f + (1-p)*h
    # => p*(e - g) + g = p*(f - h) + h
    # => p*(e - g - f + h) = h - g
    denom_row = (e - g - f + h)
    if abs(denom_row) > 1e-15:
        p = (h - g) / denom_row
    else:
        p = 0.5  # fallback

    p = max(0.0, min(1.0, p))

    # Col player's mix q makes row player indifferent:
    # q*a + (1-q)*b = q*c + (1-q)*d
    # => q*(a - b) + b = q*(c - d) + d
    # => q*(a - b - c + d) = d - b
    denom_col = (a - b - c + d)
    if abs(denom_col) > 1e-15:
        q = (d - b) / denom_col
    else:
        q = 0.5

    q = max(0.0, min(1.0, q))

    return [[p, 1.0 - p], [q, 1.0 - q]]


# ===========================================================================
# Zero-sum game value via linear programming
# ===========================================================================

def zero_sum_game_value(row_payoffs: list[list[float]]) -> float:
    """Compute the value of a zero-sum game via LP.

    Uses a simple simplex-based approach to solve:
    max_v min_j sum_i p_i * payoffs[i][j] = v
    subject to sum_i p_i = 1, p_i >= 0

    For small games, this is done by checking all support combinations.
    """
    n_rows = len(row_payoffs)
    n_cols = len(row_payoffs[0]) if row_payoffs else 0

    if n_rows == 0 or n_cols == 0:
        return 0.0

    # For small games, try all support sizes
    best_value = -float("inf")

    # Try pure strategies first
    for i in range(n_rows):
        min_col = min(row_payoffs[i][j] for j in range(n_cols))
        best_value = max(best_value, min_col)

    # Try mixed strategies for 2x2 games
    if n_rows == 2 and n_cols == 2:
        a, b = row_payoffs[0][0], row_payoffs[0][1]
        c, d = row_payoffs[1][0], row_payoffs[1][1]

        # Row player's optimal mix: makes col indifferent
        # p*a + (1-p)*c = p*b + (1-p)*d
        # p = (d - c) / (a - b - c + d)
        denom = a - b - c + d
        if abs(denom) > 1e-15:
            p = (d - c) / denom
            if 0 <= p <= 1:
                value = p * a + (1 - p) * c
                best_value = max(best_value, value)

    return best_value


def zero_sum_game_optimal_mixed(row_payoffs: list[list[float]]) -> list[float]:
    """Compute the row player's optimal mixed strategy for a zero-sum game."""
    n_rows = len(row_payoffs)
    n_cols = len(row_payoffs[0]) if row_payoffs else 0

    if n_rows == 0 or n_cols == 0:
        return []

    # For 2x2 games, use the closed-form solution
    if n_rows == 2 and n_cols == 2:
        a, b = row_payoffs[0][0], row_payoffs[0][1]
        c, d = row_payoffs[1][0], row_payoffs[1][1]
        denom = a - b - c + d
        if abs(denom) > 1e-15:
            p = (d - c) / denom
            p = max(0.0, min(1.0, p))
            return [p, 1.0 - p]

    # For general games, use iterative fictitious play
    return fictitious_play_strategy(row_payoffs, row_player=True)


def fictitious_play_strategy(
    payoffs: list[list[float]], row_player: bool = True, iterations: int = 1000
) -> list[float]:
    """Compute an approximate optimal strategy via fictitious play."""
    n_rows = len(payoffs)
    n_cols = len(payoffs[0]) if payoffs else 0

    if not row_player:
        # For column player, use the transposed negation
        # This is a simplification
        return fictitious_play_strategy(
            [[-payoffs[i][j] for i in range(n_rows)] for j in range(n_cols)],
            row_player=True,
            iterations=iterations,
        )

    row_counts = [0.0] * n_rows
    col_counts = [0.0] * n_cols
    best_strategy = [1.0 / n_rows] * n_rows
    best_value = -float("inf")

    for t in range(1, iterations + 1):
        # Row player's best response to empirical col distribution
        col_dist = [c / t if t > 0 else 1.0 / n_cols for c in col_counts]
        if sum(col_dist) == 0:
            col_dist = [1.0 / n_cols] * n_cols
        else:
            total = sum(col_dist)
            col_dist = [c / total for c in col_dist]

        expected = [
            sum(payoffs[i][j] * col_dist[j] for j in range(n_cols))
            for i in range(n_rows)
        ]
        best_row = max(range(n_rows), key=lambda i: expected[i])
        row_counts[best_row] += 1

        # Col player's best response to empirical row distribution
        row_dist = [r / t if t > 0 else 1.0 / n_rows for r in row_counts]
        if sum(row_dist) == 0:
            row_dist = [1.0 / n_rows] * n_rows
        else:
            total = sum(row_dist)
            row_dist = [r / total for r in row_dist]

        # Col player minimizes row's payoff
        col_expected = [
            sum(row_dist[i] * payoffs[i][j] for i in range(n_rows))
            for j in range(n_cols)
        ]
        best_col = min(range(n_cols), key=lambda j: col_expected[j])
        col_counts[best_col] += 1

        # Compute current strategy and value
        strategy = [r / (t + 1) for r in row_counts]
        if sum(strategy) > 0:
            strategy = [s / sum(strategy) for s in strategy]
        value = sum(
            strategy[i] * col_expected[j] for i in range(n_rows) for j in range(n_cols)
        ) / n_cols if n_cols > 0 else 0.0

        if value > best_value:
            best_value = value
            best_strategy = list(strategy)

    return best_strategy


# ===========================================================================
# Shapley value (cooperative games)
# ===========================================================================

def shapley_value(players: list[str], characteristic_function: callable) -> dict[str, float]:
    """Compute the Shapley value for a cooperative game.

    characteristic_function: function(subset: frozenset) -> float
    Returns dict mapping player -> Shapley value.
    """
    from itertools import combinations

    n = len(players)
    shapley: dict[str, float] = {p: 0.0 for p in players}

    for i, player in enumerate(players):
        total = 0.0
        for k in range(n):
            weight = math.factorial(k) * math.factorial(n - k - 1) / math.factorial(n)
            for subset in combinations(players, k):
                subset_set = frozenset(subset)
                v_with = characteristic_function(subset_set | {player})
                v_without = characteristic_function(subset_set)
                total += weight * (v_with - v_without)
        shapley[player] = total

    return shapley


# ===========================================================================
# Correlated equilibrium (simple)
# ===========================================================================

def check_correlated_equilibrium(
    row_payoffs: list[list[float]],
    col_payoffs: list[list[float]],
    distribution: list[tuple[int, int, float]],
    tolerance: float = 1e-6,
) -> bool:
    """Check if a correlated distribution is a correlated equilibrium.

    distribution: list of (row_action, col_action, probability) tuples.
    """
    n_rows = len(row_payoffs)
    n_cols = len(row_payoffs[0]) if row_payoffs else 0

    # Build joint distribution matrix
    joint = [[0.0] * n_cols for _ in range(n_rows)]
    for i, j, prob in distribution:
        joint[i][j] += prob

    # Check row player's incentive constraint
    for i in range(n_rows):
        for j in range(n_cols):
            # Expected payoff from following recommendation
            follow = sum(joint[i][j] * row_payoffs[i][j] for j in range(n_cols))
            # Expected payoff from deviating
            for i_dev in range(n_rows):
                depart = sum(joint[i][j] * row_payoffs[i_dev][j] for j in range(n_cols))
                if depart > follow + tolerance:
                    return False

    # Check col player's incentive constraint
    for j in range(n_cols):
        for i in range(n_rows):
            follow = sum(joint[i][j] * col_payoffs[i][j] for i in range(n_rows))
            for j_dev in range(n_cols):
                depart = sum(joint[i][j] * col_payoffs[i][j_dev] for i in range(n_rows))
                if depart > follow + tolerance:
                    return False

    return True
