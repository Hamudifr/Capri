"""Tests for the formal verification training module."""

from __future__ import annotations

import unittest

from research.training.verification import (
    GCLProgram,
    GuardedCommand,
    HoareTriple,
    KripkeStructure,
    ProofSystem,
    Sequent,
    assignment_wp,
    bounded_model_check,
    bfs_reachable,
    check_inductive_invariant,
    check_safety_property,
    hoare_assignment,
    lt_check_always,
    lt_check_eventually,
    lt_check_until,
    sequential_wp,
)


class TestKripkeStructure(unittest.TestCase):
    def test_bfs_reachable(self):
        k = KripkeStructure(
            states=[0, 1, 2, 3],
            transitions={0: [1, 2], 1: [3], 2: [3], 3: []},
            labels={s: set() for s in [0, 1, 2, 3]},
            init_states=[0],
        )
        reachable = bfs_reachable(k)
        self.assertEqual(reachable, {0, 1, 2, 3})

    def test_bfs_partial(self):
        k = KripkeStructure(
            states=[0, 1, 2],
            transitions={0: [1], 1: [], 2: []},
            labels={s: set() for s in [0, 1, 2]},
            init_states=[0],
        )
        reachable = bfs_reachable(k)
        self.assertEqual(reachable, {0, 1})

    def test_has_label(self):
        k = KripkeStructure(
            states=[0, 1],
            transitions={0: [1], 1: []},
            labels={0: {"p"}, 1: set()},
            init_states=[0],
        )
        self.assertTrue(k.has_label(0, "p"))
        self.assertFalse(k.has_label(1, "p"))

    def test_is_terminal(self):
        k = KripkeStructure(
            states=[0, 1],
            transitions={0: [1], 1: []},
            labels={s: set() for s in [0, 1]},
            init_states=[0],
        )
        self.assertFalse(k.is_terminal(0))
        self.assertTrue(k.is_terminal(1))


class TestLTLModelChecking(unittest.TestCase):
    def _make_simple_k(self):
        return KripkeStructure(
            states=["s0", "s1", "s2"],
            transitions={"s0": ["s1"], "s1": ["s2"], "s2": []},
            labels={"s0": {"p"}, "s1": {"p"}, "s2": {"p"}},
            init_states=["s0"],
        )

    def test_lt_check_always_true(self):
        k = self._make_simple_k()
        self.assertTrue(lt_check_always(k, "p"))

    def test_lt_check_always_false(self):
        k = KripkeStructure(
            states=["s0", "s1"],
            transitions={"s0": ["s1"], "s1": []},
            labels={"s0": {"p"}, "s1": set()},
            init_states=["s0"],
        )
        self.assertFalse(lt_check_always(k, "p"))

    def test_lt_check_eventually_true(self):
        k = KripkeStructure(
            states=["s0", "s1", "s2"],
            transitions={"s0": ["s1"], "s1": ["s2"], "s2": []},
            labels={"s0": set(), "s1": set(), "s2": {"p"}},
            init_states=["s0"],
        )
        self.assertTrue(lt_check_eventually(k, "p"))

    def test_lt_check_eventually_false(self):
        k = KripkeStructure(
            states=["s0", "s1"],
            transitions={"s0": ["s1"], "s1": []},
            labels={"s0": set(), "s1": set()},
            init_states=["s0"],
        )
        self.assertFalse(lt_check_eventually(k, "p"))

    def test_lt_check_until_true(self):
        k = KripkeStructure(
            states=["s0", "s1", "s2"],
            transitions={"s0": ["s1"], "s1": ["s2"], "s2": []},
            labels={"s0": {"a"}, "s1": {"a", "b"}, "s2": {"b"}},
            init_states=["s0"],
        )
        self.assertTrue(lt_check_until(k, "a", "b"))

    def test_lt_check_until_false(self):
        k = KripkeStructure(
            states=["s0", "s1"],
            transitions={"s0": ["s1"], "s1": []},
            labels={"s0": set(), "s1": set()},
            init_states=["s0"],
        )
        self.assertFalse(lt_check_until(k, "a", "b"))


class TestBoundedModelChecking(unittest.TestCase):
    def test_bmc_finds_prop(self):
        k = KripkeStructure(
            states=["s0", "s1", "s2"],
            transitions={"s0": ["s1"], "s1": ["s2"], "s2": []},
            labels={"s0": set(), "s1": set(), "s2": {"p"}},
            init_states=["s0"],
        )
        self.assertTrue(bounded_model_check(k, "p", bound=3))

    def test_bmc_too_small_bound(self):
        k = KripkeStructure(
            states=["s0", "s1", "s2"],
            transitions={"s0": ["s1"], "s1": ["s2"], "s2": []},
            labels={"s0": set(), "s1": set(), "s2": {"p"}},
            init_states=["s0"],
        )
        self.assertFalse(bounded_model_check(k, "p", bound=1))


