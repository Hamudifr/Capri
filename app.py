"""Minimal Vercel web entrypoint for the Capri repository.

The Capri runtime itself is a CLI/agent (the ``capri`` console script
declared in ``pyproject.toml``); this module exists only so Vercel's
Python builder can package a deployable function for the project's
production domain. It serves a static status page and performs no
runtime work.
"""

import os

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
</head>
<body>
<main>
<h1>Capri</h1>
<p>Provider-neutral agent runtime with authorized tool orchestration,
durable tasks, and bounded context retrieval.</p>
<p>The runtime ships as the <code>capri</code> CLI; this page is only the
repository's static status endpoint.</p>
<p>Deployed commit: <code>__COMMIT__</code></p>
<p><a href="https://github.com/Hamudifr/Capri">github.com/Hamudifr/Capri</a></p>
</main>
</body>
</html>
"""


def app(environ, start_response):
    """Serve the static status page for any request method."""
    commit = os.environ.get("VERCEL_GIT_COMMIT_SHA", "unknown")
    body = _PAGE.replace(b"__COMMIT__", commit.encode("ascii", "replace"))
    start_response(
        "200 OK",
        [
            ("Content-Type", "text/html; charset=utf-8"),
            # Edge-cache the status page so repeat visits are served from
            # Vercel's CDN instead of invoking the function: keeps function
            # invocations near zero on the Hobby free plan. Vercel purges the
            # cache on each new production deploy; worst case the displayed
            # commit sha lags by five minutes.
            ("Cache-Control", "public, max-age=60, s-maxage=300"),
            ("X-Content-Type-Options", "nosniff"),
            ("Referrer-Policy", "no-referrer"),
            # Static page: never renderable in a frame (clickjacking) and
            # no privileged browser features. CSP deliberately omitted:
            # the page loads Vercel Speed Insights scripts and a CSP
            # cannot be browser-verified from the repo sandbox.
            ("X-Frame-Options", "DENY"),
            ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
            ("Strict-Transport-Security", "max-age=63072000"),
            ("Content-Length", str(len(body))),
        ],
    )
    if environ.get("REQUEST_METHOD") == "HEAD":
        return [b""]
    return [body]
