# Notion memory host adapter

## Purpose

`NotionMemoryAdapter` implements the durable `MemoryProvider` contract. It can use an injected `NotionMemoryTransport` or the concrete standard-library `NotionRESTTransport`. No Notion SDK is required.

The Capri Durable Memory data source ID is `435a6e29-3b57-4637-908b-a07761e0df0f`. Its schema includes Name, Content, Type, Scope, Sensitive, Source, Confidence, Retention, Tags, Status, Expires, and Supersedes. Notion page IDs and non-null Supersedes lineage IDs are validated as UUIDs at the provider-neutral adapter boundary; `get()` also verifies that the returned record UUID matches the requested UUID, including UUID strings with different letter casing. Transport-provided textual fields and tags must be plain built-in strings; string subclasses are rejected so custom transports cannot bypass primitive validation. The adapter's own create, search, identifier, pagination-limit, retention-expiry, and time inputs also enforce exact primitive types before invoking an injected transport; page IDs and supersession IDs must be UUID strings. The REST request encoder independently enforces plain built-in strings, a `Sensitive` value of exactly `false`, and list/tuple tag containers at its outbound boundary, including direct transport calls that bypass the provider-neutral adapter. Sensitive memory writes are rejected even when callers bypass the provider-neutral adapter. Direct `create_page()` calls must provide all twelve memory schema properties before any network request; `update_page()` continues to accept partial property updates. It also applies the provider's bounded text rules to Name (1–200 characters), Content (1–20,000), Supersedes (empty or UUID, at most 64), Source (absolute HTTP(S), at most 2,048), and Expires (timezone-aware ISO-8601, at most 64), rejecting invalid text before network I/O. It also enforces the exact supported Type, Scope, Confidence, Retention, Status, and Tags vocabularies and requires Source to be an absolute HTTP(S) URL; unsupported values are rejected locally so direct transport calls cannot introduce arbitrary select/multi-select options or non-HTTP source schemes. REST page identifiers are validated as UUID strings before GET/PATCH calls; pagination page sizes and cursors require exact primitive values, and decoded Notion response objects/lists are checked as plain JSON containers before normalization. Constructor credentials, data-source IDs, timeout values, callback and environment-variable names are also type-checked before use. The provider-neutral adapter accepts only a plain ISO string, an exact `date` value, or null for Expires and normalizes date-only values to end-of-day UTC. Direct REST encoder calls independently require a valid timezone-aware ISO-8601 timestamp (or null), rejecting malformed, date-only, and timezone-naive strings before any request is sent.

## Standalone REST setup

Set `NOTION_API_TOKEN` and `CAPRI_MEMORY_DATA_SOURCE_ID` in the host's secret/configuration manager, then initialize:

```python
from capri_runtime import create_notion_memory_adapter_from_environment

# Explicit network call: validates the live data-source schema before returning.
memory = create_notion_memory_adapter_from_environment()
```

The token is held in memory only. It is not written to disk, included in logs, or exposed in the transport representation. Do not place it in source control, command-line arguments, or a committed `.env` file.

The REST transport pins `Notion-Version: 2026-03-11`, uses `GET /data_sources/{data_source_id}` for explicit schema preflight, `POST /data_sources/{data_source_id}/query`, `POST /pages`, `GET /pages/{id}`, and `PATCH /pages/{id}`. Use `create_notion_memory_adapter_from_environment()` during host startup before enabling memory reads or writes; this explicit factory performs the schema request and returns an adapter only after validation. Plain `NotionRESTTransport.from_environment()` construction remains network-free. The explicit factory verifies the configured data-source identity, every required property type, and the exact required option labels for Type, Scope, Confidence, Retention, Status, and all six supported Tags values. The check is read-only and is never run implicitly on each request. It fails closed on schema drift and does not attempt to repair or mutate the user's Notion schema. It passes opaque cursors through unchanged, requires an explicit boolean `has_more` and an explicit `next_cursor` field (non-empty string when more pages exist, null otherwise), and rejects incomplete or contradictory pagination metadata rather than treating it as the final page. The memory adapter also rejects repeated cursors, duplicate page IDs across pages, missing cursor fields, non-list result collections, and page records with missing or malformed Tags. It bounds response size, refuses HTTP redirects by default before credentials can be forwarded, and rejects any unexpected final origin. Page GET and PATCH responses must return the exact requested page ID; mismatched identities are rejected. Empty PATCH updates are rejected before network I/O. Page normalization requires an explicit boolean `in_trash` state and rejects missing or malformed values; trashed pages map to not-found. Every memory property must carry its expected Notion property type (Status supports the current `status` type and legacy `select` type); malformed or mismatched property types and malformed Expires values are rejected. The Tags multi-select must be present as a list, and every option must contain a string name; malformed options are rejected instead of silently discarded. Name, Content, and Supersedes rich-text arrays must be present and every segment must expose readable text; malformed segments are rejected instead of silently omitted from the normalized record. It maps 404 to not-found and exposes 429 `Retry-After` without retrying mutations automatically.

