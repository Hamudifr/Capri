# OpenAI Responses API adapter

## Status

Capri includes an optional, synchronous adapter at `capri_runtime.openai_responses.OpenAIResponsesAdapter`. It implements the existing `ToolModelAdapter` contract. The adapter is a transport/format bridge only: model-proposed calls still pass through `ToolOrchestrator`, `ToolExecutionBridge`, `HostToolGateway`, trusted host authority, and the normal approval/audit path.

No OpenAI SDK dependency is imported by Capri. The host supplies an initialized SDK-compatible client. No API key, client, model account, or network connection is stored in the repository or enabled in CI.

## Host setup

Install the OpenAI Python SDK in the host application's environment, then construct the client using the host's protected credential source. For example:

```python
from openai import OpenAI

from capri_runtime import OpenAIResponsesAdapter

client = OpenAI()  # The SDK reads OPENAI_API_KEY from the host environment.
adapter = OpenAIResponsesAdapter(
    client,
    model="gpt-6-astra",  # Select a model enabled for the host's account.
    instructions="Follow the host's tool and safety policy.",
    max_output_tokens=4096,
)
```

Do not hardcode API keys in source, pass them in model prompts, or store them in Capri session transcripts. The host must manage credential injection, access control, network egress, request timeouts, rate limits, and spend limits.

## Request behavior

- Uses the Responses API function-tool format and only the tools supplied by Capri's permission-filtered bridge.
- Sends the full provider-neutral transcript on each request. This allows stateless continuation and avoids reliance on a server-side response ID.
- Sets `store=False` on each request to disable Responses API response storage, and sets `parallel_tool_calls=False`. This does not mean the request is processed without provider-side handling; apply the host's applicable data controls.
- Does not enable built-in web search, file search, computer use, image generation, or arbitrary MCP tools.
- Does not force strict function schemas because existing Capri schemas can contain optional fields. The local Capri validator remains authoritative.
- Preserves Responses API reasoning items associated with tool-call turns in the bounded assistant transcript, then sends those items back with function calls and tool outputs for stateless continuation.
- Requires completed responses. It rejects malformed or duplicate-key JSON arguments, unsupported output items, invalid call IDs, and malformed transcript entries.
- Tool outputs are returned to the model as serialized Capri outcome records. The adapter does not execute handlers.

The orchestration layer bounds the transcript and provider continuation payload before any tool side effect. Provider continuation data is untrusted data and conveys no permission or approval.

## Limitations

- Synchronous only; no streaming, background response polling, automatic retry, or provider-side conversation IDs.
- Function tools only. Built-in Responses API tools are intentionally not exposed.
- The adapter expects an SDK-compatible object with `client.responses.create(**kwargs)`; no specific SDK version is pinned by Capri.
- CI uses deterministic fake clients. No live API call or billable request was made.
- Model availability, pricing, rate limits, context windows, and endpoint support are controlled by the host's selected model and account.

## Official references

- [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling)
- [Responses API create endpoint](https://developers.openai.com/api/reference/resources/responses/methods/create)
