"""Tests for the quantum computing training module."""

from __future__ import annotations

import math
import unittest

from research.training.quantum import (
    QuantumCircuit,
    amplitude_amplification,
    apply_cnot,
    apply_h,
    apply_x,
    apply_z,
    basis_state,
    bell_state,
    create_bell_pair,
    grover_search,
    max_probability,
    state_fidelity,
    state_normalize,
    state_probability,
    zero_state,
)


class TestStates(unittest.TestCase):
    def test_zero_state(self):
        state = zero_state(2)
        self.assertEqual(len(state), 4)
        self.assertAlmostEqual(abs(state[0]), 1.0)
        self.assertAlmostEqual(abs(state[1]), 0.0)

    def test_basis_state(self):
        state = basis_state(2, 3)
        self.assertEqual(len(state), 4)
        self.assertAlmostEqual(abs(state[3]), 1.0)
        self.assertAlmostEqual(abs(state[0]), 0.0)

    def test_basis_state_out_of_range(self):
        with self.assertRaises(ValueError):
            basis_state(2, 5)

    def test_state_normalize(self):
        state = [3.0, 4.0]
        normalized = state_normalize(state)
        # |3|^2 + |4|^2 = 25, normalized should have norm 1
        norm = math.sqrt(sum(abs(c) ** 2 for c in normalized))
        self.assertAlmostEqual(norm, 1.0)

    def test_state_probability(self):
        state = [1.0 / math.sqrt(2), 1.0 / math.sqrt(2)]
        self.assertAlmostEqual(state_probability(state, 0), 0.5)
        self.assertAlmostEqual(state_probability(state, 1), 0.5)

    def test_max_probability(self):
        state = [1.0 / math.sqrt(2), 1.0]
        idx, prob = max_probability(state)
        self.assertEqual(idx, 1)
        self.assertAlmostEqual(prob, 1.0)


class TestGates(unittest.TestCase):
    def test_apply_x(self):
        # X flips |0> to |1>
        state = zero_state(1)
        result = apply_x(state, 0, 1)
        self.assertAlmostEqual(abs(result[0]), 0.0)
        self.assertAlmostEqual(abs(result[1]), 1.0)

    def test_apply_h(self):
        # H on |0> gives (|0> + |1>) / sqrt(2)
        state = zero_state(1)
        result = apply_h(state, 0, 1)
        self.assertAlmostEqual(abs(result[0]), 1.0 / math.sqrt(2))
        self.assertAlmostEqual(abs(result[1]), 1.0 / math.sqrt(2))

    def test_apply_z(self):
        # Z on |1> gives -|1>
        state = basis_state(1, 1)
        result = apply_z(state, 0, 1)
        self.assertAlmostEqual(abs(result[0]), 0.0)
        self.assertAlmostEqual(abs(result[1]), 1.0)
        self.assertAlmostEqual(result[1].real, -1.0)

    def test_apply_h_twice(self):
        # H * H = I
        state = zero_state(1)
        result = apply_h(state, 0, 1)
        result = apply_h(result, 0, 1)
        self.assertAlmostEqual(abs(result[0]), 1.0)
        self.assertAlmostEqual(abs(result[1]), 0.0)


class TestBellStates(unittest.TestCase):
    def test_bell_state_form(self):
        state = bell_state(2, 0)
        # |00> + |11> / sqrt(2)
        self.assertAlmostEqual(abs(state[0]), 1.0 / math.sqrt(2))
        self.assertAlmostEqual(abs(state[3]), 1.0 / math.sqrt(2))
        self.assertAlmostEqual(abs(state[1]), 0.0)
        self.assertAlmostEqual(abs(state[2]), 0.0)

    def test_create_bell_pair(self):
        state = create_bell_pair()
        # Should be (|00> + |11>) / sqrt(2)
        self.assertAlmostEqual(abs(state[0]), 1.0 / math.sqrt(2))
        self.assertAlmostEqual(abs(state[3]), 1.0 / math.sqrt(2))

    def test_bell_state_normalized(self):
        state = create_bell_pair()
        norm = math.sqrt(sum(abs(c) ** 2 for c in state))
        self.assertAlmostEqual(norm, 1.0)

    def test_bell_states_orthogonal(self):
        b0 = bell_state(2, 0)
        b2 = bell_state(2, 2)
        fid = state_fidelity(b0, b2)
        self.assertAlmostEqual(fid, 0.0, places=5)


class TestQuantumCircuit(unittest.TestCase):
    def test_circuit_h_then_measure(self):
        circuit = QuantumCircuit(1)
        circuit.h(0)
        state = circuit.get_state()
        # Superposition
        self.assertAlmostEqual(abs(state[0]), 1.0 / math.sqrt(2))
        self.assertAlmostEqual(abs(state[1]), 1.0 / math.sqrt(2))

    def test_circuit_x_gate(self):
        circuit = QuantumCircuit(1)
        circuit.x(0)
        state = circuit.get_state()
        self.assertAlmostEqual(abs(state[0]), 0.0)
        self.assertAlmostEqual(abs(state[1]), 1.0)

    def test_circuit_bell_pair(self):
        circuit = QuantumCircuit(2)
        circuit.h(0).cnot(0, 1)
        state = circuit.get_state()
        # Bell state
        self.assertAlmostEqual(abs(state[0]), 1.0 / math.sqrt(2))
        self.assertAlmostEqual(abs(state[3]), 1.0 / math.sqrt(2))

    def test_cnot_flips_target(self):
        state = basis_state(2, 1)  # |01>
        result = apply_cnot(state, 0, 1, 2)
        # Control is 0, so target should NOT flip -> |01>
        self.assertAlmostEqual(abs(result[1]), 1.0)
        self.assertAlmostEqual(abs(result[0]), 0.0)

    def test_cnot_flips_when_control_one(self):
        state = basis_state(2, 3)  # |11>
        result = apply_cnot(state, 0, 1, 2)
        # Control is 1, so target flips -> |10> (index 2)
        self.assertAlmostEqual(abs(result[2]), 1.0)
        self.assertAlmostEqual(abs(result[3]), 0.0)


class TestAmplitudeAmplification(unittest.TestCase):
    def test_grover_search_finds_marked(self):
        # Search for the marked item in a 2-qubit space (4 items)
        state = grover_search(2, marked=3)
        idx, prob = max_probability(state)
        # The marked state should have the highest probability
        self.assertGreater(prob, 0.5)

    def test_grover_search_uniform_superposition(self):
        state = grover_search(2, marked=0)
        idx, prob = max_probability(state)
        self.assertGreater(prob, 0.5)

    def test_amplitude_amplification_boost(self):
        # Start with uniform superposition
        state = zero_state(2)
        for q in range(2):
            state = apply_h(state, q, 2)

        def is_good(i):
            return i == 3

        amplified = amplitude_amplification(state, is_good, 2, iterations=1)
        idx, prob = max_probability(amplified)
        self.assertGreater(prob, 0.3)


class TestFidelity(unittest.TestCase):
    def test_identical_states(self):
        state = zero_state(2)
        self.assertAlmostEqual(state_fidelity(state, state), 1.0)

    def test_orthogonal_states(self):
        s1 = basis_state(1, 0)
        s2 = basis_state(1, 1)
        self.assertAlmostEqual(state_fidelity(s1, s2), 0.0)


if __name__ == "__main__":
    unittest.main()
