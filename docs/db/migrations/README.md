# Database migration mirror (audit copy)

Verbatim SQL of every migration applied to the Supabase project
(`znpvstwmzyphmvkhigqp`), exported from `supabase_migrations.schema_migrations`
on 2026-11-27 (9 migrations, `statements[1]` each, byte-faithful).

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

- Files: `<version>_<name>.sql` (Supabase CLI naming). The migration
  `add cron watchdog fields to capri_project_status` had spaces in its
  platform name; its filename is sanitized to underscores.
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
