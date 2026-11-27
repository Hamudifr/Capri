SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '10s';
REVOKE TRUNCATE, TRIGGER, REFERENCES ON TABLE public.capri_backup_payloads, public.capri_backup_registry FROM anon, authenticated;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM (VALUES ('anon'), ('authenticated')) AS roles(name)
    CROSS JOIN (VALUES ('public.capri_backup_payloads'), ('public.capri_backup_registry')) AS tables(name)
    CROSS JOIN (VALUES ('TRUNCATE'), ('TRIGGER'), ('REFERENCES')) AS privileges(name)
    WHERE has_table_privilege(roles.name, tables.name, privileges.name)
  ) THEN
    RAISE EXCEPTION 'Unsafe privilege remains; roll back migration';
  END IF;
  IF EXISTS (
    SELECT 1
    FROM (VALUES ('public.capri_backup_payloads'), ('public.capri_backup_registry')) AS tables(name)
    CROSS JOIN (VALUES ('SELECT'), ('INSERT'), ('UPDATE'), ('DELETE'), ('TRUNCATE'), ('TRIGGER'), ('REFERENCES')) AS privileges(name)
    WHERE NOT has_table_privilege('service_role', tables.name, privileges.name)
  ) THEN
    RAISE EXCEPTION 'Service role lost baseline table privilege; roll back migration';
  END IF;
END $$;
