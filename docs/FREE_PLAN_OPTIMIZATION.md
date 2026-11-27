# Free-plan optimization: Vercel Hobby + Supabase Free

Goal: run Capri's two managed platforms on their free plans indefinitely,
with measured headroom, automated keep-alive, and loud failure alerting.
Limits below were verified against public pricing/limits pages in
November 2026; usage figures were measured live on 2026-11-27.

## Plan limits (as of 2026-11)

| Resource | Vercel Hobby | Supabase Free |
| --- | --- | --- |
| Price / term | $0 forever (non-commercial only) | $0 forever (commercial allowed) |
| Bandwidth | 100 GB Fast Data Transfer / month | 10 GB (5 GB egress + 5 GB cached) |
| Compute | 1M function invocations, 4 CPU-h, 360 GB-h | 500 MB shared RAM |
| Storage | 1 GB Blob | 500 MB database + 1 GB files |
| Work | 100 deploys/day, 45-min max build, 1 concurrent build | 2 active projects, 50k MAU, 500k edge invocations |
| Scheduling | 100 cron jobs (1 invocation/day each) | edge functions + pg_cron |
| Failure mode | feature paused until 30 days pass (no bill) | database rejected / uploads blocked |
| Extra risk | none (no pause) | **project paused after 7 days of inactivity** (restore kept ≤ 1 year) |

## Measured usage (2026-11-27)

| Metric | Value | Budget | Headroom |
| --- | --- | --- | --- |
| Supabase database | 11.7 MB | 500 MB | 97.7% |
| Supabase storage objects | 0 | 1 GB | 100% |
| Supabase auth users (MAU) | 0 | 50,000 | 100% |
| Supabase backup rows / bytes | 0 / 0 B | see sizing below | — |
| Supabase services | 8/8 ACTIVE_HEALTHY | — | — |
| Vercel status page | ~600 B response, <1 s build | 100 GB / 45 min | ~100% |
| GitHub Actions (this repo is public) | 1 scheduled run/day, seconds each | unlimited on public repos | 100% |

One call shows all of it plus the embedded plan limits:

```sql
select public.capri_project_status();
```

Fields: `database_bytes`, `storage_bytes`, `auth_users`, `dead_tuples`,
`top_tables`, `backup_payload_bytes`, `free_plan_limits` (snapshot with
`as_of` date), plus the original migration/RLS/extension checks.

## Keep-alive architecture (anti-pause)

Supabase Free pauses a project after 7 days without activity. Three
independent layers prevent that and alert when anything breaks:

1. **Internal**: `pg_cron` job `capri_keepalive` (installed via
   migration `install_pg_cron_keepalive`) runs
   `SELECT count(*) FROM public.capri_backup_registry` daily at 03:43 UTC
   — a real query inside Postgres. Since #299 this layer is also
   **asserted, not hoped for**: `capri_project_status()` exposes
   `cron_active` / `cron_schedule` / `cron_last_run` / `cron_stale`
   (stale = armed but the last fire is >26h old; NULL-safe so a freshly
   armed job passes), the edge function forwards the two booleans, and
   keep-alive step 4 fails red if the job is unarmed or stale — a dead
   scheduler can no longer hide behind a green workflow.
2. **External**: `.github/workflows/keep-alive.yml` runs daily at
   04:17 UTC (plus on every push to `main` and on manual dispatch):
   - `GET /functions/v1/capri-keepalive` — keyless edge function that
     performs a live `capri_project_status()` query through PostgREST,
     so each run registers database activity;
   - `GET /functions/v1/capri-ping` — pure liveness probe;
   - `GET https://capri-orcin.vercel.app/` — asserts the production
     status page renders `Deployed commit` (guards against redirect or
     protection regressions; the `*-git-main-*` and unique `*-capri-9b07`
     aliases are behind Vercel Deployment Protection and must not be
     used for monitoring);
   - a second `GET capri-keepalive` as the **pg_cron watchdog**:
     requires `cron_active:true` and `cron_stale:false` in addition to
     the budget booleans.
3. **Alerting**: any failed endpoint fails the workflow, which emails
   the repository actors. A paused Supabase project therefore surfaces
   within a day instead of silently.

Design notes:

