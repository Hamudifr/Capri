"""Stochastic processes: Poisson, Brownian motion, Markov, filtering.

Stdlib-only. Pure computation, no external dependencies.

Core concepts:
- Poisson processes: inter-arrival times, counts
- Brownian motion (Wiener process): simulation and properties
- Geometric Brownian motion: stock price modeling
- Continuous-time Markov chains
- Kalman filter (linear Gaussian)
- Particle filter (sequential Monte Carlo)
- Markov chain Monte Carlo (Metropolis-Hastings)
"""

from __future__ import annotations

import math
import random


# ===========================================================================
# Poisson process
# ===========================================================================

def poisson_interarrival(lambda_rate: float, rng: random.Random) -> float:
    """Sample inter-arrival time from a Poisson process.

    Inter-arrival times are exponentially distributed: t = -ln(U) / lambda
    """
    u = rng.random()
    while u == 0:
        u = rng.random()
    return -math.log(u) / lambda_rate


def poisson_count(lambda_rate: float, t: float, rng: random.Random) -> int:
    """Sample the number of events in time interval [0, t].

    Uses the Knuth algorithm for Poisson sampling.
    """
    if lambda_rate * t == 0:
        return 0

    L = math.exp(-lambda_rate * t)
    k = 0
    p = 1.0

    while True:
        k += 1
        p *= rng.random()
        if p <= L:
            return k - 1


def poisson_process_simulate(
    lambda_rate: float, duration: float, rng: random.Random
) -> list[float]:
    """Simulate a Poisson process over [0, duration]. Returns event times."""
    events = []
    t = 0.0
    while True:
        t += poisson_interarrival(lambda_rate, rng)
        if t > duration:
            break
        events.append(t)
    return events


# ===========================================================================
# Brownian motion
# ===========================================================================

def brownian_motion(
    n_steps: int, dt: float, rng: random.Random, start: float = 0.0
) -> list[float]:
    """Simulate a standard Brownian motion (Wiener process).

    Each step: W_{t+dt} = W_t + sqrt(dt) * N(0,1)
    Returns the path including the initial value.
    """
    path = [start]
    current = start
    sqrt_dt = math.sqrt(dt)

    for _ in range(n_steps):
        step = sqrt_dt * rng.gauss(0.0, 1.0)
        current += step
        path.append(current)

    return path


def brownian_motion_quadratic_variation(
    n_steps: int, dt: float, rng: random.Random
) -> float:
    """Estimate the quadratic variation of Brownian motion over [0, T].

    For a standard BM, the quadratic variation over [0, T] is T.
    """
    path = brownian_motion(n_steps, dt, rng)
    qv = sum((path[i + 1] - path[i]) ** 2 for i in range(len(path) - 1))
    return qv


def geometric_brownian_motion(
    S0: float, mu: float, sigma: float, n_steps: int, dt: float, rng: random.Random
) -> list[float]:
    """Simulate geometric Brownian motion (stock price model).

    S_{t+dt} = S_t * exp((mu - sigma^2/2)*dt + sigma*sqrt(dt)*Z)
    Returns the price path including the initial value.
    """
    path = [S0]
    current = S0
    sqrt_dt = math.sqrt(dt)

    for _ in range(n_steps):
        z = rng.gauss(0.0, 1.0)
        current *= math.exp((mu - 0.5 * sigma * sigma) * dt + sigma * sqrt_dt * z)
        path.append(current)

    return path


# ===========================================================================
# Continuous-time Markov chains
# ===========================================================================

