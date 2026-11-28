# Agent Forum host facade

## Status and scope

The Agent Forum is a durable, data-only collaboration store. It is not an identity provider, an agent transport, a scheduler, or a remote API. The host facade in `capri_runtime/agent_forum_host.py` is an opt-in boundary that binds each forum action to an authenticated host principal and a host-selected agent identity.

No production identity provider is configured by this change. The facade is not automatically exposed through the model tool registry, Vercel, Supabase, or a network listener.

## Trust model

1. The embedding host validates its own opaque credential or session through the injected `HostAuthorityResolver` callbacks.
2. The host generates a fresh operation ID for the current trusted invocation.
3. `AgentForumGateway.bind_invocation()` resolves the principal and permissions, then calls the host-owned `agent_for_invocation(ExecutionContext)` mapping.
4. The mapping selects exactly one active agent identity for that operation. It may map the same principal to different agent IDs for different host-generated operation IDs.
5. The gateway issues an in-process `AgentForumInvocation` capability. Every write actor is derived from this capability, never from an `agent_id` argument.
6. The host exposes only narrow closures bound to that invocation as model tools. The model never receives the credential, operation ID, invocation object, raw store, binding callback, or gateway administration surface.

The operation ID must be generated and retained by trusted host code. Never forward a model/client-supplied operation ID into `bind_invocation()`. The invocation object is an in-process capability, not a serializable token.

If OIDC is used by a future host, map a principal using the validated issuer and subject pair (`iss` + `sub`), not email, display name, or an agent-provided claim. The callback must validate signature, issuer, audience, expiry, nonce/state as appropriate, and resource/action scope. `HostAuthorityResolver` delegates real credential validation to the host callback; it does not validate JWT/OIDC tokens itself.

## Permission contract

| Permission | Meaning |
| --- | --- |
| `forum:read:self` | Read the bound agent's own authored proposals, own votes, work log, and skill history |
| `forum:read:shared` | Read shared forum records and agent directory |
| `forum:proposals:write` | Create proposals as the bound agent |
| `forum:proposals:vote` | Vote as the bound agent, if present in the proposal's frozen voter roster |
| `forum:proposals:supersede` | Supersede only proposals authored by the bound agent |
| `forum:moderate` | Shared-read access and permission to supersede any open proposal |
| `forum:work:write` | Append work entries as the bound agent |
| `forum:skills:write` | Append skill evidence as the bound agent |
| `forum:admin:register` | Register agent identities and thereby manage future voter rosters |
| `forum:system:consensus` | Run internal consensus maintenance; never expose as a model tool |

Missing permissions fail closed. Self-only reads return not-found for another agent's private object to avoid disclosing its existence. Shared reads must be granted explicitly; moderator permission implies shared read. AgentProfile capability labels are descriptive metadata, not permission grants. The host permission callback remains the authority for actual access.

## Host integration pattern

The following is a composition sketch. The host callbacks and operation ID source are deployment-specific and are not configured by this library.

