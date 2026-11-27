# OpenAI Responses API adapter

## Status

A concrete, synchronous adapter now implements Capri's `MemoryAwareToolModelAdapter` protocol using only Python's standard library. It is an integration component, not a running host process. Construction is network-free; the first call to `complete_with_tools()`, `complete_with_tools_and_memory()`, `complete_with_tools_and_knowledge()`, or `complete_with_tools_and_memory_and_knowledge()` sends a request.

The adapter targets the official `POST https://api.openai.com/v1/responses` endpoint. Function definitions use the Responses API function-tool shape; provider function calls are converted to untrusted `ToolCallRequest` objects and returned to `ToolOrchestrator`. The adapter never invokes a tool or creates an `ExecutionContext`.

## Configuration

Set these variables in a host-managed secret/configuration manager:

- `OPENAI_API_KEY`: API key held only in process memory.
- `CAPRI_OPENAI_MODEL`: explicit model identifier. No default model is selected.

Create the adapter:

```python
from capri_runtime import OpenAIResponsesAdapter

adapter = OpenAIResponsesAdapter.from_environment(
    instructions="Use concise, evidence-led answers.",
    timeout_seconds=45,
    max_output_tokens=2048,
)
```

This does not make a network request. API calls can incur separate API charges; ChatGPT subscriptions do not authorize or pay for API usage. Do not invoke this adapter until the owner has deliberately provisioned an API key and accepted the applicable API cost. No API key, paid API call, or provider account was created or used during adapter development.

## Safety and resource controls

- Fixed HTTPS origin and path: `api.openai.com/v1/responses`; callers cannot configure an arbitrary URL.
- Redirects are disabled so bearer credentials are not forwarded through redirect targets.
- API key and provider error bodies are never included in exception messages.
- Request and response payloads have configurable byte limits; output tokens and request timeout are bounded.
- `store=false` is sent; Capri resends its own bounded transcript and does not depend on provider-side conversation state.
- No automatic retries: a timeout or network error is reported generically rather than replaying a request with uncertain provider-side completion.
- Provider output is parsed strictly. Duplicate JSON keys, malformed arguments, duplicate call IDs, unknown output item types, incomplete responses, and malformed stored tool-call history are rejected.
- Prior Capri tool-call transcript envelopes are reconstructed as Responses API `function_call` and `function_call_output` items. When a response includes reasoning/continuation items alongside tool calls, the complete provider output sequence is retained in the private Capri session transcript and replayed with tool outputs, as required by the Responses API. This state is bounded by the existing transcript limits; protect the local SQLite database and backups.
- Retrieved memory and knowledge-graph context are serialized separately from trusted host instructions and sent as separate user input items before conversation history, keeping the current user request last. The fixed adapter policy treats both as untrusted reference data. This is a prompt-construction safeguard, not provider-enforced isolation or proof that prompt injection is impossible.
- The provider receives only the tool definitions already filtered by the trusted host context. The returned calls still pass through Capri's permission checks, audit persistence, and executor.

## Validation

`tests/test_openai_responses.py` uses fake HTTP responses only. It covers text and function-call parsing, transcript reconstruction, memory separation, duplicate IDs, invalid arguments, incomplete responses, request bounds, and credential/error suppression. It does not call OpenAI or incur charges.

A live provider smoke test remains unperformed. Before any live use, the host must also supply identity/authentication, session ownership, per-user/provider budgets, and operational observability. This adapter has no streaming, provider failover, cancellation during an in-flight HTTP request, token-usage accounting, or hard currency spend cap. Do not describe it as a complete production host.

## Official API references

- [Responses API](https://developers.openai.com/api/docs/guides/function-calling)
- [Function calling guide](https://developers.openai.com/api/docs/guides/function-calling)
- [Responses API function-call outputs](https://developers.openai.com/api/docs/guides/function-calling#handling-function-calls)