class CTMC:
    """Continuous-time Markov chain.

    States with transition rates Q (generator matrix).
    Holding time in state i is exponential(-Q[i][i]).
    Next state is chosen proportionally to Q[i][j] for j != i.
    """

    def __init__(self, generator: list[list[float]]):
        self.Q = generator
        self.n_states = len(generator)

    def simulate(
        self, n_steps: int, rng: random.Random, start: int = 0
    ) -> tuple[list[int], list[float]]:
        """Simulate the CTMC. Returns (states, holding_times)."""
        states = [start]
        holding_times = [0.0]
        current = start

        for _ in range(n_steps):
            # Holding time: exponential(rate = -Q[current][current])
            rate = -self.Q[current][current]
            if rate <= 0:
                break
            t = poisson_interarrival(rate, rng)
            holding_times.append(t)
            holding_times[-1] += holding_times[-2] if len(holding_times) > 1 else 0

            # Next state: proportional to Q[current][j] for j != current
            candidates = []
            weights = []
            for j in range(self.n_states):
                if j != current and self.Q[current][j] > 0:
                    candidates.append(j)
                    weights.append(self.Q[current][j])

            if not candidates:
                break

            total = sum(weights)
            r = rng.random() * total
            acc = 0.0
            for j, w in zip(candidates, weights):
                acc += w
                if acc >= r:
                    current = j
                    break

            states.append(current)

        return states, holding_times

    def stationary_distribution(self, tol: float = 1e-10, max_iter: int = 10000) -> list[float]:
        """Compute stationary distribution of the CTMC.

        Uses the embedded jump chain transition matrix P where
        P[i][j] = Q[i][j] / (-Q[i][i]) for i != j, P[i][i] = 0.
        Then applies power iteration on P, which converges to the
        stationary distribution of the jump chain. The CTMC stationary
        distribution is then proportional to pi_j * (-1/Q[j][j]).
        """
        n = self.n_states
        # Build transition probability matrix of the embedded jump chain
        P = [[0.0] * n for _ in range(n)]
        for i in range(n):
            rate = -self.Q[i][i]
            if rate <= 0:
                continue
            for j in range(n):
                if i != j and self.Q[i][j] > 0:
                    P[i][j] = self.Q[i][j] / rate

        # Power iteration on P
        pi = [1.0 / n] * n
        for _ in range(max_iter):
            new_pi = [0.0] * n
            for j in range(n):
                for i in range(n):
                    new_pi[j] += pi[i] * P[i][j]
            diff = sum(abs(new_pi[i] - pi[i]) for i in range(n))
            pi = new_pi
            if diff < tol:
                break

        # Adjust for holding times: pi_ctmc[j] proportional to pi_jump[j] / rate_j
        # where rate_j = -Q[j][j]
        adjusted = []
        for j in range(n):
            rate = -self.Q[j][j]
            if rate > 0:
                adjusted.append(pi[j] / rate)
            else:
                adjusted.append(0.0)

        total = sum(adjusted)
        if total > 0:
            adjusted = [a / total for a in adjusted]
        return adjusted


# ===========================================================================
# Kalman filter
# ===========================================================================

class KalmanFilter:
    """Linear Gaussian Kalman filter.

    State: x_t (state vector), process model: x_t = F * x_{t-1} + w, w ~ N(0, Q)
    Observation: z_t = H * x_t + v, v ~ N(0, R)
    """

    def __init__(
        self,
        F: list[list[float]],
        H: list[list[float]],
        Q: list[list[float]],
        R: list[list[float]],
        x0: list[float],
        P0: list[list[float]],
    ):
        self.F = F  # state transition
        self.H = H  # observation model
        self.Q = Q  # process noise covariance
        self.R = R  # observation noise covariance
        self.x = list(x0)  # state estimate
        self.P = [list(row) for row in P0]  # state covariance

    def predict(self) -> None:
        """Predict step: x = F*x, P = F*P*F^T + Q."""
        # x = F * x
        self.x = mat_vec_mul(self.F, self.x)
        # P = F * P * F^T + Q
        FP = mat_mul(self.F, self.P)
        Ft = mat_transpose(self.F)
        self.P = mat_mul(FP, Ft)
        self.P = mat_add(self.P, self.Q)

    def update(self, z: list[float]) -> None:
        """Update step with observation z."""
        # y = z - H*x (innovation)
        Hx = mat_vec_mul(self.H, self.x)
        y = [z[i] - Hx[i] for i in range(len(z))]

        # S = H*P*H^T + R (innovation covariance)
        HP = mat_mul(self.H, self.P)
        Ht = mat_transpose(self.H)
        S = mat_mul(HP, Ht)
        S = mat_add(S, self.R)

        # K = P*H^T*S^{-1} (Kalman gain)
        PHt = mat_mul(self.P, Ht)
        K = mat_mul(PHt, mat_inverse(S))

        # x = x + K*y
        Ky = mat_vec_mul(K, y)
        self.x = [self.x[i] + Ky[i] for i in range(len(self.x))]

        # P = (I - K*H)*P
        KH = mat_mul(K, self.H)
        I = mat_identity(len(self.x))
        I_minus_KH = mat_subtract(I, KH)
        self.P = mat_mul(I_minus_KH, self.P)

    def filter(self, observations: list[list[float]]) -> list[list[float]]:
        """Run the full Kalman filter on a sequence of observations.

        Returns the filtered state estimates.
        """
        states = []
        for z in observations:
            self.predict()
            self.update(z)
            states.append(list(self.x))
        return states


# ===========================================================================
# Matrix utilities for Kalman filter
# ===========================================================================

def mat_transpose(m: list[list[float]]) -> list[list[float]]:
    """Transpose a matrix."""
    if not m:
        return []
    return [[m[i][j] for i in range(len(m))] for j in range(len(m[0]))]


