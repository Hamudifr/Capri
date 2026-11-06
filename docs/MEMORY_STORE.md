# Durable project memory

## Scope

`capri_runtime.memory` provides a provider-neutral record model and a bounded local SQLite store for non-sensitive project knowledge. It is an internal building block, not a connected Notion client or a model orchestration layer.

The current store supports:
- create and retrieve records with source, confidence, scope, type, explicit non-sensitive classification, tags, retention, timestamps, and expiry metadata;
- deterministic token-AND search with bounded offset pagination and exact provenance fields;
- corrections as new records linked to the prior record, which is archived rather than silently overwritten;
- controlled tags from the project's six-tag vocabulary;
- explicit archive and physical content deletion (with a minimal ID-only deletion event);
- expiry sweeps and exclusion of expired records from active retrieval;
- deterministic JSON export;
- private local database permissions and path checks on supported POSIX systems.

## Trust and privacy rules

- Every record is marked `sensitivity='non_sensitive'`, and the SQLite schema constrains that field to the same value. This is a caller-declared classification, not an automatic content classifier: callers must screen text before storing it; the store cannot reliably infer whether arbitrary content contains sensitive information. There is no secret-storage mode.
- Retrieved text is untrusted data. It cannot alter system/user authority, authorize tools, or bypass the execution gate.
- Do not deserialize memory content into execution contexts, approval grants, permissions, or executable code.
- Provider adapters own their authentication and transport. No Notion credentials or provider SDK are embedded in this repository.
- The SQLite database is not encrypted. Store it only in a private host-controlled directory; do not place secrets or sensitive personal data in it.
- Deletion removes the record content from the active database table and severs surviving supersession references to that record. A minimal event containing only the memory ID, event type, and timestamp remains for auditability. This is not secure media sanitization of SQLite/WAL files or backups; hosts must manage backup expiry and storage lifecycle.
- SQLite path checks reduce accidental symlink and permission exposure but are not a sandbox or a defense against a hostile process running as the same OS user.

## Current limitations

- No Notion synchronization adapter is implemented yet. The existing Notion database remains the project-level source of non-sensitive operating memory until a separately tested host adapter is connected.
- No encryption/key management, multi-user tenant isolation, embedding/vector search, semantic ranking, background expiry worker, conflict-resolution protocol, or cross-provider sync is implemented.
- Search is deterministic substring matching: every query token must occur in title, content, or scope. It is not semantic retrieval.
- Expiry is evaluated at retrieval time and by an explicit `expire()` sweep; no background scheduler is started.
- Retention labels are metadata. Callers must supply an expiry timestamp for `expire_30d` and `expire_90d`; the store does not infer or silently assign dates.

## Example

```python
from capri_runtime import SQLiteMemoryStore

store = SQLiteMemoryStore("/private/capri/memory.sqlite3")
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
