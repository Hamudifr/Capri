"""Offline contract and regression tests for capri_runtime.agent_forum.

Covers agent registration, proposal lifecycle, consensus resolution,
append-only enforcement on votes/work/skill entries, work logging for
continuous long-running work, skill-confidence improvement, and backup
validation. No network, no live providers.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from capri_runtime.agent_forum import (
    ForumConflictError,
    ForumNotFoundError,
    ForumValidationError,
    MajorityConsensus,
    SQLiteAgentForum,
)


class ForumBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self._tmp.name) / "forum.sqlite")
        self.forum = SQLiteAgentForum(self.path)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def register(self, agent_id: str, caps=()) -> None:
        self.forum.register_agent(agent_id, agent_id, capabilities=list(caps))


class AgentLifecycleTests(ForumBase):
    def test_register_and_get_agent(self) -> None:
        self.register("a1", ["math", "coding"])
        agent = self.forum.get_agent("a1")
        self.assertEqual(agent.agent_id, "a1")
        self.assertEqual(agent.capabilities, ("math", "coding"))
        self.assertEqual(agent.version, 1)

    def test_register_is_idempotent(self) -> None:
        self.register("a1")
        self.register("a1")
        self.assertEqual(len(self.forum.list_agents()), 1)
        self.assertEqual(self.forum.get_agent("a1").version, 1)

    def test_duplicate_capability_rejected(self) -> None:
        with self.assertRaises(ForumValidationError):
            self.forum.register_agent("a1", "a1", capabilities=["x", "x"])

    def test_unknown_agent_raises(self) -> None:
        with self.assertRaises(ForumNotFoundError):
            self.forum.get_agent("nope")


class ProposalTests(ForumBase):
    def test_propose_requires_registered_author(self) -> None:
        with self.assertRaises(ForumNotFoundError):
            self.forum.propose("ghost", "idea", {})

    def test_propose_and_get(self) -> None:
        self.register("a1")
        proposal = self.forum.propose("a1", "Reverse-engineer the schema", {"target": "x"}, rationale="clean extraction")
        self.assertEqual(proposal.state, "open")
        self.assertEqual(proposal.version, 1)
        self.assertFalse(proposal.profound)
        self.assertEqual(self.forum.get_proposal(proposal.proposal_id).title, "Reverse-engineer the schema")

    def test_profound_flag(self) -> None:
        self.register("a1")
        proposal = self.forum.propose("a1", "deep idea", {}, profound=True)
        self.assertTrue(self.forum.get_proposal(proposal.proposal_id).profound)

    def test_list_proposals_by_state(self) -> None:
        self.register("a1", ["math"])
        self.register("a2", ["math"])
        p = self.forum.propose("a1", "idea", {})
        self.forum.vote(p.proposal_id, "a2", "agree")
        # With two eligible agents and one agree, not yet a majority -> open.
        self.assertEqual(len(self.forum.list_proposals("open")), 1)
        self.assertEqual(len(self.forum.list_proposals("agreed")), 0)


class ConsensusTests(ForumBase):
    def test_majority_agreement_decides_agreed(self) -> None:
        self.register("a1")
        self.register("a2")
        self.register("a3")
        p = self.forum.propose("a1", "pursue idea", {})
        self.forum.vote(p.proposal_id, "a2", "agree")
        self.forum.vote(p.proposal_id, "a3", "agree")
        decided = self.forum.resolve_consensus(p.proposal_id)
        self.assertEqual(decided.state, "agreed")

    def test_majority_disagreement_decides_rejected(self) -> None:
        self.register("a1")
        self.register("a2")
        self.register("a3")
        p = self.forum.propose("a1", "bad idea", {})
        self.forum.vote(p.proposal_id, "a2", "disagree")
        self.forum.vote(p.proposal_id, "a3", "disagree")
        self.assertEqual(self.forum.resolve_consensus(p.proposal_id).state, "rejected")

    def test_no_votes_stays_open(self) -> None:
        self.register("a1")
        self.register("a2")
        p = self.forum.propose("a1", "idea", {})
        self.assertEqual(self.forum.resolve_consensus(p.proposal_id).state, "open")

    def test_vote_triggers_consensus(self) -> None:
        self.register("a1")
        self.register("a2")
        p = self.forum.propose("a1", "idea", {})
        _, vote = self.forum.vote(p.proposal_id, "a2", "agree")
        # Two eligible, one agree is not a strict majority, so still open.
        self.assertEqual(vote.decision, "agree")
        self.assertEqual(self.forum.get_proposal(p.proposal_id).state, "open")

    def test_cannot_vote_on_decided_proposal(self) -> None:
        self.register("a1")
        self.register("a2")
        self.register("a3")
        p = self.forum.propose("a1", "idea", {})
        self.forum.vote(p.proposal_id, "a2", "agree")
        self.forum.vote(p.proposal_id, "a3", "agree")
        with self.assertRaises(ForumConflictError):
            self.forum.vote(p.proposal_id, "a2", "disagree")

    def test_duplicate_agent_vote_is_idempotent(self) -> None:
        self.register("a1")
        self.register("a2")
        p = self.forum.propose("a1", "idea", {})
        self.forum.vote(p.proposal_id, "a2", "agree")
        # Re-voting the same agent/decision returns the existing vote, no error.
        _, vote = self.forum.vote(p.proposal_id, "a2", "agree")
        self.assertEqual(vote.decision, "agree")
        self.assertEqual(len(self.forum.votes_for(p.proposal_id)), 1)

    def test_conflicting_agent_vote_replay_is_rejected(self) -> None:
        self.register("a1")
        self.register("a2")
        p = self.forum.propose("a1", "idea", {})
        self.forum.vote(p.proposal_id, "a2", "agree", rationale="initial")

        with self.assertRaises(ForumConflictError):
            self.forum.vote(p.proposal_id, "a2", "disagree", rationale="initial")
        with self.assertRaises(ForumConflictError):
            self.forum.vote(p.proposal_id, "a2", "agree", rationale="changed")

        votes = self.forum.votes_for(p.proposal_id)
        self.assertEqual(len(votes), 1)
        self.assertEqual(votes[0].decision, "agree")
        self.assertEqual(votes[0].rationale, "initial")

    def test_exact_vote_retry_after_finalization_returns_original_vote(self) -> None:
        self.register("a1")
        self.register("a2")
        self.register("a3")
        proposal = self.forum.propose("a1", "idea", {})
        self.forum.vote(proposal.proposal_id, "a2", "agree", rationale="support")
        decided, original = self.forum.vote(
            proposal.proposal_id, "a3", "agree", rationale="support"
        )
        self.assertEqual(decided.state, "agreed")

        retried, replay = self.forum.vote(
            proposal.proposal_id, "a2", "agree", rationale="support"
        )
        self.assertEqual(retried.state, "agreed")
        self.assertEqual(replay.vote_id, self.forum.votes_for(proposal.proposal_id)[0].vote_id)
        self.assertNotEqual(original.vote_id, replay.vote_id)
        with self.assertRaises(ForumConflictError):
            self.forum.vote(proposal.proposal_id, "a2", "agree", rationale="changed")
        with self.assertRaises(ForumConflictError):
            self.forum.vote(proposal.proposal_id, "a2", "disagree", rationale="support")

    def test_voter_roster_is_frozen_across_forum_instances(self) -> None:
        self.register("a1")
        self.register("a2")
        proposal = self.forum.propose("a1", "snapshot quorum", {})
        second_instance = SQLiteAgentForum(self.path)
        second_instance.register_agent("a3", "a3")

        with self.assertRaises(ForumNotFoundError):
            self.forum.vote(proposal.proposal_id, "a3", "agree")

        still_open, _ = self.forum.vote(proposal.proposal_id, "a2", "agree")
        self.assertEqual(still_open.state, "open")
        decided, _ = self.forum.vote(proposal.proposal_id, "a1", "agree")
        self.assertEqual(decided.state, "agreed")

    def test_custom_consensus_policy(self) -> None:
        # Any single agree decides, regardless of eligible count.
        class AnyAgree(MajorityConsensus):
            def decide(self, agree, disagree, abstain, eligible):
                if agree >= 1:
                    return "agreed"
                return None

        forum = SQLiteAgentForum(str(Path(self._tmp.name) / "custom.sqlite"), consensus=AnyAgree())
        forum.register_agent("a1", "a1")
        forum.register_agent("a2", "a2")
        p = forum.propose("a1", "idea", {})
        forum.vote(p.proposal_id, "a2", "agree")
        self.assertEqual(forum.resolve_consensus(p.proposal_id).state, "agreed")


class AppendOnlyTests(ForumBase):
    def test_votes_are_append_only(self) -> None:
        self.register("a1")
        self.register("a2")
        p = self.forum.propose("a1", "idea", {})
        self.forum.vote(p.proposal_id, "a2", "agree")
        with self.assertRaises(Exception):
            self._execute("UPDATE proposal_votes SET decision='disagree' WHERE proposal_id=?", (p.proposal_id,))

    def test_work_log_is_append_only(self) -> None:
        self.register("a1")
        self.forum.record_work("a1", "did a thing")
        with self.assertRaises(Exception):
            self._execute("DELETE FROM work_log")

    def test_skill_ledger_is_append_only(self) -> None:
        self.register("a1")
        self.forum.record_skill("a1", "math", confidence=0.5)
        with self.assertRaises(Exception):
            self._execute("DELETE FROM skill_ledger")

    def _execute(self, sql: str, params=()) -> None:
        # Direct write attempt must be rejected by the append-only triggers.
        import sqlite3

        conn = sqlite3.connect(self.path)
        try:
            conn.execute(sql, params)
            conn.commit()
        finally:
            conn.close()


class WorkAndSkillTests(ForumBase):
    def test_record_work_and_read_back(self) -> None:
        self.register("a1")
        self.forum.record_work("a1", "reverse-engineered the RPC", detail={"rows": 14})
        entries = self.forum.work_log("a1")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].detail, {"rows": 14})

    def test_work_requires_registered_agent(self) -> None:
        with self.assertRaises(ForumNotFoundError):
            self.forum.record_work("ghost", "work")

    def test_skill_confidence_improves_over_time(self) -> None:
        self.register("a1")
        self.forum.record_skill("a1", "math", confidence=0.4, evidence_reference="e1")
        self.forum.record_skill("a1", "math", confidence=0.6, evidence_reference="e2")
        self.forum.record_skill("a1", "math", confidence=0.85, evidence_reference="e3")
        history = self.forum.skill_history("a1", "math")
        self.assertEqual([h.confidence for h in history], [0.4, 0.6, 0.85])
        self.assertEqual(self.forum.latest_skill_confidence("a1", "math"), 0.85)

    def test_skill_confidence_bounds(self) -> None:
        self.register("a1")
        for bad in (-0.1, 1.5, 0.5):
            if bad == 0.5:
                continue
            with self.assertRaises(ForumValidationError):
                self.forum.record_skill("a1", "math", confidence=bad)

    def test_skill_history_unknown_returns_empty(self) -> None:
        self.register("a1")
        self.assertEqual(self.forum.skill_history("a1", "nope"), ())
        self.assertIsNone(self.forum.latest_skill_confidence("a1", "nope"))


class SupersedeTests(ForumBase):
    def test_supersede_open_proposal(self) -> None:
        self.register("a1")
        p = self.forum.propose("a1", "idea", {})
        result = self.forum.supersede(p.proposal_id, expected_version=p.version)
        self.assertEqual(result.state, "superseded")

    def test_supersede_wrong_version(self) -> None:
        self.register("a1")
        p = self.forum.propose("a1", "idea", {})
        with self.assertRaises(ForumConflictError):
            self.forum.supersede(p.proposal_id, expected_version=99)


class IntegrityTests(ForumBase):
    def test_integrity_check_ok(self) -> None:
        self.register("a1")
        self.forum.propose("a1", "idea", {})
        self.assertEqual(self.forum.integrity_check(), "ok")

    def test_backup_produces_valid_snapshot(self) -> None:
        self.register("a1", ["math"])
        self.register("a2")
        self.forum.record_work("a1", "work")
        self.forum.record_skill("a1", "math", confidence=0.5)
        p = self.forum.propose("a1", "idea", {})
        # One agree among two eligible agents is not a majority -> stays open,
        # which the backup must preserve exactly.
        self.forum.vote(p.proposal_id, "a2", "agree")
        backup = self.forum.backup_to(str(Path(self._tmp.name) / "backup.sqlite"))
        self.assertTrue(Path(backup).exists())
        restored = SQLiteAgentForum(backup)
        self.assertEqual(len(restored.list_agents()), 2)
        self.assertEqual(restored.get_proposal(p.proposal_id).state, "open")
        self.assertEqual(restored.latest_skill_confidence("a1", "math"), 0.5)


if __name__ == "__main__":
    unittest.main()
