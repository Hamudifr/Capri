"""Tests for the reinforcement learning training module."""

import unittest

from research.training.rl.core import (
    GridWorld,
    epsilon_greedy, softmax_policy,
    q_learning_update, sarsa_update,
    value_iteration, policy_iteration,
    reinforce_update,
    train_q_learning, evaluate_q_policy,
)


class TestEpsilonGreedy(unittest.TestCase):

    def test_greedy_selection(self):
        q = {"s1": {"a1": 10.0, "a2": 5.0}}
        # epsilon=0 means always greedy
        action = epsilon_greedy(q, "s1", 0.0, __import__("random").Random(42))
        self.assertEqual(action, "a1")

    def test_exploration(self):
        q = {"s1": {"a1": 10.0, "a2": 5.0}}
        rng = __import__("random").Random(42)
        # With epsilon=1, always explore (random)
        actions = set()
        for _ in range(50):
            actions.add(epsilon_greedy(q, "s1", 1.0, rng))
        self.assertEqual(actions, {"a1", "a2"})


class TestSoftmaxPolicy(unittest.TestCase):

    def test_uniform_high_temp(self):
        q = {"s1": {"a1": 10.0, "a2": 0.0}}
        dist = softmax_policy(q, "s1", temperature=1000.0)
        self.assertAlmostEqual(dist["a1"], 0.5, places=2)
        self.assertAlmostEqual(dist["a2"], 0.5, places=2)

    def test_greedy_low_temp(self):
        q = {"s1": {"a1": 10.0, "a2": 0.0}}
        dist = softmax_policy(q, "s1", temperature=0.01)
        self.assertAlmostEqual(dist["a1"], 1.0, places=2)
        self.assertAlmostEqual(dist["a2"], 0.0, places=2)


class TestQLearningUpdate(unittest.TestCase):

    def test_basic_update(self):
        q = {}
        q_learning_update(q, "s1", "a1", 1.0, "s2", ["a2"], alpha=0.5, gamma=0.9, done=False)
        self.assertIn("s1", q)
        self.assertIn("a1", q["s1"])
        # With no prior Q, update moves toward target = 1 + 0.9*0 = 1
        self.assertAlmostEqual(q["s1"]["a1"], 0.5, places=3)

    def test_terminal_update(self):
        q = {"s1": {"a1": 0.0}}
        q_learning_update(q, "s1", "a1", 1.0, "s2", [], alpha=0.5, gamma=0.9, done=True)
        # Terminal: target = reward = 1
        self.assertAlmostEqual(q["s1"]["a1"], 0.5, places=3)


class TestSarsaUpdate(unittest.TestCase):

    def test_basic_sarsa(self):
        q = {}
        sarsa_update(q, "s1", "a1", 1.0, "s2", "a2", alpha=0.5, gamma=0.9, done=False)
        self.assertIn("s1", q)
        self.assertIn("a1", q["s1"])


class TestValueIteration(unittest.TestCase):

    def test_simple_chain(self):
        # Simple 2-state chain: s1 -> s2 (terminal, reward 1)
        states = [1, 2]
        actions = {1: ["a"], 2: []}
        transitions = {(1, "a"): [(2, 1.0)]}
        rewards = {(1, "a", 2): 1.0}

        v = value_iteration(states, actions, transitions, rewards, gamma=0.9, theta=1e-8)
        self.assertAlmostEqual(v[2], 0.0, places=3)
        self.assertGreater(v[1], 0.0)


class TestPolicyIteration(unittest.TestCase):

    def test_simple(self):
        states = [1, 2]
        actions = {1: ["a", "b"], 2: []}
        transitions = {(1, "a"): [(2, 1.0)], (1, "b"): [(2, 0.5)]}
        rewards = {(1, "a", 2): 1.0, (1, "b", 2): 0.5}

        policy, v = policy_iteration(states, actions, transitions, rewards, gamma=0.9)
        self.assertEqual(policy[1], "a")  # Action a has higher reward


class TestGridWorld(unittest.TestCase):

    def test_reset(self):
        env = GridWorld()
        state = env.reset()
        self.assertEqual(state, (3, 0))

    def test_step_goal(self):
        env = GridWorld()
        env.state = (0, 2)
        next_state, reward, done = env.step(3)  # right to (0, 3)
        self.assertEqual(next_state, (0, 3))
        self.assertEqual(reward, 1.0)
        self.assertTrue(done)

    def test_step_pit(self):
        env = GridWorld()
        env.state = (1, 0)
        next_state, reward, done = env.step(3)  # right to (1, 1)
        self.assertEqual(next_state, (1, 1))
        self.assertEqual(reward, -1.0)
        self.assertTrue(done)

    def test_step_normal(self):
        env = GridWorld()
        env.state = (2, 1)
        next_state, reward, done = env.step(0)  # up to (1, 1) which is pit
        # Actually up from (2,1) is (1,1) = pit
        self.assertEqual(next_state, (1, 1))
        self.assertEqual(reward, -1.0)
        self.assertTrue(done)

    def test_step_boundary(self):
        env = GridWorld()
        env.state = (0, 0)
        next_state, reward, done = env.step(0)  # up from row 0 stays at row 0
        self.assertEqual(next_state, (0, 0))
        self.assertEqual(reward, 0.0)
        self.assertFalse(done)


class TestQLearningTraining(unittest.TestCase):

    def test_train_and_evaluate(self):
        env = GridWorld()
        q = train_q_learning(env, episodes=300, alpha=0.5, gamma=0.9, epsilon=0.1, seed=42)
        # After training, should have learned something
        self.assertGreater(len(q), 0)

    def test_evaluate_policy(self):
        env = GridWorld()
        q = train_q_learning(env, episodes=300, seed=42)
        success_rate = evaluate_q_policy(env, q, episodes=20)
        self.assertGreaterEqual(success_rate, 0.0)
        self.assertLessEqual(success_rate, 1.0)


class TestReinforce(unittest.TestCase):

    def test_basic_update(self):
        policy_params = {"s1": [0.0], "s2": [0.0]}
        states = ["s1", "s2"]
        actions = [0, 1]
        rewards = [0.0, 1.0]

        new_params = reinforce_update(policy_params, states, actions, rewards, alpha=0.1)
        self.assertIn("s1", new_params)
        self.assertIn("s2", new_params)


if __name__ == "__main__":
    unittest.main()
