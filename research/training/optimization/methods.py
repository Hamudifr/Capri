"""Optimization study modules.

Implements optimization algorithms: line search, conjugate gradient,
simulated annealing, genetic algorithms, and learning-rate schedules.
Pure stdlib, no dependencies.

Topics covered:
- Convexity detection (conceptual)
- Line search: golden section, backtracking
- Newton's method for root finding
- Conjugate gradient method
- Simulated annealing
- Genetic algorithm
- Learning rate schedules: step decay, exponential decay, cosine annealing, warmup
- Gradient-free methods: Nelder-Mead (simplified)
"""

from __future__ import annotations

import math
import random


# ===========================================================================
# Root finding
# ===========================================================================

def bisection_root(f, a: float, b: float, tol: float = 1e-10,
                   max_iters: int = 1000) -> float:
    """Bisection method for root finding."""
    if f(a) * f(b) > 0:
        raise ValueError("f(a) and f(b) must have opposite signs")

    for _ in range(max_iters):
        mid = (a + b) / 2
        if abs(f(mid)) < tol or (b - a) / 2 < tol:
            return mid
        if f(a) * f(mid) < 0:
            b = mid
        else:
            a = mid
    return (a + b) / 2


def newtons_method(f, f_prime, x0: float, tol: float = 1e-10,
                   max_iters: int = 1000) -> float:
    """Newton's method for root finding."""
    x = x0
    for _ in range(max_iters):
        fx = f(x)
        fpx = f_prime(x)
        if abs(fpx) < 1e-15:
            break
        x_new = x - fx / fpx
        if abs(x_new - x) < tol:
            return x_new
        x = x_new
    return x


def secant_method(f, x0: float, x1: float, tol: float = 1e-10,
                  max_iters: int = 1000) -> float:
    """Secant method for root finding."""
    for _ in range(max_iters):
        fx0, fx1 = f(x0), f(x1)
        denom = fx1 - fx0
        if abs(denom) < 1e-15:
            break
        x_new = x1 - fx1 * (x1 - x0) / denom
        if abs(x_new - x1) < tol:
            return x_new
        x0, x1 = x1, x_new
    return x1


# ===========================================================================
# Line search
# ===========================================================================

def golden_section_search(f, a: float, b: float, tol: float = 1e-10) -> float:
    """Golden section search for minimum of a unimodal function."""
    gr = (math.sqrt(5) - 1) / 2  # ~0.618

    c = b - gr * (b - a)
    d = a + gr * (b - a)

    while abs(b - a) > tol:
        if f(c) < f(d):
            b = d
        else:
            a = c
        c = b - gr * (b - a)
        d = a + gr * (b - a)

    return (a + b) / 2


def backtracking_line_search(f, grad_f, x: list[float], direction: list[float],
                             c: float = 0.5, rho: float = 0.5,
                             max_iters: int = 30) -> float:
    """Backtracking line search along a direction."""
    # Compute slope
    slope = sum(g * d for g, d in zip(grad_f(x), direction))
    if slope >= 0:
        return 0.0  # Not a descent direction

    alpha = 1.0
    for _ in range(max_iters):
        if f([xi + alpha * d for xi, d in zip(x, direction)]) <= \
           f(x) + c * alpha * slope:
            return alpha
        alpha *= rho
    return alpha


# ===========================================================================
# Conjugate gradient
# ===========================================================================

def conjugate_gradient(A: list[list[float]], b: list[float],
                       x0: list[float] | None = None,
                       tol: float = 1e-10, max_iters: int = 1000) -> list[float]:
    """Conjugate gradient method for solving Ax = b.

    Assumes A is symmetric positive definite.
    """
    n = len(b)
    if x0 is None:
        x = [0.0] * n
    else:
        x = x0[:]

    def mat_vec(m: list[list[float]], v: list[float]) -> list[float]:
        return [sum(m[i][j] * v[j] for j in range(len(v))) for i in range(len(m))]

    def dot(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b))

    r = [b[i] - mat_vec(A, x)[i] for i in range(n)]
    p = r[:]
    rsold = dot(r, r)

    for _ in range(max_iters):
        Ap = mat_vec(A, p)
        alpha = rsold / dot(p, Ap) if dot(p, Ap) != 0 else 0
        x = [xi + alpha * pi for xi, pi in zip(x, p)]
        r = [r[i] - alpha * Ap[i] for i in range(n)]
        rsnew = dot(r, r)
        if math.sqrt(rsnew) < tol:
            break
        beta = rsnew / rsold if rsold != 0 else 0
        p = [r[i] + beta * p[i] for i in range(n)]
        rsold = rsnew

    return x


