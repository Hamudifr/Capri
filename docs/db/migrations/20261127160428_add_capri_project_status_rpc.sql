create or replace function public.capri_project_status()
returns jsonb
language sql
stable
security invoker
as $$
  select jsonb_build_object(
    'migrations_total', (select count(*) from supabase_migrations.schema_migrations),
    'latest_migration', (select max(version) from supabase_migrations.schema_migrations),
    'backup_registry_rows', (select count(*) from public.capri_backup_registry),
    'backup_payload_rows', (select count(*) from public.capri_backup_payloads),
    'public_tables', (select coalesce(jsonb_agg(jsonb_build_object('table', c.relname, 'rls', c.relrowsecurity) order by c.relname), '[]'::jsonb) from pg_class c join pg_namespace n on n.oid = c.relnamespace where n.nspname = 'public' and c.relkind = 'r'),
    'extensions', (select coalesce(jsonb_agg(e.extname || ' ' || e.extversion order by e.extname), '[]'::jsonb) from pg_extension e where e.extname <> 'plpgsql')
  )
$$;
