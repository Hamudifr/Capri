"""Tests for the unified Agent Network host.

Covers registration, transport, participation enforcement, the full
propose-challenge-review-revise-ratify workflow, and the adversarial
harness.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from capri_runtime.agent_network_host import (
    AgentNetworkHost,
    AgentNetworkHostValidationError,
    AgentTransportError,
    AdversarialHarness,
)
from capri_runtime.tools import HmacApprovalKeyRing, HostAuthorityResolver


class HostBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls._db = Path(cls._tmp.name) / "test_network.db"
        cls.key_ring = HmacApprovalKeyRing(
            {"k1": b"k" * 32}, active_key_id="k1",
        )
        cls._permissions = {
            "host-admin": (
                "forum:read:shared",
                "forum:read:self",
                "forum:admin:register",
                "forum:proposals:write",
                "forum:proposals:vote",
                "forum:proposals:supersede",
                "forum:moderate",
                "forum:system:consensus",
                "forum:work:write",
                "forum:skills:write",
            ),
        }
        cls.authority = HostAuthorityResolver(
            lambda credential: "host-admin"
            if credential == "host"
            or hasattr(credential, "token")
            else None,
            lambda principal: cls._permissions.get(principal, ()),
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def setUp(self) -> None:
        self.db = Path(self._tmp.name) / f"test_{type(self).__name__}_{id(self)}.db"
        self.host = AgentNetworkHost(
            str(self.db),
            authority=self.authority,
            key_ring=self.key_ring,
        )

    def tearDown(self) -> None:
        if self.db.exists():
            self.db.unlink()


class RegistrationTests(HostBase):
    def _register(self, agent_id: str, **kwargs):
        kwargs.setdefault("host_credential", "host")
        return self.host.register_agent(agent_id, agent_id, **kwargs)

    def test_register_agent_returns_caps_and_token(self) -> None:
        caps, token = self._register(
            "alice", capabilities=["proposal", "review"],
        )
        self.assertEqual(caps, ("proposal", "review"))
        self.assertEqual(token.agent_id, "alice")

    def test_registered_agent_is_active(self) -> None:
        self._register("alice")
        self.assertEqual(self.host.get_agent_state("alice"), "active")
        self.assertIn("alice", self.host.active_agents())

    def test_register_sets_initial_state(self) -> None:
        self._register("alice", initial_state="registered")
        self.assertEqual(self.host.get_agent_state("alice"), "registered")
        self.assertNotIn("alice", self.host.active_agents())

    def test_register_invalid_initial_state(self) -> None:
        with self.assertRaises(AgentNetworkHostValidationError):
            self._register("alice", initial_state="suspended")


class TransportTests(HostBase):
    def _register(self, agent_id: str, **kwargs):
        kwargs.setdefault("host_credential", "host")
        return self.host.register_agent(agent_id, agent_id, **kwargs)

    def _connect(self, agent_id: str = "alice"):
        caps, token = self._register(agent_id)
        return self.host.connect_agent(token, operation_id=f"op-{agent_id}-0")

    def test_connect_returns_bound_invocation(self) -> None:
        invocation = self._connect()
        self.assertEqual(invocation.agent_id, "alice")

    def test_connect_blocks_suspended_agent(self) -> None:
        self._register("alice")
        # suspend alice
        self.host.registry.set_state("alice", "suspended", credential="host")
        # a fresh token should fail because alice is suspended
        new_token = self.host.verifier.issue("alice")
        with self.assertRaises(AgentTransportError):
            self.host.connect_agent(new_token, operation_id="op-alice-1")

    def test_connect_blocks_deactivated_agent(self) -> None:
        self._register("alice")
        self.host.registry.set_state("alice", "deactivated", credential="host")
        token = self.host.verifier.issue("alice")
        with self.assertRaises(AgentTransportError):
            self.host.connect_agent(token, operation_id="op-alice-0")

    def test_connect_invalid_token(self) -> None:
        with self.assertRaises(AgentTransportError):
            self.host.connect_agent("not-a-token", operation_id="op-x")


class ParticipationTests(HostBase):
    def _invocation(self, agent_id: str = "alice"):
        caps, token = self.host.register_agent(
            agent_id, agent_id, host_credential="host",
        )
        inv = self.host.connect_agent(token, operation_id=f"op-{agent_id}-0")
        return inv

    def test_propose_requires_active(self) -> None:
        inv = self._invocation()
        self.host.registry.set_state("alice", "suspended", credential="host")
        with self.assertRaises(Exception):
            self.host.propose(inv, "Idea", {"x": 1})

    def test_vote_requires_active(self) -> None:
        inv = self._invocation()
        p = self.host.propose(inv, "Idea", {"x": 1})
        self.host.registry.set_state("alice", "suspended", credential="host")
        with self.assertRaises(Exception):
            self.host.vote(inv, p.proposal_id, "agree")

    def test_challenge_requires_active(self) -> None:
        inv = self._invocation()
        p = self.host.propose(inv, "Idea", {"x": 1})
        self.host.registry.set_state("alice", "suspended", credential="host")
        with self.assertRaises(Exception):
            self.host.challenge(inv, p.proposal_id, objections={"issue": "x"})


class WorkflowTests(HostBase):
    def test_full_lifecycle(self) -> None:
        # Register two agents
        caps1, token1 = self.host.register_agent(
            "alice", "Alice", capabilities=["proposal", "review"],
            host_credential="host",
        )
        caps2, token2 = self.host.register_agent(
            "bob", "Bob", capabilities=["proposal", "review"],
            host_credential="host",
        )
        inv1 = self.host.connect_agent(token1, operation_id="op-alice-0")
        inv2 = self.host.connect_agent(token2, operation_id="op-bob-0")

        # Alice proposes
        proposal = self.host.propose(inv1, "A Shared Idea", {"plan": "value"})

        # Bob challenges
        challenge = self.host.challenge(
            inv2, proposal.proposal_id,
            objections={"issue": "too vague"},
        )
        self.assertIn("issue", challenge.objections)

        # Alice records work
        work = self.host.record_work(inv1, "Elaborated on the idea")

        # Bob reviews
        review = self.host.review(
            inv2, work.entry_id,
            verdict="approve", findings={"quality": "good"},
        )
        self.assertEqual(review.verdict, "approve")

        # Alice revises
        revised, changes = self.host.revise(
            inv1, proposal.proposal_id,
            change_summary="addressed the challenge",
            body={"plan": "detailed value"},
        )
        self.assertEqual(changes.version, 2)
        self.assertEqual(revised.version, 2)

        # Alice votes
        proposal, vote = self.host.vote(
            inv1, proposal.proposal_id, "agree", rationale="solid",
        )
        self.assertEqual(vote.decision, "agree")

        # Resolve consensus and ratify
        proposal = self.host.resolve_consensus(inv1, proposal.proposal_id)
        decision = self.host.ratify(
            proposal.proposal_id,
            host_credential="host",
            evidence_references=("ref-1", "ref-2"),
        )
        self.assertTrue(self.host.network.verify_decision_signature(decision))
        self.assertEqual(decision.evidence_references, ("ref-1", "ref-2"))

    def test_bind_principal_through_host(self) -> None:
        self.host.register_agent("alice", "Alice", host_credential="host")
        binding = self.host.bind_principal(
            "alice", "host-admin", "proposer", host_credential="host",
        )
        self.assertEqual(binding.role, "proposer")

    def test_integrity_check(self) -> None:
        self.host.register_agent("alice", "Alice", host_credential="host")
        self.assertEqual(self.host.integrity_check(), "ok")


class AdversarialTests(HostBase):
    def test_adversarial_round(self) -> None:
        harness = AdversarialHarness(self.host)
        result = harness.run_round()
        self.assertTrue(result.all_guarantees_held)
        self.assertEqual(result.proposal_count, 3)
        self.assertEqual(result.decision_count, 3)
        self.assertGreater(result.challenge_count, 0)
        self.assertGreater(result.revision_count, 0)

    def test_adversarial_suspended_agent_blocked(self) -> None:
        harness = AdversarialHarness(self.host)
        result = harness.run_round()
        # the harness itself tests this; verify it's in notes
        self.assertTrue(
            any("blocked" in n for n in result.notes),
        )


if __name__ == "__main__":
    unittest.main()