# ===========================================================================
# Simulated annealing
# ===========================================================================

def simulated_annealing(f, x0: list[float], initial_temp: float = 100.0,
                       cooling_rate: float = 0.95, min_temp: float = 1e-8,
                       max_iters: int = 10000, rng: random.Random | None = None) -> tuple[list[float], float]:
    """Simulated annealing optimizer.

    Returns (best_x, best_value).
    """
    if rng is None:
        rng = random.Random(42)

    def neighbors(x: list[float]) -> list[list[float]]:
        return [[xi + rng.gauss(0, 1.0) for xi in x]]

    x = x0[:]
    fx = f(x)
    best_x = x[:]
    best_fx = fx
    temperature = initial_temp

    for _ in range(max_iters):
        if temperature < min_temp:
            break
        for neighbor in neighbors(x):
            f_neighbor = f(neighbor)
            if f_neighbor < fx:
                x = neighbor
                fx = f_neighbor
                if fx < best_fx:
                    best_x = x[:]
                    best_fx = fx
            else:
                # Accept with probability exp(-delta / T)
                delta = f_neighbor - fx
                if rng.random() < math.exp(-delta / temperature):
                    x = neighbor
                    fx = f_neighbor
        temperature *= cooling_rate

    return best_x, best_fx


# ===========================================================================
# Genetic algorithm
# ===========================================================================

def genetic_algorithm(f, n_vars: int, population_size: int = 50,
                      generations: int = 100, mutation_rate: float = 0.1,
                      crossover_rate: float = 0.8,
                      bounds: tuple[float, float] = (-10.0, 10.0),
                      rng: random.Random | None = None) -> tuple[list[float], float]:
    """Simple genetic algorithm for continuous optimization.

    Returns (best_solution, best_value).
    """
    if rng is None:
        rng = random.Random(42)

    a, b = bounds

    def random_individual() -> list[float]:
        return [rng.uniform(a, b) for _ in range(n_vars)]

    def crossover(p1: list[float], p2: list[float]) -> list[float]:
        if rng.random() > crossover_rate:
            return p1[:]
        point = rng.randint(0, n_vars - 1)
        return p1[:point] + p2[point:]

    def mutate(ind: list[float]) -> list[float]:
        for i in range(n_vars):
            if rng.random() < mutation_rate:
                ind[i] += rng.gauss(0, (b - a) * 0.1)
                ind[i] = max(a, min(b, ind[i]))
        return ind

    population = [random_individual() for _ in range(population_size)]
    scored = [(f(ind), ind) for ind in population]
    scored.sort(key=lambda x: x[0])

    for _ in range(generations):
        new_population = []
        # Elitism: keep best 2
        new_population.extend(ind for _, ind in scored[:2])

        while len(new_population) < population_size:
            # Tournament selection
            idx1 = rng.randint(0, len(scored) - 1)
            idx2 = rng.randint(0, len(scored) - 1)
            parent1 = scored[idx1][1] if scored[idx1][0] <= scored[idx2][0] else scored[idx2][1]
            parent2 = scored[idx2][1] if scored[idx2][0] <= scored[idx1][0] else scored[idx1][1]

            child = crossover(parent1, parent2)
            child = mutate(child)
            new_population.append(child)

        population = new_population
        scored = [(f(ind), ind) for ind in population]
        scored.sort(key=lambda x: x[0])

    best_val, best_ind = scored[0]
    return best_ind, best_val


# ===========================================================================
# Learning rate schedules
# ===========================================================================

def step_decay(initial_lr: float, milestones: list[int], decay_rate: float,
               current_step: int) -> float:
    """Step decay: multiply LR by decay_rate at each milestone."""
    lr = initial_lr
    for milestone in milestones:
        if current_step >= milestone:
            lr *= decay_rate
    return lr


