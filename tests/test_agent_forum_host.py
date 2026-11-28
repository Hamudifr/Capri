"""Adversarial tests for the authenticated Agent Forum host facade."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from capri_runtime.agent_forum import (
    ForumNotFoundError,
    SQLiteAgentForum,
)
from capri_runtime.agent_forum_host import (
    AgentForumGateway,
    AgentForumInvocation,
    FORUM_REGISTER,
    FORUM_CONSENSUS,
    FORUM_MODERATE,
    FORUM_PROPOSE,
    FORUM_READ_SELF,
    FORUM_READ_SHARED,
    FORUM_SKILL_WRITE,
    FORUM_SUPERSEDE,
    FORUM_VOTE,
    FORUM_WORK_WRITE,
)
from capri_runtime.tools import (
    HostAuthorityError,
    HostAuthorityResolver,
    PermissionDeniedError,
)


class AgentForumGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.forum = SQLiteAgentForum(str(Path(self.temp.name) / "forum.sqlite"))
        for agent_id in ("a1", "a2", "b1", "reader", "moderator", "admin", "reviewer"):
            self.forum.register_agent(agent_id, agent_id)

        self.permissions = {
            "alice": (
                FORUM_READ_SELF,
                FORUM_PROPOSE,
                FORUM_VOTE,
                FORUM_SUPERSEDE,
                FORUM_WORK_WRITE,
                FORUM_SKILL_WRITE,
            ),
            "alice-review": (FORUM_READ_SELF, FORUM_SUPERSEDE),
            "bob": (FORUM_READ_SELF, FORUM_VOTE),
            "reader": (FORUM_READ_SHARED,),
            "moderator": (FORUM_READ_SELF, FORUM_MODERATE),
            "admin": (
                FORUM_READ_SHARED,
                FORUM_REGISTER,
                FORUM_CONSENSUS,
            ),
        }
        self.bindings = {
            ("alice", "alice-main"): "a1",
            ("alice", "alice-second"): "a2",
            ("alice-review", "reviewer-op"): "reviewer",
            ("bob", "bob-main"): "b1",
            ("reader", "reader-main"): "reader",
            ("moderator", "moderator-main"): "moderator",
            ("admin", "admin-main"): "admin",
        }
        authority = HostAuthorityResolver(
            lambda credential: {
                "alice-token": "alice",
                "reviewer-token": "alice-review",
                "bob-token": "bob",
                "reader-token": "reader",
                "moderator-token": "moderator",
                "admin-token": "admin",
            }.get(credential),
            lambda principal: self.permissions[principal],
        )
        self.authority = authority
        self.agent_for_invocation = lambda context: self.bindings.get(
            (context.principal_id, context.operation_id or "")
        )
        self.eligible_voters_for_proposal = lambda context: tuple(
            profile.agent_id for profile in self.forum.list_agents()
        )
        self.gateway = AgentForumGateway(
            self.forum,
            authority,
            self.agent_for_invocation,
            self.eligible_voters_for_proposal,
        )

    def bind(self, credential: str, operation_id: str) -> AgentForumInvocation:
        return self.gateway.bind_invocation(
            credential, operation_id=operation_id
        )

    def test_one_principal_can_bind_distinct_agents_from_host_operation_context(self):
        first = self.bind("alice-token", "alice-main")
        second = self.bind("alice-token", "alice-second")
        proposal_a = self.gateway.propose(first, "from first", {})
        proposal_b = self.gateway.propose(second, "from second", {})

        self.assertEqual(proposal_a.author_id, "a1")
        self.assertEqual(proposal_b.author_id, "a2")
        self.assertEqual(first.principal_id, second.principal_id)
        self.assertNotEqual(first.agent_id, second.agent_id)

    def test_model_arguments_cannot_override_the_bound_actor(self):
        invocation = self.bind("alice-token", "alice-main")
        with self.assertRaises(TypeError):
            self.gateway.propose(
                invocation, "forged", {}, author_id="b1"
            )
        proposal = self.gateway.propose(invocation, "legitimate", {})
        self.assertEqual(proposal.author_id, "a1")

    def test_unrecognized_operation_binding_fails_closed(self):
        with self.assertRaises(HostAuthorityError):
            self.bind("alice-token", "model-selected-agent-b1")

    def test_invalid_credentials_and_binding_fail_before_writes(self):
        with self.assertRaises(HostAuthorityError):
            self.bind("invalid-token", "alice-main")
        with self.assertRaises(HostAuthorityError):
            self.bind("alice-token", "unknown-operation")
        self.assertEqual(self.forum.list_proposals(), ())

    def test_missing_write_permission_is_denied(self):
        bob = self.bind("bob-token", "bob-main")
        with self.assertRaises(PermissionDeniedError):
            self.gateway.propose(bob, "not allowed", {})
        with self.assertRaises(PermissionDeniedError):
            self.gateway.record_work(bob, "not allowed")
        self.assertEqual(self.forum.list_proposals(), ())
        self.assertEqual(self.forum.work_log("b1"), ())

    def test_host_selected_voter_roster_excludes_unselected_agent_instances(self):
        restricted = AgentForumGateway(
            self.forum,
            self.authority,
            self.agent_for_invocation,
            lambda context: ("a1", "b1"),
        )
        alice = restricted.bind_invocation(
            "alice-token", operation_id="alice-main"
        )
        alice_second = restricted.bind_invocation(
            "alice-token", operation_id="alice-second"
        )
        bob = restricted.bind_invocation(
            "bob-token", operation_id="bob-main"
        )
        proposal = restricted.propose(alice, "host roster", {})

        with self.assertRaises(ForumNotFoundError):
            restricted.vote(alice_second, proposal.proposal_id, "agree")
        decided, _ = restricted.vote(bob, proposal.proposal_id, "agree")
        self.assertEqual(decided.state, "agreed")

    def test_voter_roster_resolver_failure_fails_before_proposal_write(self):
        failing = AgentForumGateway(
            self.forum,
            self.authority,
            self.agent_for_invocation,
            lambda context: (_ for _ in ()).throw(RuntimeError("roster secret")),
        )
        invocation = failing.bind_invocation(
            "alice-token", operation_id="alice-main"
        )
        with self.assertRaises(HostAuthorityError) as raised:
            failing.propose(invocation, "must not persist", {})
        self.assertNotIn("roster secret", str(raised.exception))
        self.assertEqual(self.forum.list_proposals(), ())

    def test_vote_actor_is_bound_to_authenticated_agent(self):
        alice = self.bind("alice-token", "alice-main")
        bob = self.bind("bob-token", "bob-main")
        proposal = self.gateway.propose(alice, "vote identity", {})
        self.gateway.vote(bob, proposal.proposal_id, "agree")
        votes = self.forum.votes_for(proposal.proposal_id)
        self.assertEqual(len(votes), 1)
        self.assertEqual(votes[0].agent_id, "b1")

    def test_self_read_cannot_read_another_agents_proposal_or_work(self):
        alice = self.bind("alice-token", "alice-main")
        bob = self.bind("bob-token", "bob-main")
        proposal = self.gateway.propose(alice, "private proposal", {})
        self.gateway.record_work(alice, "private work")

        with self.assertRaises(ForumNotFoundError):
            self.gateway.get_proposal(bob, proposal.proposal_id)
        with self.assertRaises(ForumNotFoundError):
            self.gateway.work_log(bob, "a1")

    def test_shared_read_policy_allows_explicit_cross_agent_reads(self):
        alice = self.bind("alice-token", "alice-main")
        reader = self.bind("reader-token", "reader-main")
        proposal = self.gateway.propose(alice, "shared proposal", {})
        self.gateway.record_work(alice, "shared work")

        self.assertEqual(
            self.gateway.get_proposal(reader, proposal.proposal_id),
            proposal,
        )
        self.assertEqual(
            self.gateway.work_log(reader, "a1")[0].summary,
            "shared work",
        )

    def test_self_vote_read_does_not_disclose_other_agents_votes(self):
        alice = self.bind("alice-token", "alice-main")
        bob = self.bind("bob-token", "bob-main")
        reader = self.bind("reader-token", "reader-main")
        proposal = self.gateway.propose(alice, "vote visibility", {})
        self.gateway.vote(bob, proposal.proposal_id, "agree")

        self.assertEqual(self.gateway.votes_for(alice, proposal.proposal_id), ())
        self.assertEqual(
            self.gateway.votes_for(bob, proposal.proposal_id)[0].agent_id,
            "b1",
        )
        self.assertEqual(
            self.gateway.votes_for(reader, proposal.proposal_id)[0].agent_id,
            "b1",
        )

    def test_only_host_admin_can_register_agents(self):
        alice = self.bind("alice-token", "alice-main")
        admin = self.bind("admin-token", "admin-main")
        with self.assertRaises(PermissionDeniedError):
            self.gateway.register_agent(alice, "self-created", "self-created")

        created = self.gateway.register_agent(admin, "host-created", "Host Created")
        self.assertEqual(created.agent_id, "host-created")

    def test_only_author_or_moderator_can_supersede(self):
        alice = self.bind("alice-token", "alice-main")
        bob = self.bind("bob-token", "bob-main")
        reviewer = self.bind("reviewer-token", "reviewer-op")
        moderator = self.bind("moderator-token", "moderator-main")
        proposal = self.gateway.propose(alice, "supersede policy", {})

        with self.assertRaises(PermissionDeniedError):
            self.gateway.supersede(
                bob, proposal.proposal_id, expected_version=proposal.version
            )
        with self.assertRaises(PermissionDeniedError):
            self.gateway.supersede(
                reviewer, proposal.proposal_id, expected_version=proposal.version
            )
        result = self.gateway.supersede(
            moderator, proposal.proposal_id, expected_version=proposal.version
        )
        self.assertEqual(result.state, "superseded")

    def test_consensus_resolution_is_system_only(self):
        alice = self.bind("alice-token", "alice-main")
        admin = self.bind("admin-token", "admin-main")
        proposal = self.gateway.propose(alice, "consensus admin", {})

        with self.assertRaises(PermissionDeniedError):
            self.gateway.resolve_consensus(alice, proposal.proposal_id)
        self.assertEqual(
            self.gateway.resolve_consensus(admin, proposal.proposal_id).state,
            "open",
        )

    def test_model_tool_allowlist_excludes_host_and_system_operations(self):
        self.assertIn("propose", AgentForumGateway.MODEL_TOOL_METHODS)
        self.assertIn("vote", AgentForumGateway.MODEL_TOOL_METHODS)
        self.assertNotIn("bind_invocation", AgentForumGateway.MODEL_TOOL_METHODS)
        self.assertNotIn("register_agent", AgentForumGateway.MODEL_TOOL_METHODS)
        self.assertNotIn("resolve_consensus", AgentForumGateway.MODEL_TOOL_METHODS)

    def test_invocation_from_another_gateway_cannot_be_reused(self):
        invocation = self.bind("alice-token", "alice-main")
        other = AgentForumGateway(
            self.forum,
            HostAuthorityResolver(
                lambda credential: "alice",
                lambda principal: self.permissions["alice"],
            ),
            lambda context: "a1",
            lambda context: ("a1",),
        )
        with self.assertRaises(HostAuthorityError):
            other.propose(invocation, "cross gateway", {})

    def test_resolver_exceptions_fail_closed(self):
        failing = AgentForumGateway(
            self.forum,
            HostAuthorityResolver(
                lambda credential: "alice",
                lambda principal: self.permissions["alice"],
            ),
            lambda context: (_ for _ in ()).throw(RuntimeError("secret")),
            lambda context: ("a1",),
        )
        with self.assertRaises(HostAuthorityError) as raised:
            failing.bind_invocation("opaque", operation_id="trusted-op")
        self.assertNotIn("secret", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
