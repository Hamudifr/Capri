"""Quantum computing: qubits, gates, Bell states, amplitude amplification.

Stdlib-only. Pure computation with complex numbers and linear algebra.

Core concepts:
- Qubit states and Bloch sphere
- Pauli gates (X, Y, Z), Hadamard (H), phase (S, T), CNOT
- Bell states (entanglement)
- Quantum circuits and measurement
- Grover's search / amplitude amplification
"""

from __future__ import annotations

import cmath
import math

# Type alias for complex vectors
Vec = list[complex]

I2 = [[1.0, 0.0], [0.0, 1.0]]
X_GATE = [[0.0, 1.0], [1.0, 0.0]]
Y_GATE = [[0.0, -1j], [1j, 0.0]]
Z_GATE = [[1.0, 0.0], [0.0, -1.0]]
H_GATE = [[1.0 / math.sqrt(2), 1.0 / math.sqrt(2)],
          [1.0 / math.sqrt(2), -1.0 / math.sqrt(2)]]
S_GATE = [[1.0, 0.0], [0.0, 1j]]
T_GATE = [[1.0, 0.0], [0.0, cmath.exp(1j * math.pi / 4)]]


# ===========================================================================
# State vectors and basic operations
# ===========================================================================

def zero_state(n: int) -> Vec:
    """Computational basis state |0...0> with n qubits."""
    return [1.0 + 0j] + [0.0 + 0j] * (2**n - 1)


def basis_state(n: int, index: int) -> Vec:
    """Computational basis state |index> with n qubits."""
    if index < 0 or index >= 2**n:
        raise ValueError(f"Index {index} out of range for {n} qubits")
    state = [0.0 + 0j] * 2**n
    state[index] = 1.0 + 0j
    return state


def state_normalize(state: Vec) -> Vec:
    """Normalize a quantum state vector."""
    norm = math.sqrt(sum(abs(c) ** 2 for c in state))
    if norm < 1e-15:
        raise ValueError("Cannot normalize zero vector")
    return [c / norm for c in state]


def state_probability(state: Vec, index: int) -> float:
    """Probability of measuring the given basis state."""
    if index >= len(state):
        return 0.0
    return abs(state[index]) ** 2


def state_expectation(state: Vec, observable: list[list[complex]]) -> complex:
    """Expectation value <psi|O|psi>."""
    n = len(state)
    result = 0.0 + 0j
    for i in range(n):
        for j in range(n):
            result += state[i].conjugate() * observable[i][j] * state[j]
    return result


def tensor_product_2(a: list[list[complex]], b: list[list[complex]]) -> list[list[complex]]:
    """Kronecker product of two 2x2 matrices."""
    return [
        [a[i][j] * b[k][l] for k in range(2) for l in range(2)]
        for i in range(2)
        for j in range(2)
    ]


def apply_gate(state: Vec, gate: list[list[complex]], qubit: int, n: int) -> Vec:
    """Apply a single-qubit gate to a specific qubit in an n-qubit state.

    The qubit indexing: qubit 0 is the most significant (leftmost).
    For each basis state |i>, the qubit bit b at position pos determines
    the output: gate[0][b] contributes to the state with bit=0, gate[1][b]
    contributes to the state with bit=1.
    """
    dim = 2**n
    pos = n - 1 - qubit  # bit position in the index
    result = [0.0 + 0j] * dim
    for i in range(dim):
        b = (i >> pos) & 1
        for out_bit in range(2):
            amplitude = gate[out_bit][b]
            if amplitude != 0:
                j = (i & ~(1 << pos)) | (out_bit << pos)
                if j < dim:
                    result[j] += amplitude * state[i]
    return result


def apply_cnot(state: Vec, control: int, target: int, n: int) -> Vec:
    """Apply CNOT gate: control qubit flips target qubit."""
    dim = 2**n
    result = [0.0 + 0j] * dim
    for i in range(dim):
        control_bit = (i >> (n - 1 - control)) & 1
        j = i
        if control_bit == 1:
            j = i ^ (1 << (n - 1 - target))
        result[j] += state[i]
    return result


# ===========================================================================
# Single-qubit gates
# ===========================================================================

def apply_x(state: Vec, qubit: int, n: int) -> Vec:
    """Apply Pauli-X (bit-flip) gate."""
    return apply_gate(state, X_GATE, qubit, n)


def apply_y(state: Vec, qubit: int, n: int) -> Vec:
    """Apply Pauli-Y gate."""
    return apply_gate(state, Y_GATE, qubit, n)


def apply_z(state: Vec, qubit: int, n: int) -> Vec:
    """Apply Pauli-Z (phase-flip) gate."""
    return apply_gate(state, Z_GATE, qubit, n)


def apply_h(state: Vec, qubit: int, n: int) -> Vec:
    """Apply Hadamard gate."""
    return apply_gate(state, H_GATE, qubit, n)


def apply_s(state: Vec, qubit: int, n: int) -> Vec:
    """Apply S (phase) gate."""
    return apply_gate(state, S_GATE, qubit, n)


def apply_t(state: Vec, qubit: int, n: int) -> Vec:
    """Apply T gate."""
    return apply_gate(state, T_GATE, qubit, n)


# ===========================================================================
# Bell states
# ===========================================================================

