-- Fail rather than overwrite an unreviewed concurrent function change.
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '10s';
DO $guard$
BEGIN
  IF (SELECT md5(prosrc) FROM pg_proc WHERE oid =
      'public.capri_push_backup(text,text,text,bigint,text,jsonb,text,text)'::regprocedure)
      IS DISTINCT FROM 'db101042213f71434812ddd959ef7de5' THEN
    RAISE EXCEPTION 'capri_push_backup preimage changed; review before migration';
  END IF;
END $guard$;

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
  -- Bound decoded allocation before materializing the bytea.
  if length(p_payload_hex) > 20000000 then
    raise exception 'payload exceeds 10000000 byte cap';
  end if;
  if p_size_bytes is null then
    raise exception 'p_size_bytes must not be null';
  end if;
  if p_sha256 is null or p_sha256 !~ '^[0-9a-f]{64}$' then
    raise exception 'p_sha256 must be 64 lowercase hex characters';
  end if;
  v_payload := decode(p_payload_hex, 'hex');
  if octet_length(v_payload) <> p_size_bytes then
    raise exception 'p_size_bytes does not match payload length';
  end if;
  if octet_length(v_payload) > 10000000 then
    raise exception 'payload exceeds 10000000 byte cap';
  end if;
  -- Built-in pg_catalog SHA-256: no extension or caller search_path dependency.
  if pg_catalog.encode(pg_catalog.sha256(v_payload), 'hex') <> p_sha256 then
    raise exception 'p_sha256 does not match payload digest';
  end if;
  insert into public.capri_backup_registry (store, backup_id, sha256, size_bytes, source_host, validation, notes)
  values (p_store, p_backup_id, p_sha256, p_size_bytes, p_source_host, p_validation, p_notes)
  returning id into v_id;
  insert into public.capri_backup_payloads (registry_id, payload) values (v_id, v_payload);
  return v_id;
end;
$$;

