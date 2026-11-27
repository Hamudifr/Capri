create table if not exists public.capri_backup_payloads (
  registry_id uuid primary key references public.capri_backup_registry (id) on delete cascade,
  payload bytea not null
);
alter table public.capri_backup_payloads enable row level security;

create or replace function public.capri_push_backup(
  p_store text,
  p_backup_id text,
  p_sha256 text,
  p_size_bytes bigint,
  p_source_host text,
  p_validation jsonb,
  p_payload_hex text,
  p_notes text default null
)
returns uuid
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_id uuid;
  v_payload bytea;
begin
  if p_payload_hex is null or p_payload_hex = '' or p_payload_hex !~ '^[0-9a-fA-F]+$' or length(p_payload_hex) % 2 <> 0 then
    raise exception 'p_payload_hex must be non-empty, even-length hex';
  end if;
  v_payload := decode(p_payload_hex, 'hex');
  if octet_length(v_payload) <> p_size_bytes then
    raise exception 'p_size_bytes does not match payload length';
  end if;
  if octet_length(v_payload) > 10000000 then
    raise exception 'payload exceeds 10000000 byte cap';
  end if;
  insert into public.capri_backup_registry (store, backup_id, sha256, size_bytes, source_host, validation, notes)
  values (p_store, p_backup_id, p_sha256, p_size_bytes, p_source_host, p_validation, p_notes)
  returning id into v_id;
  insert into public.capri_backup_payloads (registry_id, payload) values (v_id, v_payload);
  return v_id;
end;
$$;

revoke execute on function public.capri_push_backup(text, text, text, bigint, text, jsonb, text, text) from public, anon, authenticated;
grant execute on function public.capri_push_backup(text, text, text, bigint, text, jsonb, text, text) to service_role;

create or replace function public.capri_prune_backups(p_store text, p_keep_last integer)
returns integer
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_deleted integer := 0;
begin
  if p_keep_last < 1 then
    raise exception 'p_keep_last must be >= 1';
  end if;
  with doomed as (
    select id
    from public.capri_backup_registry
    where store = p_store
    order by created_at desc, id desc
    offset p_keep_last
  )
  delete from public.capri_backup_registry r
  using doomed d
  where r.id = d.id;
  get diagnostics v_deleted = row_count;
  return v_deleted;
end;
$$;

revoke execute on function public.capri_prune_backups(text, integer) from public, anon, authenticated;
grant execute on function public.capri_prune_backups(text, integer) to service_role;
