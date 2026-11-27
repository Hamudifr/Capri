CREATE EXTENSION IF NOT EXISTS pg_cron;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'capri_keepalive') THEN
    PERFORM cron.schedule(
      'capri_keepalive',
      '43 3 * * *',
      $job$SELECT count(*) FROM public.capri_backup_registry$job$
    );
  END IF;
END $$;
