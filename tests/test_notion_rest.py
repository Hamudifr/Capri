import io, json, os, unittest
from urllib.error import HTTPError
from capri_runtime.memory import MemoryNotFoundError, MemoryValidationError
from capri_runtime.notion_memory import NotionMemoryAdapter
from capri_runtime.notion_rest import (
    NOTION_API_VERSION, NotionRateLimitError, NotionRESTTransport,
    NotionTransportError, _NoRedirectHandler,
    create_notion_memory_adapter_from_environment,
)

PAGE_ID="b55c9c91-384d-452b-81db-d1ef79372b75"
DATA_SOURCE_ID="435a6e29-3b57-4637-908b-a07761e0df0f"

class FakeResponse:
    def __init__(self,payload,status=200,url="https://api.notion.com/v1/pages",headers=None):
        self.status=status; self.body=json.dumps(payload).encode(); self.url=url; self.headers=headers or {}
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def read(self,size=-1): return self.body if size<0 else self.body[:size]
    def geturl(self): return self.url
    def getcode(self): return self.status

class FakeOpener:
    def __init__(self,response=None,error=None): self.response=response or FakeResponse({}); self.error=error; self.requests=[]
    def __call__(self,request,timeout):
        self.requests.append((request,timeout))
        if self.error: raise self.error
        return self.response

class SequenceOpener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        if not self.responses:
            raise AssertionError("unexpected extra request")
        return self.responses.pop(0)


def data_source_schema():
    expected = {
        "Name": ("title", None),
        "Content": ("rich_text", None),
        "Type": ("select", ["Operating Directive", "Architecture Decision", "Project Fact", "Security Boundary", "User Preference"]),
        "Scope": ("select", ["Capri System", "GitHub Repository", "Notion Workspace", "Tool Integration"]),
        "Sensitive": ("checkbox", None),
        "Source": ("url", None),
        "Confidence": ("select", ["User-Directed", "Verified", "Inferred", "Unverified"]),
        "Retention": ("select", ["Keep until deleted", "Expire after 30 days", "Expire after 90 days", "Archive when superseded"]),
        "Tags": ("multi_select", ["autonomy", "delivery", "security", "memory", "architecture", "tooling"]),
        "Status": ("status", ["Active", "Review", "Archived"]),
        "Expires": ("date", None),
        "Supersedes": ("rich_text", None),
    }
    properties = {}
    for name, (kind, options) in expected.items():
        config = {} if options is None else {"options": [{"name": option} for option in options]}
        properties[name] = {"id": name, "name": name, "type": kind, kind: config}
    return {"object": "data_source", "id": DATA_SOURCE_ID, "properties": properties}


def page():
    return {"id":PAGE_ID,"created_time":"2026-11-06T20:00:00Z","last_edited_time":"2026-11-06T20:10:00Z","in_trash":False,"properties":{
        "Name":{"type":"title","title":[{"plain_text":"Title"}]},"Content":{"type":"rich_text","rich_text":[{"plain_text":"Body"}]},
        "Type":{"type":"select","select":{"name":"Project Fact"}},"Scope":{"type":"select","select":{"name":"GitHub Repository"}},
        "Sensitive":{"type":"checkbox","checkbox":False},"Source":{"type":"url","url":"https://github.com/Hamudifr/Capri"},
        "Confidence":{"type":"select","select":{"name":"Verified"}},"Retention":{"type":"select","select":{"name":"Keep until deleted"}},
        "Tags":{"type":"multi_select","multi_select":[{"name":"memory"}]},"Status":{"type":"status","status":{"name":"Active"}},
        "Expires":{"type":"date","date":None},"Supersedes":{"type":"rich_text","rich_text":[]}
    }}

