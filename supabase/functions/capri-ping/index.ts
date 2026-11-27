// Capri liveness probe - keyless (verify_jwt false, see supabase/config.toml).
// Mirrors the deployed capri-ping function; see docs/FREE_PLAN_OPTIMIZATION.md.
Deno.serve((req) => {
  return new Response(
    JSON.stringify({
      ok: true,
      service: "capri",
      purpose: "liveness probe for the Capri Supabase project",
      time: new Date().toISOString(),
    }),
    {
      headers: { "content-type": "application/json" },
      status: 200,
    },
  );
});
