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
        if not isinstance(items, list):
            raise NotionTransportError("Notion rich-text property is missing or malformed")
        parts = []
        for item in items:
            if not isinstance(item, Mapping):
                raise NotionTransportError("Notion rich-text contains a malformed item")
            plain_text = item.get("plain_text")
            if type(plain_text) is str:
                parts.append(plain_text)
                continue
            text_value = item.get("text")
            if isinstance(text_value, Mapping) and type(text_value.get("content")) is str:
                parts.append(text_value["content"])
                continue
            raise NotionTransportError("Notion rich-text item has no readable text")
        return "".join(parts)

    @classmethod
    def _normalize_page(cls, raw: Mapping[str,object]) -> dict[str,object]:
        in_trash = raw.get("in_trash")
        if type(in_trash) is not bool:
            raise NotionTransportError("Notion page response has no valid trash state")
        if in_trash:
            raise MemoryNotFoundError("Notion page is in trash")
        props = raw.get("properties")
        if not isinstance(props, Mapping):
            raise NotionTransportError("Notion page response has no properties")

        def p(name, expected_type):
            value = props.get(name)
            expected = (expected_type,) if isinstance(expected_type, str) else expected_type
            if (
                not isinstance(value, Mapping)
                or type(value.get("type")) is not str
                or value["type"] not in expected
            ):
                raise NotionTransportError(f"Notion page property {name} has an unexpected type")
            return value

        def option(name, kind):
            value = p(name, kind).get(kind)
            if not isinstance(value, Mapping) or type(value.get("name")) is not str:
                raise NotionTransportError(f"Notion page property {name} has a malformed option")
            return value["name"]

        expiry_value = p("Expires", "date").get("date")
        if expiry_value is None:
            expires_at = None
        elif isinstance(expiry_value, Mapping) and type(expiry_value.get("start")) is str:
            expires_at = expiry_value["start"]
        else:
            raise NotionTransportError("Notion Expires property is malformed")

        tags = p("Tags", "multi_select").get("multi_select")
        if not isinstance(tags, list):
            raise NotionTransportError("Notion Tags property is missing or malformed")
        normalized_tags = []
        for item in tags:
            if not isinstance(item, Mapping) or type(item.get("name")) is not str:
                raise NotionTransportError("Notion Tags contains a malformed option")
            normalized_tags.append(item["name"])

        status_property = props.get("Status")
        if (
            not isinstance(status_property, Mapping)
            or type(status_property.get("type")) is not str
            or status_property["type"] not in {"status", "select"}
        ):
            raise NotionTransportError("Notion Status property has an unexpected type")
        status = option("Status", status_property["type"])

        return {
            "id": raw.get("id"), "created_time": raw.get("created_time"),
            "last_edited_time": raw.get("last_edited_time"), "in_trash": False,
            "properties": {
                "Name": cls._plain(p("Name", "title").get("title")),
                "Content": cls._plain(p("Content", "rich_text").get("rich_text")),
                "Type": option("Type", "select"), "Scope": option("Scope", "select"),
                "Sensitive": p("Sensitive", "checkbox").get("checkbox"),
                "Source": p("Source", "url").get("url"),
                "Confidence": option("Confidence", "select"),
                "Retention": option("Retention", "select"),
                "Tags": normalized_tags,
                "Status": status,
                "Expires": expires_at,
                "Supersedes": cls._plain(p("Supersedes", "rich_text").get("rich_text")) or None,
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

    def validate_data_source_schema(self) -> None:
        """Fail closed unless the configured data source matches Capri's memory schema.

        This is an explicit, read-only startup preflight. It does not create or
        modify Notion properties and is not run implicitly on every request.
        """
        raw = self._request("GET", f"/data_sources/{self.data_source_id}")
        if raw.get("object") != "data_source" or raw.get("id") != self.data_source_id:
            raise NotionTransportError("Notion data source identity does not match configuration")
        properties = raw.get("properties")
        if not isinstance(properties, Mapping):
            raise NotionTransportError("Notion data source schema is missing properties")

        expected_types = {
            "Name": ("title",),
            "Content": ("rich_text",),
            "Type": ("select",),
            "Scope": ("select",),
            "Sensitive": ("checkbox",),
            "Source": ("url",),
            "Confidence": ("select",),
            "Retention": ("select",),
            "Tags": ("multi_select",),
            "Status": ("status", "select"),
            "Expires": ("date",),
            "Supersedes": ("rich_text",),
        }
        required_options = {
            "Type": ("Operating Directive", "Architecture Decision", "Project Fact", "Security Boundary", "User Preference"),
            "Scope": ("Capri System", "GitHub Repository", "Notion Workspace", "Tool Integration"),
            "Confidence": ("User-Directed", "Verified", "Inferred", "Unverified"),
            "Retention": ("Keep until deleted", "Expire after 30 days", "Expire after 90 days", "Archive when superseded"),
            "Status": ("Active", "Review", "Archived"),
        }

        for name, allowed_types in expected_types.items():
            descriptor = properties.get(name)
            if (
                not isinstance(descriptor, Mapping)
                or type(descriptor.get("type")) is not str
                or descriptor["type"] not in allowed_types
            ):
                raise NotionTransportError(f"Notion data source property {name} has an unexpected type")

        for name, required_names in required_options.items():
            descriptor = properties[name]
            property_type = descriptor["type"]
            config = descriptor.get(property_type)
            if not isinstance(config, Mapping) or type(config.get("options")) is not list:
                raise NotionTransportError(f"Notion data source property {name} has malformed options")
            option_names = {
                option.get("name")
                for option in config["options"]
                if isinstance(option, Mapping) and type(option.get("name")) is str
            }
            if not set(required_names).issubset(option_names):
                raise NotionTransportError(f"Notion data source property {name} is missing required options")

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
        has_more = raw.get("has_more")
        if type(has_more) is not bool:
            raise NotionTransportError("Notion query omitted its pagination state")
        if "next_cursor" not in raw:
            raise NotionTransportError("Notion query omitted its cursor field")
        next_cursor = raw["next_cursor"]
        if has_more:
            if type(next_cursor) is not str or not next_cursor:
                raise NotionTransportError("Notion query omitted its continuation cursor")
        elif next_cursor is not None:
            raise NotionTransportError("Notion query returned a cursor without more results")
        return {"results":[self._normalize_page(x) for x in results],"next_cursor":next_cursor}

    def update_page(self, page_id: str, properties: Mapping[str,object]) -> Mapping[str,object]:
        if not isinstance(page_id,str) or not re.fullmatch(r"[0-9a-fA-F-]{32,36}",page_id): raise MemoryValidationError("Notion page ID is invalid")
        raw=self._request("PATCH",f"/pages/{quote(page_id,safe='')}",{"properties":self._encode_properties(properties)})
        return self._normalize_page(raw)

    def delete_page(self, page_id: str) -> None:
        if not isinstance(page_id,str) or not re.fullmatch(r"[0-9a-fA-F-]{32,36}",page_id): raise MemoryValidationError("Notion page ID is invalid")
        self._request("PATCH",f"/pages/{quote(page_id,safe='')}",{"in_trash":True})
