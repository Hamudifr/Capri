"""Opt-in live Notion REST smoke test.

No test page is created unless CAPRI_NOTION_LIVE_TESTS=true.
"""
from __future__ import annotations

import os
import sys
from uuid import uuid4

from .memory import MemoryNotFoundError
from .notion_memory import MemorySyncError, NotionMemoryAdapter
from .notion_rest import NotionRESTTransport


def run_smoke(adapter: NotionMemoryAdapter) -> None:
    token = uuid4().hex
    created_ids: list[str] = []
    try:
        original = adapter.create(
            title=f"Capri Notion REST smoke {token[:12]}",
            content=f"Temporary non-sensitive integration smoke record {token}",
            record_type="project_fact",
            scope="GitHub Repository",
            source="https://github.com/Hamudifr/Capri",
            confidence="verified",
            retention="keep",
            tags=("tooling",),
        )
        created_ids.append(original.memory_id)
        if adapter.get(original.memory_id).content != f"Temporary non-sensitive integration smoke record {token}":
            raise RuntimeError("Notion create/read round trip did not preserve content")

        try:
            corrected = adapter.correct(
                original.memory_id,
                content=f"Corrected temporary integration smoke record {token}",
            )
        except MemorySyncError as exc:
            created_ids.append(exc.new_memory_id)
            raise
        created_ids.append(corrected.memory_id)

        if corrected.supersedes_id != original.memory_id or corrected.status != "active":
            raise RuntimeError("Notion correction did not preserve supersession metadata")
        if adapter.get(original.memory_id).status != "archived":
            raise RuntimeError("Notion correction did not archive the previous record")
        matches = adapter.search(token, limit=10)
        if not any(item.memory_id == corrected.memory_id for item in matches):
            raise RuntimeError("Notion search did not find the corrected smoke record")

        if adapter.archive(corrected.memory_id).status != "archived":
            raise RuntimeError("Notion archive operation did not persist")
    finally:
        cleanup_failures: list[str] = []
        for memory_id in reversed(created_ids):
            try:
                adapter.delete(memory_id)
                try:
                    adapter.get(memory_id)
                except MemoryNotFoundError:
                    continue
                cleanup_failures.append(memory_id)
            except MemoryNotFoundError:
                continue
            except Exception:
                cleanup_failures.append(memory_id)
        if cleanup_failures:
            raise RuntimeError(
                "Notion smoke cleanup could not move these temporary pages to trash: "
                + ", ".join(cleanup_failures)
            )


def main() -> int:
    if os.environ.get("CAPRI_NOTION_LIVE_TESTS", "").lower() != "true":
        print("SKIP: set CAPRI_NOTION_LIVE_TESTS=true to enable live Notion smoke test")
        return 0
    try:
        transport = NotionRESTTransport.from_environment()
        run_smoke(NotionMemoryAdapter(transport))
    except Exception:
        print("FAIL: Notion REST smoke test failed; check sanitized transport errors and workspace sharing")
        return 1
    print("PASS: Notion REST create/read/correct/search/archive/trash round trip")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
