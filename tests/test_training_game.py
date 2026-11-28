"""Tests for the game theory training module."""

import unittest

from research.training.game.core import (
    make_zero_sum_game, make_bimatrix_game,
    best_response, strictly_dominated, weakly_dominated, eliminate_dominated,
    nash_equilibrium_2p, mixed_nash_equilibrium_2x2,
    zero_sum_game_value, zero_sum_game_optimal_mixed, fictitious_play_strategy,
    shapley_value, check_correlated_equilibrium,
)


class TestPayoffMatrices(unittest.TestCase):

    def test_zero_sum(self):
        game = make_zero_sum_game([[1, -1], [-1, 1]])
        self.assertEqual(game["n_rows"], 2)
        self.assertEqual(game["n_cols"], 2)
        self.assertEqual(game["col_payoffs"][0][0], -1)

    def test_bimatrix(self):
        game = make_bimatrix_game([[1, 0], [0, 1]], [[0, 1], [1, 0]])
        self.assertEqual(game["n_rows"], 2)
        self.assertEqual(game["col_payoffs"][0][1], 1)


class TestBestResponse(unittest.TestCase):

    def test_basic(self):
        payoffs = [[3, 1], [2, 4]]
        # Opponent plays col 0 (prob 1.0)
        br = best_response(payoffs, [1.0, 0.0])
        # Row 0 gets 3, row 1 gets 2 -> row 0 is best
        self.assertEqual(br, 0)

    def test_mixed(self):
        payoffs = [[3, 1], [2, 4]]
        # Opponent plays 50/50
        br = best_response(payoffs, [0.5, 0.5])
        # Row 0: 3*0.5 + 1*0.5 = 2, Row 1: 2*0.5 + 4*0.5 = 3 -> row 1
        self.assertEqual(br, 1)


class TestDominance(unittest.TestCase):

    def test_strictly_dominated_row(self):
        payoffs = [[1, 1], [2, 2]]
        self.assertTrue(strictly_dominated(payoffs, 0, "row"))

    def test_not_dominated(self):
        payoffs = [[1, 2], [2, 1]]
        self.assertFalse(strictly_dominated(payoffs, 0, "row"))

    def test_weakly_dominated(self):
        payoffs = [[1, 2], [1, 3]]
        self.assertTrue(weakly_dominated(payoffs, 0, "row"))

    def test_eliminate(self):
        payoffs = [[1, 1], [2, 2], [3, 3]]
        result = eliminate_dominated(payoffs, "row")
        # Should remove rows 0 and 1 (dominated by 2)
        self.assertEqual(len(result), 1)


class TestNashEquilibrium(unittest.TestCase):

    def test_matching_pennies(self):
        # Row:  1 -1 / -1 1
        # Col: -1 1 /  1 -1
        game = make_bimatrix_game([[1, -1], [-1, 1]], [[-1, 1], [1, -1]])
        eq = nash_equilibrium_2p(game["row_payoffs"], game["col_payoffs"])
        # Matching pennies has no pure NE
        self.assertEqual(len(eq), 0)

    def test_coordination_game(self):
        # Both want to coordinate
        game = make_bimatrix_game([[1, 0], [0, 1]], [[1, 0], [0, 1]])
        eq = nash_equilibrium_2p(game["row_payoffs"], game["col_payoffs"])
        self.assertEqual(len(eq), 2)  # (0,0) and (1,1)

    def test_dominant_strategy(self):
        # Row has dominant strategy 0
        game = make_bimatrix_game([[3, 1], [2, 0]], [[1, 0], [0, 1]])
        eq = nash_equilibrium_2p(game["row_payoffs"], game["col_payoffs"])
        # (0, 0) should be a NE
        found = any(r[0] > 0 and c[0] > 0 for r, c in eq)
        self.assertTrue(found)

    def test_mixed_2x2_matching_pennies(self):
        # Matching pennies - mixed NE at (0.5, 0.5)
        row_p = [[1, -1], [-1, 1]]
        col_p = [[-1, 1], [1, -1]]
        result = mixed_nash_equilibrium_2x2(row_p, col_p)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result[0][0], 0.5, places=2)
        self.assertAlmostEqual(result[1][0], 0.5, places=2)


class TestZeroSumGame(unittest.TestCase):

    def test_matching_pennies_value(self):
        row_p = [[1, -1], [-1, 1]]
        value = zero_sum_game_value(row_p)
        # Value of matching pennies is 0
        self.assertAlmostEqual(value, 0.0, places=2)

    def test_simple_dominance(self):
        # Row always wins with row 0
        row_p = [[5, 3], [1, 0]]
        value = zero_sum_game_value(row_p)
        self.assertGreater(value, 0)

    def test_optimal_mixed_2x2(self):
        row_p = [[3, 1], [1, 3]]
        strategy = zero_sum_game_optimal_mixed(row_p)
        self.assertEqual(len(strategy), 2)
        total = sum(strategy)
        self.assertAlmostEqual(total, 1.0, places=2)

    def test_fictitious_play(self):
        row_p = [[3, 1], [1, 3]]
        strategy = fictitious_play_strategy(row_p, row_player=True, iterations=500)
        total = sum(strategy)
        self.assertAlmostEqual(total, 1.0, places=2)
        self.assertGreater(strategy[0], 0)
        self.assertGreater(strategy[1], 0)


class TestShapleyValue(unittest.TestCase):

    def test_two_players(self):
        # Simple characteristic function: v({a})=1, v({b})=2, v({a,b})=5
        def v(subset):
            n = len(subset)
            if n == 0:
                return 0
            if n == 1:
                return 2 if "b" in subset else 1
            return 5

        shapley = shapley_value(["a", "b"], v)
        # Total surplus = 5 - 0 = 5
        total = sum(shapley.values())
        self.assertAlmostEqual(total, 5.0, places=5)

    def test_three_players(self):
        def v(subset):
            n = len(subset)
            if n == 0:
                return 0
            if n == 1:
                return 1
            if n == 2:
                return 3
            return 6

        shapley = shapley_value(["a", "b", "c"], v)
        total = sum(shapley.values())
        self.assertAlmostEqual(total, 6.0, places=5)
        # Symmetric game -> equal Shapley values
        self.assertAlmostEqual(shapley["a"], shapley["b"], places=5)
        self.assertAlmostEqual(shapley["b"], shapley["c"], places=5)


class TestCorrelatedEquilibrium(unittest.TestCase):

    def test_coordination_ce(self):
        # Coordination game: both play (0,0) or (1,1)
        row_p = [[1, 0], [0, 1]]
        col_p = [[1, 0], [0, 1]]
        # Distribution: 0.5 on (0,0), 0.5 on (1,1)
        dist = [(0, 0, 0.5), (1, 1, 0.5)]
        self.assertTrue(check_correlated_equilibrium(row_p, col_p, dist))

    def test_deviation_detected(self):
        # Distribution that allows profitable deviation
        row_p = [[3, 0], [0, 1]]
        col_p = [[3, 0], [0, 1]]
        # Row recommended to play 0, but can deviate to 1 for higher payoff
        # Actually (0,0) gives 3 to both, (1,1) gives 1. Let's try dist on (1,0)
        dist = [(1, 0, 1.0)]
        # Row gets 0 from (1,0), but deviating to row 0 gives 3
        self.assertFalse(check_correlated_equilibrium(row_p, col_p, dist))


if __name__ == "__main__":
    unittest.main()
