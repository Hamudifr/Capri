# Provider usage telemetry

Capri's OpenAI Responses adapter can return validated per-response usage metadata to the host:

- requested model identifier and provider response ID;
- input, output and total token counts;
- cached input and cache-write token counts when supplied;
- reasoning-token count when supplied;
- measured provider request latency in milliseconds.

The usage object contains no prompt or response text. It is carried on AssistantTurn and accumulated as one record per provider response in OrchestrationResult.provider_usage. A host may provide a usage_observer to persist each record with the session ID and authenticated principal ID. The observer runs before any proposed tool call is executed. If persistence fails, orchestration stops before tool execution.

Missing provider usage is represented as unavailable (no record), never as zero. Malformed usage metadata is rejected. Token counts are telemetry only: Capri does not infer currency cost, apply provider pricing, or enforce token/spend limits from these fields. The existing budget store continues to enforce reservation counters only. A host must not treat token telemetry alone as a verified strategy-evaluation cohort; it still needs authenticated task identity, task-family classification, outcome evidence and an immutable evidence manifest.

The OpenAI Responses API documents the optional usage object with input/output/total tokens and token-detail breakdowns: [Responses API create reference](https://developers.openai.com/api/reference/resources/responses/methods/create).

No network request is made by tests; all usage responses are fixtures.
