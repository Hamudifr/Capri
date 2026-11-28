"""Reinforcement learning: MDPs, value iteration, policy iteration, Q-learning.

Stdlib-only. Pure computation, no external dependencies.

Core concepts:
- Markov decision processes (MDPs): states, actions, rewards, transitions
- Value iteration and policy iteration for planning
- Model-free learning: Q-learning, SARSA, epsilon-greedy policy
- Policy gradient (REINFORCE) for continuous action spaces
"""

from __future__ import annotations

import math
import random

# A transition: (next_state, reward, done)
Transition = tuple[object, float, bool]


# ===========================================================================
# Epsilon-greedy policy
# ===========================================================================

def epsilon_greedy(q_values: dict, state: object, epsilon: float, rng: random.Random) -> object:
    """Select an action using epsilon-greedy policy.

    q_values: dict mapping state -> dict mapping action -> Q-value
    """
    if state not in q_values or not q_values[state]:
        # No Q-values for this state yet - return a random action from
        # any known state, or None if completely empty
        if not q_values:
            return None
        for actions in q_values.values():
            if actions:
                return rng.choice(list(actions.keys()))
        return None
    action_values = q_values[state]
    if rng.random() < epsilon:
        return rng.choice(list(action_values.keys()))
    # Tie-breaking among best actions
    best = max(action_values.values())
    best_actions = [a for a, v in action_values.items() if abs(v - best) < 1e-12]
    return rng.choice(best_actions)


def softmax_policy(
    q_values: dict, state: object, temperature: float
) -> dict:
    """Softmax policy: returns probability distribution over actions.

    temperature > 0 controls exploration. Low temp -> greedy, high -> uniform.
    """
    if state not in q_values:
        return {}
    actions = list(q_values[state].keys())
    values = [q_values[state][a] / temperature for a in actions]
    max_v = max(values)
    exps = [math.exp(v - max_v) for v in values]
    total = sum(exps)
    return {a: e / total for a, e in zip(actions, exps)}


# ===========================================================================
# Q-learning
# ===========================================================================

def q_learning_update(
    q: dict,
    state: object,
    action: object,
    reward: float,
    next_state: object,
    next_actions: list,
    alpha: float,
    gamma: float,
    done: bool,
) -> None:
    """One-step Q-learning update.

    If next_state has no Q-values yet, treat it as 0.
    """
    if state not in q:
        q[state] = {}
    if next_state not in q:
        q[next_state] = {}

    current_q = q[state].get(action, 0.0)
    if done or not next_actions:
        target = reward
    else:
        next_q_values = q[next_state].values() if q[next_state] else [0.0]
        best_next = max(next_q_values)
        target = reward + gamma * best_next
    q[state][action] = current_q + alpha * (target - current_q)


def sarsa_update(
    q: dict,
    state: object,
    action: object,
    reward: float,
    next_state: object,
    next_action: object,
    alpha: float,
    gamma: float,
    done: bool,
) -> None:
    """One-step SARSA update (on-policy)."""
    if state not in q:
        q[state] = {}
    if next_state not in q:
        q[next_state] = {}

    current_q = q[state].get(action, 0.0)
    if done:
        target = reward
    else:
        next_q = q[next_state].get(next_action, 0.0)
        target = reward + gamma * next_q
    q[state][action] = current_q + alpha * (target - current_q)


# ===========================================================================
# Value iteration (planning with known model)
# ===========================================================================

def value_iteration(
    states: list,
    actions: dict,
    transitions: dict,
    rewards: dict,
    gamma: float = 0.9,
    theta: float = 1e-6,
    max_iter: int = 10000,
) -> dict:
    """Value iteration for an MDP with known transition model.

    transitions: dict mapping (state, action) -> list of (next_state, prob)
    rewards: dict mapping (state, action, next_state) -> reward
    """
    v: dict = {s: 0.0 for s in states}

    for _ in range(max_iter):
        delta = 0.0
        new_v = dict(v)
        for s in states:
            best = -float("inf")
            for a in actions.get(s, []):
                exp_val = 0.0
                for (ns, prob) in transitions.get((s, a), []):
                    r = rewards.get((s, a, ns), 0.0)
                    exp_val += prob * (r + gamma * v.get(ns, 0.0))
                if exp_val > best:
                    best = exp_val
            if best == -float("inf"):
                best = 0.0
            new_v[s] = best
            delta = max(delta, abs(best - v[s]))
        v = new_v
        if delta < theta:
            break
    return v


def extract_policy(
    states: list,
    actions: dict,
    transitions: dict,
    rewards: dict,
    v: dict,
    gamma: float = 0.9,
) -> dict:
    """Extract the greedy policy from a value function."""
    policy: dict = {}
    for s in states:
        best_action = None
        best_val = -float("inf")
        for a in actions.get(s, []):
            exp_val = 0.0
            for (ns, prob) in transitions.get((s, a), []):
                r = rewards.get((s, a, ns), 0.0)
                exp_val += prob * (r + gamma * v.get(ns, 0.0))
            if exp_val > best_val:
                best_val = exp_val
                best_action = a
        policy[s] = best_action
    return policy