## Lifecycle and consistency

- Create validates values and writes the exact data-source properties. Sensitive pages are rejected on read.
- Search uses deterministic token-AND substring matching over active/review pages and bounded cursor pagination. When exact-title and term-match relevance tie, the most recently edited record ranks first, matching the local SQLite memory provider.
- Create operations compare the returned normalized record against the requested payload; a mismatch raises `MemorySyncError` with the created page ID for reconciliation. Corrections create a replacement with Status=Review and a Supersedes link, archive the old record, then activate the replacement. The adapter validates each update response's identity, lifecycle state, and unchanged payload, then reads both records back to confirm the old record persisted as Archived and the replacement persisted as Active with the expected Supersedes link and payload. Silent no-op, altered-payload, or inconsistent updates raise `MemorySyncError` with the replacement ID for reconciliation. Explicit archive operations compare the pre-update payload with the response and read the page back to confirm Archived persisted without content or lineage changes.
- Notion has no multi-page transaction. If correction stops part-way, the replacement remains Review and `MemorySyncError.new_memory_id` identifies it for reconciliation. Hosts must serialize cross-process writes.
- Archive changes the Status property.
- Delete moves the page to Notion trash (`in_trash=true`); the REST transport validates the PATCH response identity and explicit trash state, then performs a GET readback. The provider-neutral adapter independently reads back after any injected transport and only reports success when the record is no longer retrievable. It is not permanent deletion or secure media erasure. The REST API's trash operation is reversible.
- Expiry archives due records; the host must schedule `expire()`.
- Date-only expiry values are interpreted as end-of-day UTC. Datetime values must include a timezone.
- Export includes all statuses and is deterministic.

## Security boundaries and limitations

- Retrieved content is untrusted data, never authority or permission.
- The Sensitive checkbox must be present and must be the exact boolean `false` on reads; missing, null, integer, string, or true values are rejected. The Status property must also be present and map to a supported lifecycle state; missing status is never defaulted to Active. The REST transport preserves absent values as unclassified so the adapter can reject them. The adapter still cannot classify arbitrary text, so the host must screen content before create/update.
- Notion page history is not a transactional audit ledger. Preserve the separate audit store for security events.
- The transport does not provide encryption at rest, background scheduling, semantic search, cross-process locking, conflict-free multi-writer semantics, or backup/restore.
- The host is responsible for Notion integration sharing, token rotation, least-privilege scopes, and process supervision.

Official references: [Notion versioning](https://developers.notion.com/reference/versioning), [query a data source](https://developers.notion.com/reference/query-a-data-source), [retrieve a page](https://developers.notion.com/reference/retrieve-a-page), and [update a page](https://developers.notion.com/reference/patch-page).


## Optional live workspace verification

The repository workflow includes a live smoke job that is disabled by default. To enable it, configure:

- Repository variable `CAPRI_NOTION_LIVE_TESTS=true`.
- Repository variable `CAPRI_MEMORY_DATA_SOURCE_ID=435a6e29-3b57-4637-908b-a07761e0df0f`.
- Repository secret `NOTION_API_TOKEN` containing a least-privilege Notion integration token shared with the Capri Durable Memory data source.

The smoke test creates a unique non-sensitive temporary record, reads it, corrects it through the supersession flow, searches it, archives it, and moves both temporary pages to Notion trash. It verifies that trashed pages are no longer retrievable. It does not permanently erase pages or store the token. Do not enable this job until the integration has the intended least-privilege access.
