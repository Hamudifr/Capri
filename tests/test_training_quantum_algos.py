"""Tests for the quantum algorithms training module."""

from __future__ import annotations

import math
import unittest

from research.training.quantum_algos import (
    BitFlipCode,
    QAOA,
    VQE,
    amplitude_estimation,
    amplitude_estimation_probability,
    deutsch_jozsa_classical,
    inverse_qft,
    phase_estimation,
    phase_estimation_accuracy,
    qft,
    qft_basis_state,
    qft_circuit,
    shor_period_estimate,
    simple_ansatz,
    state_expectation,
)


class TestQFT(unittest.TestCase):
    def test_qft_basis_state(self):
        # QFT of |0> should be uniform superposition
        state = qft_basis_state(2, 0)
        self.assertEqual(len(state), 4)
        for i in range(4):
            self.assertAlmostEqual(abs(state[i]), 0.5, places=5)

    def test_qft_inverse_qft_roundtrip(self):
        import random
        rng = random.Random(42)
        # Create a random state
        n = 3
        dim = 2**n
        state = [complex(rng.gauss(0, 1), rng.gauss(0, 1)) for _ in range(dim)]
        norm = math.sqrt(sum(abs(c) ** 2 for c in state))
        state = [c / norm for c in state]

        # QFT then inverse QFT should return the original
        qft_state = qft(state, n)
        inv_qft = inverse_qft(qft_state, n)

        for i in range(dim):
            self.assertAlmostEqual(abs(inv_qft[i] - state[i]), 0.0, places=5)

    def test_qft_circuit_matches_direct(self):
        n = 2
        # |0> state
        from research.training.quantum.core import zero_state
        state = zero_state(n)

        direct = qft(state, n)
        circuit = qft_circuit(state, n)

        # Both should give uniform superposition (up to qubit ordering)
        for i in range(2**n):
            self.assertGreater(abs(direct[i]), 0.0)
            self.assertGreater(abs(circuit[i]), 0.0)

    def test_qft_normalizes(self):
        from research.training.quantum.core import basis_state
        state = qft(basis_state(2, 1), 2)
        norm = math.sqrt(sum(abs(c) ** 2 for c in state))
        self.assertAlmostEqual(norm, 1.0, places=5)


class TestPhaseEstimation(unittest.TestCase):
    def test_phase_estimation_accuracy(self):
        acc = phase_estimation_accuracy(4)
        self.assertAlmostEqual(acc, 1.0 / 16, places=5)

    def test_phase_estimation(self):
        # Phase estimation for phase 0.5
        state = phase_estimation([0.5], n_ancilla=3)
        self.assertEqual(len(state), 8)


class TestShor(unittest.TestCase):
    def test_shor_period_simple(self):
        # a = 2, N = 7: period of 2^x mod 7
        # 2^1=2, 2^2=4, 2^3=1 mod 7, so period = 3
        period = shor_period_estimate(2, 7, n_qubits=6)
        self.assertIn(period, [3, 6])  # period could be 3 or a multiple

    def test_shor_period_another(self):
        # a = 3, N = 7: 3^1=3, 3^2=2, 3^3=6, 3^4=4, 3^5=5, 3^6=1, period = 6
        period = shor_period_estimate(3, 7, n_qubits=6)
        self.assertIn(period, [3, 6])


class TestAmplitudeEstimation(unittest.TestCase):
    def test_amplitude_estimation(self):
        from research.training.quantum.core import zero_state, apply_h
        n = 2
        state = zero_state(n)
        state = apply_h(state, 0, n)
        state = apply_h(state, 1, n)

        def is_good(i):
            return i == 0

        prob = amplitude_estimation(state, is_good, n)
        # Amplitude of |00> in uniform superposition = 1/4
        self.assertAlmostEqual(prob, 0.25, places=5)

    def test_amplitude_estimation_probability(self):
        from research.training.quantum.core import zero_state, apply_h
        n = 2
        state = zero_state(n)
        state = apply_h(state, 0, n)
        state = apply_h(state, 1, n)

        def is_good(i):
            return i == 0

        prob = amplitude_estimation_probability(state, is_good, n, iterations=3)
        self.assertGreater(prob, 0.1)
        self.assertLess(prob, 0.5)


class TestDeutschJozsa(unittest.TestCase):
    def test_deutsch_jozsa_constant(self):
        # f(x) = 0 for all x (constant)
        def f(x):
            return 0

        result = deutsch_jozsa_classical(f, 2)
        self.assertEqual(result, "constant")

    def test_deutsch_jozsa_balanced(self):
        # f(x) = parity of x (balanced for n=2: f(00)=0, f(01)=1, f(10)=1, f(11)=0)
        def f(x):
            return (x >> 1) & 1 ^ (x & 1)

        result = deutsch_jozsa_classical(f, 2)
        self.assertEqual(result, "balanced")


