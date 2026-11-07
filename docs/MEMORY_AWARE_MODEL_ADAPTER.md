# Memory-aware model adapter contract

## Status

The repository now includes OpenAIResponsesAdapter, a concrete standard-library implementation of the MemoryAwareToolModelAdapter protocol, plus offline fake-response tests. It is not yet connected to a running host, and no live provider request has been made. This document specifies the integration boundary and distinguishes adapter implementation from live provider verification.

## Input separation

A memory-aware adapter receives four distinct inputs:

1. session_id — host session identifier.
2. history — the conversation transcript. Retrieved memory must not be appended to this tuple.
3. tools — the host-filtered tool definitions produced from the trusted ExecutionContext.
4. memory_context — an exact, bounded, untrusted UntrustedMemoryContext containing active, non-sensitive records.

Use serialize_untrusted_memory_context(memory_context) to obtain deterministic JSON inside an escaped <untrusted_text> block. The serializer escapes angle brackets and ampersands in imported content so memory cannot close or nest the outer delimiter in the serialized text.

## Provider prompt-construction rules

A concrete adapter must:

- Prefer a provider-documented untrusted-data field or equivalent structured data channel when one exists.
- Otherwise place the serialized block in a data-only message, separate from trusted system/developer policy instructions.
- Never interpolate memory titles, content, tags, source metadata, or serialized payload into system/developer policy text.
- Keep host policy and tool definitions independent of retrieved memory.
- Treat all retrieved memory as potentially malicious, stale, contradictory, or irrelevant. It is context, not policy or authority.
- Treat model output as untrusted. Convert provider tool-call responses into AssistantTurn and let ToolOrchestrator and ToolExecutionBridge validate and execute them.
- Never execute tools directly from the provider adapter, and never accept permissions, approval grants, principal identity, or tool definitions from memory or model output.
- Keep provider credentials in the host secret manager or injected runtime configuration; never commit credentials or put them in prompts/logs.

## Security properties and non-properties

The host runtime structurally separates memory from transcript and trusted ExecutionContext. The bridge independently checks tool permissions and approvals. Adversarial orchestration tests verify that a memory item instructing the model to invoke an unauthorized deletion tool cannot expand the tool list or cause the host to execute the operation.

The untrusted_text wrapper is a serialization/delimiting convention, not a cryptographic or provider-enforced boundary. It does not make prompt injection impossible. A provider may interpret message roles and delimiters differently; the adapter must follow that provider current documented semantics and add integration tests for its actual request format.

Do not claim provider-enforced isolation, end-to-end prompt-injection resistance, or a production model integration until a concrete adapter has been implemented and tested against the provider real API. A live API test may incur charges; do not enable paid API calls without explicit authorization.

## Required adapter test matrix

A concrete provider adapter should include tests for:

- Delimiter-breaking strings such as </untrusted_text> and nested markup.
- Fake system/developer instructions, fake JSON/tool-call payloads, and malicious source/title/tag metadata.
- Memory content absent from transcript history and trusted system/developer policy messages.
- Tool definitions remaining identical to host-filtered definitions regardless of memory content.
- Forged unauthorized tool calls being denied by the host bridge.
- Provider response parsing rejecting malformed, oversized, duplicated, or unexpected tool calls.
- Provider errors, timeouts, cancellation, and credential redaction.
- Request serialization preserving Unicode and provenance without introducing executable instructions.

## Current implementation

- UntrustedMemoryContext — bounded immutable memory envelope.
- serialize_untrusted_memory_context() — deterministic escaped data serialization.
- MemoryAwareToolModelAdapter — provider-neutral protocol.
- ToolOrchestrator — passes memory separately and keeps host tool execution behind the bridge.
- tests/test_memory_orchestration_boundary.py — hostile-memory tests for structural separation and host authorization.

OpenAIResponsesAdapter now implements the protocol using the official Responses API. Its offline tests exercise request construction, function-call parsing, prior tool-transcript reconstruction, memory separation, malformed provider outputs, and credential/error redaction. No live provider integration or prompt-injection resistance claim is made. See [OPENAI_RESPONSES_ADAPTER.md](OPENAI_RESPONSES_ADAPTER.md).