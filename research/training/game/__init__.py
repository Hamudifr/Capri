"""Game theory: zero-sum games, Nash equilibrium, and cooperative games."""

from research.training.game.core import (
    make_zero_sum_game, make_bimatrix_game,
    minimax, minimax_with_moves,
    best_response, strictly_dominated, weakly_dominated, eliminate_dominated,
    nash_equilibrium_2p, mixed_nash_equilibrium_2x2,
    zero_sum_game_value, zero_sum_game_optimal_mixed, fictitious_play_strategy,
    shapley_value, check_correlated_equilibrium,
)
