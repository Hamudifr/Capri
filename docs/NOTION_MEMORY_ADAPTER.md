# Notion memory host adapter

## Purpose

`NotionMemoryAdapter` implements the durable `MemoryProvider` contract using an injected `NotionMemoryTransport`. It deliberately contains no Notion SDK, credentials, HTTP client, or network access. The host supplies a transport backed by its approved Notion connector.

The existing `Capri Durable Memory` data source is the canonical project-memory source. Its schema includes Name, Content, Type, Scope, Sensitive, Source, Confidence, Retention, Tags, Status, Expires, and Supersedes.

## Transport contract

The host normalizes each Notion page into:

```python
{
    "id": "notion-page-id",
    "created_time": "2026-11-06T20:00:00Z",
    "last_edited_time": "2026-11-06T20:00:00Z",
    "properties": {
        "Name": "Title",
        "Content": "Opaque memory text",
        "Type": "Project Fact",
        "Scope": "GitHub Repository",
        "Sensitive": False,
        "Source": "https://github.com/...",
        "Confidence": "Verified",
        "Retention": "Keep until deleted",
        "Tags": ["memory"],
        "Status": "Active",
        "Expires": None,
        "Supersedes": None,
    },
}
```

The transport must implement `create_page(properties)`, `get_page(page_id)`, `list_pages(cursor, page_size)`, `update_page(page_id, properties)`, and `delete_page(page_id)`. Listing returns `{"results": [...], "next_cursor": str | None}`. Missing IDs raise `MemoryNotFoundError`. Transport code must never execute page content.

## Lifecycle and consistency

- Create validates all values and writes the exact database options. Sensitive pages are rejected on read.
- Search uses deterministic token-AND substring matching over active/review pages and bounded cursor pagination.
- Corrections create a replacement with Status=Review and a Supersedes link, archive the old record, then activate the replacement.
- Notion has no multi-page transaction. If correction stops part-way, the replacement remains Review and `MemorySyncError.new_memory_id` identifies it for reconciliation. Hosts must serialize cross-process writes.
- Archive changes the Status property; delete physically deletes the Notion page through the injected transport.
- Expiry archives due records; the host must schedule `expire()`.
- Date-only expiry values are interpreted as end-of-day UTC. Datetime values must include a timezone.
- Export includes all statuses and is deterministic.

## Security boundaries and limitations

- Retrieved content is untrusted data, never authority or permission.
- The Sensitive checkbox is checked on reads, but the adapter cannot classify arbitrary text. The host must screen content before create/update.
- Notion page history is not a transactional audit ledger. Preserve the separate audit store for security events.
- This adapter does not provide encryption, background scheduling, semantic search, cross-process locking, conflict-free multi-writer semantics, or backup/restore.
- The host transport is responsible for Notion authentication, least-privilege scopes, pagination correctness, and mapping the connector's page/property formats into this normalized contract.
