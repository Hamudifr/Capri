"""Host-injected Notion adapter for the durable memory provider contract.

The transport is deliberately injected: this module contains no Notion SDK,
credentials, network client, or hidden authority. A host maps its approved Notion
connector operations to the normalized page contract documented below.
"""
from __future__ import annotations

import json
import threading
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import date, datetime, time, timezone
from typing import Protocol
from urllib.parse import urlsplit
from uuid import UUID

from .memory import (
    MemoryErrorBase,
    MemoryNotFoundError,
    MemoryRecord,
    MemoryValidationError,
    _ALLOWED_CONFIDENCE,
    _ALLOWED_RETENTION,
    _ALLOWED_TYPES,
    _iso,
    _now,
    _validate_expiry,
    _validate_tags,
    _validate_text,
)

_TYPE_TO_LABEL = {
    "operating_directive": "Operating Directive",
    "architecture_decision": "Architecture Decision",
    "project_fact": "Project Fact",
    "security_boundary": "Security Boundary",
    "user_preference": "User Preference",
}
_LABEL_TO_TYPE = {value: key for key, value in _TYPE_TO_LABEL.items()}
_CONFIDENCE_TO_LABEL = {
    "user_directed": "User-Directed",
    "verified": "Verified",
    "inferred": "Inferred",
    "unverified": "Unverified",
}
_LABEL_TO_CONFIDENCE = {value: key for key, value in _CONFIDENCE_TO_LABEL.items()}
_RETENTION_TO_LABEL = {
    "keep": "Keep until deleted",
    "expire_30d": "Expire after 30 days",
    "expire_90d": "Expire after 90 days",
    "archive_when_superseded": "Archive when superseded",
}
_LABEL_TO_RETENTION = {value: key for key, value in _RETENTION_TO_LABEL.items()}
_STATUS_TO_LABEL = {"active": "Active", "review": "Review", "archived": "Archived"}
_LABEL_TO_STATUS = {value: key for key, value in _STATUS_TO_LABEL.items()}
_ALLOWED_SCOPES = {"Capri System", "GitHub Repository", "Notion Workspace", "Tool Integration"}
_MAX_RECORDS = 10_000


def _validate_transport_text(value: object, field: str, maximum: int) -> str:
    if type(value) is not str:
        raise MemoryValidationError(f"{field} must be a plain string")
    return _validate_text(value, field, maximum)


class MemorySyncError(MemoryErrorBase):
    """A multi-page Notion correction stopped in a recoverable partial state."""

    def __init__(self, message: str, new_memory_id: str) -> None:
        super().__init__(message)
        self.new_memory_id = new_memory_id


class NotionMemoryTransport(Protocol):
    """Normalized host boundary for the Notion data source.

    Page shape:
      {"id": str, "created_time": ISO timestamp, "last_edited_time": ISO timestamp,
       "properties": {"Name": str, "Content": str, "Type": str, "Scope": str,
         "Sensitive": bool, "Source": URL, "Confidence": str, "Retention": str,
         "Tags": list[str], "Status": str, "Expires": ISO timestamp|date|None,
         "Supersedes": str|None}}

    list_pages returns {"results": [page, ...], "next_cursor": str|None}.
    Implementations must raise MemoryNotFoundError for missing page IDs and must
    never execute or interpret page content.
    """

    def create_page(self, properties: Mapping[str, object]) -> Mapping[str, object]: ...
    def get_page(self, page_id: str) -> Mapping[str, object]: ...
    def list_pages(self, *, cursor: str | None, page_size: int) -> Mapping[str, object]: ...
    def update_page(self, page_id: str, properties: Mapping[str, object]) -> Mapping[str, object]: ...
    def delete_page(self, page_id: str) -> None: ...


