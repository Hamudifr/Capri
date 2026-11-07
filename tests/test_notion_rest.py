import io, json, os, unittest
from urllib.error import HTTPError
from capri_runtime.memory import MemoryNotFoundError, MemoryValidationError
from capri_runtime.notion_memory import NotionMemoryAdapter
from capri_runtime.notion_rest import NOTION_API_VERSION, NotionRateLimitError, NotionRESTTransport, NotionTransportError, _NoRedirectHandler

PAGE_ID="b55c9c91-384d-452b-81db-d1ef79372b75"
DATA_SOURCE_ID="435a6e29-3b57-4637-908b-a07761e0df0f"

class FakeResponse:
    def __init__(self,payload,status=200,url="https://api.notion.com/v1/pages"):
        self.status=status; self.body=json.dumps(payload).encode(); self.url=url
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

def page():
    return {"id":PAGE_ID,"created_time":"2026-11-06T20:00:00Z","last_edited_time":"2026-11-06T20:10:00Z","in_trash":False,"properties":{
        "Name":{"title":[{"plain_text":"Title"}]},"Content":{"rich_text":[{"plain_text":"Body"}]},
        "Type":{"select":{"name":"Project Fact"}},"Scope":{"select":{"name":"GitHub Repository"}},
        "Sensitive":{"checkbox":False},"Source":{"url":"https://github.com/Hamudifr/Capri"},
        "Confidence":{"select":{"name":"Verified"}},"Retention":{"select":{"name":"Keep until deleted"}},
        "Tags":{"multi_select":[{"name":"memory"}]},"Status":{"status":{"name":"Active"}},
        "Expires":{"date":None},"Supersedes":{"rich_text":[]}
    }}

class NotionRESTTransportTests(unittest.TestCase):
    def make(self,payload=None,error=None):
        op=FakeOpener(FakeResponse(payload or page()),error)
        return NotionRESTTransport("test-secret",DATA_SOURCE_ID,opener=op),op

    def test_get_maps_properties_and_auth_version_headers(self):
        t,op=self.make(); result=t.get_page(PAGE_ID); req,timeout=op.requests[0]
        self.assertEqual(result["properties"]["Name"],"Title")
        self.assertEqual(result["properties"]["Tags"],["memory"])
        self.assertIsNone(result["properties"]["Supersedes"])
        self.assertEqual(req.get_header("Notion-version"),NOTION_API_VERSION)
        self.assertIn("Bearer test-secret",req.get_header("Authorization"))
        self.assertEqual(timeout,10.0)

    def test_missing_sensitive_and_status_properties_remain_unclassified(self):
        raw = page()
        raw["properties"]["Sensitive"] = {}
        t, _ = self.make(raw)
        normalized = t.get_page(PAGE_ID)
        self.assertIsNone(normalized["properties"]["Sensitive"])
        with self.assertRaises(MemoryValidationError):
            NotionMemoryAdapter(t).get(PAGE_ID)

        raw = page()
        raw["properties"]["Status"] = {}
        t, _ = self.make(raw)
        normalized = t.get_page(PAGE_ID)
        self.assertIsNone(normalized["properties"]["Status"])
        with self.assertRaises(MemoryValidationError):
            NotionMemoryAdapter(t).get(PAGE_ID)

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
        t2,op2=self.make(); t2.delete_page(PAGE_ID)
        self.assertEqual(json.loads(op2.requests[0][0].data),{"in_trash":True})

    def test_404_is_not_found_and_429_exposes_retry_after(self):
        err=HTTPError("https://api.notion.com/v1/pages",404,"Not found",{},io.BytesIO(b'{"code":"object_not_found"}'))
        t,_=self.make(error=err)
        with self.assertRaises(MemoryNotFoundError): t.get_page(PAGE_ID)
        err=HTTPError("https://api.notion.com/v1/pages",429,"Rate limited",{"Retry-After":"3"},io.BytesIO(b'{"code":"rate_limited"}'))
        t,_=self.make(error=err)
        with self.assertRaises(NotionRateLimitError) as caught: t.get_page(PAGE_ID)
        self.assertEqual(caught.exception.retry_after,3.0)

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
        t,op=self.make(); op.response=FakeResponse(page(),url="https://attacker.example/steal")
        with self.assertRaises(NotionTransportError): t.get_page(PAGE_ID)
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
                    raw["properties"]["Tags"] = {"multi_select": value}
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

if __name__=="__main__": unittest.main()
