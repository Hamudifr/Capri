# Local SQLite store backup and recovery

## Coverage

The local Capri SQLite stores expose consistent backup operations:

| Store | Method | Snapshot validation |
|---|---|---|
| Sessions and transcripts | `SQLiteSessionStore.backup_to()` | SQLite integrity, foreign keys, every transcript, principal ownership, and durable turn leases |
| Security and audit state | `SQLiteSecurityStore.backup_to()` | SQLite integrity and store-specific validation |
| Tasks and execution history | `SQLiteTaskStore.backup_to()` | SQLite integrity, foreign keys, task plans, results, progress, events and timestamps |
| Local memory | `SQLiteMemoryStore.backup_to()` | SQLite integrity, foreign keys, record metadata, retention, timestamps, tags and events |

The task and memory stores use the shared `capri_runtime.sqlite_backup` primitive. The session and security stores retain their existing store-specific implementations.

## Backup procedure

Each store's `backup_to(destination_path)` method:
- Uses SQLite's online backup API, so committed WAL content is captured consistently.
- Requires an existing destination directory owned by the current user and private (0700 or stricter on POSIX).
- Refuses to overwrite existing files and rejects symlink destinations.
- Creates a temporary file privately, validates the completed snapshot, publishes without overwrite, and fsyncs the file and parent directory.
- Returns the absolute backup path.

Example:

```python
from capri_runtime import (
    SQLiteMemoryStore,
    SQLiteSecurityStore,
    SQLiteSessionStore,
    SQLiteTaskStore,
)

sessions = SQLiteSessionStore(
    "/private/capri/sessions.sqlite3",
    max_output_chars=131072,
)
tasks = SQLiteTaskStore("/private/capri/tasks.sqlite3")
memory = SQLiteMemoryStore("/private/capri/memory.sqlite3")
security = SQLiteSecurityStore("/private/capri/security.sqlite3")

sessions.backup_to("/private/capri/backups/sessions.sqlite3")
tasks.backup_to("/private/capri/backups/tasks.sqlite3")
memory.backup_to("/private/capri/backups/memory.sqlite3")
security.backup_to("/private/capri/backups/security.sqlite3")
```

Use distinct destination names. Each method refuses to overwrite a prior backup.

## Restore procedure

These backup files are standalone SQLite databases. A controlled restore is manual:

1. Stop the host and all worker processes that may access the stores.
2. Preserve the original database files; do not overwrite or delete them.
3. Point a new store instance at the selected backup file, using the same store configuration and transcript limits as the source.
4. Run the store's `integrity_check()` method.
5. Verify application-level records, principal ownership, audit state, and task state before resuming the host.
6. Record the restore time and source backup identifier in the operational ledger.

For session stores, see [SQLITE_SESSION_BACKUP.md](SQLITE_SESSION_BACKUP.md) for transcript-limit and ownership-specific details.

## Off-site replication (Supabase)

The Supabase project (`znpvstwmzyphmvkhigqp`) hosts the off-site backup
registry created by migration `create_capri_backup_push_and_prune`:

| Object | Purpose |
|---|---|
| `public.capri_backup_registry` | One row per backup: store, backup id, sha256, size, source host, validation metadata, notes. RLS enabled with zero policies (service-role only). |
| `public.capri_backup_payloads` | The backup bytes (`bytea`), keyed 1:1 to the registry row and cascade-deleted with it. Same RLS posture. |
| `capri_push_backup(...)` RPC | Atomically inserts the registry row and payload. Parameters use hex text (no bytea-over-JSON ambiguity), verify payload length against `p_size_bytes`, and enforce a 10 MB cap. Granted to `service_role` only; revoked from `public`, `anon`, and `authenticated`. |
| `capri_prune_backups(store, keep_last)` RPC | Deletes all but the newest `keep_last` backups for a store; rejects `keep_last < 1`. Granted to `service_role` only. |

Procedure (`scripts/backup_offsite.py`):

```bash
export SUPABASE_URL=https://<ref>.supabase.co
export SUPABASE_SERVICE_ROLE_KEY=<service-role key>   # never committed
python3 scripts/backup_offsite.py \
  --store memory --db /private/capri/memory.sqlite3 \
  --dest /private/capri/backups \
  --upload --prune-keep 7
```

Without `--upload` the script only creates the local snapshot, verifies
`PRAGMA integrity_check` on it, and prints a JSON manifest; it never touches
the network. `--prune-keep` requires `--upload` and must be set explicitly
per run; cadence and default retention counts remain host policy.

Encryption stance (v1): payloads leave the host over TLS and are encrypted at
rest by Supabase (provider-managed disk encryption). Client-side pre-upload
encryption is deliberately deferred until a key-management decision is made
(see gaps below).

Verification status: schema and both RPCs are verified live against the
project (push, readback, prune, and the `keep_last >= 1` guard exercised;
test rows deleted afterwards). The HTTP path of the script is unit-tested
offline with a mocked transport because CI and the agent sandbox have no
network access to Supabase and no service-role credentials.

## Security and operational gaps

- All current backup files are plaintext SQLite. Protect the destination directory, filesystem, and backup transport. Use encrypted volumes or an approved encryption layer when backups leave the protected host.
- No backup scheduler, encryption key management, or automated restore workflow is included. Off-site replication primitives now exist (Supabase registry plus `scripts/backup_offsite.py`); pushing and pruning still require explicit operator action, and retention counts are not yet codified as policy.
- No disaster-recovery exercise or restore-time objective has been verified.
- No live user database was copied during implementation; CI tests use isolated temporary databases.

A backup method is not a backup policy. The embedding host must still define cadence, retention, encryption, monitoring, and restore drills before production use.