class NotionMemoryAdapter:
    """MemoryProvider backed by a host-supplied Notion transport.

    Corrections use a review-first sequence because Notion has no multi-page
    transaction: create the replacement as Review, archive the old page, then
    activate the replacement. If any step fails, the replacement remains Review
    and MemorySyncError exposes its ID for reconciliation. A per-instance lock
    serializes local operations; hosts must serialize cross-process writes.
    """

    def __init__(self, transport: NotionMemoryTransport, *, max_records: int = _MAX_RECORDS) -> None:
        if not isinstance(max_records, int) or isinstance(max_records, bool) or not 1 <= max_records <= _MAX_RECORDS:
            raise MemoryValidationError("max_records must be between 1 and 10000")
        for name in ("create_page", "get_page", "list_pages", "update_page", "delete_page"):
            if not callable(getattr(transport, name, None)):
                raise MemoryValidationError(f"transport is missing {name}")
        self._transport = transport
        self._max_records = max_records
        self._lock = threading.RLock()

    @staticmethod
    def _timestamp(value: object, field: str) -> str:
        _validate_transport_text(value, field, 64)
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise MemoryValidationError(f"{field} must be an ISO-8601 timestamp") from None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise MemoryValidationError(f"{field} must include a timezone")
        return _iso(parsed)

    @staticmethod
    def _expiry(value: object) -> str | None:
        if value is None:
            return None
        if type(value) is date:
            value = datetime.combine(value, time.max, tzinfo=timezone.utc).isoformat()
        elif type(value) is str:
            if len(value) == 10:
                try:
                    day = date.fromisoformat(value)
                    value = datetime.combine(day, time.max, tzinfo=timezone.utc).isoformat()
                except ValueError:
                    pass
        else:
            raise MemoryValidationError("Expires must be a plain ISO timestamp, date, or None")
        return _validate_expiry(value)

    @staticmethod
    def _source(value: object) -> str:
        source = _validate_text(value, "source", 2_048)
        parsed = urlsplit(source)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            raise MemoryValidationError("source must be an absolute HTTP(S) URL")
        return source

    @classmethod
    def _record_from_page(cls, page: Mapping[str, object]) -> MemoryRecord:
        if not isinstance(page, Mapping):
            raise MemoryValidationError("Notion transport returned a non-object page")
        page_id = page.get("id")
        _validate_transport_text(page_id, "Notion page id", 64)
        try:
            UUID(page_id)
        except (ValueError, TypeError, AttributeError):
            raise MemoryValidationError("Notion page id must be a UUID") from None
        props = page.get("properties")
        if not isinstance(props, Mapping):
            raise MemoryValidationError("Notion page properties are missing")
        title = _validate_transport_text(props.get("Name"), "title", 200)
        content = _validate_transport_text(props.get("Content"), "content", 20_000)
        type_label = _validate_transport_text(props.get("Type"), "Notion Type property", 100)
        record_type = _LABEL_TO_TYPE.get(type_label)
        if record_type not in _ALLOWED_TYPES:
            raise MemoryValidationError("Notion Type property is unsupported")
        scope = _validate_transport_text(props.get("Scope"), "scope", 100)
        if scope not in _ALLOWED_SCOPES:
            raise MemoryValidationError("Notion Scope property is unsupported")
        # The transport contract requires an explicit boolean classification.
        # Missing, null, string, and integer lookalikes must not silently become
        # non-sensitive; an unclassified page is rejected fail-closed.
        sensitive = props.get("Sensitive")
        if type(sensitive) is not bool or sensitive:
            raise MemoryValidationError("sensitive or unclassified Notion memory is not permitted")
        source = cls._source(_validate_transport_text(props.get("Source"), "source", 2_048))
        confidence_label = _validate_transport_text(props.get("Confidence"), "Notion Confidence property", 100)
        confidence = _LABEL_TO_CONFIDENCE.get(confidence_label)
        if confidence not in _ALLOWED_CONFIDENCE:
            raise MemoryValidationError("Notion Confidence property is unsupported")
        retention_label = _validate_transport_text(props.get("Retention"), "Notion Retention property", 100)
        retention = _LABEL_TO_RETENTION.get(retention_label)
        if retention not in _ALLOWED_RETENTION:
            raise MemoryValidationError("Notion Retention property is unsupported")
        tags_value = props.get("Tags")
        if type(tags_value) not in (list, tuple):
            raise MemoryValidationError("Notion Tags property is missing or malformed")
        if any(type(tag) is not str for tag in tags_value):
            raise MemoryValidationError("Notion Tags must contain plain strings")
        tags = _validate_tags(tags_value)
        status_label = props.get("Status")
        if type(status_label) is not str:
            raise MemoryValidationError("Notion Status property is missing or unsupported")
        status = _LABEL_TO_STATUS.get(status_label)
        if status not in _STATUS_TO_LABEL:
            raise MemoryValidationError("Notion Status property is unsupported")
        expires_at = cls._expiry(props.get("Expires"))
        if retention in {"expire_30d", "expire_90d"} and expires_at is None:
            raise MemoryValidationError("expiring Notion memory is missing Expires")
        created_at = cls._timestamp(page.get("created_time"), "created_time")
        updated_at = cls._timestamp(page.get("last_edited_time"), "last_edited_time")
        supersedes_id = props.get("Supersedes")
        if supersedes_id is not None:
            _validate_transport_text(supersedes_id, "Supersedes", 64)
            try:
                UUID(supersedes_id)
            except (ValueError, TypeError, AttributeError):
                raise MemoryValidationError("Notion Supersedes id must be a UUID") from None
        return MemoryRecord(
            page_id, title, content, record_type, scope, "non_sensitive", source,
            confidence, retention, tags, created_at, updated_at, expires_at,
            status, supersedes_id,
        )

    @staticmethod
    def _properties(
        *, title: str, content: str, record_type: str, scope: str, source: str,
        confidence: str, retention: str, tags: tuple[str, ...],
        expires_at: str | None, status: str, supersedes_id: str | None,
    ) -> dict[str, object]:
        return {
            "Name": title,
            "Content": content,
            "Type": _TYPE_TO_LABEL[record_type],
            "Scope": scope,
            "Sensitive": False,
            "Source": source,
            "Confidence": _CONFIDENCE_TO_LABEL[confidence],
            "Retention": _RETENTION_TO_LABEL[retention],
            "Tags": list(tags),
            "Status": _STATUS_TO_LABEL[status],
            "Expires": expires_at,
            "Supersedes": supersedes_id,
        }

    def _create(
        self, *, title: str, content: str, record_type: str, scope: str, source: str,
        confidence: str, retention: str = "keep", tags: tuple[str, ...] | list[str] = (),
        expires_at: str | None = None, status: str = "active",
        supersedes_id: str | None = None,
    ) -> MemoryRecord:
        _validate_text(title, "title", 200)
        _validate_text(content, "content", 20_000)
        if not isinstance(record_type, str) or record_type not in _ALLOWED_TYPES:
            raise MemoryValidationError("unsupported record_type")
        _validate_text(scope, "scope", 100)
        if scope not in _ALLOWED_SCOPES:
            raise MemoryValidationError("unsupported scope")
        source = self._source(source)
        if not isinstance(confidence, str) or confidence not in _ALLOWED_CONFIDENCE:
            raise MemoryValidationError("unsupported confidence")
        if not isinstance(retention, str) or retention not in _ALLOWED_RETENTION:
            raise MemoryValidationError("unsupported retention")
        if not isinstance(status, str) or status not in _STATUS_TO_LABEL:
            raise MemoryValidationError("unsupported status")
        tags = _validate_tags(tags)
        expires_at = self._expiry(expires_at)
        if retention in {"expire_30d", "expire_90d"} and expires_at is None:
            raise MemoryValidationError("expiring retention requires expires_at")
        if supersedes_id is not None:
            _validate_text(supersedes_id, "supersedes_id", 64)
        properties = self._properties(
            title=title, content=content, record_type=record_type, scope=scope,
            source=source, confidence=confidence, retention=retention, tags=tags,
            expires_at=expires_at, status=status, supersedes_id=supersedes_id,
        )
        page = self._transport.create_page(properties)
        return self._record_from_page(page)

    def create(
        self, *, title: str, content: str, record_type: str, scope: str,
        source: str, confidence: str, retention: str = "keep",
        tags: tuple[str, ...] | list[str] = (), expires_at: str | None = None,
    ) -> MemoryRecord:
        with self._lock:
            return self._create(
                title=title, content=content, record_type=record_type, scope=scope,
                source=source, confidence=confidence, retention=retention,
                tags=tags, expires_at=expires_at,
            )

    def get(self, memory_id: str) -> MemoryRecord:
        _validate_text(memory_id, "memory_id", 64)
        return self._record_from_page(self._transport.get_page(memory_id))

    def _list_all(self) -> tuple[MemoryRecord, ...]:
        records: list[MemoryRecord] = []
        seen_memory_ids: set[str] = set()
        seen_cursors: set[str] = set()
        cursor: str | None = None
        page_requests = 0
        while True:
            page_size = min(100, self._max_records - len(records))
            if page_size <= 0 or page_requests >= self._max_records:
                raise MemoryValidationError("Notion memory pagination capacity reached")
            page_requests += 1
            response = self._transport.list_pages(cursor=cursor, page_size=page_size)
            if not isinstance(response, Mapping) or type(response.get("results")) is not list:
                raise MemoryValidationError("Notion list response is malformed")
            if "next_cursor" not in response:
                raise MemoryValidationError("Notion list response omitted its cursor field")
            batch = response["results"]
            if len(batch) > page_size:
                raise MemoryValidationError("Notion transport exceeded the requested page size")
            for page in batch:
                record = self._record_from_page(page)
                if record.memory_id in seen_memory_ids:
                    raise MemoryValidationError("Notion pagination returned a duplicate page")
                seen_memory_ids.add(record.memory_id)
                records.append(record)
            next_cursor = response["next_cursor"]
            if next_cursor is None:
                return tuple(records)
            if type(next_cursor) is not str or not next_cursor:
                raise MemoryValidationError("Notion pagination cursor is malformed")
            if next_cursor in seen_cursors:
                raise MemoryValidationError("Notion pagination cursor repeated")
            seen_cursors.add(next_cursor)
            # Cursors are opaque API tokens: never parse, normalize, or persist them.
            cursor = next_cursor

    def search(self, query: str, *, limit: int = 20, offset: int = 0) -> tuple[MemoryRecord, ...]:
        _validate_text(query, "query", 500)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise MemoryValidationError("limit must be between 1 and 100")
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= self._max_records:
            raise MemoryValidationError("offset is outside the supported range")
        terms = tuple(dict.fromkeys(part.casefold() for part in query.split() if part))
        if not terms:
            raise MemoryValidationError("query must contain at least one search term")
        ranked = []
        for record in self._list_all():
            if record.status not in {"active", "review"}:
                continue
            if record.expires_at is not None and record.expires_at <= _iso(_now()):
                continue
            haystack = (record.title + "\n" + record.content + "\n" + record.scope + "\n" + " ".join(record.tags)).casefold()
            matched = sum(term in haystack for term in terms)
            if matched == len(terms):
                exact = int(record.title.casefold() == query.casefold())
                ranked.append((exact, matched, record.updated_at, record))
        ranked.sort(
            key=lambda item: (
                -item[0],
                -item[1],
                -datetime.fromisoformat(item[2]).timestamp(),
                item[3].memory_id,
            )
        )
        return tuple(item[3] for item in ranked[offset:offset + limit])

    def correct(self, memory_id: str, **changes: object) -> MemoryRecord:
        allowed = {"title", "content", "record_type", "scope", "source", "confidence", "retention", "tags", "expires_at"}
        if not changes or set(changes) - allowed:
            raise MemoryValidationError("correction must contain only supported fields")
        with self._lock:
            old = self.get(memory_id)
            values = {
                "title": old.title, "content": old.content, "record_type": old.record_type,
                "scope": old.scope, "source": old.source, "confidence": old.confidence,
                "retention": old.retention, "tags": old.tags, "expires_at": old.expires_at,
            }
            values.update(changes)
            new = self._create(**values, status="review", supersedes_id=old.memory_id)
            try:
                self._transport.update_page(old.memory_id, {"Status": "Archived"})
                self._transport.update_page(new.memory_id, {"Status": "Active"})
            except Exception as exc:
                raise MemorySyncError(
                    f"Notion correction is partially complete; reconcile replacement {new.memory_id}",
                    new.memory_id,
                ) from exc
            return self.get(new.memory_id)

    def archive(self, memory_id: str) -> MemoryRecord:
        _validate_text(memory_id, "memory_id", 64)
        return self._record_from_page(
            self._transport.update_page(memory_id, {"Status": "Archived"})
        )

    def delete(self, memory_id: str) -> None:
        """Move the Notion page to trash; this is not secure or permanent erasure."""
        _validate_text(memory_id, "memory_id", 64)
        self._transport.delete_page(memory_id)

    def expire(self, *, now: datetime | None = None) -> tuple[str, ...]:
        instant = _iso(now or _now())
        expired = []
        with self._lock:
            for record in self._list_all():
                if record.status in {"active", "review"} and record.expires_at is not None and record.expires_at <= instant:
                    self.archive(record.memory_id)
                    expired.append(record.memory_id)
        return tuple(sorted(expired))

    def export_json(self) -> str:
        records = sorted(self._list_all(), key=lambda item: (item.created_at, item.memory_id))
        return json.dumps([asdict(record) for record in records], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
