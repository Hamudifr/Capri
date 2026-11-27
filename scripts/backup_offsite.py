#!/usr/bin/env python3
"""Create a local Capri store snapshot and optionally push it off-site.

Off-site destination: the Supabase project's capri_backup_registry (see
docs/SQLITE_STORE_BACKUP.md). Without --upload this script only creates the
local snapshot and prints a JSON manifest; it never touches the network.
Uploads require SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY from the
environment; credentials are never read from or written to the repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Sequence

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from capri_runtime import (  # noqa: E402  (path bootstrap first)
    SQLiteMemoryStore,
    SQLiteSecurityStore,
    SQLiteSessionStore,
    SQLiteTaskStore,
)

STORE_CLASSES = {
    "memory": SQLiteMemoryStore,
    "security": SQLiteSecurityStore,
    "sessions": SQLiteSessionStore,
    "tasks": SQLiteTaskStore,
}
MAX_PAYLOAD_BYTES = 10_000_000
URL_ENV = "SUPABASE_URL"
KEY_ENV = "SUPABASE_SERVICE_ROLE_KEY"


class BackupOffsiteError(Exception):
    """Configuration or precondition failure with a user-facing message."""


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def enforce_size_cap(size_bytes: int) -> None:
    if size_bytes <= 0:
        raise BackupOffsiteError("backup payload must be non-empty")
    if size_bytes > MAX_PAYLOAD_BYTES:
        raise BackupOffsiteError(
            f"backup payload {size_bytes} bytes exceeds the "
            f"{MAX_PAYLOAD_BYTES} byte off-site cap"
        )


def build_push_request(
    *,
    base_url: str,
    api_key: str,
    store: str,
    backup_id: str,
    sha256: str,
    size_bytes: int,
    source_host: str,
    validation: dict[str, Any],
    notes: str | None,
    payload_bytes: bytes,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    body: dict[str, Any] = {
        "p_store": store,
        "p_backup_id": backup_id,
        "p_sha256": sha256,
        "p_size_bytes": size_bytes,
        "p_source_host": source_host,
        "p_validation": validation,
        "p_payload_hex": payload_bytes.hex(),
    }
    if notes is not None:
        body["p_notes"] = notes
    headers = {
        "apikey": api_key,
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url = base_url.rstrip("/") + "/rest/v1/rpc/capri_push_backup"
    return url, headers, body


def build_prune_request(
    *, base_url: str, api_key: str, store: str, keep_last: int
) -> tuple[str, dict[str, str], dict[str, Any]]:
    if keep_last < 1:
        raise BackupOffsiteError("--prune-keep must be >= 1")
    headers = {
        "apikey": api_key,
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url = base_url.rstrip("/") + "/rest/v1/rpc/capri_prune_backups"
    return url, headers, {"p_store": store, "p_keep_last": keep_last}


def post_json(
    url: str, headers: dict[str, str], body: dict[str, Any]
) -> Any:
    request = urllib.request.Request(  # noqa: S310 - URL comes from env, TLS only
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise BackupOffsiteError(
            f"off-site request failed with HTTP {exc.code}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise BackupOffsiteError(f"off-site request failed: {exc.reason}") from exc
    return json.loads(raw) if raw else None


def upload_backup(
    *,
    base_url: str,
    api_key: str,
    store: str,
    backup_id: str,
    sha256: str,
    size_bytes: int,
    source_host: str,
    validation: dict[str, Any],
    notes: str | None,
    payload_bytes: bytes,
    post: Callable[..., Any] = post_json,
) -> str:
    enforce_size_cap(size_bytes)
    if len(payload_bytes) != size_bytes:
        raise BackupOffsiteError("payload byte length does not match size_bytes")
    url, headers, body = build_push_request(
        base_url=base_url,
        api_key=api_key,
        store=store,
        backup_id=backup_id,
        sha256=sha256,
        size_bytes=size_bytes,
        source_host=source_host,
        validation=validation,
        notes=notes,
        payload_bytes=payload_bytes,
    )
    response = post(url, headers, body)
    registry_id = response.get("id") if isinstance(response, dict) else None
    if not isinstance(registry_id, str) or not registry_id:
        raise BackupOffsiteError(f"unexpected push response: {response!r}")
    return registry_id


def prune_backups(
    *,
    base_url: str,
    api_key: str,
    store: str,
    keep_last: int,
    post: Callable[..., Any] = post_json,
) -> int:
    url, headers, body = build_prune_request(
        base_url=base_url, api_key=api_key, store=store, keep_last=keep_last
    )
    response = post(url, headers, body)
    try:
        return int(response)
    except (TypeError, ValueError) as exc:
        raise BackupOffsiteError(
            f"unexpected prune response: {response!r}"
        ) from exc


def local_snapshot(store: str, source_db: str, dest_dir: str) -> str:
    if store not in STORE_CLASSES:
        raise BackupOffsiteError(
            f"unknown store {store!r}; expected one of {sorted(STORE_CLASSES)}"
        )
    if not os.path.isfile(source_db):
        raise BackupOffsiteError(f"source database not found: {source_db}")
    if not os.path.isdir(dest_dir):
        raise BackupOffsiteError(f"destination directory not found: {dest_dir}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_id = f"{store}_{stamp}_{os.getpid()}.sqlite3"
    destination = os.path.join(os.path.abspath(dest_dir), backup_id)
    store_instance = STORE_CLASSES[store](os.path.abspath(source_db))
    return store_instance.backup_to(destination)


def load_upload_config() -> tuple[str, str]:
    base_url = os.environ.get(URL_ENV, "").strip()
    api_key = os.environ.get(KEY_ENV, "").strip()
    missing = [
        name
        for name, value in ((URL_ENV, base_url), (KEY_ENV, api_key))
        if not value
    ]
    if missing:
        raise BackupOffsiteError(
            "missing required environment variable(s): " + ", ".join(missing)
        )
    return base_url, api_key


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Snapshot a Capri SQLite store and optionally push it to the "
            "Supabase off-site backup registry."
        )
    )
    parser.add_argument(
        "--store",
        required=True,
        choices=sorted(STORE_CLASSES),
        help="which Capri store the source database belongs to",
    )
    parser.add_argument(
        "--db", required=True, help="path to the live SQLite database file"
    )
    parser.add_argument(
        "--dest",
        required=True,
        help="existing private directory for the local snapshot",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="push the snapshot to the Supabase off-site registry",
    )
    parser.add_argument(
        "--prune-keep",
        type=int,
        default=None,
        metavar="N",
        help=(
            "after a successful upload, delete all but the newest N backups "
            "for this store (requires --upload; N >= 1)"
        ),
    )
    parser.add_argument(
        "--notes",
        default=None,
        help="optional free-form note stored with the off-site manifest row",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.prune_keep is not None and not args.upload:
            raise BackupOffsiteError("--prune-keep requires --upload")
        base_url = api_key = ""
        if args.upload:
            base_url, api_key = load_upload_config()
        backup_path = local_snapshot(args.store, args.db, args.dest)
        with open(backup_path, "rb") as handle:
            payload = handle.read()
        size_bytes = len(payload)
        enforce_size_cap(size_bytes)
        digest = hashlib.sha256(payload).hexdigest()
        backup_id = os.path.basename(backup_path)
        validation = {
            "method": "store.backup_to pre-publish validation",
            "store_class": STORE_CLASSES[args.store].__name__,
            "local_integrity_check": None,
        }
        import sqlite3

        with sqlite3.connect(backup_path) as connection:
            row = connection.execute("PRAGMA integrity_check").fetchone()
        validation["local_integrity_check"] = (
            row[0] if row is not None else None
        )
        if validation["local_integrity_check"] != "ok":
            raise BackupOffsiteError(
                f"local integrity check failed: "
                f"{validation['local_integrity_check']!r}"
            )
        manifest: dict[str, Any] = {
            "store": args.store,
            "backup_id": backup_id,
            "backup_path": backup_path,
            "sha256": digest,
            "size_bytes": size_bytes,
            "source_host": socket.gethostname(),
            "validation": validation,
            "uploaded": False,
            "registry_id": None,
            "pruned": None,
        }
        if args.upload:
            registry_id = upload_backup(
                base_url=base_url,
                api_key=api_key,
                store=args.store,
                backup_id=backup_id,
                sha256=digest,
                size_bytes=size_bytes,
                source_host=manifest["source_host"],
                validation=validation,
                notes=args.notes,
                payload_bytes=payload,
            )
            manifest["uploaded"] = True
            manifest["registry_id"] = registry_id
            manifest["supabase_url"] = base_url
            if args.prune_keep is not None:
                manifest["pruned"] = prune_backups(
                    base_url=base_url,
                    api_key=api_key,
                    store=args.store,
                    keep_last=args.prune_keep,
                )
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 0
    except BackupOffsiteError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
