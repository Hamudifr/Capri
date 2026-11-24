import unittest

from capri_cognition.ccel import (
    CCELValidationError,
    Example,
    NoConsistentModelError,
    Program,
    normalize_grid,
    predict,
    select_probe,
    synthesize,
)


class GridAndProgramTests(unittest.TestCase):
    def test_rotate_clockwise(self):
        grid = ((1, 2, 3), (4, 5, 6))
        self.assertEqual(
            Program(("rotate_cw",)).apply(grid),
            ((4, 1), (5, 2), (6, 3)),
        )

    def test_flip_horizontal(self):
        self.assertEqual(
            Program(("flip_horizontal",)).apply(((1, 2), (3, 4))),
            ((2, 1), (4, 3)),
        )

    def test_rectangular_and_cell_validation(self):
        with self.assertRaises(CCELValidationError):
            normalize_grid(((1, 2), (3,)))
        with self.assertRaises(CCELValidationError):
            normalize_grid(((True,),))
        with self.assertRaises(CCELValidationError):
            normalize_grid(((10,),))


class SynthesisTests(unittest.TestCase):
    def test_synthesizes_a_rule_from_examples(self):
        examples = (
            Example(((1, 2, 3), (4, 5, 6)), ((4, 1), (5, 2), (6, 3))),
            Example(((7, 8), (9, 1), (2, 3)), ((2, 9, 7), (3, 1, 8))),
        )
        result = synthesize(examples, max_depth=1)
        self.assertEqual(result.depth, 1)
        self.assertIn(Program(("rotate_cw",)), result.programs)
        self.assertEqual(result.examples_seen, 2)

    def test_identity_is_minimum_depth(self):
        result = synthesize((Example(((1, 2),), ((1, 2),)),))
        self.assertEqual(result.depth, 0)
        self.assertEqual(result.programs, (Program(()),))

    def test_ambiguity_is_preserved(self):
        # A one-row grid can be transposed or rotated clockwise to the same
        # column. Both equally simple explanations must remain available.
        result = synthesize(
            (Example(((1, 2),), ((1,), (2,))),), max_depth=1
        )
        self.assertEqual(result.depth, 1)
        self.assertIn(Program(("transpose",)), result.programs)
        self.assertIn(Program(("rotate_cw",)), result.programs)

    def test_no_consistent_model_is_explicit(self):
        with self.assertRaises(NoConsistentModelError):
            synthesize((Example(((1, 2, 3),), ((9, 9),)),), max_depth=1)

    def test_search_budget_is_enforced(self):
        with self.assertRaises(CCELValidationError):
            synthesize((Example(((1,),), ((1,),)),), max_candidates=0)

    def test_probe_selects_maximum_disagreement(self):
        programs = (
            Program(("rotate_cw",)),
            Program(("flip_horizontal",)),
        )
        probes = (
            ((1, 1), (1, 1)),  # Both candidates predict the same result.
            ((1, 2, 3), (4, 5, 6)),  # Predictions differ.
        )
        choice = select_probe(programs, probes)
        self.assertEqual(choice.grid, probes[1])
        self.assertEqual(choice.distinct_outcomes, 2)
        self.assertGreater(choice.entropy_bits, 0)

    def test_predict_returns_all_distinct_outputs(self):
        programs = (Program(("rotate_cw",)), Program(("flip_horizontal",)))
        outputs = predict(programs, ((1, 2, 3), (4, 5, 6)))
        self.assertEqual(len(outputs), 2)

    def test_deterministic_probe_tie_break(self):
        programs = (Program(("rotate_cw",)), Program(("flip_horizontal",)))
        probes = (((1, 2), (3, 4)), ((5, 6), (7, 8)))
        choice = select_probe(programs, probes)
        self.assertEqual(choice.grid, min(probes))


if __name__ == "__main__":
    unittest.main()
