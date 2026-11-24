"""Read-only Notion adapter for Capri's Neurons and Synapses data sources."""
from __future__ import annotations

import math
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from .knowledge_graph import (
    GraphNeuron, GraphSynapse, KnowledgeGraphError, KnowledgeGraphProvider,
)
from .notion_rest import NotionRESTTransport


class NotionGraphTransport(Protocol):
    def query_data_source(
        self, data_source_id: str, *, cursor: str | None = None, page_size: int = 100
    ) -> Mapping[str, object]: ...


def _uuid(value: object, field: str) -> str:
    if type(value) is not str:
        raise KnowledgeGraphError(f"{field} must be a UUID")
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise KnowledgeGraphError(f"{field} must be a UUID") from None


def _rich_text(value: object, field: str, maximum: int, *, title: bool = False) -> str:
    if type(value) is not list:
        raise KnowledgeGraphError(f"{field} must be a Notion rich-text array")
    parts: list[str] = []
    for item in value:
        if type(item) is not dict:
            raise KnowledgeGraphError(f"{field} contains a malformed rich-text item")
        text = item.get("plain_text")
        if type(text) is not str:
            nested = item.get("text")
            text = nested.get("content") if type(nested) is dict else None
        if type(text) is not str:
            raise KnowledgeGraphError(f"{field} contains unreadable rich text")
        parts.append(text)
    result = "".join(parts)
    if len(result) > maximum or (title and not result.strip()):
        raise KnowledgeGraphError(f"{field} exceeds its limit or is empty")
    return result


def _property(properties: object, name: str, kind: str) -> Mapping[str, object]:
    if type(properties) is not dict:
        raise KnowledgeGraphError("Notion page properties are missing")
    value = properties.get(name)
    if type(value) is not dict or value.get("type") != kind:
        raise KnowledgeGraphError(f"Notion property {name} has an unexpected type")
    return value


def _select(properties: object, name: str) -> str:
    item = _property(properties, name, "select").get("select")
    if type(item) is not dict or type(item.get("name")) is not str:
        raise KnowledgeGraphError(f"Notion select property {name} is malformed")
    return item["name"]


def _url(properties: object, name: str) -> str | None:
    value = _property(properties, name, "url").get("url")
    if value is not None and type(value) is not str:
        raise KnowledgeGraphError(f"Notion URL property {name} is malformed")
    return value


def _relation(properties: object, name: str) -> str:
    items = _property(properties, name, "relation").get("relation")
    if type(items) is not list or len(items) != 1 or type(items[0]) is not dict:
        raise KnowledgeGraphError(f"Notion relation {name} must contain exactly one neuron")
    return _uuid(items[0].get("id"), name)


def _number(properties: object, name: str) -> float:
    value = _property(properties, name, "number").get("number")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise KnowledgeGraphError(f"Notion number property {name} is malformed")
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        raise KnowledgeGraphError(f"Notion number property {name} is malformed") from None
    if not math.isfinite(number):
        raise KnowledgeGraphError(f"Notion number property {name} is not finite")
    return number


def _tags(properties: object) -> tuple[str, ...]:
    values = _property(properties, "Tags", "multi_select").get("multi_select")
    if type(values) is not list or len(values) > 20:
        raise KnowledgeGraphError("Notion Tags property is malformed")
    result = []
    for value in values:
        if type(value) is not dict or type(value.get("name")) is not str:
            raise KnowledgeGraphError("Notion Tags contains a malformed option")
        result.append(value["name"])
    return tuple(result)


def _timestamp(value: object, field: str) -> str:
    if type(value) is not str or not value or len(value) > 64:
        raise KnowledgeGraphError(f"Notion {field} timestamp is malformed")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone is required")
        return parsed.astimezone(timezone.utc).isoformat()
    except (OverflowError, TypeError, ValueError, OSError):
        raise KnowledgeGraphError(f"Notion {field} timestamp is malformed") from None


def _page_properties(raw: object) -> tuple[str, Mapping[str, object], str, str]:
    if type(raw) is not dict or raw.get("object") != "page":
        raise KnowledgeGraphError("Notion data source returned a non-page object")
    page_id = _uuid(raw.get("id"), "Notion page id")
    if raw.get("in_trash") is not False:
        raise KnowledgeGraphError("trashed or unclassified Notion pages are excluded")
    props = raw.get("properties")
    if type(props) is not dict:
        raise KnowledgeGraphError("Notion page properties are missing")
    created = _timestamp(raw.get("created_time"), "created_time")
    edited = _timestamp(raw.get("last_edited_time"), "last_edited_time")
    return page_id, props, created, edited


def _neuron(raw: object) -> GraphNeuron:
    page_id, props, created, edited = _page_properties(raw)
    title = _rich_text(_property(props, "Neuron", "title").get("title"), "Neuron", 200, title=True)
    notes = _rich_text(_property(props, "Notes", "rich_text").get("rich_text"), "Notes", 20_000)
    confidence = _number(props, "Confidence")
    return GraphNeuron(
        neuron_id=page_id,
        title=title,
        notes=notes,
        kind=_select(props, "Kind"),
        layer=_select(props, "Layer"),
        evidence_state=_select(props, "Evidence State"),
        confidence=confidence,
        source=_url(props, "Source"),
        tags=_tags(props),
        created_at=created,
        updated_at=edited,
    )