def exponential_decay(initial_lr: float, decay_rate: float,
                      current_step: int) -> float:
    """Exponential decay: LR = initial_lr * decay_rate^step."""
    return initial_lr * (decay_rate ** current_step)


def cosine_annealing(initial_lr: float, current_step: int,
                     max_steps: int) -> float:
    """Cosine annealing: LR = min_lr + 0.5*(max_lr-min_lr)*(1+cos(pi*T/T_max))."""
    if max_steps == 0:
        return 0.0
    return 0.5 * initial_lr * (1 + math.cos(math.pi * current_step / max_steps))


def linear_warmup(initial_lr: float, current_step: int, warmup_steps: int) -> float:
    """Linear warmup: LR increases linearly from 0 to initial_lr."""
    if warmup_steps == 0 or current_step >= warmup_steps:
        return initial_lr
    return initial_lr * current_step / warmup_steps


def cosine_with_warmup(initial_lr: float, current_step: int, max_steps: int,
                       warmup_steps: int) -> float:
    """Cosine annealing with linear warmup."""
    if current_step < warmup_steps:
        return linear_warmup(initial_lr, current_step, warmup_steps)
    return cosine_annealing(initial_lr, current_step - warmup_steps,
                            max_steps - warmup_steps)


# ===========================================================================
# Nelder-Mead (simplified)
# ===========================================================================

def nelder_mead(f, x0: list[float], max_iters: int = 1000,
                tol: float = 1e-8) -> list[float]:
    """Simplified Nelder-Mead simplex optimization."""
    n = len(x0)
    # Create initial simplex
    simplex = [x0[:]]
    for i in range(n):
        point = x0[:]
        point[i] += 1.0
        simplex.append(point)

    def evaluate_simplex(s: list[list[float]]) -> list[float]:
        return [f(p) for p in s]

    alpha = 1.0
    gamma = 2.0
    rho = 0.5
    sigma = 0.5

    for _ in range(max_iters):
        values = evaluate_simplex(simplex)
        order = sorted(range(len(values)), key=lambda i: values[i])
        simplex = [simplex[i] for i in order]
        values = [values[i] for i in order]

        # Check convergence
        if max(abs(v - values[0]) for v in values) < tol:
            return simplex[0]

        # Compute centroid (excluding worst, which is last after sorting)
        centroid = [0.0] * n
        for i in range(n):
            for j in range(n):
                centroid[j] += simplex[i][j] / n

        # Reflection
        reflect = [centroid[j] + alpha * (centroid[j] - simplex[-1][j]) for j in range(n)]
        f_reflect = f(reflect)

        if values[0] <= f_reflect < values[-2]:
            simplex[-1] = reflect
        elif f_reflect < values[0]:
            # Expansion
            expand = [centroid[j] + gamma * (reflect[j] - centroid[j]) for j in range(n)]
            f_expand = f(expand)
            if f_expand < f_reflect:
                simplex[-1] = expand
            else:
                simplex[-1] = reflect
        else:
            # Contraction
            if f_reflect < values[-1]:
                # Outside contraction
                contr = [centroid[j] + rho * (reflect[j] - centroid[j]) for j in range(n)]
            else:
                # Inside contraction
                contr = [centroid[j] - rho * (centroid[j] - simplex[-1][j]) for j in range(n)]
            f_contr = f(contr)
            if f_contr < min(f_reflect, values[-1]):
                simplex[-1] = contr
            else:
                # Shrink
                for i in range(1, n + 1):
                    simplex[i] = [simplex[0][j] + sigma * (simplex[i][j] - simplex[0][j])
                                  for j in range(n)]

    return simplex[0]


def __all__() -> list[str]:
    return [
        "bisection_root", "newtons_method", "secant_method",
        "golden_section_search", "backtracking_line_search",
        "conjugate_gradient", "simulated_annealing", "genetic_algorithm",
        "step_decay", "exponential_decay", "cosine_annealing",
        "linear_warmup", "cosine_with_warmup", "nelder_mead",
    ]
