import math
import unittest

import numpy as np

from minimax_audit import (
    deterministic_response_information,
    extract_terminal_package,
    disagreement_game,
    solve_row_strategy,
)


class MinimaxAuditTests(unittest.TestCase):
    def test_identity_game_value(self):
        for size in (2, 3, 5, 12):
            solution = solve_row_strategy(np.eye(size))
            self.assertAlmostEqual(solution.value, 1 / size, places=8)

    def test_xor_against_literals_has_half_margin(self):
        target = (0, 1, 1, 0)
        circuits = [
            (0, 0, 0, 0), (1, 1, 1, 1),
            (0, 0, 1, 1), (1, 1, 0, 0),
            (0, 1, 0, 1), (1, 0, 1, 0),
        ]
        game = disagreement_game(target, circuits)
        self.assertAlmostEqual(solve_row_strategy(game).value, 0.5, places=8)

    def test_deterministic_response_information(self):
        m = 8
        info = deterministic_response_information([1 / m] * m, list(range(m)))
        self.assertAlmostEqual(info, math.log(m), places=8)
        self.assertAlmostEqual(
            deterministic_response_information([1 / m] * m, [0] * m), 0.0, places=8
        )

    def test_causal_kpt_game_has_terminal_universal_package(self):
        universe = tuple(range(4))

        def package(stage, history):
            if stage == 0:
                return {0}
            if stage == 1:
                return {1} if history[0] == 1 else {2}
            return set(universe)

        stage, history, terminal = extract_terminal_package(universe, package, 3)
        self.assertEqual(stage, 2)
        self.assertEqual(history, (1, 0))
        self.assertEqual(terminal, set(universe))

    def test_identity_packages_do_not_satisfy_constant_round_kpt_property(self):
        universe = tuple(range(4))

        def identity_package(stage, history):
            return {stage}

        with self.assertRaises(AssertionError):
            extract_terminal_package(universe, identity_package, 3)


if __name__ == "__main__":
    unittest.main()