- `capri-keepalive` is `verify_jwt: false` and returns only
  `{ok, under_limit, cron_active, cron_stale, time}` — booleans only,
  no secrets, no numeric telemetry. Budget metrics are validated
  **fail-closed** (#301): if the RPC omits or nulls any number, the
  function answers `502 {ok:false, under_limit:false}` instead of
  coercing absent data into a healthy verdict (`Number(null) is 0`
  was exactly the false-green this replaced).
- Probe responses are validated by `scripts/check_probe.py` (strict
  JSON + boolean-identity checks, unit-tested in
  `tests/test_check_probe.py` via the quality gate) rather than inline
  shell greps, so contract regressions fail CI before they fail a
  scheduled run.
- `capri_project_status()` is `SECURITY DEFINER` with a pinned
  `search_path` because `service_role` has no access to the
  `supabase_migrations` schema; an invoker function returns HTTP 403
  when called through PostgREST. EXECUTE stays revoked from
  `public`/`anon`/`authenticated`.
- GitHub disables scheduled workflows after 60 days without repository
  activity. If keep-alive goes silent, re-enable it in the Actions tab
  (any push to `main` also re-triggers it).

## Backup sizing (the main growth driver)

`scripts/backup_offsite.py` uploads to `capri_backup_registry` /
`capri_backup_payloads` with a hard 10 MB per-payload cap
(`MAX_PAYLOAD_BYTES`) and `--prune-keep N` deletes all but the newest N
backups per store. Run uploads with `--prune-keep 10` (or lower): worst
case 10 stores × 10 backups × 10 MB is bounded by however many stores
you actually run — keep total registry bytes under ~100 MB (20% of the
500 MB database cap) and the database has effectively unlimited runway
because pruned rows return their space after vacuum.

## Vercel-side optimizations

- `app.py` sends `Cache-Control: public, max-age=60, s-maxage=300`, so
  repeat visits are served by the CDN instead of invoking the function;
  function invocations stay near zero. Vercel purges the cache on each
  production deploy (worst case: the displayed commit sha lags 5 min).
- The page is a dependency-free WSGI function (~1.5 KB source,
  `requirements.txt` empty) — build install step is a no-op.
- Deploy volume (~5/day) is far below the 100/day cap; builds finish in
  well under a minute against the 45-minute ceiling.

## Edge functions and the Supabase GitHub integration (incident note)

Observed 2026-11-27: every push to `main` makes the linked Supabase
GitHub integration re-upload both edge functions with a **broken build
artifact** — the function reports `ACTIVE` but every invocation fails
(HTTP 5xx), which failed the keep-alive workflow three runs in a row.
A/B proof with byte-identical source:

| Deployed by | capri-ping result |
| --- | --- |
| integration re-upload (v2, after the #285 merge) | invocations fail |
| connector API (v3, identical body) | invocations succeed |

Recovery procedure: re-deploy both functions through the connector API
(any content change forces a new version), then re-run the keep-alive
workflow.

**Resolved 2026-11-27 (PR #287):** the root cause was an empty
`entrypoint_path` — with no `supabase/functions/` directory in the
repository the integration produced artifacts that had no entrypoint.
After #287 added the source mirrors, the integration's own re-deploy on
merge switched `entrypoint_path` to
`file:///app/supabase/functions/<slug>/index.ts` and invocations stayed
green (verified at that moment: keepalive v8 answered
`{ok:true, under_limit:true}` and the push-triggered keep-alive run
passed; the function has since grown to v11 with the extended
`{ok, under_limit, cron_active, cron_stale, time}` contract and
fail-closed metric validation - see the design notes above). The
repository is now the
source of truth: `supabase/functions/<slug>/index.ts` with
`verify_jwt = false` pinned in `supabase/config.toml`, and every push
re-deploys exactly this reviewed content. The keep-alive probes still
retry five times to ride out brief deploy windows; a run that stays red
after a merge means a new regression of this class — re-deploy via the
connector and re-check `entrypoint_path`.

## CI layer (GitHub Actions, CodeQL, Dependabot)

Public repositories use GitHub Actions for free (no minutes quota), so
the entries below are not about a metered budget - they remove
duplicate and queued work, keep feedback fast, and stay correct if the
repository ever goes private.

- **Trigger audit (all 8 registered workflows):** only `quality`
  (always-on contract) and `keep-alive` (must verify every main push)
  run on every push; everything else is path-scoped (`c/**`, `rust/**`,
  `benchmarks/...`) with `cancel-in-progress` concurrency groups.
- **keep-alive concurrency:** push and schedule runs share one group;
  each run re-verifies all three endpoints from scratch, so the newer
  run supersedes the older instead of both running in parallel.
- **CodeQL (advanced setup, free for public repositories):** `python`,
  `javascript-typescript`, and `c-cpp`, all `build-mode: none` so no
  toolchain can flake; `github/codeql-action` SHA-pinned; runs on every
  push/PR plus a weekly Sunday 05:11 UTC sweep (offset from keep-alive
  04:17 and pg_cron 03:43 so nothing stacks). Rust is deferred until
  its CodeQL support is confirmed stable for the pinned action version.
- **Dependabot (`github-actions`, weekly Monday 05:11 UTC):** two
  pattern-disjoint groups - `github/codeql-action*` with **no**
  update-type filter (init/analyze must move in lockstep: split PRs
  leave mixed versions and CodeQL rejects the workflow outright, which
  the first Dependabot run proved) and `actions/*` limited to
  minor/patch (majors stay individual, self-validating PRs). The `pypi`
  ecosystem is intentionally absent: `requirements.txt` and
  `pyproject.toml` carry zero third-party dependencies.

## Owner checklist (dashboard-only, not reachable from the repo)

1. **Vercel → Settings → Git → Ignored Build Step**: skip docs-only
   pushes to conserve build capacity, e.g.
   `git diff --quiet $VERCEL_GIT_COMMIT_SHA HEAD~1 -- . ':!docs/**' ':!*.md'`.
2. **Vercel Hobby is non-commercial** — if Capri commercializes, move
   the project to Pro before that happens.
3. **Supabase → Project Settings → Usage**: egress (10 GB/month) is the
   one metric not visible in SQL; review it monthly.
4. If Supabase ever pauses the project: restore from the dashboard
   (restorable for up to 1 year) — the keep-alive workflow will have
   already failed loudly.
5. Vercel **Deployment Protection** currently covers the `*-git-main-*`
   and unique deployment aliases (they redirect to login); the public
   production domain is `https://capri-orcin.vercel.app`.
