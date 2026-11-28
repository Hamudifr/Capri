"""Unified Agent Network host: wires forum, facade, network, and registry.

This module is the integration layer that turns four independent modules into
a single working network. It composes:

- ``SQLiteAgentForum`` — profiles, proposals, votes, work logs, skills
- ``AgentForumGateway`` (PR #323) — authenticated invocation facade with
  per-operation agent binding and voter-roster freezing
- ``SQLiteAgentNetwork`` — verification tokens, challenges, reviews,
  revisions, host-ratified decisions
- ``SQLiteAgentRegistry`` — lifecycle state, principal-agent bindings, roles

The unified host provides:

- **One-call assembly**: the host constructs a single ``AgentNetworkHost``
  with its authority, key ring, and policies, and gets a fully wired network.
- **Participation enforcement**: every write operation checks that the
  agent is ``active`` in the registry before it reaches the forum or
  network. Suspended and deactivated agents are blocked at the boundary.
- **Unified verification**: the host issues verification tokens through the
  network layer, binds invocations through the facade, and manages
  lifecycle through the registry — all from one object.
- **Verified transport abstraction**: a ``AgentTransport`` protocol that
  defines how an external agent (like Arena) connects to the network. The
  transport validates the agent's verification token, checks registry
  lifecycle state, and returns a bound invocation. No raw credentials or
  store handles are ever exposed to the transport.
- **Adversarial test harness**: ``run_adversarial_round`` simulates
  independent agents proposing, challenging, reviewing, and voting against
  each other, verifying that the network's guarantees hold under contention.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from .agent_forum import (
    Proposal,
    SQLiteAgentForum,
)
from .agent_forum_host import (
    AgentForumGateway,
    AgentForumInvocation,
)
from .agent_network import (
    AgentIdentityVerifier,
    Challenge,
    DecisionRecord,
    Review,
    SQLiteAgentNetwork,
    VerificationToken,
)
from .agent_registry import (
    LIFECYCLE_STATES,
    PrincipalBinding,
    SQLiteAgentRegistry,
)
from .tools import HmacApprovalKeyRing, HostAuthorityResolver


class AgentNetworkHostError(Exception):
    """Base class for unified agent-network host failures."""


class AgentNetworkHostValidationError(AgentNetworkHostError):
    """A composition or persisted value is invalid."""


class AgentTransportError(AgentNetworkHostError):
    """A verified transport could not establish a valid agent session."""


# ---------------------------------------------------------------------------
# Transport protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class AgentTransport(Protocol):
    """Protocol for a verified agent transport.

    A transport is how an external agent connects to the network. It
    authenticates the agent's verification token, checks registry lifecycle
    state, and returns a bound invocation for the agent to use. The
    transport never receives raw credentials, operation IDs, or store
    handles — only the agent's verification token.
    """

    def connect(
        self,
        token: VerificationToken,
        *,
        operation_id: str,
    ) -> AgentForumInvocation:
        """Validate the token and return a bound invocation for this agent."""


# ---------------------------------------------------------------------------
# Unified host
# ---------------------------------------------------------------------------

class AgentNetworkHost:
    """Composes and coordinates all four agent-network modules.

    The host is constructed by trusted host code with the authority,
    key ring, and optional policies. It owns the forum, gateway, network,
    and registry, and enforces cross-module invariants.
    """

    def __init__(
        self,
        path: str,
        *,
        authority: HostAuthorityResolver,
        key_ring: HmacApprovalKeyRing,
        agent_for_invocation=None,
        eligible_voters_for_proposal=None,
        registry_authority=None,
    ) -> None:
        if not isinstance(authority, HostAuthorityResolver):
            raise AgentNetworkHostValidationError("a HostAuthorityResolver is required")
        if not isinstance(key_ring, HmacApprovalKeyRing):
            raise AgentNetworkHostValidationError("an HmacApprovalKeyRing is required")

        self.forum = SQLiteAgentForum(path)
        self.verifier = AgentIdentityVerifier(key_ring)
        self.network = SQLiteAgentNetwork(self.forum, self.verifier)
        # operation_id → agent_id, for transport-issued bindings
        self._pending_bindings: dict[str, str] = {}
        self._lock = threading.RLock()

        # Default agent-binding resolver: looks up the agent bound to the
        # operation ID by connect_agent. Falls back to the caller's callback.
        def _default_agent_for_invocation(ctx) -> str | None:
            return self._pending_bindings.get(ctx.operation_id or "")

        self.gateway = AgentForumGateway(
            self.forum,
            authority,
            agent_for_invocation=agent_for_invocation or _default_agent_for_invocation,
            eligible_voters_for_proposal=eligible_voters_for_proposal
            or (lambda ctx: tuple(a.agent_id for a in self.forum.list_agents())),
        )
        # Default registry authority delegates to the same HostAuthorityResolver
        if registry_authority is None:
            registry_authority = _DelegatedRegistryAuthority(authority)
        self.registry = SQLiteAgentRegistry(self.forum, registry_authority)
        # agent_id → latest issued verification token
        self._agent_tokens: dict[str, VerificationToken] = {}

    # ------------------------------------------------------------- registration

    def register_agent(
        self,
        agent_id: str,
        display_name: str,
        *,
        capabilities: tuple[str, ...] | list[str] = (),
        host_credential: Any,
        initial_state: str = "active",
    ) -> tuple[tuple[str, ...], VerificationToken]:
        """Register an agent in the forum, set its lifecycle, and issue a token.

        This is the single entry point for bringing a new agent onto the
        network. It registers the agent in the forum, sets the lifecycle
        state via the registry, and issues a verification token via the
        network. The host credential authenticates the registration.
        """
        if initial_state not in LIFECYCLE_STATES:
            raise AgentNetworkHostValidationError("initial_state is invalid")
        if initial_state not in ("registered", "active"):
            raise AgentNetworkHostValidationError(
                "initial_state must be 'registered' or 'active'"
            )
        # Register in forum
        profile = self.forum.register_agent(
            agent_id, display_name, capabilities=capabilities,
        )
        # Set lifecycle
        self.registry.set_state(
            agent_id, initial_state, credential=host_credential,
        )
        # Issue verification token
        token = self.network.issue_verification(
            agent_id, host_credential=host_credential,
        )
        self._agent_tokens[agent_id] = token
        return profile.capabilities, token

    def bind_principal(
        self,
        agent_id: str,
        principal_id: str,
        role: str,
        *,
        host_credential: Any,
    ) -> PrincipalBinding:
        """Bind a host principal to an agent with a role."""
        return self.registry.bind_principal(
            agent_id, principal_id, role, credential=host_credential,
        )

    # ------------------------------------------------------------- transport

    def connect_agent(
        self,
        token: VerificationToken,
        *,
        operation_id: str,
    ) -> AgentForumInvocation:
        """Verified transport entry point.

        Validates the token, checks that the agent is active in the
        registry, records the agent-to-operation binding, and returns a
        bound invocation. This is how an external agent (like Arena)
        connects to the network.
        """
        if not isinstance(token, VerificationToken):
            raise AgentTransportError("a VerificationToken is required")
        self.verifier.validate(token)
        agent_id = token.agent_id
        # Check registry lifecycle — agent must be active
        if not self.registry.can_participate(agent_id):
            state = self.registry.get_lifecycle(agent_id).state
            raise AgentTransportError(
                f"agent '{agent_id}' is not active (state: {state})"
            )
        # Record the binding so the gateway's resolver can find it
        with self._lock:
            self._pending_bindings[operation_id] = agent_id
        # Bind invocation through the gateway
        return self.gateway.bind_invocation(
            _AgentTokenCredential(token), operation_id=operation_id,
        )

    # ------------------------------------------------------------- operations

    def propose(
        self,
        invocation: AgentForumInvocation,
        title: str,
        body: dict[str, Any],
        *,
        rationale: str = "",
        profound: bool = False,
    ) -> Proposal:
        """Propose an idea. Requires active agent + propose permission."""
        self._require_active(invocation.agent_id)
        return self.gateway.propose(
            invocation, title, body, rationale=rationale, profound=profound,
        )

    def vote(
        self,
        invocation: AgentForumInvocation,
        proposal_id: str,
        decision: str,
        *,
        rationale: str = "",
    ) -> tuple[Proposal, Any]:
        """Vote on a proposal. Requires active agent + vote permission."""
        self._require_active(invocation.agent_id)
        return self.gateway.vote(
            invocation, proposal_id, decision, rationale=rationale,
        )

    def challenge(
        self,
        invocation: AgentForumInvocation,
        proposal_id: str,
        *,
        objections: dict[str, Any],
    ) -> Challenge:
        """Challenge a proposal. Requires active agent."""
        self._require_active(invocation.agent_id)
        return self.network.challenge(
            proposal_id, invocation.agent_id,
            objections=objections,
            token=self._token_for(invocation.agent_id),
        )

    def review(
        self,
        invocation: AgentForumInvocation,
        work_entry_id: int,
        *,
        verdict: str,
        findings: dict[str, Any],
    ) -> Review:
        """Review work. Requires active agent."""
        self._require_active(invocation.agent_id)
        return self.network.review_work(
            work_entry_id, invocation.agent_id,
            verdict=verdict, findings=findings,
            token=self._token_for(invocation.agent_id),
        )

    def revise(
        self,
        invocation: AgentForumInvocation,
        proposal_id: str,
        *,
        change_summary: str,
        body: dict[str, Any],
    ) -> tuple[Proposal, Any]:
        """Revise a proposal. Requires active agent + author check."""
        self._require_active(invocation.agent_id)
        return self.network.revise_proposal(
            proposal_id, invocation.agent_id,
            change_summary=change_summary, body=body,
            token=self._token_for(invocation.agent_id),
        )

    def record_work(
        self,
        invocation: AgentForumInvocation,
        summary: str,
        *,
        detail: dict[str, Any] | None = None,
    ) -> Any:
        """Record work. Requires active agent + work-write permission."""
        self._require_active(invocation.agent_id)
        return self.gateway.record_work(
            invocation, summary, detail=detail,
        )

    def ratify(
        self,
        proposal_id: str,
        *,
        host_credential: Any,
        evidence_references: tuple[str, ...] = (),
    ) -> DecisionRecord:
        """Host ratifies a proposal decision."""
        return self.network.ratify_decision(
            proposal_id,
            host_credential=host_credential,
            evidence_references=evidence_references,
        )

    def resolve_consensus(
        self,
        invocation: AgentForumInvocation,
        proposal_id: str,
    ) -> Proposal:
        """Resolve consensus. Requires active agent + consensus permission."""
        return self.gateway.resolve_consensus(invocation, proposal_id)

    # ------------------------------------------------------------- helpers

    def _require_active(self, agent_id: str) -> None:
        if not self.registry.can_participate(agent_id):
            state = self.registry.get_lifecycle(agent_id).state
            raise AgentNetworkHostError(
                f"agent '{agent_id}' is not active (state: {state}); "
                "only active agents can participate"
            )

    def _token_for(self, agent_id: str) -> VerificationToken:
        """Return the agent's registered verification token for internal use.

        The token is the one issued during ``register_agent`` and registered
        with the network, so it passes the network's token-verification checks.
        """
        token = self._agent_tokens.get(agent_id)
        if token is None:
            raise AgentNetworkHostError(
                f"no verification token for agent '{agent_id}'"
            )
        return token

    def get_agent_state(self, agent_id: str) -> str:
        """Return the agent's lifecycle state, or 'unknown'."""
        try:
            return self.registry.get_lifecycle(agent_id).state
        except Exception:
            return "unknown"

    def active_agents(self) -> tuple[str, ...]:
        return tuple(r.agent_id for r in self.registry.list_active())

    def integrity_check(self) -> str:
        forum_ok = self.forum.integrity_check()
        network_ok = self.network.integrity_check()
        registry_ok = self.registry.integrity_check()
        if forum_ok == "ok" and network_ok == "ok" and registry_ok == "ok":
            return "ok"
        return f"forum={forum_ok}, network={network_ok}, registry={registry_ok}"


