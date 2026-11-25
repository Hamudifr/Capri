# Provider usage telemetry

Capri's OpenAI Responses adapter can return validated per-response usage metadata to the host:

- requested model identifier and provider response ID;
- input, output and total token counts;
- cached input and cache-write token counts when supplied;
- reasoning-token count when supplied;
- measured provider request latency in milliseconds.

The usage object contains no prompt or response text. It is carried on AssistantTurn and accumulated as one record per provider response in OrchestrationResult.provider_usage. A host may provide a usage_observer to persist each record with the session ID and authenticated principal ID. The observer runs before any proposed tool call is executed. If persistence fails, orchestration stops before tool execution and the raised ToolOrchestrationError carries the usage records collected so far for recovery. Use the provider response ID as an idempotency key when persisting. If both the observer and OrchestrationResult are used, do not persist the same response twice.

Missing provider usage is represented as unavailable (no record), never as zero. Malformed usage metadata is rejected. Token counts are telemetry only: Capri does not infer currency cost, apply provider pricing, or enforce token/spend limits from these fields. The existing budget store continues to enforce reservation counters only. A host must not treat token telemetry alone as a verified strategy-evaluation cohort; it still needs authenticated task identity, task-family classification, outcome evidence and an immutable evidence manifest.

The OpenAI Responses API documents the optional usage object with input/output/total tokens and token-detail breakdowns: [Responses API create reference](https://developers.openai.com/api/reference/resources/responses/methods/create).

No network request is made by tests; all usage responses are fixtures.

## Durable SQLite usage journal

A host can pass <code>SQLiteProviderUsageJournal.record_usage</code> directly as the orchestrator's <code>usage_observer</code>. The journal shares the private SQLiteTaskStore database, binds each provider response to its authenticated principal and session, and uses the provider/response ID pair as an idempotency key. Replaying an identical record is a no-op; reusing the same response ID with different metadata or counts is rejected.

The journal is append-only, stores no prompt or response content, and exposes per-session records plus per-principal/model token aggregates. The host must explicitly construct it and inject <code>record_usage</code>; usage is not persisted automatically. Task-store integrity and backup validation verify its schema, append-only triggers, event hashes, token invariants and UTC timestamps. The SHA-256 event digest is an integrity checksum, not keyed authentication against a party with direct database write access. There is no automatic retention or compaction, so hosts must include the table in backup/rotation planning and monitor storage. It still records token counts and latency only: it does not calculate currency cost or enforce spend limits.
