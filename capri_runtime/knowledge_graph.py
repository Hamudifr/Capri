"""Deterministic, bounded retrieval over Capri's evidence-aware knowledge graph.

All graph records are untrusted data. Retrieval is read-only and never grants
instructions, permissions, identity, or tool authority.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from collections import deque
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit
from uuid import UUID


class KnowledgeGraphError(ValueError):
    """Graph input or retrieval output violates the bounded contract."""


_EVIDENCE_RANK = {
    "Verified": 5, "Reported": 4, "Inferred": 3,
    "Unverified": 2, "Disputed": 1, "Superseded": 0,
}
_RELATIONSHIPS = {
    "Supports", "Contradicts", "Depends on", "Derived from",
    "Supersedes", "Related to", "Implements", "Part of",
}
_ACTIVE_EDGE_STATES = {"Active"}
_TOKEN_RE = re.compile(r"[\w-]{2,}", re.UNICODE)


def _text(value: object, field: str, maximum: int, *, empty: bool = False) -> str:
    if type(value) is not str or len(value) > maximum or (not empty and not value.strip()):
        raise KnowledgeGraphError(f"{field} is invalid")
    if any(0xD800 <= ord(ch) <= 0xDFFF for ch in value):
        raise KnowledgeGraphError(f"{field} contains invalid Unicode")
    return value


def _uuid(value: object, field: str) -> str:
    if type(value) is not str:
        raise KnowledgeGraphError(f"{field} must be a UUID")
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise KnowledgeGraphError(f"{field} must be a UUID") from None


def _source(value: object) -> str | None:
    if value is None or value == "":
        return None
    source = _text(value, "source", 2048)
    try:
        parsed = urlsplit(source)
        port = parsed.port
    except ValueError:
        raise KnowledgeGraphError("source URL is malformed") from None
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or port == 0:
        raise KnowledgeGraphError("source must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise KnowledgeGraphError("source URL must not contain credentials")
    return source


@dataclass(frozen=True, slots=True)
class GraphNeuron:
    neuron_id: str
    title: str
    notes: str
    kind: str
    layer: str
    evidence_state: str
    confidence: float
    source: str | None = None
    tags: tuple[str, ...] = ()
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "neuron_id", _uuid(self.neuron_id, "neuron_id"))
        _text(self.title, "title", 200)
        _text(self.notes, "notes", 20_000, empty=True)
        if self.kind not in {"Fact", "Concept", "Rule", "Skill", "Memory", "Task", "Evidence", "Hypothesis"}:
            raise KnowledgeGraphError("neuron kind is unsupported")
        if self.layer not in {"Input", "Validation", "Memory", "Reasoning", "Decision", "Output", "Feedback"}:
            raise KnowledgeGraphError("neuron layer is unsupported")
        if self.evidence_state not in _EVIDENCE_RANK:
            raise KnowledgeGraphError("neuron evidence state is unsupported")
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)) or not 0 <= self.confidence <= 1:
            raise KnowledgeGraphError("neuron confidence must be between zero and one")
        object.__setattr__(self, "source", _source(self.source))
        if type(self.tags) is not tuple or len(self.tags) > 20:
            raise KnowledgeGraphError("neuron tags must be a bounded immutable tuple")
        for tag in self.tags:
            _text(tag, "tag", 64)
        _text(self.created_at, "created_at", 64, empty=True)
        _text(self.updated_at, "updated_at", 64, empty=True)


@dataclass(frozen=True, slots=True)
class GraphSynapse:
    synapse_id: str
    title: str
    from_neuron_id: str
    to_neuron_id: str
    relationship: str
    rationale: str
    evidence: str | None
    strength: float
    status: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "synapse_id", _uuid(self.synapse_id, "synapse_id"))
        object.__setattr__(self, "from_neuron_id", _uuid(self.from_neuron_id, "from_neuron_id"))
        object.__setattr__(self, "to_neuron_id", _uuid(self.to_neuron_id, "to_neuron_id"))
        _text(self.title, "title", 200)
        if self.relationship not in _RELATIONSHIPS:
            raise KnowledgeGraphError("synapse relationship is unsupported")
        _text(self.rationale, "rationale", 4000, empty=True)
        object.__setattr__(self, "evidence", _source(self.evidence))
        if isinstance(self.strength, bool) or not isinstance(self.strength, (int, float)) or not 0 <= self.strength <= 1:
            raise KnowledgeGraphError("synapse strength must be between zero and one")
        if self.status not in {"Active", "Proposed", "Rejected", "Superseded"}:
            raise KnowledgeGraphError("synapse status is unsupported")
        if self.from_neuron_id == self.to_neuron_id:
            raise KnowledgeGraphError("self-referential synapses are not supported")


class KnowledgeGraphProvider(Protocol):
    def load_graph(self) -> tuple[tuple[GraphNeuron, ...], tuple[GraphSynapse, ...]]:
        """Return a bounded immutable snapshot; implementations must be read-only."""
        ...


@dataclass(frozen=True, slots=True)
class UntrustedKnowledgeContext:
    neurons: tuple[GraphNeuron, ...]
    synapses: tuple[GraphSynapse, ...]
    query: str
    truncated: bool = False

    def __post_init__(self) -> None:
        if type(self.neurons) is not tuple or len(self.neurons) > 20:
            raise KnowledgeGraphError("knowledge context allows at most 20 neurons")
        if type(self.synapses) is not tuple or len(self.synapses) > 40:
            raise KnowledgeGraphError("knowledge context allows at most 40 synapses")
        _text(self.query, "query", 4000)
        neuron_ids = [n.neuron_id for n in self.neurons]
        if len(neuron_ids) != len(set(neuron_ids)):
            raise KnowledgeGraphError("knowledge context contains duplicate neurons")
        synapse_ids = [s.synapse_id for s in self.synapses]
        if len(synapse_ids) != len(set(synapse_ids)):
            raise KnowledgeGraphError("knowledge context contains duplicate synapses")
        known = set(neuron_ids)
        if any(s.from_neuron_id not in known or s.to_neuron_id not in known for s in self.synapses):
            raise KnowledgeGraphError("knowledge context contains a dangling synapse")
        if type(self.truncated) is not bool:
            raise KnowledgeGraphError("truncated must be a boolean")
        if len(serialize_untrusted_knowledge_context(self).encode("utf-8")) > 100_000:
            raise KnowledgeGraphError("serialized knowledge context exceeds 100 KB")


def _freshness(value: str) -> float:
    if not value:
        return 0.0
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.timestamp() if parsed.tzinfo is not None else 0.0
    except (ValueError, OverflowError, OSError):
        return 0.0


def _tokens(value: str) -> set[str]:
    return {part.casefold() for part in _TOKEN_RE.findall(value)}


def _score(query_tokens: set[str], neuron: GraphNeuron) -> float:
    title = _tokens(neuron.title)
    notes = _tokens(neuron.notes)
    tags = {tag.casefold() for tag in neuron.tags}
    if not query_tokens:
        return 0.0
    title_hits = len(query_tokens & title)
    note_hits = len(query_tokens & notes)
    tag_hits = len(query_tokens & tags)
    coverage = len(query_tokens & (title | notes | tags)) / len(query_tokens)
    return (title_hits * 4.0 + tag_hits * 2.0 + note_hits) * coverage


def retrieve_knowledge(
    query: str,
    provider: KnowledgeGraphProvider,
    *,
    max_hops: int = 1,
    max_neurons: int = 20,
    max_synapses: int = 40,
    include_history: bool = False,
) -> UntrustedKnowledgeContext:
    """Rank query seeds and traverse active edges breadth-first within hard caps."""
    _text(query, "query", 4000)
    if isinstance(max_hops, bool) or type(max_hops) is not int or not 0 <= max_hops <= 2:
        raise KnowledgeGraphError("max_hops must be between zero and two")
    if type(max_neurons) is not int or not 1 <= max_neurons <= 20:
        raise KnowledgeGraphError("max_neurons must be between one and twenty")
    if type(max_synapses) is not int or not 0 <= max_synapses <= 40:
        raise KnowledgeGraphError("max_synapses must be between zero and forty")
    if type(include_history) is not bool:
        raise KnowledgeGraphError("include_history must be a boolean")
    loaded = provider.load_graph()
    if type(loaded) is not tuple or len(loaded) != 2:
        raise KnowledgeGraphError("provider returned an invalid graph snapshot")
    neurons, synapses = loaded
    if type(neurons) is not tuple or type(synapses) is not tuple or len(neurons) > 1000 or len(synapses) > 5000:
        raise KnowledgeGraphError("provider graph snapshot exceeds hard limits")
    by_id: dict[str, GraphNeuron] = {}
    for neuron in neurons:
        if type(neuron) is not GraphNeuron or neuron.neuron_id in by_id:
            raise KnowledgeGraphError("provider returned invalid or duplicate neurons")
        by_id[neuron.neuron_id] = neuron
    edge_ids: set[str] = set()
    valid_edges: list[GraphSynapse] = []
    for edge in synapses:
        if type(edge) is not GraphSynapse or edge.synapse_id in edge_ids:
            raise KnowledgeGraphError("provider returned invalid or duplicate synapses")
        edge_ids.add(edge.synapse_id)
        if edge.from_neuron_id not in by_id or edge.to_neuron_id not in by_id:
            raise KnowledgeGraphError("provider returned a dangling synapse endpoint")
        if edge.status == "Active":
            valid_edges.append(edge)
    tokens = _tokens(query)
    candidates = [
        n for n in neurons
        if (include_history or n.evidence_state != "Superseded")
        and _score(tokens, n) > 0
    ]
    candidates.sort(key=lambda n: (
        -_score(tokens, n), -_EVIDENCE_RANK[n.evidence_state],
        -float(n.confidence), n.title.casefold(), n.neuron_id,
    ))
    if not candidates:
        return UntrustedKnowledgeContext((), (), query)
    selected: dict[str, GraphNeuron] = {}
    selected_edges: dict[str, GraphSynapse] = {}
    queue: deque[tuple[str, int]] = deque()
    seed_limit = min(5, max_neurons)
    truncated = len(candidates) > seed_limit
    for neuron in candidates[:seed_limit]:
        selected[neuron.neuron_id] = neuron
        queue.append((neuron.neuron_id, 0))
    adjacency: dict[str, list[GraphSynapse]] = {}
    for edge in valid_edges:
        adjacency.setdefault(edge.from_neuron_id, []).append(edge)
        adjacency.setdefault(edge.to_neuron_id, []).append(edge)
    for items in adjacency.values():
        items.sort(key=lambda e: (e.relationship, e.synapse_id))
    while queue and len(selected) < max_neurons and len(selected_edges) < max_synapses:
        current, depth = queue.popleft()
        if depth >= max_hops:
            continue
        for edge in adjacency.get(current, ()):
            if edge.synapse_id in selected_edges:
                continue
            left, right = by_id[edge.from_neuron_id], by_id[edge.to_neuron_id]
            is_contradiction = edge.relationship == "Contradicts"
            is_supersession = edge.relationship == "Supersedes"
            if not include_history and is_supersession:
                continue
            # Contradiction edges deliberately preserve both claims, even when one
            # is marked Superseded. Its lifecycle label remains visible to the LLM.
            neighbor_id = edge.to_neuron_id if current == edge.from_neuron_id else edge.from_neuron_id
            neighbor = by_id[neighbor_id]
            if neighbor.evidence_state == "Superseded" and not (include_history or is_contradiction):
                continue
            if len(selected_edges) >= max_synapses:
                break
            selected_edges[edge.synapse_id] = edge
            if neighbor_id not in selected and len(selected) < max_neurons:
                selected[neighbor_id] = neighbor
                queue.append((neighbor_id, depth + 1))
            if is_contradiction:
                for endpoint in (left, right):
                    if endpoint.neuron_id not in selected and len(selected) < max_neurons:
                        selected[endpoint.neuron_id] = endpoint
                        queue.append((endpoint.neuron_id, depth + 1))
    if queue and (len(selected) >= max_neurons or len(selected_edges) >= max_synapses):
        truncated = True
    ordered_neurons = tuple(sorted(
        selected.values(),
        key=lambda n: (
            -_score(tokens, n), -_EVIDENCE_RANK[n.evidence_state],
            -float(n.confidence), 0 if n.source else 1,
            -_freshness(n.updated_at), n.title.casefold(), n.neuron_id,
        ),
    ))
    ordered_edges = tuple(sorted(selected_edges.values(), key=lambda e: e.synapse_id))
    return UntrustedKnowledgeContext(ordered_neurons, ordered_edges, query, truncated)


def serialize_untrusted_knowledge_context(context: UntrustedKnowledgeContext) -> str:
    """Serialize graph data with provenance as escaped JSON, never as instructions."""
    if type(context) is not UntrustedKnowledgeContext:
        raise KnowledgeGraphError("context must be an exact UntrustedKnowledgeContext")
    payload = {
        "format": "capri.untrusted-knowledge.v1",
        "query": context.query,
        "truncated": context.truncated,
        "neurons": [{
            "id": n.neuron_id, "title": n.title, "notes": n.notes,
            "kind": n.kind, "layer": n.layer, "evidence_state": n.evidence_state,
            "confidence": n.confidence, "source": n.source, "tags": list(n.tags),
            "created_at": n.created_at, "updated_at": n.updated_at,
        } for n in context.neurons],
        "synapses": [{
            "id": e.synapse_id, "title": e.title, "from": e.from_neuron_id,
            "to": e.to_neuron_id, "relationship": e.relationship,
            "rationale": e.rationale, "evidence": e.evidence,
            "strength": e.strength, "status": e.status,
        } for e in context.synapses],
    }
    encoded = json.dumps(payload, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))
    encoded = encoded.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    return f"<untrusted_text>{encoded}</untrusted_text>"


class InMemoryKnowledgeGraphProvider:
    """Immutable fixture/provider useful for offline tests and local graph snapshots."""
    def __init__(self, neurons: tuple[GraphNeuron, ...], synapses: tuple[GraphSynapse, ...]) -> None:
        self._neurons = tuple(neurons)
        self._synapses = tuple(synapses)

    def load_graph(self) -> tuple[tuple[GraphNeuron, ...], tuple[GraphSynapse, ...]]:
        return self._neurons, self._synapses