def mat_mul(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    """Matrix multiplication."""
    n = len(a)
    m = len(b[0]) if b else 0
    p = len(b)
    return [[sum(a[i][k] * b[k][j] for k in range(p)) for j in range(m)] for i in range(n)]


def mat_vec_mul(m: list[list[float]], v: list[float]) -> list[float]:
    """Matrix-vector multiplication."""
    return [sum(m[i][j] * v[j] for j in range(len(v))) for i in range(len(m))]


def mat_add(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    """Matrix addition."""
    return [[a[i][j] + b[i][j] for j in range(len(a[i]))] for i in range(len(a))]


def mat_subtract(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    """Matrix subtraction."""
    return [[a[i][j] - b[i][j] for j in range(len(a[i]))] for i in range(len(a))]


def mat_identity(n: int) -> list[list[float]]:
    """Identity matrix."""
    return [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]


def mat_inverse(m: list[list[float]]) -> list[list[float]]:
    """Invert a matrix using Gauss-Jordan elimination."""
    n = len(m)
    aug = [list(m[i]) + [1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]

    for col in range(n):
        # Find pivot
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) < 1e-12:
            raise ValueError("Matrix is singular")
        aug[col], aug[pivot] = aug[pivot], aug[col]

        # Normalize pivot row
        pivot_val = aug[col][col]
        aug[col] = [v / pivot_val for v in aug[col]]

        # Eliminate other rows
        for r in range(n):
            if r != col:
                factor = aug[r][col]
                aug[r] = [aug[r][c] - factor * aug[col][c] for c in range(2 * n)]

    return [row[n:] for row in aug]


# ===========================================================================
# Particle filter
# ===========================================================================

class ParticleFilter:
    """Sequential Monte Carlo particle filter for nonlinear systems.

    Models:
    - Transition: x_t = f(x_{t-1}, w) with process noise w
    - Observation: z_t = h(x_t, v) with observation noise v
    """

    def __init__(
        self,
        n_particles: int,
        transition_fn,
        observation_fn,
        process_noise_fn,
        observation_noise_fn,
        rng: random.Random | None = None,
    ):
        self.n_particles = n_particles
        self.transition_fn = transition_fn
        self.observation_fn = observation_fn
        self.process_noise_fn = process_noise_fn
        self.observation_noise_fn = observation_noise_fn
        self.rng = rng or random.Random(42)
        self.particles: list[float] = []
        self.weights: list[float] = []

    def initialize(self, initial_particles: list[float]) -> None:
        """Initialize particles."""
        self.particles = list(initial_particles)
        self.weights = [1.0 / len(self.particles)] * len(self.particles)

    def predict(self) -> None:
        """Propagate particles through the transition model."""
        self.particles = [
            self.transition_fn(x, self.process_noise_fn(self.rng))
            for x in self.particles
        ]

    def update(self, observation: float) -> None:
        """Update particle weights based on observation."""
        weights = []
        total = 0.0
        for x in self.particles:
            predicted = self.observation_fn(x, self.observation_noise_fn(self.rng))
            # Weight proportional to Gaussian likelihood
            residual = observation - predicted
            weights.append(math.exp(-0.5 * residual * residual))
            total += weights[-1]

        if total > 0:
            self.weights = [w / total for w in weights]
        else:
            # If all weights are zero, reset to uniform
            self.weights = [1.0 / len(self.particles)] * len(self.particles)

    def resample(self) -> None:
        """Systematic resampling."""
        n = len(self.particles)
        indices = []
        position = self.rng.random() / n
        cumulative = 0.0
        j = 0

        for i in range(n):
            cumulative += self.weights[j]
            while cumulative > position and j < n - 1:
                j += 1
                cumulative += self.weights[j]
            indices.append(j)
            position += 1.0 / n

        self.particles = [self.particles[i] for i in indices]
        self.weights = [1.0 / n] * n

    def estimate(self) -> float:
        """Compute the weighted mean estimate."""
        return sum(x * w for x, w in zip(self.particles, self.weights))

    def step(self, observation: float) -> float:
        """Full filter step: predict, update, resample, estimate."""
        self.predict()
        self.update(observation)
        self.resample()
        return self.estimate()


# ===========================================================================
# Metropolis-Hastings MCMC
# ===========================================================================

def metropolis_hastings(
    target_density,
    n_samples: int,
    initial: float,
    proposal_std: float = 1.0,
    rng: random.Random | None = None,
    burn_in: int = 0,
) -> list[float]:
    """Metropolis-Hastings MCMC sampling.

    target_density: unnormalized log-density function
    Returns list of samples (after burn-in).
    """
    rng = rng or random.Random(42)
    samples = []
    current = initial
    current_log_prob = target_density(current)

    for i in range(n_samples):
        # Propose
        proposal = current + proposal_std * rng.gauss(0.0, 1.0)
        proposal_log_prob = target_density(proposal)

        # Accept/reject
        log_accept_ratio = proposal_log_prob - current_log_prob
        if math.log(rng.random()) < log_accept_ratio:
            current = proposal
            current_log_prob = proposal_log_prob

        if i >= burn_in:
            samples.append(current)

    return samples
