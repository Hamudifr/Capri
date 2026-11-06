# Notion memory host adapter

## Purpose

`NotionMemoryAdapter` implements the durable `MemoryProvider` contract. It can use an injected `NotionMemoryTransport` or the concrete standard-library `NotionRESTTransport`. No Notion SDK is required.

The Capri Durable Memory data source ID is `435a6e29-3b57-4637-908b-a07761e0df0f`. Its schema includes Name, Content, Type, Scope, Sensitive, Source, Confidence, Retention, Tags, Status, Expires, and Supersedes.

## Standalone REST setup

Set `NOTION_API_TOKEN` and `CAPRI_MEMORY_DATA_SOURCE_ID` in the host's secret/configuration manager, then initialize:

```python
from capri_runtime import NotionMemoryAdapter
from capri_runtime.notion_rest import NotionRESTTransport

memory = NotionMemoryAdapter(NotionRESTTransport.from_environment())
```

The token is held in memory only. It is not written to disk, included in logs, or exposed in the transport representation. Do not place it in source control, command-line arguments, or a committed `.env` file.

The REST transport pins `Notion-Version: 2026-03-11`, uses `POST /data_sources/{data_source_id}/query`, `POST /pages`, `GET /pages/{id}`, and `PATCH /pages/{id}`. It passes opaque cursors through unchanged, bounds response size, rejects redirects outside the approved HTTPS origin, maps 404 to not-found, and exposes 429 `Retry-After` without retrying mutations automatically.

## Lifecycle and consistency

- Create validates values and writes the exact data-source properties. Sensitive pages are rejected on read.
- Search uses deterministic token-AND substring matching over active/review pages and bounded cursor pagination.
- Corrections create a replacement with Status=Review and a Supersedes link, archive the old record, then activate the replacement.
- Notion has no multi-page transaction. If correction stops part-way, the replacement remains Review and `MemorySyncError.new_memory_id` identifies it for reconciliation. Hosts must serialize cross-process writes.
- Archive changes the Status property.
- Delete moves the page to Notion trash (`in_trash=true`); it is not permanent deletion or secure media erasure.
- Expiry archives due records; the host must schedule `expire()`.
- Date-only expiry values are interpreted as end-of-day UTC. Datetime values must include a timezone.
- Export includes all statuses and is deterministic.

## Security boundaries and limitations

- Retrieved content is untrusted data, never authority or permission.
- The Sensitive checkbox is checked on reads, but the adapter cannot classify arbitrary text. The host must screen content before create/update.
- Notion page history is not a transactional audit ledger. Preserve the separate audit store for security events.
- The transport does not provide encryption at rest, background scheduling, semantic search, cross-process locking, conflict-free multi-writer semantics, or backup/restore.
- The host is responsible for Notion integration sharing, token rotation, least-privilege scopes, and process supervision.

Official references: [Notion versioning](https://developers.notion.com/reference/versioning), [query a data source](https://developers.notion.com/reference/query-a-data-source), [retrieve a page](https://developers.notion.com/reference/retrieve-a-page), and [update a page](https://developers.notion.com/reference/patch-page).