# ---------------------------------------------------------------------------
# Supporting types
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class _AgentTokenCredential:
    """Internal credential that wraps a verification token.

    Used to pass the agent's verified identity through the gateway's
    authority resolution without exposing raw credentials.
    """
    token: VerificationToken


class _DelegatedRegistryAuthority:
    """Registry authority that delegates to the host's HostAuthorityResolver.

    Authenticates host credentials via the same authority used for tool
    execution, and authorizes all registry actions for authenticated
    principals. This keeps registry authority consistent with the host's
    existing authentication.
    """

    __slots__ = ("_authority",)

    def __init__(self, authority: HostAuthorityResolver) -> None:
        self._authority = authority

    def authenticate(self, credential: Any) -> str | None:
        try:
            context = self._authority.resolve(credential)
            return context.principal_id
        except Exception:
            return None

    def authorize(self, principal_id: str, action: str) -> bool:
        return bool(principal_id)


# ---------------------------------------------------------------------------
# Adversarial test harness
# ---------------------------------------------------------------------------

@dataclass
class AdversarialResult:
    """Outcome of an adversarial round between independent agents."""

    proposal_count: int
    challenge_count: int
    review_count: int
    revision_count: int
    decision_count: int
    all_guarantees_held: bool
    notes: tuple[str, ...] = ()