class TestHoareLogic(unittest.TestCase):
    def test_hoare_assignment_simple(self):
        # {True} x = 5 {x == 5}
        state = {"x": 0}
        result = hoare_assignment(state, "x", lambda s: 5, lambda s: True, lambda s: s["x"] == 5)
        self.assertTrue(result)

    def test_hoare_assignment_precondition_fails(self):
        # {x > 10} x = 5 {x == 5} -- precondition fails
        state = {"x": 3}
        result = hoare_assignment(
            state, "x", lambda s: 5,
            lambda s: s["x"] > 10,
            lambda s: s["x"] == 5,
        )
        self.assertFalse(result)

    def test_hoare_triple_verify(self):
        triple = HoareTriple(
            lambda s: s["x"] == 0,
            lambda s: s.update({"x": 10}),
            lambda s: s["x"] == 10,
        )
        state = {"x": 0}
        self.assertTrue(triple.verify(state))

    def test_weakest_precondition_assignment(self):
        # x = 5; postcondition: x == 5
        # Weakest precondition should be True
        wp = assignment_wp("x", lambda s: 5, lambda s: s["x"] == 5)
        self.assertTrue(wp({"x": 0}))

    def test_weakest_precondition_fails(self):
        # x = 5; postcondition: x == 10
        wp = assignment_wp("x", lambda s: 5, lambda s: s["x"] == 10)
        self.assertFalse(wp({"x": 0}))

    def test_sequential_wp(self):
        # x = 5; y = x + 1; postcondition: y == 6
        cmd1 = lambda s: s.update({"x": 5})
        wp2 = assignment_wp("y", lambda s: s["x"] + 1, lambda s: s["y"] == 6)
        wp_all = sequential_wp(cmd1, wp2)
        self.assertTrue(wp_all({"x": 0, "y": 0}))


class TestGCL(unittest.TestCase):
    def test_gcl_execute_simple(self):
        cmd = GuardedCommand(
            lambda s: s["x"] < 10,
            lambda s: s.update({"x": s["x"] + 1}),
        )
        prog = GCLProgram([cmd])
        state = {"x": 5}
        result = prog.execute(state)
        self.assertEqual(result["x"], 6)

    def test_gcl_guard_fails(self):
        cmd = GuardedCommand(
            lambda s: s["x"] < 5,
            lambda s: s.update({"x": s["x"] + 1}),
        )
        prog = GCLProgram([cmd])
        state = {"x": 10}
        result = prog.execute(state)
        self.assertEqual(result["x"], 10)

    def test_gcl_wp(self):
        cmd = GuardedCommand(
            lambda s: s["x"] > 0,
            lambda s: s.update({"y": s["x"] * 2}),
        )
        prog = GCLProgram([cmd])
        post = lambda s: s["y"] == 10
        wp = prog.weakest_precondition(post)
        # x > 0 and x*2 == 10 -> x == 5
        self.assertTrue(wp({"x": 5, "y": 0}))
        self.assertFalse(wp({"x": 3, "y": 0}))


class TestProofSystem(unittest.TestCase):
    def test_axiom(self):
        seq = Sequent(frozenset({"A"}), frozenset({"A"}))
        self.assertTrue(seq.is_axiom())

    def test_non_axiom(self):
        seq = Sequent(frozenset({"A"}), frozenset({"B"}))
        self.assertFalse(seq.is_axiom())

    def test_prove_simple(self):
        ps = ProofSystem()
        # A |- A is an axiom
        seq = Sequent(frozenset({"A"}), frozenset({"A"}))
        self.assertTrue(ps.prove(seq))

    def test_prove_weakening(self):
        ps = ProofSystem()
        # A, B |- A  (weakening from A |- A)
        seq = Sequent(frozenset({"A", "B"}), frozenset({"A"}))
        # A |- A is an axiom, then weakening adds B
        self.assertTrue(ps.prove(seq))

    def test_and_right_rule(self):
        ps = ProofSystem()
        # and_right: from |- A and |- B, infer |- A ∧ B
        premise1 = Sequent(frozenset(), frozenset({"A"}))
        premise2 = Sequent(frozenset(), frozenset({"B"}))
        conclusion = ps.apply_rule("and_right", [premise1, premise2])
        self.assertEqual(conclusion.succedents, frozenset({"A∧B"}))
        self.assertEqual(conclusion.antecedents, frozenset())


class TestInvariants(unittest.TestCase):
    def test_check_safety_property(self):
        k = KripkeStructure(
            states=["s0", "s1", "s2"],
            transitions={"s0": ["s1"], "s1": ["s2"], "s2": []},
            labels={s: set() for s in ["s0", "s1", "s2"]},
            init_states=["s0"],
        )
        # Invariant: state index < 3
        inv = lambda s: int(s[1]) < 3
        self.assertTrue(check_safety_property(k, inv))

    def test_check_safety_property_fails(self):
        k = KripkeStructure(
            states=["s0", "s1", "s2"],
            transitions={"s0": ["s1"], "s1": ["s2"], "s2": []},
            labels={s: set() for s in ["s0", "s1", "s2"]},
            init_states=["s0"],
        )
        # Invariant fails at s2
        inv = lambda s: int(s[1]) < 2
        self.assertFalse(check_safety_property(k, inv))

    def test_check_inductive_invariant(self):
        k = KripkeStructure(
            states=["s0", "s1"],
            transitions={"s0": ["s1"], "s1": ["s1"]},
            labels={s: set() for s in ["s0", "s1"]},
            init_states=["s0"],
        )
        # Invariant: state in {"s0", "s1"} -- always true, inductive
        inv = lambda s: s in ("s0", "s1")
        self.assertTrue(check_inductive_invariant(k, inv))

    def test_check_inductive_invariant_fails(self):
        k = KripkeStructure(
            states=["s0", "s1"],
            transitions={"s0": ["s1"], "s1": []},
            labels={s: set() for s in ["s0", "s1"]},
            init_states=["s0"],
        )
        # Invariant: s0 -> holds initially, but s1 violates it
        inv = lambda s: s == "s0"
        self.assertFalse(check_inductive_invariant(k, inv))


if __name__ == "__main__":
    unittest.main()