def bell_state(n: int = 2, which: int = 0) -> Vec:
    """Generate one of the four Bell states for 2 qubits.

    which: 0 = |00> + |11>, 1 = |01> + |10>, 2 = |00> - |11>, 3 = |01> - |10>
    """
    if n != 2:
        raise ValueError("Bell states are defined for 2 qubits")
    state = [0.0 + 0j] * 4
    if which == 0:
        state[0] = 1.0 / math.sqrt(2)
        state[3] = 1.0 / math.sqrt(2)
    elif which == 1:
        state[1] = 1.0 / math.sqrt(2)
        state[2] = 1.0 / math.sqrt(2)
    elif which == 2:
        state[0] = 1.0 / math.sqrt(2)
        state[3] = -1.0 / math.sqrt(2)
    elif which == 3:
        state[1] = 1.0 / math.sqrt(2)
        state[2] = -1.0 / math.sqrt(2)
    else:
        raise ValueError(f"Invalid Bell state index: {which}")
    return state


def create_bell_pair() -> Vec:
    """Create a Bell pair (|00> + |11>) / sqrt(2) from |00>."""
    state = zero_state(2)
    state = apply_h(state, 0, 2)
    state = apply_cnot(state, 0, 1, 2)
    return state


# ===========================================================================
# Quantum circuits
# ===========================================================================

class QuantumCircuit:
    """A simple quantum circuit with gate application and measurement."""

    def __init__(self, n_qubits: int):
        self.n = n_qubits
        self.state = zero_state(n_qubits)

    def x(self, qubit: int) -> "QuantumCircuit":
        self.state = apply_x(self.state, qubit, self.n)
        return self

    def y(self, qubit: int) -> "QuantumCircuit":
        self.state = apply_y(self.state, qubit, self.n)
        return self

    def z(self, qubit: int) -> "QuantumCircuit":
        self.state = apply_z(self.state, qubit, self.n)
        return self

    def h(self, qubit: int) -> "QuantumCircuit":
        self.state = apply_h(self.state, qubit, self.n)
        return self

    def s(self, qubit: int) -> "QuantumCircuit":
        self.state = apply_s(self.state, qubit, self.n)
        return self

    def t(self, qubit: int) -> "QuantumCircuit":
        self.state = apply_t(self.state, qubit, self.n)
        return self

    def cnot(self, control: int, target: int) -> "QuantumCircuit":
        self.state = apply_cnot(self.state, control, target, self.n)
        return self

    def measure(self, qubit: int, rng=None) -> int:
        """Measure a single qubit. Returns 0 or 1."""
        # Compute probabilities of the two outcomes
        p0 = 0.0
        p1 = 0.0
        for i in range(len(self.state)):
            bit = (i >> (self.n - 1 - qubit)) & 1
            if bit == 0:
                p0 += abs(self.state[i]) ** 2
            else:
                p1 += abs(self.state[i]) ** 2

        if rng is None:
            # Deterministic: use a simple pseudo-random choice
            import random
            rng = random.Random(0)

        if p0 + p1 <= 0:
            return 0
        return 1 if rng.random() < p1 / (p0 + p1) else 0

    def measure_all(self, rng=None) -> int:
        """Measure all qubits and return the integer result."""
        result = 0
        for q in range(self.n):
            bit = self.measure(q, rng)
            result = (result << 1) | bit
        return result

    def get_state(self) -> Vec:
        """Return the current state vector."""
        return list(self.state)


# ===========================================================================
# Amplitude amplification (Grover's algorithm)
# ===========================================================================

def grover_diffusion_operator(state: Vec, n: int) -> Vec:
    """Grover diffusion operator: 2|s><s| - I, where |s> is the uniform state.

    This reflects about the uniform superposition.
    """
    dim = 2**n
    avg = sum(state) / dim
    # Apply 2|s><s| - I
    result = [-c + 2 * avg for c in state]
    return result


def amplitude_amplification(
    state: Vec,
    is_good,  # Callable[[int], bool]
    n: int,
    iterations: int | None = None,
) -> Vec:
    """Amplitude amplification: boost amplitude of 'good' states.

    If is_good is None, the last basis state |2^n - 1> is marked as good.
    """
    if is_good is None:
        def is_good(i: int) -> bool:
            return i == 2**n - 1

    dim = 2**n

    # Optimal number of iterations: ~ pi/4 * sqrt(N/M)
    good_count = sum(1 for i in range(dim) if is_good(i))
    if good_count == 0:
        return list(state)
    if good_count == dim:
        return list(state)

    if iterations is None:
        iterations = int(math.pi / 4 * math.sqrt(dim / good_count))
        iterations = max(1, min(iterations, dim - 1))

    # Build reflection operator for the good states
    # Oracle: flip sign of good states
    for _ in range(iterations):
        # Oracle: multiply good state amplitudes by -1
        state = [-c if is_good(i) else c for i, c in enumerate(state)]
        # Diffusion
        state = grover_diffusion_operator(state, n)

    return state


def grover_search(n: int, marked: int, iterations: int | None = None) -> Vec:
    """Run Grover's search algorithm for a single marked item.

    Returns the final state vector after amplitude amplification.
    """
    state = zero_state(n)
    # Apply Hadamard to all qubits to create uniform superposition
    for q in range(n):
        state = apply_h(state, q, n)

    def is_good(i: int) -> bool:
        return i == marked

    return amplitude_amplification(state, is_good, n, iterations)


# ===========================================================================
# Utility
# ===========================================================================

def state_fidelity(a: Vec, b: Vec) -> float:
    """Fidelity between two quantum states: |<a|b>|^2."""
    inner = sum(ac.conjugate() * bc for ac, bc in zip(a, b))
    return abs(inner) ** 2


def max_probability(state: Vec) -> tuple[int, float]:
    """Return (index, probability) of the most likely measurement outcome."""
    best_idx = 0
    best_prob = 0.0
    for i, c in enumerate(state):
        p = abs(c) ** 2
        if p > best_prob:
            best_prob = p
            best_idx = i
    return best_idx, best_prob