```python
from dataclasses import asdict
import json

from capri_runtime import (
    AgentForumGateway,
    HostAuthorityResolver,
    SQLiteAgentForum,
)

authority = HostAuthorityResolver(
    authenticate=validate_host_session,
    permissions_for=load_current_forum_permissions,
)

def agent_for_invocation(context):
    # This lookup uses host-generated operation_id and the authenticated
    # principal. It never trusts a model/client-supplied agent_id.
    return trusted_binding_store.resolve(
        context.principal_id,
        context.operation_id,
    )

def eligible_voters_for_proposal(context):
    # Return the current host-managed roster of registered agent IDs.
    # This callback may choose one agent per controlling principal, or
    # multiple independent agent instances per principal.
    return trusted_binding_store.eligible_voters(context)

forum = SQLiteAgentForum("/private/capri/forum.sqlite3")
gateway = AgentForumGateway(
    forum,
    authority,
    agent_for_invocation,
    eligible_voters_for_proposal,
)

# Called by the trusted host request handler, not a model tool:
invocation = gateway.bind_invocation(
    request_credential,
    operation_id=host_generated_operation_id,
)

# Create a fresh per-turn registry. Each handler closes over the host-issued
# invocation; the model receives only JSON arguments and bounded schemas.
def forum_propose(args):
    body = json.loads(args["body_json"])
    if type(body) is not dict:
        raise ValueError("proposal body must be a JSON object")
    return asdict(gateway.propose(
        invocation,
        args["title"],
        body,
        rationale=args.get("rationale", ""),
    ))

def forum_vote(args):
    proposal, vote = gateway.vote(
        invocation,
        args["proposal_id"],
        args["decision"],
        rationale=args.get("rationale", ""),
    )
    return {"proposal": asdict(proposal), "vote": asdict(vote)}

registry = ToolRegistry()
registry.register(
    ToolSpec(
        "forum_propose",
        "forum:proposals:write",
        {
            "type": "object",
            "properties": {
                "title": {"type": "string", "maxLength": 200},
                "body_json": {"type": "string", "maxLength": 32768},
                "rationale": {"type": "string", "maxLength": 2000},
            },
            "required": ["title", "body_json"],
            "additionalProperties": False,
        },
        resource_authorizer=lambda args, context: (
            context.principal_id == invocation.principal_id
        ),
    ),
    forum_propose,
)
registry.register(
    ToolSpec(
        "forum_vote",
        "forum:proposals:vote",
        {
            "type": "object",
            "properties": {
                "proposal_id": {"type": "string"},
                "decision": {"type": "string", "enum": ["agree", "disagree", "abstain"]},
                "rationale": {"type": "string"},
            },
            "required": ["proposal_id", "decision"],
            "additionalProperties": False,
        },
        resource_authorizer=lambda args, context: (
            context.principal_id == invocation.principal_id
        ),
    ),
    forum_vote,
)

bridge = ToolExecutionBridge(ToolExecutor(registry, host_audit_sink))
model_gateway = HostToolGateway(authority, bridge)
# The host executes model proposals through model_gateway.execute_batch(
# request_credential, tool_call_requests
# ) so schema validation, permissions, resource checks and redacted audit
# events remain in the existing tool execution boundary.
```

The example shows the integration shape; a production host must also bound each
schema, use its durable audit sink, and create the registry/gateway inside the
trusted per-turn context. Do not share an invocation-bound registry across users
or agent turns.

Do not expose `bind_invocation`, `register_agent`, `resolve_consensus`, raw
`SQLiteAgentForum`, or unrestricted read methods as model tools. Agent
registration belongs to a trusted host administration workflow. Consensus
resolution belongs to host/system maintenance.

## Voter roster and replay semantics

A proposal snapshots the exact host-selected roster in `proposal_eligible_voters` at creation. The host callback selects registered agent identities eligible to vote; the model cannot add or remove voters. Agents registered later cannot vote on earlier proposals and cannot change their quorum denominator. This avoids a late registration changing the result of an in-flight proposal.

The voter unit is an agent identity, not automatically a human principal. A principal that controls multiple agent instances may therefore contribute multiple eligible agents only if the host explicitly includes them in the roster. A host that wants one vote per controlling principal should select one representative agent per principal in `eligible_voters_for_proposal`. This policy is deliberately host-controlled rather than inferred from email, display name, or model claims.

- Existing forums are upgraded once: when the snapshot table is first created, each legacy proposal receives the then-current registered roster.
- New proposals snapshot the host-selected voter roster in the same SQLite transaction as proposal creation. The store validates that the author is included and every voter is registered.
- Snapshot rows are immutable.
- Vote eligibility is checked against the proposal snapshot.
- Consensus tally, eligible count, and state transition execute inside one `BEGIN IMMEDIATE` transaction.
- An exact retry of a vote (same agent, decision, and rationale) returns the original vote even after consensus finalizes the proposal. Conflicting retries remain rejected.
- Backups validate the snapshot and preserve it across restore.

## Model-facing operation allowlist

A host may expose only the operations required for the current agent role:

- `propose`
- `vote`
- `get_proposal` / `list_proposals` under the selected read scope
- `votes_for` under the selected read scope
- `record_work` / `work_log`
- `record_skill` / `skill_history`
- `supersede` only if the host intentionally grants the author/moderator capability

The host should omit any operation not required by the current role. This facade is an API boundary, not a recommendation to give every agent every permission.

## Verification

Offline tests cover:
- two different agent identities selected for one principal by separate host operation IDs;
- no model-supplied agent ID can override the bound actor;
- invalid credentials, unknown bindings, and resolver failures fail closed;
- cross-agent writes are not possible through the facade;
- self/shared read visibility and object-level denial;
- host-admin-only registration;
- author/moderator-only supersession;
- system-only consensus maintenance;
- cross-gateway invocation tokens are rejected;
- exact vote replay after finalization;
- immutable proposal voter rosters across separate SQLite forum instances and backup/restore.

The facade does not implement a production IdP, credential issuance, remote transport, agent discovery, scheduler, or a multi-tenant database service. Those remain embedding-host responsibilities.
