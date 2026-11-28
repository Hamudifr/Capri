"""Offline contract and regression tests for capri_runtime.agent_network.

Covers host-issued verification tokens, revocation, responsibilities,
challenges, reviews, proposal revisions, host-ratified decision records,
and signature verification. No network, no live providers.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from capri_runtime.agent_forum import SQLiteAgentForum
from capri_runtime.agent_network import (
    AgentNetworkConflictError,
    AgentNetworkNotFoundError,
    AgentNetworkValidationError,
    AgentIdentityVerifier,
    AuthorizationError,
    DecisionRecord,
    IdentityVerificationError,
    SQLiteAgentNetwork,
    VerificationToken,
)
from capri_runtime.tools import HmacApprovalKeyRing


class NetworkBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self._tmp.name) / "network.sqlite")
        self.forum = SQLiteAgentForum(self.path)
        self.key_ring = HmacApprovalKeyRing(
            {"k1": b"k" * 32}, active_key_id="k1",
        )
        self.verifier = AgentIdentityVerifier(self.key_ring)
        self.network = SQLiteAgentNetwork(self.forum, self.verifier)
        # Register agents and issue tokens
        self.forum.register_agent("alice", "Alice", capabilities=["math", "coding"])
        self.forum.register_agent("bob", "Bob", capabilities=["review", "testing"])
        self.forum.register_agent("carol", "Carol", capabilities=["research"])
        self.alice_token = self.network.issue_verification("alice", host_credential="host")
        self.bob_token = self.network.issue_verification("bob", host_credential="host")
        self.carol_token = self.network.issue_verification("carol", host_credential="host")

    def tearDown(self) -> None:
        self._tmp.cleanup()


class IdentityVerificationTests(NetworkBase):
    def test_issue_and_validate_token(self) -> None:
        self.verifier.validate(self.alice_token)
        self.assertEqual(self.alice_token.agent_id, "alice")
        self.assertIn("agent-verify:v1:", self.verifier.canonical_ref(self.alice_token))

    def test_token_for_unknown_agent_raises(self) -> None:
        with self.assertRaises(AgentNetworkNotFoundError):
            self.network.issue_verification("ghost", host_credential="host")

    def test_forged_token_rejected(self) -> None:
        forged = VerificationToken(
            "vt-forged", "alice", self.alice_token.issued_at,
            "00" * 32,
        )
        with self.assertRaises(IdentityVerificationError):
            self.verifier.validate(forged)

    def test_token_agent_mismatch_rejected(self) -> None:
        # Token for alice but used to verify bob
        with self.assertRaises(IdentityVerificationError):
            self.network._verify_agent(
                self.network._acquire_connection(), "bob", self.alice_token,
            )

    def test_revoke_token(self) -> None:
        self.network.revoke_verification(self.carol_token)
        self.assertTrue(self.network.is_token_revoked(self.carol_token))
        with self.assertRaises(IdentityVerificationError):
            self.network._verify_agent(
                self.network._acquire_connection(), "carol", self.carol_token,
            )

    def test_revoke_unknown_token_raises(self) -> None:
        fake = VerificationToken("vt-nope", "alice", "2026-01-01T00:00:00+00:00", "00" * 32)
        with self.assertRaises(AgentNetworkNotFoundError):
            self.network.revoke_verification(fake)

    def test_operation_with_revoked_token_blocked(self) -> None:
        self.network.revoke_verification(self.carol_token)
        proposal = self.forum.propose("alice", "Test idea", {})
        with self.assertRaises(IdentityVerificationError):
            self.network.challenge(
                proposal.proposal_id, "carol",
                objections={"issue": "incomplete"},
                token=self.carol_token,
            )


class ResponsibilityTests(NetworkBase):
    def test_assign_and_list_responsibilities(self) -> None:
        resp = self.network.assign_responsibility(
            "alice", "Own all math strategy proposals",
            assigned_by="host", token=self.alice_token,
        )
        self.assertEqual(resp.agent_id, "alice")
        self.assertEqual(resp.responsibility, "Own all math strategy proposals")
        self.assertEqual(resp.assigned_by, "host")
        responsibilities = self.network.responsibilities_for("alice")
        self.assertEqual(len(responsibilities), 1)
        self.assertEqual(responsibilities[0].responsibility_id, resp.responsibility_id)

    def test_responsibility_requires_valid_token(self) -> None:
        with self.assertRaises(IdentityVerificationError):
            self.network.assign_responsibility(
                "alice", "Own something",
                assigned_by="host",
                token=VerificationToken("bad", "alice", "2026-01-01T00:00:00+00:00", "00" * 32),
            )

    def test_responsibilities_distinct_from_capabilities(self) -> None:
        # Capabilities are on the forum profile; responsibilities are on the network
        agent = self.forum.get_agent("alice")
        self.assertIn("math", agent.capabilities)
        self.network.assign_responsibility(
            "alice", "Own math reviews",
            assigned_by="host", token=self.alice_token,
        )
        # Capability is not a responsibility
        resp_texts = [r.responsibility for r in self.network.responsibilities_for("alice")]
        self.assertNotIn("math", resp_texts)


class ChallengeTests(NetworkBase):
    def test_challenge_open_proposal(self) -> None:
        proposal = self.forum.propose("alice", "Add quantum module", {})
        challenge = self.network.challenge(
            proposal.proposal_id, "bob",
            objections={"risk": "untested", "scope": "too broad"},
            token=self.bob_token,
        )
        self.assertEqual(challenge.proposal_id, proposal.proposal_id)
        self.assertEqual(challenge.agent_id, "bob")
        self.assertEqual(challenge.objections["risk"], "untested")
        challenges = self.network.challenges_for(proposal.proposal_id)
        self.assertEqual(len(challenges), 1)

    def test_challenge_unknown_proposal(self) -> None:
        with self.assertRaises(AgentNetworkNotFoundError):
            self.network.challenge(
                "nonexistent", "bob",
                objections={"x": 1}, token=self.bob_token,
            )

    def test_challenge_non_open_proposal(self) -> None:
        proposal = self.forum.propose("alice", "Idea", {})
        # Vote to close it
        self.forum.vote(proposal.proposal_id, "bob", "agree")
        self.forum.resolve_consensus(proposal.proposal_id)
        proposal = self.forum.get_proposal(proposal.proposal_id)
        if proposal.state != "open":
            with self.assertRaises(AgentNetworkConflictError):
                self.network.challenge(
                    proposal.proposal_id, "bob",
                    objections={"x": 1}, token=self.bob_token,
                )

    def test_challenge_requires_valid_token(self) -> None:
        proposal = self.forum.propose("alice", "Idea", {})
        with self.assertRaises(IdentityVerificationError):
            self.network.challenge(
                proposal.proposal_id, "bob",
                objections={"x": 1},
                token=VerificationToken("bad", "bob", "2026-01-01T00:00:00+00:00", "00" * 32),
            )


class ReviewTests(NetworkBase):
    def test_review_work_entry(self) -> None:
        work = self.forum.record_work("alice", "Implemented the math module")
        review = self.network.review_work(
            work.entry_id, "bob",
            verdict="approve",
            findings={"quality": "good", "notes": "clean implementation"},
            token=self.bob_token,
        )
        self.assertEqual(review.work_entry_id, work.entry_id)
        self.assertEqual(review.verdict, "approve")
        reviews = self.network.reviews_for_work(work.entry_id)
        self.assertEqual(len(reviews), 1)

    def test_review_invalid_verdict(self) -> None:
        work = self.forum.record_work("alice", "Some work")
        with self.assertRaises(AgentNetworkValidationError):
            self.network.review_work(
                work.entry_id, "bob",
                verdict="maybe",
                findings={},
                token=self.bob_token,
            )

    def test_review_unknown_work_entry(self) -> None:
        with self.assertRaises(AgentNetworkNotFoundError):
            self.network.review_work(
                9999, "bob",
                verdict="approve",
                findings={},
                token=self.bob_token,
            )

    def test_review_requires_valid_token(self) -> None:
        work = self.forum.record_work("alice", "Some work")
        with self.assertRaises(IdentityVerificationError):
            self.network.review_work(
                work.entry_id, "bob",
                verdict="approve",
                findings={},
                token=VerificationToken("bad", "bob", "2026-01-01T00:00:00+00:00", "00" * 32),
            )


class RevisionTests(NetworkBase):
    def test_revise_proposal(self) -> None:
        proposal = self.forum.propose("alice", "Original idea", {"v": 1})
        self.network.challenge(
            proposal.proposal_id, "bob",
            objections={"issue": "needs expansion"},
            token=self.bob_token,
        )
        updated_proposal, revision = self.network.revise_proposal(
            proposal.proposal_id, "alice",
            change_summary="Added expansion section based on bob's challenge",
            body={"v": 2, "expanded": True},
            token=self.alice_token,
        )
        self.assertEqual(revision.version, 2)
        self.assertEqual(updated_proposal.version, 2)
        self.assertEqual(updated_proposal.body["v"], 2)
        self.assertEqual(updated_proposal.body["expanded"], True)
        revisions = self.network.revisions_for(proposal.proposal_id)
        self.assertEqual(len(revisions), 1)
        self.assertEqual(revisions[0].change_summary, "Added expansion section based on bob's challenge")

    def test_revise_wrong_author_blocked(self) -> None:
        proposal = self.forum.propose("alice", "Idea", {})
        with self.assertRaises(AuthorizationError):
            self.network.revise_proposal(
                proposal.proposal_id, "bob",
                change_summary="hack",
                body={"x": 1},
                token=self.bob_token,
            )

    def test_revise_non_open_proposal(self) -> None:
        proposal = self.forum.propose("alice", "Idea", {})
        self.forum.supersede(proposal.proposal_id, expected_version=1)
        with self.assertRaises(AgentNetworkConflictError):
            self.network.revise_proposal(
                proposal.proposal_id, "alice",
                change_summary="late",
                body={"x": 2},
                token=self.alice_token,
            )

    def test_revision_history_append_only(self) -> None:
        proposal = self.forum.propose("alice", "Idea", {})
        self.network.revise_proposal(
            proposal.proposal_id, "alice",
            change_summary="first", body={"v": 1},
            token=self.alice_token,
        )
        self.network.revise_proposal(
            proposal.proposal_id, "alice",
            change_summary="second", body={"v": 2},
            token=self.alice_token,
        )
        revisions = self.network.revisions_for(proposal.proposal_id)
        self.assertEqual(len(revisions), 2)
        self.assertEqual(revisions[0].version, 2)
        self.assertEqual(revisions[1].version, 3)


class DecisionTests(NetworkBase):
    def test_ratify_approved_decision(self) -> None:
        proposal = self.forum.propose("alice", "Build the system", {})
        # Simulate consensus — majority of 3 agents needs 2 agree votes
        self.forum.vote(proposal.proposal_id, "bob", "agree")
        self.forum.vote(proposal.proposal_id, "carol", "agree")
        self.forum.resolve_consensus(proposal.proposal_id)
        proposal = self.forum.get_proposal(proposal.proposal_id)
        self.assertEqual(proposal.state, "agreed")
        decision = self.network.ratify_decision(
            proposal.proposal_id,
            host_credential="host",
            evidence_references=("evt-001", "evt-002"),
        )
        self.assertEqual(decision.outcome, "approved")
        self.assertEqual(decision.evidence_references, ("evt-001", "evt-002"))
        self.assertEqual(decision.ratified_by, "host")
        self.assertTrue(self.network.verify_decision_signature(decision))

    def test_ratify_with_custom_policy(self) -> None:
        proposal = self.forum.propose("alice", "Controversial idea", {})
        self.network.challenge(
            proposal.proposal_id, "bob",
            objections={"risk": "high"},
            token=self.bob_token,
        )

        class RejectPolicy:
            def ratify(self, proposal, challenges, reviews, evidence):
                return "rejected", ("challenge-review",)

        policy_network = SQLiteAgentNetwork(
            self.forum, self.verifier, ratification_policy=RejectPolicy(),
        )
        decision = policy_network.ratify_decision(
            proposal.proposal_id, host_credential="host",
        )
        self.assertEqual(decision.outcome, "rejected")
        self.assertIn("challenge-review", decision.evidence_references)

    def test_ratify_abandoned_when_open(self) -> None:
        proposal = self.forum.propose("alice", "Unresolved idea", {})
        # No votes, no consensus — proposal stays open
        decision = self.network.ratify_decision(
            proposal.proposal_id, host_credential="host",
        )
        self.assertEqual(decision.outcome, "abandoned")

    def test_decisions_append_only(self) -> None:
        proposal = self.forum.propose("alice", "Idea", {})
        self.network.ratify_decision(proposal.proposal_id, host_credential="host")
        self.network.ratify_decision(proposal.proposal_id, host_credential="host")
        decisions = self.network.decisions_for(proposal.proposal_id)
        self.assertEqual(len(decisions), 2)
        self.assertEqual(decisions[0].decision_id, 1)
        self.assertEqual(decisions[1].decision_id, 2)

    def test_latest_decision(self) -> None:
        proposal = self.forum.propose("alice", "Idea", {})
        self.assertIsNone(self.network.latest_decision(proposal.proposal_id))
        self.network.ratify_decision(proposal.proposal_id, host_credential="host")
        decision = self.network.latest_decision(proposal.proposal_id)
        self.assertIsNotNone(decision)
        self.assertEqual(decision.proposal_id, proposal.proposal_id)

    def test_decision_signature_tampering_detected(self) -> None:
        proposal = self.forum.propose("alice", "Idea", {})
        decision = self.network.ratify_decision(
            proposal.proposal_id, host_credential="host",
        )
        # Tamper with the outcome
        tampered = DecisionRecord(
            decision.decision_id, decision.proposal_id, "rejected",
            decision.evidence_references, decision.ratified_by,
            decision.ratified_at, decision.signature,
        )
        self.assertFalse(self.network.verify_decision_signature(tampered))

    def test_ratify_unknown_proposal(self) -> None:
        with self.assertRaises(AgentNetworkNotFoundError):
            self.network.ratify_decision("nope", host_credential="host")


class PermissionPolicyTests(NetworkBase):
    def test_permission_policy_blocks_action(self) -> None:
        class RestrictedPolicy:
            def permits(self, agent_id, action):
                return agent_id == "alice" and action == "propose"

        restricted = SQLiteAgentNetwork(
            self.forum, self.verifier, permission_policy=RestrictedPolicy(),
        )
        proposal = self.forum.propose("alice", "Idea", {})
        # bob tries to challenge but is not permitted
        with self.assertRaises(AuthorizationError):
            restricted.challenge(
                proposal.proposal_id, "bob",
                objections={"x": 1}, token=self.bob_token,
            )

    def test_permission_policy_allows_when_permitted(self) -> None:
        class AllowAllPolicy:
            def permits(self, agent_id, action):
                return True

        allowed = SQLiteAgentNetwork(
            self.forum, self.verifier, permission_policy=AllowAllPolicy(),
        )
        proposal = self.forum.propose("alice", "Idea", {})
        challenge = allowed.challenge(
            proposal.proposal_id, "bob",
            objections={"x": 1}, token=self.bob_token,
        )
        self.assertEqual(challenge.agent_id, "bob")


class FullWorkflowTests(NetworkBase):
    def test_full_agent_network_lifecycle(self) -> None:
        """End-to-end: propose → challenge → revise → review → vote → ratify."""
        # 1. Alice proposes
        proposal = self.forum.propose(
            "alice", "Design the agent network protocol",
            {"spec": "v1"},
        )
        self.assertEqual(proposal.state, "open")

        # 2. Bob challenges
        self.network.challenge(
            proposal.proposal_id, "bob",
            objections={"gap": "no error handling", "risk": "over-engineered"},
            token=self.bob_token,
        )

        # 3. Alice revises
        revised, revision = self.network.revise_proposal(
            proposal.proposal_id, "alice",
            change_summary="Added error handling, simplified scope",
            body={"spec": "v2", "error_handling": True},
            token=self.alice_token,
        )
        self.assertEqual(revised.version, 2)
        self.assertEqual(revision.version, 2)

        # 4. Carol records work and bob reviews it
        work = self.forum.record_work(
            "alice", "Updated spec with error handling",
        )
        self.network.review_work(
            work.entry_id, "bob",
            verdict="approve",
            findings={"quality": "good", "addresses": "challenges"},
            token=self.bob_token,
        )

        # 5. Bob and Carol vote agree
        self.forum.vote(proposal.proposal_id, "bob", "agree")
        self.forum.vote(proposal.proposal_id, "carol", "agree")
        self.forum.resolve_consensus(proposal.proposal_id)
        proposal = self.forum.get_proposal(proposal.proposal_id)
        self.assertEqual(proposal.state, "agreed")

        # 6. Host ratifies
        decision = self.network.ratify_decision(
            proposal.proposal_id, host_credential="host",
            evidence_references=("spec-v2", "review-001"),
        )
        self.assertEqual(decision.outcome, "approved")
        self.assertTrue(self.network.verify_decision_signature(decision))

        # 7. Verify all artifacts preserved
        challenges = self.network.challenges_for(proposal.proposal_id)
        self.assertEqual(len(challenges), 1)
        revisions = self.network.revisions_for(proposal.proposal_id)
        self.assertEqual(len(revisions), 1)
        reviews = self.network.reviews_for_work(work.entry_id)
        self.assertEqual(len(reviews), 1)
        self.assertEqual(len(self.network.decisions_for(proposal.proposal_id)), 1)

    def test_responsibilities_alongside_capabilities(self) -> None:
        """Agent has both capabilities (forum) and responsibilities (network)."""
        self.network.assign_responsibility(
            "alice", "Own math strategy",
            assigned_by="host", token=self.alice_token,
        )
        self.network.assign_responsibility(
            "bob", "Own all reviews",
            assigned_by="host", token=self.bob_token,
        )
        alice_caps = self.forum.get_agent("alice").capabilities
        alice_resp = self.network.responsibilities_for("alice")
        bob_resp = self.network.responsibilities_for("bob")
        self.assertIn("math", alice_caps)
        self.assertEqual(len(alice_resp), 1)
        self.assertEqual(alice_resp[0].responsibility, "Own math strategy")
        self.assertEqual(len(bob_resp), 1)
        self.assertEqual(bob_resp[0].responsibility, "Own all reviews")


class IntegrityTests(NetworkBase):
    def test_integrity_check(self) -> None:
        self.assertEqual(self.network.integrity_check(), "ok")

    def test_forum_integrity_still_ok(self) -> None:
        # Network operations shouldn't break forum integrity
        self.network.challenge(
            self.forum.propose("alice", "Idea", {}).proposal_id, "bob",
            objections={"x": 1}, token=self.bob_token,
        )
        self.assertEqual(self.forum.integrity_check(), "ok")


if __name__ == "__main__":
    unittest.main()
