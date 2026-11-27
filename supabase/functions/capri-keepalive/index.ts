// Capri free-plan keep-alive + budget watchdog - keyless (verify_jwt
// false, see supabase/config.toml). Calls capri_project_status() through
// PostgREST so every invocation registers real database activity, and
// reports whether database+storage stay under 80% of the Supabase free
// caps. Numeric sizes stay server-side; the public response exposes
// booleans only. Mirrors the deployed capri-keepalive function; see
// docs/FREE_PLAN_OPTIMIZATION.md.
Deno.serve(async () => {
  const url = Deno.env.get("SUPABASE_URL");
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    });
  const fail = (extra: Record<string, unknown>, status: number) =>
    json({ ok: false, under_limit: false, ...extra, time: new Date().toISOString() }, status);
  if (!url || !key) {
    return fail({ error: "platform env missing" }, 500);
  }
  try {
    const res = await fetch(`${url}/rest/v1/rpc/capri_project_status`, {
      method: "POST",
      headers: {
        apikey: key,
        authorization: `Bearer ${key}`,
        "content-type": "application/json",
      },
      body: "{}",
    });
    if (!res.ok) {
      return fail({ rpc_status: res.status }, 502);
    }
    const status = (await res.json()) as {
      database_bytes?: number;
      storage_bytes?: number;
      free_plan_limits?: { database_bytes?: number; storage_bytes?: number };
      cron_active?: boolean;
      cron_stale?: boolean;
    };
    const limits = status.free_plan_limits ?? {};
    const db = Number(status.database_bytes ?? 0);
    const storage = Number(status.storage_bytes ?? 0);
    const dbLimit = Number(limits.database_bytes ?? 524288000);
    const storageLimit = Number(limits.storage_bytes ?? 1073741824);
    const underLimit = db < dbLimit * 0.8 && storage < storageLimit * 0.8;
    return json({
      ok: true,
      under_limit: underLimit,
      // pg_cron layer-1 watchdog: job armed, and not stale (a stale
      // signal only appears >26h after the last recorded fire, so the
      // first scheduled run after arming still passes).
      cron_active: status.cron_active === true,
      cron_stale: status.cron_stale === true,
      time: new Date().toISOString(),
    });
  } catch (error) {
    return fail({ error: String(error) }, 500);
  }
});
