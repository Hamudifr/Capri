"""Offline contract and regression tests for capri_runtime.agent_registry.

Covers host-gated lifecycle transitions, principal-agent bindings, roles,
participation gating, and integrity. No network, no live providers.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from capri_runtime.agent_forum import SQLiteAgentForum
from capri_runtime.agent_registry import (
    AgentRegistryConflictError,
    AgentRegistryNotFoundError,
    AgentRegistryValidationError,
    AuthorizationError,
    SQLiteAgentRegistry,
)


class SimpleAuthority:
    """Test host authority: authenticates a credential to a principal, authorizes all."""

    def __init__(self, principals=None):
        self._credentials = principals or {"host-cred": "host-admin"}

    def authenticate(self, credential):
        return self._credentials.get(credential)

    def authorize(self, principal_id, action):
        return True


class RestrictedAuthority(SimpleAuthority):
    """Authority that denies some actions for some principals."""

    def authorize(self, principal_id, action):
        if principal_id == "host-admin":
            return True
        return action == "set_state"


class RegistryBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self._tmp.name) / "registry.sqlite")
        self.forum = SQLiteAgentForum(self.path)
        self.authority = SimpleAuthority()
        self.registry = SQLiteAgentRegistry(self.forum, self.authority)
        # Register agents in the forum
        self.forum.register_agent("alice", "Alice", capabilities=["math", "coding"])
        self.forum.register_agent("bob", "Bob", capabilities=["review", "testing"])
        self.forum.register_agent("carol", "Carol", capabilities=["research"])

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def activate(self, agent_id, credential="host-cred"):
        return self.registry.set_state(agent_id, "active", credential=credential)


class LifecycleTests(RegistryBase):
    def test_initial_state_registered(self) -> None:
        rec = self.registry.set_state("alice", "registered", credential="host-cred")
        self.assertEqual(rec.state, "registered")
        self.assertEqual(rec.version, 1)
        self.assertEqual(rec.assigned_by, "host-admin")

    def test_initial_state_active(self) -> None:
        rec = self.registry.set_state("alice", "active", credential="host-cred")
        self.assertEqual(rec.state, "active")

    def test_initial_state_suspended_rejected(self) -> None:
        with self.assertRaises(AgentRegistryConflictError):
            self.registry.set_state("alice", "suspended", credential="host-cred")

    def test_registered_to_active(self) -> None:
        self.registry.set_state("alice", "registered", credential="host-cred")
        rec = self.registry.set_state("alice", "active", credential="host-cred")
        self.assertEqual(rec.state, "active")
        self.assertEqual(rec.version, 2)

    def test_active_to_suspended(self) -> None:
        self.activate("alice")
        rec = self.registry.set_state("alice", "suspended", credential="host-cred")
        self.assertEqual(rec.state, "suspended")

    def test_suspended_to_active(self) -> None:
        self.activate("alice")
        self.registry.set_state("alice", "suspended", credential="host-cred")
        rec = self.registry.set_state("alice", "active", credential="host-cred")
        self.assertEqual(rec.state, "active")

    def test_active_to_deactivated(self) -> None:
        self.activate("alice")
        rec = self.registry.set_state("alice", "deactivated", credential="host-cred")
        self.assertEqual(rec.state, "deactivated")

    def test_deactivated_is_terminal(self) -> None:
        self.activate("alice")
        self.registry.set_state("alice", "deactivated", credential="host-cred")
        with self.assertRaises(AgentRegistryConflictError):
            self.registry.set_state("alice", "active", credential="host-cred")

    def test_invalid_transition(self) -> None:
        self.registry.set_state("alice", "registered", credential="host-cred")
        # registered → deactivated is valid, but registered → suspended is not
        with self.assertRaises(AgentRegistryConflictError):
            self.registry.set_state("alice", "suspended", credential="host-cred")

    def test_invalid_state_rejected(self) -> None:
        with self.assertRaises(AgentRegistryValidationError):
            self.registry.set_state("alice", "nonsense", credential="host-cred")

    def test_unknown_agent_rejected(self) -> None:
        with self.assertRaises(AgentRegistryNotFoundError):
            self.registry.set_state("ghost", "active", credential="host-cred")

    def test_invalid_credential_rejected(self) -> None:
        with self.assertRaises(AgentRegistryValidationError):
            self.registry.set_state("alice", "active", credential="bad-cred")

    def test_same_state_is_idempotent(self) -> None:
        self.registry.set_state("alice", "registered", credential="host-cred")
        rec1 = self.registry.set_state("alice", "registered", credential="host-cred")
        rec2 = self.registry.set_state("alice", "registered", credential="host-cred")
        self.assertEqual(rec1.version, rec2.version)

    def test_get_lifecycle_unknown_agent(self) -> None:
        with self.assertRaises(AgentRegistryNotFoundError):
            self.registry.get_lifecycle("ghost")

    def test_list_by_state(self) -> None:
        self.registry.set_state("alice", "registered", credential="host-cred")
        self.registry.set_state("bob", "active", credential="host-cred")
        self.registry.set_state("carol", "active", credential="host-cred")
        active = self.registry.list_by_state("active")
        self.assertEqual(len(active), 2)
        agent_ids = {r.agent_id for r in active}
        self.assertIn("bob", agent_ids)
        self.assertIn("carol", agent_ids)
        registered = self.registry.list_by_state("registered")
        self.assertEqual(len(registered), 1)
        self.assertEqual(registered[0].agent_id, "alice")

    def test_list_active(self) -> None:
        self.registry.set_state("alice", "registered", credential="host-cred")
        self.registry.set_state("bob", "active", credential="host-cred")
        active = self.registry.list_active()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].agent_id, "bob")


class ParticipationTests(RegistryBase):
    def test_unregistered_agent_cannot_participate(self) -> None:
        self.assertFalse(self.registry.can_participate("alice"))

    def test_active_agent_can_participate(self) -> None:
        self.activate("alice")
        self.assertTrue(self.registry.can_participate("alice"))

    def test_suspended_agent_cannot_participate(self) -> None:
        self.activate("alice")
        self.registry.set_state("alice", "suspended", credential="host-cred")
        self.assertFalse(self.registry.can_participate("alice"))

    def test_deactivated_agent_cannot_participate(self) -> None:
        self.activate("alice")
        self.registry.set_state("alice", "deactivated", credential="host-cred")
        self.assertFalse(self.registry.can_participate("alice"))

    def test_is_active_unknown_agent(self) -> None:
        self.assertFalse(self.registry.is_active("ghost"))


class BindingTests(RegistryBase):
    def test_bind_principal(self) -> None:
        binding = self.registry.bind_principal(
            "alice", "host-admin", "proposer", credential="host-cred",
        )
        self.assertEqual(binding.agent_id, "alice")
        self.assertEqual(binding.principal_id, "host-admin")
        self.assertEqual(binding.role, "proposer")
        self.assertEqual(binding.bound_by, "host-admin")

    def test_bind_all_roles(self) -> None:
        for role in ("proposer", "reviewer", "moderator", "scribe", "observer"):
            binding = self.registry.bind_principal(
                "alice", "host-admin", role, credential="host-cred",
            )
            self.assertEqual(binding.role, role)
            # Unbind before rebinding with next role
            self.registry.unbind_principal("alice", "host-admin", credential="host-cred")

    def test_invalid_role_rejected(self) -> None:
        with self.assertRaises(AgentRegistryValidationError):
            self.registry.bind_principal(
                "alice", "host-admin", "superuser", credential="host-cred",
            )

    def test_bind_unknown_agent_rejected(self) -> None:
        with self.assertRaises(AgentRegistryNotFoundError):
            self.registry.bind_principal(
                "ghost", "host-admin", "proposer", credential="host-cred",
            )

    def test_bind_duplicate_rejected(self) -> None:
        self.registry.bind_principal("alice", "host-admin", "proposer", credential="host-cred")
        with self.assertRaises(AgentRegistryConflictError):
            self.registry.bind_principal("alice", "host-admin", "reviewer", credential="host-cred")

    def test_one_principal_many_agents(self) -> None:
        self.registry.bind_principal("alice", "host-admin", "proposer", credential="host-cred")
        self.registry.bind_principal("bob", "host-admin", "reviewer", credential="host-cred")
        self.registry.bind_principal("carol", "host-admin", "scribe", credential="host-cred")
        agents = self.registry.agents_for_principal("host-admin")
        self.assertEqual(len(agents), 3)
        agent_ids = {a.agent_id for a in agents}
        self.assertEqual(agent_ids, {"alice", "bob", "carol"})

    def test_many_principals_one_agent(self) -> None:
        self.registry.bind_principal("alice", "host-admin", "proposer", credential="host-cred")
        self.registry.bind_principal("alice", "supervisor-1", "moderator", credential="host-cred")
        bindings = self.registry.bindings_for_agent("alice")
        self.assertEqual(len(bindings), 2)
        roles = {b.role for b in bindings}
        self.assertEqual(roles, {"proposer", "moderator"})

    def test_role_for(self) -> None:
        self.registry.bind_principal("alice", "host-admin", "proposer", credential="host-cred")
        self.assertEqual(self.registry.role_for("alice", "host-admin"), "proposer")
        self.assertIsNone(self.registry.role_for("alice", "unknown-principal"))

    def test_unbind_principal(self) -> None:
        self.registry.bind_principal("alice", "host-admin", "proposer", credential="host-cred")
        self.registry.unbind_principal("alice", "host-admin", credential="host-cred")
        # After unbind, the binding is gone from active bindings
        bindings = self.registry.bindings_for_agent("alice")
        self.assertEqual(len(bindings), 0)
        self.assertIsNone(self.registry.role_for("alice", "host-admin"))

    def test_unbind_nonexistent_binding(self) -> None:
        with self.assertRaises(AgentRegistryNotFoundError):
            self.registry.unbind_principal("alice", "nobody", credential="host-cred")

    def test_rebind_after_unbind(self) -> None:
        self.registry.bind_principal("alice", "host-admin", "proposer", credential="host-cred")
        self.registry.unbind_principal("alice", "host-admin", credential="host-cred")
        # Can now bind with a different role
        binding = self.registry.bind_principal(
            "alice", "host-admin", "reviewer", credential="host-cred",
        )
        self.assertEqual(binding.role, "reviewer")

    def test_unbind_idempotent(self) -> None:
        self.registry.bind_principal("alice", "host-admin", "proposer", credential="host-cred")
        self.registry.unbind_principal("alice", "host-admin", credential="host-cred")
        # Second unbind should be a no-op
        self.registry.unbind_principal("alice", "host-admin", credential="host-cred")

    def test_bind_requires_host_credential(self) -> None:
        with self.assertRaises(AgentRegistryValidationError):
            self.registry.bind_principal("alice", "host-admin", "proposer", credential="bad")


class AuthorizationTests(RegistryBase):
    def test_restricted_authority_blocks_action(self) -> None:
        auth = RestrictedAuthority({"host-cred": "host-admin", "guest-cred": "guest"})
        restricted = SQLiteAgentRegistry(self.forum, auth)
        # host-admin is allowed everything
        restricted.set_state("alice", "active", credential="host-cred")
        # guest is only authorized for set_state, not bind_principal
        with self.assertRaises(AuthorizationError):
            restricted.bind_principal("bob", "guest", "proposer", credential="guest-cred")

    def test_restricted_authority_allows_authorized_action(self) -> None:
        auth = RestrictedAuthority({"host-cred": "host-admin", "guest-cred": "guest"})
        restricted = SQLiteAgentRegistry(self.forum, auth)
        # guest can do set_state (authorized), but not bind_principal
        rec = restricted.set_state("alice", "active", credential="guest-cred")
        self.assertEqual(rec.state, "active")
        with self.assertRaises(AuthorizationError):
            restricted.bind_principal("alice", "guest", "proposer", credential="guest-cred")


class IntegrityTests(RegistryBase):
    def test_integrity_check(self) -> None:
        self.activate("alice")
        self.registry.bind_principal("alice", "host-admin", "proposer", credential="host-cred")
        self.assertEqual(self.registry.integrity_check(), "ok")

    def test_forum_integrity_still_ok(self) -> None:
        self.activate("alice")
        self.registry.bind_principal("alice", "host-admin", "proposer", credential="host-cred")
        self.assertEqual(self.forum.integrity_check(), "ok")

    def test_backup_validation(self) -> None:
        self.activate("alice")
        self.registry.bind_principal("alice", "host-admin", "proposer", credential="host-cred")
        # Validate snapshot
        self.registry._validate_backup_snapshot()


class FullLifecycleTests(RegistryBase):
    def test_agent_full_lifecycle(self) -> None:
        """End-to-end: register → activate → bind → participate → suspend → deactivate."""
        # 1. Set initial state to registered
        self.registry.set_state("alice", "registered", credential="host-cred")
        self.assertFalse(self.registry.can_participate("alice"))

        # 2. Activate
        self.registry.set_state("alice", "active", credential="host-cred")
        self.assertTrue(self.registry.can_participate("alice"))

        # 3. Bind principal with a role
        binding = self.registry.bind_principal(
            "alice", "host-admin", "proposer", credential="host-cred",
        )
        self.assertEqual(binding.role, "proposer")
        self.assertEqual(self.registry.role_for("alice", "host-admin"), "proposer")

        # 4. Agent can now participate in the forum
        proposal = self.forum.propose("alice", "First proposal", {})
        self.assertEqual(proposal.state, "open")

        # 5. Suspend
        self.registry.set_state("alice", "suspended", credential="host-cred")
        self.assertFalse(self.registry.can_participate("alice"))

        # 6. Deactivate (terminal)
        self.registry.set_state("alice", "deactivated", credential="host-cred")
        self.assertFalse(self.registry.can_participate("alice"))

        # 7. Cannot transition from deactivated
        with self.assertRaises(AgentRegistryConflictError):
            self.registry.set_state("alice", "active", credential="host-cred")

    def test_multiple_agents_independent_lifecycles(self) -> None:
        """Each agent has its own independent lifecycle."""
        self.registry.set_state("alice", "active", credential="host-cred")
        self.registry.set_state("bob", "registered", credential="host-cred")
        self.registry.set_state("carol", "active", credential="host-cred")

        self.assertTrue(self.registry.can_participate("alice"))
        self.assertFalse(self.registry.can_participate("bob"))
        self.assertTrue(self.registry.can_participate("carol"))

        # Suspend alice only
        self.registry.set_state("alice", "suspended", credential="host-cred")
        self.assertFalse(self.registry.can_participate("alice"))
        self.assertTrue(self.registry.can_participate("carol"))

        # Bob is unaffected
        self.assertFalse(self.registry.can_participate("bob"))


if __name__ == "__main__":
    unittest.main()
