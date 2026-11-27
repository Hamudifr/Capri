# Database migration mirror (audit copy)

Verbatim SQL of every migration applied to the Supabase project
(`znpvstwmzyphmvkhigqp`), exported from `supabase_migrations.schema_migrations`
on 2026-11-27 (14 migrations, `statements[1]` each). Every file was
md5-verified against `md5(statements[1])` read back from the platform at
export time (byte-faithful, not eyeballed).

## Why this path and not `supabase/migrations/`

- **Platform is authoritative.** Migrations are applied through the
  Supabase connector's `create_migration` (DDL never runs ad hoc); the
  `schema_migrations` rows are the source of truth for what is live.
- **The GitHub integration's behavior toward a CLI migrations directory is
  unobservable from the repo side.** Dropping files into `supabase/migrations/`
  would couple the live deploy path to an untested assumption. This mirror
  deliberately lives outside every watched deploy path; promoting it to
  `supabase/migrations/` is a separate, deliberate change that requires its
  own canary verification (integration run + `migrations_total` readback).

## Conventions

- Files: `<version>_<name>.sql` (Supabase CLI naming). Two migrations were
  created with spaces in their platform names — `add cron watchdog fields to
  capri_project_status` and `scope cron watchdog to capri_keepalive jobid` —
  so their filenames are sanitized to underscores (contents unchanged).
- Contents are an exact mirror, not an edited re-statement. Historical
  statements (e.g. the earlier `security invoker` RPC) are kept as written
  even though later migrations supersede them.

## Re-export query

```sql
SELECT version, name, statements[1] AS stmt
FROM supabase_migrations.schema_migrations
ORDER BY version;
```

Add new files here whenever a `create_migration` lands, in the same change
or an immediate follow-up.