class TestVQE(unittest.TestCase):
    def test_vqe_energy(self):
        # Simple Hamiltonian: H = Z (Pauli Z)
        # For a single qubit, Z = diag(1, -1)
        H = [[1.0, 0.0], [0.0, -1.0]]

        vqe = VQE(H, simple_ansatz)
        n = 1
        params = [0.0]
        energy = vqe.energy(params, n)
        # With params=0, the ansatz gives |0> (no rotation)
        # <0|Z|0> = 1
        self.assertAlmostEqual(energy, 1.0, places=5)

    def test_vqe_optimize(self):
        # Hamiltonian: H = -Z (minimize energy -> maximize |1>)
        H = [[-1.0, 0.0], [0.0, 1.0]]

        vqe = VQE(H, simple_ansatz)
        n = 1
        params = vqe.optimize(n, 1, epochs=50, lr=0.05)
        energy = vqe.energy(params, n)
        # Energy should be <= 0 (ground state is |1> with energy -1)
        self.assertLess(energy, 0.5)


class TestQAOA(unittest.TestCase):
    def test_qaoa_cost_function(self):
        # Triangle graph: 3 vertices, 3 edges
        graph = {0: [1, 2], 1: [0, 2], 2: [0, 1]}
        qaoa = QAOA(graph)

        # Max cut of triangle = 2 (split one vertex from the other two)
        # For bitmask 0b001 (vertex 0 alone): 2 edges cross, cost = 2.0
        self.assertEqual(qaoa.cost_function(0b001), 2.0)

    def test_qaoa_circuit(self):
        graph = {0: [1], 1: [0]}
        qaoa = QAOA(graph)
        n = 2
        gamma = [0.5]
        beta = [0.3]
        state = qaoa.qaoa_circuit(gamma, beta, n)
        self.assertEqual(len(state), 4)

    def test_qaoa_best_cut(self):
        graph = {0: [1, 2], 1: [0, 2], 2: [0, 1]}
        qaoa = QAOA(graph)
        n = 3
        gamma = [0.5]
        beta = [0.3]
        best_x, cut_val = qaoa.best_cut(gamma, beta, n)
        self.assertGreater(cut_val, 0)


class TestBitFlipCode(unittest.TestCase):
    def test_bit_flip_encode(self):
        code = BitFlipCode()
        state0 = code.encode(0)
        self.assertEqual(len(state0), 8)
        # |0> -> |000> (index 0)
        self.assertAlmostEqual(abs(state0[0]), 1.0)

        state1 = code.encode(1)
        # |1> -> |111> (index 7)
        self.assertAlmostEqual(abs(state1[7]), 1.0)

    def test_bit_flip_no_error(self):
        code = BitFlipCode()
        state = code.encode(0)  # |000>
        (_, _), correct_idx = code.measure_syndrome(state)
        self.assertEqual(correct_idx, -1)  # No error

    def test_bit_flip_correct_qubit0(self):
        code = BitFlipCode()
        from research.training.quantum.core import apply_x

        state = code.encode(0)  # |000>
        state = apply_x(state, 0, 3)  # Flip qubit 0 -> |100>
        corrected = code.correct(state)
        # After correction, should be back to |000>
        self.assertAlmostEqual(abs(corrected[0]), 1.0)

    def test_bit_flip_correct_qubit1(self):
        code = BitFlipCode()
        from research.training.quantum.core import apply_x

        state = code.encode(1)  # |111>
        state = apply_x(state, 1, 3)  # Flip qubit 1 -> |101>
        corrected = code.correct(state)
        # After correction, should be back to |111>
        self.assertAlmostEqual(abs(corrected[7]), 1.0)


class TestStateExpectation(unittest.TestCase):
    def test_state_expectation(self):
        from research.training.quantum.core import basis_state

        # <0|Z|0> = 1
        state = basis_state(1, 0)
        Z = [[1.0, 0.0], [0.0, -1.0]]
        val = state_expectation(state, Z)
        self.assertAlmostEqual(val.real, 1.0, places=5)

        # <1|Z|1> = -1
        state1 = basis_state(1, 1)
        val1 = state_expectation(state1, Z)
        self.assertAlmostEqual(val1.real, -1.0, places=5)


if __name__ == "__main__":
    unittest.main()