class NotionRESTTransportTests(unittest.TestCase):
    def make(self,payload=None,error=None):
        op=FakeOpener(FakeResponse(payload or page()),error)
        return NotionRESTTransport("test-secret",DATA_SOURCE_ID,opener=op),op

    def test_schema_preflight_accepts_expected_schema(self):
        t, op = self.make(data_source_schema())
        t.validate_data_source_schema()
        request, timeout = op.requests[0]
        self.assertIn(f"/data_sources/{DATA_SOURCE_ID}", request.full_url)
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(timeout, 10.0)

    def test_schema_preflight_rejects_identity_type_and_option_drift(self):
        cases = []
        raw = data_source_schema()
        raw["id"] = PAGE_ID
        cases.append(("wrong data source ID", raw))
        raw = data_source_schema()
        raw["properties"]["Sensitive"]["type"] = "select"
        cases.append(("wrong property type", raw))
        raw = data_source_schema()
        raw["properties"].pop("Tags")
        cases.append(("missing property", raw))
        raw = data_source_schema()
        raw["properties"]["Status"]["status"]["options"] = [{"name": "Active"}, {"name": "Archived"}]
        cases.append(("missing lifecycle option", raw))
        raw = data_source_schema()
        raw["properties"]["Tags"]["multi_select"]["options"].pop()
        cases.append(("missing supported tag option", raw))
        raw = data_source_schema()
        raw["properties"]["Type"]["select"]["options"] = "not-a-list"
        cases.append(("malformed options", raw))
        for label, payload in cases:
            with self.subTest(label=label):
                t, _ = self.make(payload)
                with self.assertRaises(NotionTransportError):
                    t.validate_data_source_schema()

    def test_schema_preflight_accepts_legacy_select_status(self):
        raw = data_source_schema()
        status = raw["properties"]["Status"]
        raw["properties"]["Status"] = {
            "id": status["id"], "name": "Status", "type": "select",
            "select": status["status"],
        }
        t, _ = self.make(raw)
        t.validate_data_source_schema()

    def test_get_rejects_response_for_different_page_id(self):
        raw = page()
        raw["id"] = DATA_SOURCE_ID
        transport, _ = self.make(raw)
        with self.assertRaises(NotionTransportError):
            transport.get_page(PAGE_ID)

    def test_update_rejects_empty_payload_before_network(self):
        transport, opener = self.make()
        with self.assertRaises(MemoryValidationError):
            transport.update_page(PAGE_ID, {})
        self.assertEqual(opener.requests, [])

    def test_update_rejects_response_for_different_page_id(self):
        raw = page()
        raw["id"] = DATA_SOURCE_ID
        transport, _ = self.make(raw)
        with self.assertRaises(NotionTransportError):
            transport.update_page(PAGE_ID, {"Status": "Archived"})

    def test_get_maps_properties_and_auth_version_headers(self):
        t,op=self.make(); result=t.get_page(PAGE_ID); req,timeout=op.requests[0]
        self.assertEqual(result["properties"]["Name"],"Title")
        self.assertEqual(result["properties"]["Tags"],["memory"])
        self.assertIsNone(result["properties"]["Supersedes"])
        self.assertEqual(req.get_header("Notion-version"),NOTION_API_VERSION)
        self.assertIn("Bearer test-secret",req.get_header("Authorization"))
        self.assertEqual(timeout,10.0)

    def test_page_properties_require_expected_notion_types(self):
        wrong_types = {
            "Name": "rich_text", "Content": "title", "Type": "status",
            "Scope": "url", "Sensitive": "select", "Source": "checkbox",
            "Confidence": "status", "Retention": "rich_text",
            "Tags": "rich_text", "Status": "checkbox",
            "Expires": "rich_text", "Supersedes": "title",
        }
        for property_name, wrong_type in wrong_types.items():
            with self.subTest(property_name=property_name, wrong_type=wrong_type):
                raw = page()
                raw["properties"][property_name]["type"] = wrong_type
                t, _ = self.make(raw)
                with self.assertRaises(NotionTransportError):
                    t.get_page(PAGE_ID)

    def test_malformed_expiry_value_is_rejected(self):
        raw = page()
        raw["properties"]["Expires"]["date"] = "not-a-date-object"
        t, _ = self.make(raw)
        with self.assertRaises(NotionTransportError):
            t.get_page(PAGE_ID)

    def test_legacy_select_status_type_remains_supported(self):
        raw = page()
        raw["properties"]["Status"] = {"type": "select", "select": {"name": "Active"}}
        t, _ = self.make(raw)
        self.assertEqual(t.get_page(PAGE_ID)["properties"]["Status"], "Active")

    def test_missing_sensitive_and_status_properties_are_rejected(self):
        for property_name in ("Sensitive", "Status"):
            with self.subTest(property_name=property_name):
                raw = page()
                raw["properties"][property_name] = {}
                t, _ = self.make(raw)
                with self.assertRaises(NotionTransportError):
                    t.get_page(PAGE_ID)

    def test_create_rejects_incomplete_memory_properties_before_network(self):
        valid = {
            "Name": "Title",
            "Content": "Body",
            "Type": "Project Fact",
            "Scope": "GitHub Repository",
            "Sensitive": False,
            "Source": "https://example.com/source",
            "Confidence": "Verified",
            "Retention": "Keep until deleted",
            "Tags": ["memory"],
            "Status": "Active",
            "Expires": None,
            "Supersedes": None,
        }
        for missing in valid:
            with self.subTest(missing=missing):
                properties = dict(valid)
                properties.pop(missing)
                transport, opener = self.make()
                with self.assertRaises(MemoryValidationError):
                    transport.create_page(properties)
                self.assertEqual(opener.requests, [])

    def test_create_uses_data_source_parent_and_chunks_rich_text(self):
        t,op=self.make()
        t.create_page({"Name":"Title","Content":"x"*4500,"Type":"Project Fact","Scope":"GitHub Repository","Sensitive":False,"Source":"https://github.com/Hamudifr/Capri","Confidence":"Verified","Retention":"Keep until deleted","Tags":["memory"],"Status":"Active","Expires":None,"Supersedes":None})
        body=json.loads(op.requests[0][0].data)
        self.assertEqual(body["parent"]["data_source_id"],DATA_SOURCE_ID)
        self.assertEqual(len(body["properties"]["Content"]["rich_text"]),3)
        self.assertEqual(body["properties"]["Status"]["status"]["name"],"Active")

    def test_query_passes_cursor_opaque_and_uses_data_source_endpoint(self):
        t,op=self.make({"results":[page()],"has_more":True,"next_cursor":"opaque+/cursor=="})
        result=t.list_pages(cursor="not:to:parse?=",page_size=50)
        req=op.requests[0][0]; body=json.loads(req.data)
        self.assertIn(f"/data_sources/{DATA_SOURCE_ID}/query",req.full_url)
        self.assertEqual(body["start_cursor"],"not:to:parse?=")
        self.assertFalse(body["in_trash"])
        self.assertEqual(result["next_cursor"],"opaque+/cursor==")

    def test_query_requires_consistent_explicit_pagination_state(self):
        malformed = (
            {"results": [page()], "next_cursor": None},
            {"results": [page()], "has_more": None, "next_cursor": None},
            {"results": [page()], "has_more": 0, "next_cursor": None},
            {"results": [page()], "has_more": 1, "next_cursor": "cursor"},
            {"results": [page()], "has_more": "false", "next_cursor": None},
            {"results": [page()], "has_more": False, "next_cursor": "unexpected"},
            {"results": [page()], "has_more": False},
            {"results": [page()], "has_more": True, "next_cursor": None},
            {"results": [page()], "has_more": True, "next_cursor": ""},
        )
        for payload in malformed:
            with self.subTest(payload=payload):
                t, _ = self.make(payload)
                with self.assertRaises(NotionTransportError):
                    t.list_pages(cursor=None, page_size=10)

        t, _ = self.make({"results": [page()], "has_more": False, "next_cursor": None})
        self.assertIsNone(t.list_pages(cursor=None, page_size=10)["next_cursor"])

    def test_query_rejects_missing_cursor_and_malformed_page_items(self):
        t,_=self.make({"results":[page()],"has_more":True,"next_cursor":None})
        with self.assertRaises(NotionTransportError):
            t.list_pages(cursor=None,page_size=20)
        t,_=self.make({"results":[None],"has_more":False,"next_cursor":None})
        with self.assertRaises(NotionTransportError):
            t.list_pages(cursor=None,page_size=20)

    def test_update_status_and_trash_use_patch(self):
        t,op=self.make(); t.update_page(PAGE_ID,{"Status":"Archived"})
        self.assertEqual(json.loads(op.requests[0][0].data)["properties"]["Status"]["status"]["name"],"Archived")

    def test_delete_requires_confirmed_trash_response_and_readback(self):
        trashed = {"object": "page", "id": PAGE_ID, "in_trash": True}
        opener = SequenceOpener(FakeResponse(trashed), FakeResponse(trashed))
        transport = NotionRESTTransport("test-secret", DATA_SOURCE_ID, opener=opener)
        transport.delete_page(PAGE_ID)
        self.assertEqual(len(opener.requests), 2)
        self.assertEqual(opener.requests[0][0].get_method(), "PATCH")
        self.assertEqual(json.loads(opener.requests[0][0].data), {"in_trash": True})
        self.assertEqual(opener.requests[1][0].get_method(), "GET")
        self.assertIn(f"/pages/{PAGE_ID}", opener.requests[1][0].full_url)

    def test_delete_rejects_unconfirmed_or_wrong_identity_response(self):
        invalid_responses = (
            {"object": "page", "id": PAGE_ID, "in_trash": False},
            {"object": "page", "id": PAGE_ID, "in_trash": 1},
            {"object": "page", "id": DATA_SOURCE_ID, "in_trash": True},
            {"object": "database", "id": PAGE_ID, "in_trash": True},
            {"id": PAGE_ID, "in_trash": True},
        )
        for payload in invalid_responses:
            with self.subTest(payload=payload):
                opener = SequenceOpener(FakeResponse(payload))
                transport = NotionRESTTransport("test-secret", DATA_SOURCE_ID, opener=opener)
                with self.assertRaises(NotionTransportError):
                    transport.delete_page(PAGE_ID)
                self.assertEqual(len(opener.requests), 1)

    def test_delete_rejects_page_still_retrievable_after_trash(self):
        trashed = {"object": "page", "id": PAGE_ID, "in_trash": True}
        opener = SequenceOpener(FakeResponse(trashed), FakeResponse(page()))
        transport = NotionRESTTransport("test-secret", DATA_SOURCE_ID, opener=opener)
        with self.assertRaises(NotionTransportError):
            transport.delete_page(PAGE_ID)
        self.assertEqual(len(opener.requests), 2)

    def test_404_is_not_found_and_429_exposes_retry_after(self):
        err=HTTPError("https://api.notion.com/v1/pages",404,"Not found",{},io.BytesIO(b'{"code":"object_not_found"}'))
        t,_=self.make(error=err)
        with self.assertRaises(MemoryNotFoundError): t.get_page(PAGE_ID)
        err=HTTPError("https://api.notion.com/v1/pages",429,"Rate limited",{"Retry-After":"3"},io.BytesIO(b'{"code":"rate_limited"}'))
        t,_=self.make(error=err)
        with self.assertRaises(NotionRateLimitError) as caught: t.get_page(PAGE_ID)
        self.assertEqual(caught.exception.retry_after,3.0)

        response = FakeResponse({"code":"rate_limited"}, status=429, headers={"Retry-After":"4.5"})
        opener = FakeOpener(response)
        transport = NotionRESTTransport("test-secret", DATA_SOURCE_ID, opener=opener)
        with self.assertRaises(NotionRateLimitError) as caught: transport.get_page(PAGE_ID)
        self.assertEqual(caught.exception.retry_after,4.5)
        self.assertEqual(len(opener.requests),1)

    def test_auth_errors_redact_response_and_token(self):
        err=HTTPError("https://api.notion.com/v1/pages",401,"Unauthorized",{},io.BytesIO(b'{"message":"private detail","code":"unauthorized"}'))
        t,_=self.make(error=err)
        with self.assertRaises(NotionTransportError) as caught: t.get_page(PAGE_ID)
        self.assertNotIn("private detail",str(caught.exception))
        self.assertNotIn("test-secret",str(caught.exception))

    def test_default_redirect_handler_refuses_cross_origin_redirects(self):
        handler = _NoRedirectHandler()
        from urllib.request import Request
        self.assertIsNone(handler.redirect_request(
            Request("https://api.notion.com/v1/pages"), None, 302, "Found", {},
            "https://attacker.example/steal",
        ))

    def test_redirects_to_untrusted_origin_and_trashed_pages_rejected(self):
        for final_url in (
            "https://attacker.example/steal",
            "https://api.notion.com:8443/v1/pages",
            "https://user:password@api.notion.com/v1/pages",
            "https://api.notion.com:not-a-port/v1/pages",
        ):
            with self.subTest(final_url=final_url):
                t, op = self.make()
                op.response = FakeResponse(page(), url=final_url)
                with self.assertRaises(NotionTransportError):
                    t.get_page(PAGE_ID)
        raw=page(); raw["in_trash"]=True
        t,_=self.make(raw)
        with self.assertRaises(MemoryNotFoundError): t.get_page(PAGE_ID)

    def test_missing_or_malformed_trash_state_is_rejected(self):
        for value in ("missing", None, 0, 1, "false"):
            with self.subTest(value=value):
                raw = page()
                if value == "missing":
                    raw.pop("in_trash")
                else:
                    raw["in_trash"] = value
                t, _ = self.make(raw)
                with self.assertRaises(NotionTransportError):
                    t.get_page(PAGE_ID)

    def test_missing_or_malformed_tag_options_are_rejected(self):
        invalid_values = ("missing", None, [None], [{"name": 7}], [{"name": "memory"}, {}])
        for value in invalid_values:
            with self.subTest(value=value):
                raw = page()
                if value == "missing":
                    raw["properties"]["Tags"] = {}
                else:
                    raw["properties"]["Tags"] = {"type": "multi_select", "multi_select": value}
                t, _ = self.make(raw)
                with self.assertRaises(NotionTransportError):
                    t.get_page(PAGE_ID)

    def test_malformed_rich_text_is_rejected_instead_of_partially_dropped(self):
        cases = (
            ("Name", "title", [None]),
            ("Content", "rich_text", [{"plain_text": "kept"}, {}]),
            ("Content", "rich_text", "not-a-list"),
            ("Supersedes", "rich_text", [{"text": {}}]),
        )
        for property_name, field_name, value in cases:
            with self.subTest(property_name=property_name, value=value):
                raw = page()
                raw["properties"][property_name][field_name] = value
                t, _ = self.make(raw)
                with self.assertRaises(NotionTransportError):
                    t.get_page(PAGE_ID)

        raw = page()
        raw["properties"]["Content"]["rich_text"] = [{"text": {"content": "fallback text"}}]
        t, _ = self.make(raw)
        self.assertEqual(t.get_page(PAGE_ID)["properties"]["Content"], "fallback text")

    def test_outbound_encoder_rejects_malformed_or_timezone_naive_expiry(self):
        for value in ("not-a-date", "2026-12-01", "2026-12-01T12:00:00"):
            with self.subTest(value=value):
                with self.assertRaises(MemoryValidationError):
                    NotionRESTTransport._encode_properties({"Expires": value})

    def test_outbound_encoder_accepts_timezone_aware_expiry(self):
        for value in ("2026-12-01T12:00:00+00:00", "2026-12-01T12:00:00Z"):
            with self.subTest(value=value):
                self.assertEqual(
                    NotionRESTTransport._encode_properties({"Expires": value}),
                    {"Expires": {"date": {"start": value}}},
                )

    def test_outbound_encoder_rejects_sensitive_classification(self):
        with self.assertRaises(MemoryValidationError):
            NotionRESTTransport._encode_properties({"Sensitive": True})
        self.assertEqual(
            NotionRESTTransport._encode_properties({"Sensitive": False}),
            {"Sensitive": {"checkbox": False}},
        )

    def test_outbound_encoder_rejects_unsupported_select_and_status_labels(self):
        invalid = (
            {"Type": "Unapproved Type"},
            {"Scope": "Unapproved Scope"},
            {"Confidence": "Unapproved Confidence"},
            {"Retention": "Unapproved Retention"},
            {"Status": "Unapproved Status"},
        )
        for properties in invalid:
            with self.subTest(properties=properties):
                with self.assertRaises(MemoryValidationError):
                    NotionRESTTransport._encode_properties(properties)

    def test_outbound_encoder_rejects_unsupported_or_duplicate_tags(self):
        invalid = (
            {"Tags": ["unknown-tag"]},
            {"Tags": ["memory", "memory"]},
            {"Tags": ["memory"] * 21},
        )
        for properties in invalid:
            with self.subTest(properties=properties):
                with self.assertRaises(MemoryValidationError):
                    NotionRESTTransport._encode_properties(properties)

    def test_outbound_encoder_rejects_non_http_source_urls(self):
        for value in (
            None, "javascript:alert(1)", "file:///etc/passwd", "/relative/path", "https://",
            "https://user:password@example.com/source", "https://[invalid", "https://example.com:bad",
        ):
            with self.subTest(value=value):
                with self.assertRaises(MemoryValidationError):
                    NotionRESTTransport._encode_properties({"Source": value})

    def test_create_rejects_null_required_source_before_network(self):
        properties = {
            "Name": "Title",
            "Content": "Body",
            "Type": "Project Fact",
            "Scope": "GitHub Repository",
            "Sensitive": False,
            "Source": None,
            "Confidence": "Verified",
            "Retention": "Keep until deleted",
            "Tags": ["memory"],
            "Status": "Active",
            "Expires": None,
            "Supersedes": None,
        }
        transport, opener = self.make()
        with self.assertRaises(MemoryValidationError):
            transport.create_page(properties)
        self.assertEqual(opener.requests, [])

    def test_outbound_encoder_accepts_only_supported_memory_labels_and_tags(self):
        properties = {
            "Type": "Project Fact",
            "Scope": "GitHub Repository",
            "Confidence": "Verified",
            "Retention": "Keep until deleted",
            "Status": "Active",
            "Tags": ["memory", "security"],
            "Source": "https://example.com/source",
        }
        encoded = NotionRESTTransport._encode_properties(properties)
        self.assertEqual(encoded["Type"], {"select": {"name": "Project Fact"}})
        self.assertEqual(encoded["Tags"], {"multi_select": [{"name": "memory"}, {"name": "security"}]})
        self.assertEqual(encoded["Source"], {"url": "https://example.com/source"})

    def test_outbound_encoder_enforces_memory_text_bounds(self):
        invalid = (
            {"Name": ""},
            {"Name": "x" * 201},
            {"Content": ""},
            {"Content": "x" * 20_001},
            {"Supersedes": "x" * 65},
            {"Source": "https://example.com/" + "x" * 2048},
            {"Name": "invalid\ud800text"},
        )
        for properties in invalid:
            with self.subTest(field=next(iter(properties))):
                with self.assertRaises(MemoryValidationError):
                    NotionRESTTransport._encode_properties(properties)

    def test_outbound_encoder_accepts_empty_supersedes_and_boundary_lengths(self):
        encoded = NotionRESTTransport._encode_properties({
            "Name": "x" * 200,
            "Content": "x" * 20_000,
            "Supersedes": None,
            "Source": "https://example.com/" + "x" * 2028,
        })
        self.assertEqual(encoded["Supersedes"], {"rich_text": []})
        self.assertEqual(len(encoded["Name"]["title"]), 1)
        self.assertEqual(len(encoded["Content"]["rich_text"]), 10)

    def test_outbound_encoder_rejects_string_and_container_subclasses(self):
        class TextSubclass(str):
            pass
        class ListSubclass(list):
            pass
        class TupleSubclass(tuple):
            pass

        invalid = (
            {"Name": TextSubclass("Title")},
            {"Content": TextSubclass("Body")},
            {"Type": TextSubclass("Project Fact")},
            {"Scope": TextSubclass("GitHub Repository")},
            {"Confidence": TextSubclass("Verified")},
            {"Retention": TextSubclass("Keep until deleted")},
            {"Status": TextSubclass("Active")},
            {"Source": TextSubclass("https://example.com")},
            {"Expires": TextSubclass("2026-12-01T00:00:00+00:00")},
            {"Tags": ListSubclass(["memory"])},
            {"Tags": TupleSubclass(("memory",))},
            {"Tags": ["memory", TextSubclass("memory")]},
            {TextSubclass("Name"): "Title"},
        )
        for properties in invalid:
            with self.subTest(properties=properties):
                with self.assertRaises(MemoryValidationError):
                    NotionRESTTransport._encode_properties(properties)

        self.assertEqual(
            NotionRESTTransport._encode_properties({"Tags": ("memory",)})["Tags"],
            {"multi_select": [{"name": "memory"}]},
        )

    def test_constructor_rejects_subclassed_configuration_primitives(self):
        class TextSubclass(str):
            pass
        class FloatSubclass(float):
            pass

        for args, kwargs in (
            ((TextSubclass("token"), DATA_SOURCE_ID), {}),
            (("token", TextSubclass(DATA_SOURCE_ID)), {}),
            (("token", DATA_SOURCE_ID), {"timeout": FloatSubclass(10.0)}),
        ):
            with self.subTest(args=args, kwargs=kwargs):
                with self.assertRaises(MemoryValidationError):
                    NotionRESTTransport(*args, **kwargs)

    def test_read_and_pagination_inputs_require_exact_primitives(self):
        class TextSubclass(str):
            pass
        class IntSubclass(int):
            pass

        t, op = self.make()
        invalid_calls = (
            lambda: t.get_page(TextSubclass(PAGE_ID)),
            lambda: t.update_page(TextSubclass(PAGE_ID), {"Status": "Active"}),
            lambda: t.delete_page(TextSubclass(PAGE_ID)),
            lambda: t.get_page("not-a-uuid"),
            lambda: t.update_page("not-a-uuid", {"Status": "Active"}),
            lambda: t.delete_page("not-a-uuid"),
            lambda: t.list_pages(cursor=TextSubclass("opaque"), page_size=10),
            lambda: t.list_pages(cursor="", page_size=10),
            lambda: t.list_pages(cursor=None, page_size=IntSubclass(10)),
            lambda: t.list_pages(cursor=None, page_size=True),
        )
        for call in invalid_calls:
            with self.subTest(call=call):
                with self.assertRaises(MemoryValidationError):
                    call()
        self.assertEqual(op.requests, [])

    def test_response_normalizer_rejects_container_subclasses(self):
        class DictSubclass(dict):
            pass
        class ListSubclass(list):
            pass

        with self.assertRaises(NotionTransportError):
            NotionRESTTransport._normalize_page(DictSubclass(page()))
        with self.assertRaises(NotionTransportError):
            NotionRESTTransport._plain(ListSubclass([{"plain_text": "text"}]))
        with self.assertRaises(NotionTransportError):
            NotionRESTTransport._plain([DictSubclass({"plain_text": "text"})])

    def test_response_size_and_configuration_are_bounded(self):
        t,op=self.make()
        class Big(FakeResponse):
            def read(self,size=-1): return b"x"*(8*1024*1024+1)
        op.response=Big({})
        with self.assertRaises(NotionTransportError): t.get_page(PAGE_ID)
        with self.assertRaises(MemoryValidationError): NotionRESTTransport("",DATA_SOURCE_ID)
        with self.assertRaises(MemoryValidationError): NotionRESTTransport("x","not-a-uuid")

    def test_environment_factory_does_not_leak_token_in_repr(self):
        old=dict(os.environ)
        try:
            os.environ["CAPRI_TEST_NOTION_TOKEN"]="hidden-token"
            os.environ["CAPRI_TEST_NOTION_SOURCE"]=DATA_SOURCE_ID
            t=NotionRESTTransport.from_environment(token_env="CAPRI_TEST_NOTION_TOKEN",data_source_env="CAPRI_TEST_NOTION_SOURCE")
            self.assertNotIn("hidden-token",repr(t))
        finally:
            os.environ.clear(); os.environ.update(old)

    def test_memory_adapter_environment_factory_preflights_schema_before_return(self):
        old = dict(os.environ)
        try:
            os.environ["CAPRI_FACTORY_NOTION_TOKEN"] = "hidden-token"
            os.environ["CAPRI_FACTORY_NOTION_SOURCE"] = DATA_SOURCE_ID
            opener = FakeOpener(FakeResponse(data_source_schema()))
            adapter = create_notion_memory_adapter_from_environment(
                token_env="CAPRI_FACTORY_NOTION_TOKEN",
                data_source_env="CAPRI_FACTORY_NOTION_SOURCE",
                opener=opener,
            )
            self.assertIsInstance(adapter, NotionMemoryAdapter)
            self.assertEqual(len(opener.requests), 1)
            request, _ = opener.requests[0]
            self.assertEqual(request.get_method(), "GET")
            self.assertIn(f"/data_sources/{DATA_SOURCE_ID}", request.full_url)
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_memory_adapter_environment_factory_fails_closed_on_schema_drift(self):
        old = dict(os.environ)
        try:
            os.environ["CAPRI_FACTORY_NOTION_TOKEN"] = "hidden-token"
            os.environ["CAPRI_FACTORY_NOTION_SOURCE"] = DATA_SOURCE_ID
            schema = data_source_schema()
            schema["properties"].pop("Sensitive")
            opener = FakeOpener(FakeResponse(schema))
            with self.assertRaises(NotionTransportError):
                create_notion_memory_adapter_from_environment(
                    token_env="CAPRI_FACTORY_NOTION_TOKEN",
                    data_source_env="CAPRI_FACTORY_NOTION_SOURCE",
                    opener=opener,
                )
            self.assertEqual(len(opener.requests), 1)
        finally:
            os.environ.clear()
            os.environ.update(old)


if __name__=="__main__": unittest.main()
