-- The function is invoked by the postgres-owned ensure_rls event trigger.
-- It is not a user-facing RPC and must not be callable through PostgREST.
REVOKE EXECUTE ON FUNCTION public.rls_auto_enable()
  FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.rls_auto_enable()
  TO postgres;
