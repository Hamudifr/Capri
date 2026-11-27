"""Offline tests for the off-site backup pusher (scripts/backup_offsite.py).

The HTTP transport is mocked; no test touches the network or needs
Supabase credentials.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "backup_offsite.py"

_SPEC = importlib.util.spec_from_file_location("backup_offsite", SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
backup_offsite = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(backup_offsite)


def _clean_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("SUPABASE_")
    }
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if extra:
        env.update(extra)
    return env


def _run_cli(args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        env=env if env is not None else _clean_env(),
        timeout=120,
        check=False,
    )


class LocalSnapshotTests(unittest.TestCase):
    def test_dry_run_creates_snapshot_and_manifest(self) -> None:
        from capri_runtime import SQLiteMemoryStore

        with tempfile.TemporaryDirectory() as work:
            source = os.path.join(work, "memory.sqlite3")
            dest = os.path.join(work, "backups")
            os.mkdir(dest, 0o700)
            SQLiteMemoryStore(source)
            result = _run_cli(
                ["--store", "memory", "--db", source, "--dest", dest]
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(result.stdout)
            self.assertEqual(manifest["store"], "memory")
            self.assertFalse(manifest["uploaded"])
            self.assertIsNone(manifest["registry_id"])
            backup_path = manifest["backup_path"]
            self.assertTrue(os.path.isfile(backup_path))
            with open(backup_path, "rb") as handle:
                payload = handle.read()
            self.assertEqual(len(payload), manifest["size_bytes"])
            self.assertEqual(
                hashlib.sha256(payload).hexdigest(), manifest["sha256"]
            )
            self.assertEqual(
                manifest["validation"]["local_integrity_check"], "ok"
            )
            connection = sqlite3.connect(backup_path)
            try:
                row = connection.execute("PRAGMA integrity_check").fetchone()
            finally:
                connection.close()
            self.assertEqual(row[0], "ok")

    def test_unknown_store_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as work:
            result = _run_cli(
                [
                    "--store",
                    "widgets",
                    "--db",
                    os.path.join(work, "x.sqlite3"),
                    "--dest",
                    work,
                ]
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid choice", result.stderr)

    def test_missing_source_database_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as work:
            dest = os.path.join(work, "backups")
            os.mkdir(dest, 0o700)
            result = _run_cli(
                [
                    "--store",
                    "memory",
                    "--db",
                    os.path.join(work, "absent.sqlite3"),
                    "--dest",
                    dest,
                ]
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("source database not found", result.stderr)

    def test_upload_without_credentials_fails_before_any_work(self) -> None:
        with tempfile.TemporaryDirectory() as work:
            dest = os.path.join(work, "backups")
            os.mkdir(dest, 0o700)
            result = _run_cli(
                [
                    "--store",
                    "memory",
                    "--db",
                    os.path.join(work, "absent.sqlite3"),
                    "--dest",
                    dest,
                    "--upload",
                ]
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("SUPABASE_URL", result.stderr)
        self.assertIn("SUPABASE_SERVICE_ROLE_KEY", result.stderr)

    def test_prune_keep_requires_upload(self) -> None:
        with tempfile.TemporaryDirectory() as work:
            dest = os.path.join(work, "backups")
            os.mkdir(dest, 0o700)
            result = _run_cli(
                [
                    "--store",
                    "memory",
                    "--db",
                    os.path.join(work, "absent.sqlite3"),
                    "--dest",
                    dest,
                    "--prune-keep",
                    "3",
                ]
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--prune-keep requires --upload", result.stderr)


class RequestBuilderTests(unittest.TestCase):
    def test_push_request_shape(self) -> None:
        payload = b"sqlite-bytes"
        url, headers, body = backup_offsite.build_push_request(
            base_url="https://example.supabase.co/",
            api_key="secret-key",
            store="memory",
            backup_id="memory_1.sqlite3",
            sha256="ab" * 32,
            size_bytes=len(payload),
            source_host="host1",
            validation={"method": "test"},
            notes="nightly",
            payload_bytes=payload,
        )
        self.assertEqual(
            url, "https://example.supabase.co/rest/v1/rpc/capri_push_backup"
        )
        self.assertEqual(headers["apikey"], "secret-key")
        self.assertEqual(headers["Authorization"], "Bearer secret-key")
        self.assertEqual(body["p_store"], "memory")
        self.assertEqual(body["p_size_bytes"], len(payload))
        self.assertEqual(body["p_payload_hex"], payload.hex())
        self.assertEqual(body["p_notes"], "nightly")

    def test_push_request_omits_null_notes(self) -> None:
        _, _, body = backup_offsite.build_push_request(
            base_url="https://example.supabase.co",
            api_key="k",
            store="tasks",
            backup_id="b",
            sha256="0" * 64,
            size_bytes=1,
            source_host="h",
            validation={},
            notes=None,
            payload_bytes=b"x",
        )
        self.assertNotIn("p_notes", body)

    def test_prune_request_rejects_keep_last_below_one(self) -> None:
        with self.assertRaises(backup_offsite.BackupOffsiteError):
            backup_offsite.build_prune_request(
                base_url="https://example.supabase.co",
                api_key="k",
                store="memory",
                keep_last=0,
            )

    def test_size_cap(self) -> None:
        with self.assertRaises(backup_offsite.BackupOffsiteError):
            backup_offsite.enforce_size_cap(0)
        with self.assertRaises(backup_offsite.BackupOffsiteError):
            backup_offsite.enforce_size_cap(backup_offsite.MAX_PAYLOAD_BYTES + 1)
        backup_offsite.enforce_size_cap(backup_offsite.MAX_PAYLOAD_BYTES)


class UploadTests(unittest.TestCase):
    def test_upload_success_with_mocked_transport(self) -> None:
        captured: dict[str, object] = {}

        def fake_post(url: str, headers: dict[str, str], body: dict[str, object]):
            captured.update(url=url, headers=headers, body=body)
            return {"id": "3f0e1a2b-0000-4000-8000-000000000001"}

        registry_id = backup_offsite.upload_backup(
            base_url="https://example.supabase.co",
            api_key="secret",
            store="security",
            backup_id="security_1.sqlite3",
            sha256="cd" * 32,
            size_bytes=4,
            source_host="host1",
            validation={"method": "test"},
            notes=None,
            payload_bytes=b"data",
            post=fake_post,
        )
        self.assertEqual(registry_id, "3f0e1a2b-0000-4000-8000-000000000001")
        self.assertIn("capri_push_backup", str(captured["url"]))
        body = captured["body"]
        assert isinstance(body, dict)
        self.assertEqual(body["p_payload_hex"], b"data".hex())

    def test_upload_rejects_size_mismatch(self) -> None:
        with self.assertRaises(backup_offsite.BackupOffsiteError):
            backup_offsite.upload_backup(
                base_url="https://example.supabase.co",
                api_key="secret",
                store="memory",
                backup_id="b",
                sha256="0" * 64,
                size_bytes=99,
                source_host="h",
                validation={},
                notes=None,
                payload_bytes=b"short",
                post=lambda *args: {},
            )

    def test_upload_rejects_unexpected_response(self) -> None:
        with self.assertRaises(backup_offsite.BackupOffsiteError):
            backup_offsite.upload_backup(
                base_url="https://example.supabase.co",
                api_key="secret",
                store="memory",
                backup_id="b",
                sha256="0" * 64,
                size_bytes=1,
                source_host="h",
                validation={},
                notes=None,
                payload_bytes=b"x",
                post=lambda *args: {"error": "nope"},
            )

    def test_prune_with_mocked_transport(self) -> None:
        seen: dict[str, object] = {}

        def fake_post(url: str, headers: dict[str, str], body: dict[str, object]):
            seen.update(url=url, body=body)
            return 3

        deleted = backup_offsite.prune_backups(
            base_url="https://example.supabase.co",
            api_key="secret",
            store="memory",
            keep_last=7,
            post=fake_post,
        )
        self.assertEqual(deleted, 3)
        self.assertIn("capri_prune_backups", str(seen["url"]))
        assert isinstance(seen["body"], dict)
        self.assertEqual(seen["body"]["p_keep_last"], 7)

    def test_load_upload_config_missing_env(self) -> None:
        saved = {
            name: os.environ.pop(name, None)
            for name in (backup_offsite.URL_ENV, backup_offsite.KEY_ENV)
        }
        try:
            with self.assertRaises(backup_offsite.BackupOffsiteError):
                backup_offsite.load_upload_config()
        finally:
            for name, value in saved.items():
                if value is not None:
                    os.environ[name] = value


if __name__ == "__main__":
    unittest.main()
