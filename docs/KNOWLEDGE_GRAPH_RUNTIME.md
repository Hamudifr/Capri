# Knowledge graph runtime

## Status

Implemented as an offline-capable, read-only retrieval layer. The graph provider reads the Notion Neurons and Synapses data sources through the existing injected-token Notion REST transport. It does not write to Notion, call an embedding service, or make an LLM request.

## Runtime composition

- `GraphNeuron` and `GraphSynapse` are immutable, validated records.
- `KnowledgeGraphProvider` is the provider-neutral snapshot interface.
- `NotionKnowledgeGraphProvider` pages through the two configured Notion data sources and rejects malformed properties, duplicate IDs, dangling endpoints, invalid relations, and snapshots above configured limits. The two reads are sequential, not an atomic cross-database transaction, so concurrent edits can produce a mixed-time snapshot.
- `retrieve_knowledge()` ranks direct lexical matches by relevance, evidence state, confidence, source availability, and recency, then performs deterministic breadth-first traversal.
- `UntrustedKnowledgeContext` is an immutable envelope capped at 20 neurons, 40 synapses, and 100 KB serialized.
- `serialize_untrusted_knowledge_context()` emits deterministic JSON with delimiter-breaking characters escaped.

## Retrieval semantics

- Start from at most five high-relevance seed neurons.
- Traverse active edges up to two hops (one by default). For neighborhood discovery, an edge can be traversed from either endpoint; each serialized synapse retains its directed `from`/`to` orientation.
- `truncated` is set when seed, neuron, or synapse caps actually omit matching context. The configured hop depth is an intentional boundary and does not by itself set `truncated`.
- Keep both endpoints of every returned `Contradicts` edge, even if one endpoint is marked `Superseded`; preserve its lifecycle label so the model sees the history.
- Exclude superseded neurons and `Supersedes` edges by default. Set `include_history=True` for historical queries.
- Exclude Proposed, Rejected, and Superseded edges from default traversal.
- Never infer that an edge proves either endpoint.
- Fail closed on malformed records and dangling endpoints. If the output cap prevents a complete relation pair, omit the edge and mark the context as truncated.
- Retrieval never changes graph records.

## LLM and host boundary

`ToolOrchestrator.run()` accepts an optional `knowledge_context`. `OpenAIResponsesAdapter` prepends it as a separate user-role data message before conversation history, keeping the current user request last. Trusted host instructions and host-filtered tool definitions remain separate. The base policy explicitly treats both retrieved memory and graph data as untrusted reference context. Memory and graph context can be passed together using `complete_with_tools_and_memory_and_knowledge`.

`CapriHostRuntime` accepts an optional trusted `knowledge_context_resolver(principal_id, session_id, user_text)`. It is invoked only after authentication and session ownership checks. The host resolver owns scope and provider configuration; untrusted callers cannot supply graph records or alter permissions.

Example host setup:

```python
from capri_runtime import (
    create_notion_knowledge_graph_provider_from_environment,
    retrieve_knowledge,
)

provider = create_notion_knowledge_graph_provider_from_environment(
    neuron_data_source_id="YOUR_NEURONS_DATA_SOURCE_UUID",
    synapse_data_source_id="YOUR_SYNAPSES_DATA_SOURCE_UUID",
)

def resolve_graph(principal_id, session_id, user_text):
    # Add host-owned scope filtering here if the graph is not globally shared.
    return retrieve_knowledge(user_text, provider, max_hops=1)

host = CapriHostRuntime(
    authority,
    session_store,
    orchestrator,
    knowledge_context_resolver=resolve_graph,
)
```

The provider reads `NOTION_API_TOKEN` from the host environment by default. The data-source IDs are configuration, not secrets. Do not place credentials in code, graph records, or prompts.

## Security properties and limitations

- Graph text, tags, titles, sources, and relationship rationales are untrusted data.
- Escaped delimiters are a serialization convention, not a cryptographic prompt-injection defense or provider-enforced isolation.
- The adapter never executes tools. Model tool calls remain proposals checked by the host's existing ToolExecutionBridge and trusted ExecutionContext.
- The host must not allow graph content to supply principal identity, policy, permissions, approvals, tool definitions, or resolver configuration.
- The current lexical scorer is deterministic and dependency-free. It is not semantic search. Embeddings remain deferred until a benchmark shows a measurable retrieval gap.
- The Notion provider loads a bounded snapshot for each resolution. Add a host-owned cache only after measuring latency and freshness requirements.
- No live OpenAI request is made by offline tests. Live API usage may incur cost and requires explicit owner authorization.

## Offline validation

`tests/test_knowledge_graph.py` covers connected traversal, contradictions, supersession, hostile prompt-injection text, malformed/dangling endpoints, node caps, Notion pagination, and the LLM input boundary. `tests/test_host_runtime.py` verifies graph retrieval happens only after authenticated session ownership and that memory and graph context remain separate.
