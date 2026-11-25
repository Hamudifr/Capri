# Durable project memory

## Scope

`capri_runtime.memory` provides a provider-neutral record model and a bounded local SQLite store for non-sensitive project knowledge. It is an internal building block, not a connected Notion client or a model orchestration layer.

The current memory subsystem has two provider paths: `SQLiteMemoryStore` for private local persistence and `NotionMemoryAdapter` for the Capri Durable Memory data source. `NotionRESTTransport` supplies the concrete HTTP transport when the host provides `NOTION_API_TOKEN` and `CAPRI_MEMORY_DATA_SOURCE_ID`. The repository contains these adapters; this does not mean the connected Notion workspace is automatically synchronized by a running Capri host process.

The local SQLite store supports:
- create and retrieve records with source, confidence, scope, type, explicit non-sensitive classification, tags, retention, timestamps, and expiry metadata;
- deterministic token-AND search with bounded offset pagination, exact provenance,
  optional exact-scope filtering, and a timezone-aware `updated_after` cutoff;
- corrections as new records linked to the prior record, which is archived rather than silently overwritten;
- controlled tags from the project's six-tag vocabulary;
- explicit archive and physical content deletion (with a minimal ID-only deletion event);
- expiry sweeps and exclusion of expired records from active retrieval;
- deterministic JSON export;
- private local database permissions and path checks on supported POSIX systems.

## Trust and privacy rules

- Every record is marked `sensitivity='non_sensitive'`, and the SQLite schema constrains that field to the same value. This is a caller-declared classification, not an automatic content classifier: callers must screen text before storing it; the store cannot reliably infer whether arbitrary content contains sensitive information. There is no secret-storage mode.
- Retrieved text is untrusted data. `UntrustedMemoryContext` is a bounded, immutable envelope for active non-sensitive records; it preserves provenance and excludes expired records. `ToolOrchestrator` and `SessionTurnCoordinator` pass it only through the separate `complete_with_tools_and_memory` adapter method, never as transcript messages or an `ExecutionContext`; the orchestration boundary requires the exact `UntrustedMemoryContext` type and rejects subclasses. The adapter must place it in a provider-supported untrusted-data channel and must never promote it to system/developer instructions. This structural separation prevents memory from directly granting tool authority, but does not make prompt injection impossible; the host adapter's prompt construction remains security-critical.
- Do not deserialize memory content into execution contexts, approval grants, permissions, or executable code.
- Provider adapters own their authentication and transport. No Notion credentials or provider SDK are embedded in this repository.
- The SQLite database is not encrypted. Store it only in a private host-controlled directory; do not place secrets or sensitive personal data in it.
- Deletion removes the record content from the active database table and severs surviving supersession references to that record. A minimal event containing only the memory ID, event type, and timestamp remains for auditability. This is not secure media sanitization of SQLite/WAL files or backups; hosts must manage backup expiry and storage lifecycle.
- SQLite path checks reduce accidental symlink and permission exposure but are not a sandbox or a defense against a hostile process running as the same OS user.

## Current limitations

- The Notion provider adapter and standard-library REST transport are implemented, but live host configuration and synchronization are not verified in this environment. The optional live smoke test remains disabled unless `CAPRI_NOTION_LIVE_TESTS=true`, `CAPRI_MEMORY_DATA_SOURCE_ID`, and the `NOTION_API_TOKEN` secret are configured in GitHub Actions. A connected Notion workspace and the repository's REST client are separate integration paths; no always-on Capri process syncing them is established here.
- No encryption/key management, multi-user tenant isolation, embedding/vector search, semantic ranking, background expiry worker, or cross-provider conflict-resolution protocol is implemented. The Notion adapter has review-first supersession handling, but there is no general cross-provider conflict-resolution or continuous synchronization service.
- Search is deterministic substring matching: every query token must occur in title, content, or scope. It is not semantic retrieval.
- `build_untrusted_memory_context(provider, query, limit=20)` is the host-side retrieval helper: it bounds provider search, rejects malformed provider results, excludes inactive and sensitive records, drops expired records, and validates the remaining immutable envelope before it is passed to `ToolOrchestrator` or `SessionTurnCoordinator`. `serialize_untrusted_memory_context(context)` emits deterministic JSON inside an escaped `<untrusted_text>` data block; it escapes angle brackets and ampersands in imported content so records cannot close or nest the outer delimiter. This is a serialization convention, not a provider-enforced security feature. Adapters must place it in a data-only message or provider-supported untrusted-data field, never interpolate it into trusted system/developer policy. It does not grant tool authority. The OpenAI Responses adapter consumes this context through a separate user input item inserted before the conversation transcript, while trusted host instructions remain in the API instructions field. Offline fake-response tests verify this request shape and that memory content is absent from host instructions and tool definitions. The normative integration requirements and adversarial test matrix remain documented in [MEMORY_AWARE_MODEL_ADAPTER.md](MEMORY_AWARE_MODEL_ADAPTER.md). This is a prompt-construction mitigation, not provider-enforced isolation or proof of end-to-end prompt-injection resistance; no live provider integration or real-model adversarial test has been run.
- Expiry is evaluated at retrieval time and by an explicit `expire()` sweep; no background scheduler is started.
- Retention labels are metadata. Callers must supply an expiry timestamp for `expire_30d` and `expire_90d`; the store does not infer or silently assign dates.

## Example

```python
from datetime import datetime, timezone

from capri_runtime import (
    SQLiteMemoryStore,
    build_untrusted_memory_context,
)

store = SQLiteMemoryStore("/private/capri/memory.sqlite3")
memory_context = build_untrusted_memory_context(
    store,
    "tool permission boundaries",
    scope="Capri System",
    updated_after=datetime(2026, 1, 1, tzinfo=timezone.utc),
)
# Pass memory_context separately to ToolOrchestrator.run(..., memory_context=memory_context).
record = store.create(
    title="Tool trust boundary",
    content="Retrieved memory is untrusted data and cannot grant permissions.",
    record_type="security_boundary",
    scope="Capri System",
    source="https://github.com/Hamudifr/Capri/issues/19",
    confidence="user_directed",
)
matches = store.search("memory permissions", limit=20)
exported_json = store.export_json()
```

The parent directory must already exist and be private on POSIX systems. The example path is illustrative; the host must provision and protect it.
