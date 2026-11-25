# SQLite session backup

## Scope

`SQLiteSessionStore.backup_to(destination_path)` creates a consistent standalone snapshot of the session database using SQLite's online backup API. It captures committed WAL content and includes session transcripts, durable turn leases, principal ownership records, and immutable-owner triggers.

It does not back up the separate task or memory databases. It does not encrypt the snapshot, schedule backups, copy to off-site storage, or provide a retention policy.

## Creating a backup

The destination directory must already exist, be owned by the current user, and be private (0700 or stricter on POSIX). The destination must not exist and must not be a symlink.

```python
from capri_runtime import SQLiteSessionStore

sessions = SQLiteSessionStore(
    "/private/capri/sessions.sqlite3",
    max_output_chars=131072,
)
backup_path = sessions.backup_to(
    "/private/capri/backups/sessions-2026-11-07.sqlite3"
)
assert sessions.integrity_check() == "ok"
```

The backup is published without overwriting a destination created in a race. The temporary file is created privately, the completed database is fsynced, and the parent directory is fsynced after publication.

Before publishing, the implementation checks:
- SQLite `integrity_check` and `foreign_key_check`.
- Every stored session transcript against the configured session limits.
- Every principal-owner identifier and creation timestamp.
- Every durable turn lease's session reference, bounded owner token, and timezone-aware expiry. Expired leases are preserved as stale state; they are not treated as corruption.
- File type, ownership, link count, and POSIX file mode.

## Restoring

The backup is a standalone SQLite database. A controlled restore can point a new `SQLiteSessionStore` instance at the backup file after stopping the host and verifying the backup:

```python
restored_sessions = SQLiteSessionStore(
    "/private/capri/backups/sessions-2026-11-07.sqlite3",
    max_output_chars=131072,
)
assert restored_sessions.integrity_check() == "ok"
```

Use the same configured transcript limits as the source store. Do not replace a live database while the host is running. Keep the original database until the restored store has been verified. This is a manual restore procedure, not an automated rollback workflow.

## Security and limitations

- Session messages and provider continuation items are plaintext inside SQLite. Backups are also plaintext.
- The destination directory and backup storage must be protected by the host. Use encrypted storage or an encrypted volume if backups leave the protected host.
- No live project database was copied during development; tests use isolated temporary databases.
- The task store and SQLite memory store do not yet expose the same backup method.
- No scheduled backup, retention, off-site replication, encryption, or disaster-recovery exercise is implemented.
