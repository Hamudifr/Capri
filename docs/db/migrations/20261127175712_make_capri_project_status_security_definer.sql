CREATE OR REPLACE FUNCTION public.capri_project_status()
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $function$
  select jsonb_build_object(
    'migrations_total', (select count(*) from supabase_migrations.schema_migrations),
    'latest_migration', (select max(version) from supabase_migrations.schema_migrations),
    'backup_registry_rows', (select count(*) from public.capri_backup_registry),
    'backup_payload_rows', (select count(*) from public.capri_backup_payloads),
    'backup_payload_bytes', (select coalesce(sum(size_bytes), 0) from public.capri_backup_registry),
    'public_tables', (select coalesce(jsonb_agg(jsonb_build_object('table', c.relname, 'rls', c.relrowsecurity) order by c.relname), '[]'::jsonb) from pg_class c join pg_namespace n on n.oid = c.relnamespace where n.nspname = 'public' and c.relkind = 'r'),
    'extensions', (select coalesce(jsonb_agg(e.extname || ' ' || e.extversion order by e.extname), '[]'::jsonb) from pg_extension e where e.extname <> 'plpgsql'),
    'database_bytes', pg_database_size(current_database()),
    'storage_bytes', (select coalesce(sum((metadata->>'size')::bigint), 0) from storage.objects),
    'auth_users', (select count(*) from auth.users),
    'dead_tuples', (select coalesce(sum(n_dead_tup), 0) from pg_stat_user_tables),
    'top_tables', (
      select coalesce(jsonb_agg(jsonb_build_object('table', t.relname, 'bytes', t.bytes, 'live', t.live, 'dead', t.dead) order by t.bytes desc), '[]'::jsonb)
      from (
        select c.relname,
               pg_total_relation_size(c.oid) as bytes,
               coalesce(s.n_live_tup, 0) as live,
               coalesce(s.n_dead_tup, 0) as dead
        from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        left join pg_stat_user_tables s on s.relid = c.oid
        where n.nspname = 'public' and c.relkind = 'r'
        order by bytes desc
        limit 5
      ) t
    ),
    'free_plan_limits', jsonb_build_object(
      'as_of', '2026-11',
      'database_bytes', 524288000,
      'storage_bytes', 1073741824,
      'egress_bytes_month', 10737418240,
      'mau', 50000,
      'edge_invocations_month', 500000,
      'pause_inactive_days', 7
    )
  )
$function$;

REVOKE ALL ON FUNCTION public.capri_project_status() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.capri_project_status() FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION public.capri_project_status() TO service_role;
