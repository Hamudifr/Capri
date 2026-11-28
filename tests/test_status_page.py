"""WSGI tests for the Vercel status page (app.py).

Commits the ad-hoc local smoke gate: callable shape, status page
markers, security headers, commit substitution, and HEAD handling.
"""

from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path

APP_PATH = Path(__file__).resolve().parent.parent / "app.py"
_SPEC = importlib.util.spec_from_file_location("capri_status_app", APP_PATH)
assert _SPEC is not None and _SPEC.loader is not None
app_module = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(app_module)


def call(
    method: str = "GET", commit: str | None = None
) -> tuple[str, dict[str, str], bytes]:
    """Invoke the WSGI app with a controlled VERCEL_GIT_COMMIT_SHA."""
    saved = os.environ.get("VERCEL_GIT_COMMIT_SHA")
    if commit is None:
        os.environ.pop("VERCEL_GIT_COMMIT_SHA", None)
    else:
        os.environ["VERCEL_GIT_COMMIT_SHA"] = commit
    try:
        captured: dict[str, object] = {}

        def start_response(status: str, headers: list[tuple[str, str]], exc_info=None):
            captured["status"] = status
            captured["headers"] = headers

        body = b"".join(app_module.app({"REQUEST_METHOD": method}, start_response))
    finally:
        if saved is None:
            os.environ.pop("VERCEL_GIT_COMMIT_SHA", None)
        else:
            os.environ["VERCEL_GIT_COMMIT_SHA"] = saved
    assert "status" in captured and "headers" in captured
    return str(captured["status"]), dict(captured["headers"]), body  # type: ignore[arg-type]


class StatusPageTests(unittest.TestCase):
    def test_get_serves_200_html_with_markers(self) -> None:
        status, headers, body = call("GET")
        self.assertEqual(status, "200 OK")
        self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
        text = body.decode("utf-8")
        self.assertIn("<title>Capri</title>", text)
        self.assertIn("Deployed commit", text)
        self.assertIn("github.com/Hamudifr/Capri", text)

    def test_head_returns_empty_body_with_headers(self) -> None:
        status, headers, body = call("HEAD")
        self.assertEqual(status, "200 OK")
        self.assertEqual(body, b"")
        self.assertIn("Content-Length", headers)

    def test_content_length_matches_body(self) -> None:
        _, headers, body = call("GET")
        self.assertEqual(int(headers["Content-Length"]), len(body))

    def test_commit_substitution(self) -> None:
        commit = "deadbeefcafe1234" * 2 + "deadbeefcafe1234"
        _, _, body = call("GET", commit=commit)
        self.assertIn(commit.encode("ascii"), body)

    def test_malformed_commit_falls_back_to_unknown(self) -> None:
        for commit in (
            "<script>alert(1)</script>",
            "a" * 39,
            "g" * 40,
            "a" * 41,
            "deadbeef\r\nX-Injected: yes",
        ):
            with self.subTest(commit=commit):
                _, _, body = call("GET", commit=commit)
                self.assertIn(b"<code>unknown</code>", body)
                self.assertNotIn(b"<script>alert(1)</script>", body)

    def test_missing_commit_falls_back_to_unknown(self) -> None:
        _, _, body = call("GET", commit=None)
        self.assertIn(b"unknown", body)

    def test_security_headers(self) -> None:
        _, headers, _ = call("GET")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(
            headers["Permissions-Policy"], "camera=(), microphone=(), geolocation=()"
        )
        self.assertTrue(headers["Strict-Transport-Security"].startswith("max-age="))

    def test_cache_control_allows_edge_caching(self) -> None:
        _, headers, _ = call("GET")
        self.assertIn("public", headers["Cache-Control"])
        self.assertIn("s-maxage", headers["Cache-Control"])

    def test_any_method_serves_200(self) -> None:
        status, _, _ = call("POST")
        self.assertEqual(status, "200 OK")


if __name__ == "__main__":
    unittest.main()