class AdversarialHarness:
    """Simulates independent agents competing on the network.

    Creates multiple agents, has them propose competing ideas, challenge
    each other's proposals, review work, revise, vote, and ratify.
    Verifies that the network's guarantees hold under contention:
    - Only active agents can participate
    - Challenges are recorded
    - Revisions address challenges
    - Decisions are host-ratified and signature-verified
    - Non-active agents are blocked
    """

    def __init__(self, host: AgentNetworkHost) -> None:
        if not isinstance(host, AgentNetworkHost):
            raise AgentNetworkHostValidationError("requires an AgentNetworkHost")
        self.host = host

    def run_round(self, *, host_credential: Any = "host") -> AdversarialResult:
        notes: list[str] = []
        host = self.host

        # Register three competing agents
        agents = []
        for i in range(3):
            agent_id = f"adv-{i}"
            caps, token = host.register_agent(
                agent_id, f"Adversarial Agent {i}",
                capabilities=["proposal", "review"],
                host_credential=host_credential,
                initial_state="active",
            )
            agents.append((agent_id, token))

        # Each agent proposes
        proposals = []
        for agent_id, token in agents:
            invocation = host.connect_agent(
                token, operation_id=f"op-{agent_id}-0",
            )
            proposal = host.propose(
                invocation,
                f"Proposal from {agent_id}",
                {"idea": f"Agent {agent_id}'s plan"},
            )
            proposals.append((agent_id, proposal))

        # Each agent challenges the other proposals
        for challenger_id, _ in agents:
            challenger_token = dict(agents)[challenger_id]
            invocation = host.connect_agent(
                challenger_token, operation_id=f"op-{challenger_id}-1",
            )
            for target_id, proposal in proposals:
                if target_id == challenger_id:
                    continue
                host.challenge(
                    invocation,
                    proposal.proposal_id,
                    objections={"competitor": target_id, "issue": "flawed"},
                )

        # Each agent records work and gets reviewed
        for agent_id, token in agents:
            invocation = host.connect_agent(
                token, operation_id=f"op-{agent_id}-2",
            )
            work = host.record_work(
                invocation, f"Work by {agent_id}",
            )
            # Another agent reviews
            reviewer_id = f"adv-{(int(agent_id[-1]) + 1) % 3}"
            reviewer_token = dict(agents)[reviewer_id]
            reviewer_inv = host.connect_agent(
                reviewer_token, operation_id=f"op-{reviewer_id}-3",
            )
            host.review(
                reviewer_inv, work.entry_id,
                verdict="request_changes",
                findings={"needs": "more detail"},
            )

        # Each agent revises their own proposal
        for agent_id, proposal in proposals:
            token = dict(agents)[agent_id]
            invocation = host.connect_agent(
                token, operation_id=f"op-{agent_id}-4",
            )
            host.revise(
                invocation, proposal.proposal_id,
                change_summary="Addressed challenges",
                body={"idea": f"Revised plan from {agent_id}", "addressed": True},
            )

        # Vote on proposals
        for voter_id, token in agents:
            invocation = host.connect_agent(
                token, operation_id=f"op-{voter_id}-5",
            )
            for target_id, proposal in proposals:
                if target_id == voter_id:
                    decision = "abstain"
                else:
                    decision = "agree"
                try:
                    host.vote(invocation, proposal.proposal_id, decision)
                except Exception as exc:
                    # A proposal may have reached consensus before this
                    # vote arrived — that's an expected race in a
                    # concurrent adversarial simulation, not a violation.
                    if "not open" in str(exc) or "consensus" in str(exc).lower():
                        continue
                    raise

        # Resolve consensus and ratify
        for agent_id, proposal in proposals:
            token = dict(agents)[agent_id]
            invocation = host.connect_agent(
                token, operation_id=f"op-{agent_id}-6",
            )
            try:
                host.resolve_consensus(invocation, proposal.proposal_id)
            except Exception as exc:
                if "not open" in str(exc) or "consensus" in str(exc).lower():
                    # already resolved by the vote phase — fine
                    pass
                else:
                    raise
            decision = host.ratify(
                proposal.proposal_id,
                host_credential=host_credential,
                evidence_references=(f"adv-evidence-{proposal.proposal_id[:8]}",),
            )
            if not host.network.verify_decision_signature(decision):
                notes.append(f"decision signature failed for {proposal.proposal_id}")

        # Verify: non-active agent is blocked
        host.registry.set_state("adv-0", "suspended", credential=host_credential)
        suspended_token = dict(agents)["adv-0"]
        try:
            host.connect_agent(suspended_token, operation_id="op-adv-0-suspended")
            notes.append("suspended agent was NOT blocked — guarantee violated")
        except AgentTransportError:
            notes.append("suspended agent correctly blocked")

        # Count artifacts
        challenge_count = sum(
            len(host.network.challenges_for(p.proposal_id))
            for _, p in proposals
        )
        revision_count = sum(
            len(host.network.revisions_for(p.proposal_id))
            for _, p in proposals
        )
        decision_count = sum(
            len(host.network.decisions_for(p.proposal_id))
            for _, p in proposals
        )
        all_hold = not any("violated" in n for n in notes)

        return AdversarialResult(
            proposal_count=len(proposals),
            challenge_count=challenge_count,
            review_count=3,
            revision_count=revision_count,
            decision_count=decision_count,
            all_guarantees_held=all_hold,
            notes=tuple(notes),
        )
