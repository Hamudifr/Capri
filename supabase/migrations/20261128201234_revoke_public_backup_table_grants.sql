-- Backup registry and payload access is server-side only.
-- The backup client uses service_role; public and authenticated clients
-- have no application use for these tables.
REVOKE ALL PRIVILEGES ON TABLE
  public.capri_backup_registry,
  public.capri_backup_payloads
FROM anon, authenticated;