def policy_iteration(
    states: list,
    actions: dict,
    transitions: dict,
    rewards: dict,
    gamma: float = 0.9,
    max_iter: int = 100,
) -> tuple[dict, dict]:
    """Policy iteration: alternates policy evaluation and improvement."""
    policy = {}
    for s in states:
        if actions.get(s):
            policy[s] = actions[s][0]
        else:
            policy[s] = None

    for _ in range(max_iter):
        # Policy evaluation
        v = {s: 0.0 for s in states}
        for _ in range(1000):
            delta = 0.0
            for s in states:
                a = policy.get(s)
                if a is None or not actions.get(s):
                    continue
                exp_val = 0.0
                for (ns, prob) in transitions.get((s, a), []):
                    r = rewards.get((s, a, ns), 0.0)
                    exp_val += prob * (r + gamma * v.get(ns, 0.0))
                delta = max(delta, abs(exp_val - v[s]))
                v[s] = exp_val
            if delta < 1e-10:
                break

        # Policy improvement
        stable = True
        for s in states:
            if not actions.get(s):
                continue
            best_action = None
            best_val = -float("inf")
            for a in actions.get(s, []):
                exp_val = 0.0
                for (ns, prob) in transitions.get((s, a), []):
                    r = rewards.get((s, a, ns), 0.0)
                    exp_val += prob * (r + gamma * v.get(ns, 0.0))
                if exp_val > best_val:
                    best_val = exp_val
                    best_action = a
            if best_action != policy[s]:
                policy[s] = best_action
                stable = False
        if stable:
            break

    return policy, v


# ===========================================================================
# REINFORCE (policy gradient)
# ===========================================================================

def reinforce_update(
    policy_params: dict,
    states: list,
    actions: list,
    rewards: list,
    gamma: float = 0.9,
    alpha: float = 0.01,
) -> dict:
    """One-episode REINFORCE (Monte Carlo policy gradient) update.

    policy_params: dict mapping state -> (theta0, theta1) for
        softmax over 2 actions: P(a0) = sigmoid(theta0), P(a1) = 1 - P(a0)
    Returns updated policy_params.

    This is a simplified binary-action softmax policy gradient.
    """
    new_params = {s: list(v) for s, v in policy_params.items()}

    # Compute returns
    G = 0.0
    returns = [0.0] * len(rewards)
    for t in range(len(rewards) - 1, -1, -1):
        G = rewards[t] + gamma * G
        returns[t] = G

    # Policy gradient update
    for t, s in enumerate(states):
        if s not in new_params:
            continue
        a = actions[t]
        theta = new_params[s]
        # Log-probability of action a under softmax
        z = theta[0]
        # sigmoid
        p0 = 1.0 / (1.0 + math.exp(-z))
        grad = (a - p0) * returns[t]
        theta[0] += alpha * grad
        # theta[1] would be the logit for action 1; in binary case it's -theta[0]
    return new_params


# ===========================================================================
# Simple gridworld environment
# ===========================================================================

class GridWorld:
    """A simple 4x4 gridworld MDP (the classic RL test environment).

    States: (row, col) tuples, 0-3.
    Actions: 0=up, 1=down, 2=left, 3=right
    Goal: (0, 3) gives +1 reward and terminates.
    Pit: (1, 1) gives -1 reward and terminates.
    """

    ACTIONS = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    SIZE = 4

    def __init__(self, rng: random.Random | None = None):
        self.rng = rng or random.Random(42)
        self.state = (3, 0)

    def reset(self) -> tuple:
        self.state = (3, 0)
        return self.state

    def step(self, action: int) -> tuple:
        dr, dc = self.ACTIONS[action]
        r, c = self.state
        nr = max(0, min(self.SIZE - 1, r + dr))
        nc = max(0, min(self.SIZE - 1, c + dc))
        self.state = (nr, nc)

        if self.state == (0, 3):
            return self.state, 1.0, True
        if self.state == (1, 1):
            return self.state, -1.0, True
        return self.state, 0.0, False

    def get_possible_actions(self) -> list[int]:
        return list(range(4))


def train_q_learning(
    env: GridWorld,
    episodes: int = 500,
    alpha: float = 0.5,
    gamma: float = 0.9,
    epsilon: float = 0.1,
    seed: int = 42,
) -> dict:
    """Train a Q-learning agent on a GridWorld. Returns learned Q-table."""
    rng = random.Random(seed)
    q: dict = {}
    env.rng = rng

    for _ in range(episodes):
        state = env.reset()
        done = False
        steps = 0
        while not done and steps < 200:
            action = epsilon_greedy(q, state, epsilon, rng)
            if action is None:
                action = rng.randint(0, 3)
            next_state, reward, done = env.step(action)
            next_actions = env.get_possible_actions() if not done else []
            q_learning_update(q, state, action, reward, next_state, next_actions, alpha, gamma, done)
            state = next_state
            steps += 1
    return q


def evaluate_q_policy(env: GridWorld, q: dict, episodes: int = 50) -> float:
    """Evaluate a learned Q-policy: fraction of episodes reaching goal."""
    rng = random.Random(99)
    env.rng = rng
    successes = 0
    for _ in range(episodes):
        state = env.reset()
        done = False
        steps = 0
        while not done and steps < 200:
            action = max(q.get(state, {}).items(), key=lambda x: x[1])[0] if q.get(state) else 0
            state, reward, done = env.step(action)
            steps += 1
        if reward > 0:
            successes += 1
    return successes / episodes
