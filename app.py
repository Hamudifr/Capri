""""Minimal Vercel status page for the Capri repository.

The Capri runtime itself is a CLI/agent (the ``capri`` console script
declared in ``pyproject.toml``). This WSGI entrypoint serves a small
status page and reads only the public, keyless Supabase keep-alive probe.
It never uses a database credential or exposes raw telemetry.
"""

from __future__ import annotations

import html
import json
import os
import re
from urllib.parse import urlsplit
from urllib.request import urlopen

_PAGE = b"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Capri</title>
<script>
  window.si = window.si || function () { (window.siq = window.siq || []).push(arguments); };
</script>
<script defer src="/_vercel/speed-insights/script.js"></script>
<style>
  body { font-family: system-ui, sans-serif; line-height: 1.55; margin: 3rem auto; max-width: 46rem; padding: 0 1.25rem; }
  h1 { margin-bottom: .25rem; }
  .muted { color: #667085; }
  .status { border: 1px solid #d0d5dd; border-radius: .75rem; margin: 1.5rem 0; padding: 1rem 1.25rem; }
  .status ul { list-style: none; margin: .75rem 0; padding: 0; }
  .status li { display: flex; flex-wrap: wrap; gap: .35rem .75rem; justify-content: space-between; padding: .35rem 0; }
  .ok { color: #067647; }
  .warn { color: #b54708; }
</style>
</head>
<body>
<main>
<h1>Capri</h1>
<p>Provider-neutral agent runtime with authorized tool orchestration,
durable tasks, and bounded context retrieval.</p>
<p>The runtime ships as the <code>capri</code> CLI. This page reports
repository and infrastructure status; it does not host the agent runtime.</p>
__INFRA_STATUS__
<p>Deployed commit: <code>__COMMIT__</code></p>
<p><a href="https://github.com/Hamudifr/Capri">github.com/Hamudifr/Capri</a></p>
</main>
</body>
</html>
"""


def _load_supabase_status() -> dict[str, bool | str] | None:
    """Read the safe keyless probe, failing closed on every bad response."""
    project_ref = os.environ.get("SUPABASE_PROJECT_REF", "").strip()
    base_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not re.fullmatch(r"[a-z0-9]{20}", project_ref):
        return None

    parsed = urlsplit(base_url)
    expected_host = f"{project_ref}.supabase.co"
    if (
        parsed.scheme != "https"
        or parsed.netloc != expected_host
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        return None

    try:
        with urlopen(f"{base_url}/functions/v1/capri-keepalive", timeout=2) as response:
            if response.status != 200:
                return None
            raw = response.read(4097)
    except (OSError, ValueError):
        return None

    if len(raw) > 4096:
        return None
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None

    keys = ("ok", "under_limit", "cron_active", "cron_stale")
    if any(type(payload.get(key)) is not bool for key in keys):
        return None

    checked_at = payload.get("time")
    if not isinstance(checked_at, str) or len(checked_at) > 64:
        checked_at = ""
    return {key: payload[key] for key in keys} | {"time": checked_at}


def _render_status(status: dict[str, bool | str] | None) -> str:
    """Render only fixed labels and strict boolean results from the probe."""
    if status is None:
        return (
            '<section class="status" aria-labelledby="infra-title">'
            '<h2 id="infra-title">Infrastructure status</h2>'
            '<p class="warn">Live Supabase check unavailable. Status is unverified.</p>'
            '<p class="muted">No credentials or database details are displayed.</p>'
            '</section>'
        )

    checks = (
        ("Supabase database probe", status["ok"], "Responding", "Unavailable"),
        ("Free-plan usage threshold", status["under_limit"], "Within threshold", "Attention required"),
        (
            "Daily keep-alive scheduler",
            status["cron_active"] and not status["cron_stale"],
            "Active and recent",
            "Inactive or stale",
        ),
    )
    rows = []
    for label, healthy, good, bad in checks:
        state = good if healthy else bad
        css = "ok" if healthy else "warn"
        rows.append(
            f'<li><span>{label}</span><strong class="{css}">{state}</strong></li>'
        )

    checked_at = html.escape(str(status["time"]) or "time unavailable")
    return (
        '<section class="status" aria-labelledby="infra-title">'
        '<h2 id="infra-title">Infrastructure status</h2>'
        f'<ul>{"".join(rows)}</ul>'
        f'<p class="muted">Last checked: {checked_at}. The page may be CDN-cached for up to five minutes.</p>'
        '<p class="muted">Only boolean health signals are shown; no credentials or raw database metrics are exposed.</p>'
        '</section>'
    )


def app(environ, start_response):
    """Serve the status page and a bounded, credential-free health check."""
    commit = os.environ.get("VERCEL_GIT_COMMIT_SHA", "unknown")
    if not re.fullmatch(r"[0-9a-f]{7,64}", commit):
        commit = "unknown"

    status_markup = _render_status(_load_supabase_status())
    body = (
        _PAGE.replace(b"__COMMIT__", commit.encode("ascii"))
        .replace(b"__INFRA_STATUS__", status_markup.encode("utf-8"))
    )
    start_response(
        "200 OK",
        [
            ("Content-Type", "text/html; charset=utf-8"),
            # Live checks run only on cache misses. Repeat visits are served
            # from Vercel's CDN; the health signal can be up to five minutes old.
            ("Cache-Control", "public, max-age=60, s-maxage=300"),
            ("X-Content-Type-Options", "nosniff"),
            ("Referrer-Policy", "no-referrer"),
            ("X-Frame-Options", "DENY"),
            ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
            ("Strict-Transport-Security", "max-age=63072000"),
            ("Content-Length", str(len(body))),
        ],
    )
    if environ.get("REQUEST_METHOD") == "HEAD":
        return [b""]
    return [body]
