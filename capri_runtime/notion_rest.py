"""Concrete Notion REST transport for the injected memory adapter."""
from __future__ import annotations
import json, os, re, uuid
from collections.abc import Mapping
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from .memory import MemoryErrorBase, MemoryNotFoundError, MemoryValidationError
from .notion_memory import NotionMemoryTransport

NOTION_API_VERSION = "2026-03-11"
NOTION_API_BASE = "https://api.notion.com/v1"
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_MAX_RICH_TEXT_CHUNK = 2_000

class _NoRedirectHandler(HTTPRedirectHandler):
    """Refuse redirects so bearer credentials are never forwarded to another origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class NotionTransportError(MemoryErrorBase):
    """Redacted Notion REST transport failure."""

class NotionRateLimitError(NotionTransportError):
    """HTTP 429; caller may use retry_after. No mutation is retried automatically."""
    def __init__(self, retry_after: float | None) -> None:
        super().__init__("Notion rate limit reached")
        self.retry_after = retry_after

class NotionRESTTransport:
    """Standard-library Notion REST client; token is injected and held in memory only."""
    def __init__(self, api_token: str, data_source_id: str, *, timeout: float = 10.0, opener: Callable[..., object] | None = None) -> None:
        if not isinstance(api_token, str) or not api_token.strip() or len(api_token) > 4096:
            raise MemoryValidationError("Notion API token is missing or invalid")
        try:
            self.data_source_id = str(uuid.UUID(data_source_id))
        except (ValueError, TypeError, AttributeError):
            raise MemoryValidationError("Notion data source ID must be a UUID") from None
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1 <= timeout <= 30:
            raise MemoryValidationError("timeout must be between 1 and 30 seconds")
        self._token = api_token
        self._timeout = float(timeout)
        self._opener = opener or build_opener(_NoRedirectHandler()).open

    @classmethod
    def from_environment(cls, *, token_env: str = "NOTION_API_TOKEN", data_source_env: str = "CAPRI_MEMORY_DATA_SOURCE_ID", timeout: float = 10.0, opener: Callable[..., object] | None = None) -> "NotionRESTTransport":
        token, source = os.environ.get(token_env), os.environ.get(data_source_env)
        if not token: raise MemoryValidationError(f"{token_env} is not configured")
        if not source: raise MemoryValidationError(f"{data_source_env} is not configured")
        return cls(token, source, timeout=timeout, opener=opener)

    def __repr__(self) -> str:
        return f"NotionRESTTransport(data_source_id={self.data_source_id!r}, api_version={NOTION_API_VERSION!r})"

    @staticmethod
    def _rich_text(value: str) -> list[dict[str, object]]:
        return [{"type":"text","text":{"content":value[i:i+_MAX_RICH_TEXT_CHUNK]}} for i in range(0,len(value),_MAX_RICH_TEXT_CHUNK)]

    @classmethod
    def _encode_properties(cls, properties: Mapping[str, object]) -> dict[str, object]:
        out = {}
        for name, value in properties.items():
            if name in {"Name","Content","Supersedes"}:
                if value is None and name == "Supersedes": value = ""
                if not isinstance(value,str): raise MemoryValidationError(f"{name} must be text")
                out[name] = {"title" if name=="Name" else "rich_text": cls._rich_text(value)}
            elif name in {"Type","Scope","Confidence","Retention"}:
                if not isinstance(value,str): raise MemoryValidationError(f"{name} must be text")
                out[name] = {"select":{"name":value}}
            elif name == "Status":
                if not isinstance(value,str): raise MemoryValidationError("Status must be text")
                out[name] = {"status":{"name":value}}
            elif name == "Sensitive":
                if not isinstance(value,bool): raise MemoryValidationError("Sensitive must be boolean")
                out[name] = {"checkbox":value}
            elif name == "Source":
                if value is not None and not isinstance(value,str): raise MemoryValidationError("Source must be URL text")
                out[name] = {"url":value}
            elif name == "Tags":
                if not isinstance(value,(list,tuple)) or any(not isinstance(x,str) for x in value): raise MemoryValidationError("Tags must be strings")
                out[name] = {"multi_select":[{"name":x} for x in value]}
            elif name == "Expires":
                if value is not None and not isinstance(value,str): raise MemoryValidationError("Expires must be an ISO timestamp")
                out[name] = {"date":None if value is None else {"start":value}}
            else:
                raise MemoryValidationError(f"unsupported Notion property: {name}")
        return out

    @staticmethod
    def _plain(items: object) -> str:
        if not isinstance(items,list): return ""
        parts=[]
        for item in items:
            if not isinstance(item,Mapping): continue
            if isinstance(item.get("plain_text"),str): parts.append(item["plain_text"])
            elif isinstance(item.get("text"),Mapping) and isinstance(item["text"].get("content"),str): parts.append(item["text"]["content"])
        return "".join(parts)

    @classmethod
    def _normalize_page(cls, raw: Mapping[str,object]) -> dict[str,object]:
        in_trash = raw.get("in_trash")
        if type(in_trash) is not bool:
            raise NotionTransportError("Notion page response has no valid trash state")
        if in_trash:
            raise MemoryNotFoundError("Notion page is in trash")
        props=raw.get("properties")
        if not isinstance(props,Mapping): raise NotionTransportError("Notion page response has no properties")
        def p(name):
            value=props.get(name,{})
            return value if isinstance(value,Mapping) else {}
        def option(name,kind):
            value=p(name).get(kind)
            return value.get("name") if isinstance(value,Mapping) and isinstance(value.get("name"),str) else None
        expiry=p("Expires").get("date")
        tags=p("Tags").get("multi_select")
        # Missing lifecycle state must remain unclassified for the adapter to reject.
        status=option("Status","status") or option("Status","select")
        return {
            "id":raw.get("id"),"created_time":raw.get("created_time"),
            "last_edited_time":raw.get("last_edited_time"),"in_trash":False,
            "properties":{
                "Name":cls._plain(p("Name").get("title")),
                "Content":cls._plain(p("Content").get("rich_text")),
                "Type":option("Type","select"),"Scope":option("Scope","select"),
                # Preserve absence; do not silently classify a missing checkbox as non-sensitive.
                "Sensitive":p("Sensitive").get("checkbox"),"Source":p("Source").get("url"),
                "Confidence":option("Confidence","select"),"Retention":option("Retention","select"),
                "Tags":[x.get("name") for x in tags if isinstance(x,Mapping) and isinstance(x.get("name"),str)] if isinstance(tags,list) else [],
                "Status":status,"Expires":expiry.get("start") if isinstance(expiry,Mapping) else None,
                "Supersedes":cls._plain(p("Supersedes").get("rich_text")) or None,
            }
        }

    @staticmethod
    def _error_code(body: bytes) -> str | None:
        try: data=json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError,json.JSONDecodeError): return None
        return data.get("code") if isinstance(data,Mapping) and isinstance(data.get("code"),str) else None

    def _request(self, method: str, path: str, payload: Mapping[str,object] | None=None) -> Mapping[str,object]:
        if not path.startswith("/") or ".." in path.split("/"): raise MemoryValidationError("invalid Notion API path")
        url=NOTION_API_BASE+path
        body=None if payload is None else json.dumps(payload,ensure_ascii=False,separators=(",",":")).encode()
        headers={"Authorization":f"Bearer {self._token}","Notion-Version":NOTION_API_VERSION,"Accept":"application/json"}
        if body is not None: headers["Content-Type"]="application/json"
        request=Request(url,data=body,headers=headers,method=method)
        try:
            response=self._opener(request,timeout=self._timeout)
            with response as result:
                final=result.geturl() if callable(getattr(result,"geturl",None)) else url
                parsed=urlsplit(final)
                if parsed.scheme!="https" or parsed.hostname!="api.notion.com": raise NotionTransportError("Notion API redirected outside approved HTTPS origin")
                status=getattr(result,"status",result.getcode())
                raw=result.read(_MAX_RESPONSE_BYTES+1)
            if len(raw)>_MAX_RESPONSE_BYTES: raise NotionTransportError("Notion API response exceeded size limit")
            if not 200<=status<300:
                code=self._error_code(raw) or "unknown"
                if status==404 or code=="object_not_found": raise MemoryNotFoundError("Notion resource not found")
                if status==429: raise NotionRateLimitError(None)
                raise NotionTransportError(f"Notion API request failed (HTTP {status}, code {code})")
        except HTTPError as exc:
            code=self._error_code(exc.read(4096)) or "unknown"
            if exc.code==404 or code=="object_not_found": raise MemoryNotFoundError("Notion resource not found") from None
            if exc.code==429:
                try: retry=float(exc.headers.get("Retry-After")) if exc.headers.get("Retry-After") else None
                except (TypeError,ValueError): retry=None
                raise NotionRateLimitError(retry) from None
            if exc.code in {401,403}: raise NotionTransportError("Notion authorization or sharing permission failed") from None
            raise NotionTransportError(f"Notion API request failed (HTTP {exc.code}, code {code})") from None
        except URLError: raise NotionTransportError("Notion API connection failed") from None
        except (TimeoutError,OSError): raise NotionTransportError("Notion API transport failed") from None
        try: data=json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError,json.JSONDecodeError): raise NotionTransportError("Notion API returned malformed JSON") from None
        if not isinstance(data,Mapping): raise NotionTransportError("Notion API returned non-object response")
        return data

    def create_page(self, properties: Mapping[str,object]) -> Mapping[str,object]:
        raw=self._request("POST","/pages",{"parent":{"type":"data_source_id","data_source_id":self.data_source_id},"properties":self._encode_properties(properties)})
        return self._normalize_page(raw)

    def get_page(self, page_id: str) -> Mapping[str,object]:
        if not isinstance(page_id,str) or not re.fullmatch(r"[0-9a-fA-F-]{32,36}",page_id): raise MemoryValidationError("Notion page ID is invalid")
        return self._normalize_page(self._request("GET",f"/pages/{quote(page_id,safe='')}"))

    def list_pages(self, *, cursor: str | None, page_size: int) -> Mapping[str,object]:
        if isinstance(page_size,bool) or not isinstance(page_size,int) or not 1<=page_size<=100: raise MemoryValidationError("page_size must be between 1 and 100")
        payload={"page_size":page_size,"in_trash":False}
        if cursor is not None:
            if not isinstance(cursor,str): raise MemoryValidationError("Notion cursor must be an opaque string")
            payload["start_cursor"]=cursor
        raw=self._request("POST",f"/data_sources/{self.data_source_id}/query",payload)
        results=raw.get("results")
        if not isinstance(results,list) or any(not isinstance(x,Mapping) for x in results):
            raise NotionTransportError("Notion query returned malformed results")
        has_more = raw.get("has_more") is True
        next_cursor = raw.get("next_cursor") if has_more else None
        if has_more and (not isinstance(next_cursor,str) or not next_cursor):
            raise NotionTransportError("Notion query omitted its continuation cursor")
        return {"results":[self._normalize_page(x) for x in results],"next_cursor":next_cursor}

    def update_page(self, page_id: str, properties: Mapping[str,object]) -> Mapping[str,object]:
        if not isinstance(page_id,str) or not re.fullmatch(r"[0-9a-fA-F-]{32,36}",page_id): raise MemoryValidationError("Notion page ID is invalid")
        raw=self._request("PATCH",f"/pages/{quote(page_id,safe='')}",{"properties":self._encode_properties(properties)})
        return self._normalize_page(raw)

    def delete_page(self, page_id: str) -> None:
        if not isinstance(page_id,str) or not re.fullmatch(r"[0-9a-fA-F-]{32,36}",page_id): raise MemoryValidationError("Notion page ID is invalid")
        self._request("PATCH",f"/pages/{quote(page_id,safe='')}",{"in_trash":True})
