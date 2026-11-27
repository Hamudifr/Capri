create table if not exists public.capri_backup_registry (
  id uuid primary key default gen_random_uuid(),
  store text not null check (store in ('sessions','security','tasks','memory')),
  backup_id text not null,
  sha256 text,
  size_bytes bigint check (size_bytes is null or size_bytes >= 0),
  created_at timestamptz not null default now(),
  source_host text,
  validation jsonb,
  notes text,
  unique (store, backup_id)
);
create index if not exists capri_backup_registry_store_created_idx on public.capri_backup_registry (store, created_at desc);
alter table public.capri_backup_registry enable row level security;