def _synapse(raw: object) -> GraphSynapse:
    page_id, props, _created, _edited = _page_properties(raw)
    title = _rich_text(_property(props, "Connection", "title").get("title"), "Connection", 200, title=True)
    rationale = _rich_text(_property(props, "Rationale", "rich_text").get("rich_text"), "Rationale", 4000)
    return GraphSynapse(
        synapse_id=page_id,
        title=title,
        from_neuron_id=_relation(props, "From Neuron"),
        to_neuron_id=_relation(props, "To Neuron"),
        relationship=_select(props, "Relationship"),
        rationale=rationale,
        evidence=_url(props, "Evidence"),
        strength=_number(props, "Strength"),
        status=_select(props, "Status"),
    )


class NotionKnowledgeGraphProvider:
    """Load a bounded graph snapshot from two sequential Notion data-source reads.

    Notion does not provide a transaction spanning these data sources, so the
    result is not an atomic cross-database snapshot. The transport is injected.
    This adapter never writes to Notion and fails closed on malformed relations,
    missing fields, duplicate IDs, or pagination beyond the configured maximum.
    """
    def __init__(
        self,
        transport: NotionGraphTransport,
        neuron_data_source_id: str,
        synapse_data_source_id: str,
        *,
        page_size: int = 100,
        max_neurons: int = 1000,
        max_synapses: int = 5000,
    ) -> None:
        if not callable(getattr(transport, "query_data_source", None)):
            raise KnowledgeGraphError("transport must implement query_data_source()")
        self.transport = transport
        self.neuron_data_source_id = _uuid(neuron_data_source_id, "neuron data source id")
        self.synapse_data_source_id = _uuid(synapse_data_source_id, "synapse data source id")
        if self.neuron_data_source_id == self.synapse_data_source_id:
            raise KnowledgeGraphError("neuron and synapse data sources must be distinct")
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise KnowledgeGraphError("page_size must be between one and one hundred")
        if type(max_neurons) is not int or not 1 <= max_neurons <= 1000:
            raise KnowledgeGraphError("max_neurons must be between one and one thousand")
        if type(max_synapses) is not int or not 1 <= max_synapses <= 5000:
            raise KnowledgeGraphError("max_synapses must be between one and five thousand")
        self.page_size = page_size
        self.max_neurons = max_neurons
        self.max_synapses = max_synapses

    def _load(self, data_source_id: str, maximum: int, parser):
        records = []
        cursor = None
        seen_cursors = set()
        while True:
            page = self.transport.query_data_source(
                data_source_id, cursor=cursor, page_size=self.page_size
            )
            if (
                not isinstance(page, Mapping)
                or type(page.get("results")) is not list
                or "next_cursor" not in page
            ):
                raise KnowledgeGraphError("Notion graph transport returned malformed pagination")
            records.extend(parser(raw) for raw in page["results"])
            if len(records) > maximum:
                raise KnowledgeGraphError("Notion graph exceeds the configured record limit")
            next_cursor = page.get("next_cursor")
            if next_cursor is None:
                break
            if not page["results"]:
                raise KnowledgeGraphError("Notion graph pagination advanced without returning records")
            if type(next_cursor) is not str or not next_cursor or next_cursor in seen_cursors:
                raise KnowledgeGraphError("Notion graph pagination cursor is invalid or repeated")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        return tuple(records)

    def load_graph(self) -> tuple[tuple[GraphNeuron, ...], tuple[GraphSynapse, ...]]:
        neurons = self._load(self.neuron_data_source_id, self.max_neurons, _neuron)
        synapses = self._load(self.synapse_data_source_id, self.max_synapses, _synapse)
        neuron_ids = {item.neuron_id for item in neurons}
        if len(neuron_ids) != len(neurons):
            raise KnowledgeGraphError("Notion Neurons contains duplicate page IDs")
        synapse_ids = {item.synapse_id for item in synapses}
        if len(synapse_ids) != len(synapses):
            raise KnowledgeGraphError("Notion Synapses contains duplicate page IDs")
        if any(edge.from_neuron_id not in neuron_ids or edge.to_neuron_id not in neuron_ids for edge in synapses):
            raise KnowledgeGraphError("Notion Synapses contains a dangling endpoint")
        return neurons, synapses


def create_notion_knowledge_graph_provider_from_environment(
    neuron_data_source_id: str,
    synapse_data_source_id: str,
    *,
    token_env: str = "NOTION_API_TOKEN",
    timeout: float = 10.0,
    opener=None,
) -> NotionKnowledgeGraphProvider:
    """Construct an injected-token, read-only graph provider; no write or live LLM call."""
    if type(token_env) is not str or not token_env:
        raise KnowledgeGraphError("token_env must be a non-empty environment variable name")
    token = os.environ.get(token_env)
    if not token:
        raise KnowledgeGraphError(f"{token_env} is not configured")
    transport = NotionRESTTransport(token, neuron_data_source_id, timeout=timeout, opener=opener)
    return NotionKnowledgeGraphProvider(
        transport, neuron_data_source_id, synapse_data_source_id
    )
