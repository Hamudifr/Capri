import os
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from capri_runtime.notion_memory import MemorySyncError, NotionMemoryAdapter
from capri_runtime.notion_smoke import main, run_smoke
from test_notion_memory import FakeNotionTransport


class NotionSmokeTests(unittest.TestCase):
    def test_smoke_cycle_cleans_up_all_temporary_pages(self):
        transport = FakeNotionTransport()
        run_smoke(NotionMemoryAdapter(transport))
        self.assertEqual(transport.pages, {})

    def test_smoke_cleans_up_page_id_from_failed_initial_create(self):
        transport = FakeNotionTransport()
        adapter = NotionMemoryAdapter(transport)
        orphan = adapter.create(
            title="Temporary orphan",
            content="Temporary test record",
            record_type="project_fact",
            scope="GitHub Repository",
            source="https://github.com/Hamudifr/Capri",
            confidence="verified",
            retention="keep",
            tags=("tooling",),
        )
        failure = MemorySyncError("create response mismatch", orphan.memory_id)
        with patch.object(adapter, "create", side_effect=failure):
            with self.assertRaises(MemorySyncError):
                run_smoke(adapter)
        self.assertEqual(transport.pages, {})

    def test_live_smoke_is_opt_in(self):
        with patch.dict(os.environ, {"CAPRI_NOTION_LIVE_TESTS": "false"}, clear=False):
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(), 0)
        self.assertIn("SKIP", output.getvalue())

    def test_live_smoke_requires_runtime_credentials_when_enabled(self):
        with patch.dict(os.environ, {"CAPRI_NOTION_LIVE_TESTS": "true"}, clear=True):
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(), 1)
        self.assertIn("FAIL", output.getvalue())
        self.assertNotIn("NOTION_API_TOKEN", output.getvalue())


if __name__ == "__main__":
    unittest.main()
