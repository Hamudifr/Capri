"""WSGI tests for the Vercel status page (app.py).

Covers the page contract plus the credential-free Supabase health probe.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

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
        _, _, body = call("GET", commit="deadbeefcafe1234")
        self.assertIn(b"deadbeefcafe1234", body)

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


PROJECT_REF = "znpvstwmzyphmvkhigqp"
SUPABASE_URL = f"https://{PROJECT_REF}.supabase.co"
HEALTHY = {
    "ok": True,
    "under_limit": True,
    "cron_active": True,
    "cron_stale": False,
    "time": "2026-11-28T03:43:00.000Z",
}


class FakeOpener:
    def __init__(self, response: object) -> None:
        self.response = response
        self.open_args: tuple[object, ...] | None = None
        self.timeout: int | None = None

    def open(self, url: str, timeout: int) -> object:
        self.open_args = (url,)
        self.timeout = timeout
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


class FakeResponse:
    status = 200

    def __init__(self, body: bytes) -> None:
        self.body = io.BytesIO(body)

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self.body.read(size)


class SupabaseStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "SUPABASE_PROJECT_REF": PROJECT_REF,
                "SUPABASE_URL": SUPABASE_URL,
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_reads_only_the_keyless_health_contract(self) -> None:
        response = FakeResponse(json.dumps(HEALTHY).encode())
        opener = FakeOpener(response)
        with patch.object(app_module, "build_opener", return_value=opener) as factory:
            status = app_module._load_supabase_status()

        self.assertEqual(status, HEALTHY)
        factory.assert_called_once()
        self.assertEqual(
            opener.open_args,
            (f"{SUPABASE_URL}/functions/v1/capri-keepalive",),
        )
        self.assertEqual(opener.timeout, 2)

    def test_rejects_a_different_host_without_network_access(self) -> None:
        with patch.dict(os.environ, {"SUPABASE_URL": "https://attacker.example"}):
            with patch.object(app_module, "build_opener") as factory:
                self.assertIsNone(app_module._load_supabase_status())
        factory.assert_not_called()

    def test_rejects_redirects_instead_of_following_them(self) -> None:
        redirect = HTTPError(
            f"{SUPABASE_URL}/functions/v1/capri-keepalive",
            302,
            "redirect",
            {},
            None,
        )
        with patch.object(app_module, "build_opener", return_value=FakeOpener(redirect)):
            self.assertIsNone(app_module._load_supabase_status())

    def test_rejects_non_boolean_health_fields(self) -> None:
        payload = dict(HEALTHY, cron_active="true")
        response = FakeResponse(json.dumps(payload).encode())
        with patch.object(app_module, "build_opener", return_value=FakeOpener(response)):
            self.assertIsNone(app_module._load_supabase_status())

    def test_rejects_oversized_response(self) -> None:
        response = FakeResponse(b" " * 4097)
        with patch.object(app_module, "build_opener", return_value=FakeOpener(response)):
            self.assertIsNone(app_module._load_supabase_status())

    def test_network_failure_is_unverified_not_healthy(self) -> None:
        with patch.object(app_module, "build_opener", side_effect=TimeoutError):
            self.assertIsNone(app_module._load_supabase_status())

    def test_status_page_renders_safe_signals_and_keeps_cdn_cache(self) -> None:
        captured: dict[str, object] = {}

        def start_response(status: str, headers: list[tuple[str, str]]) -> None:
            captured["status"] = status
            captured["headers"] = dict(headers)

        with patch.dict(os.environ, {"VERCEL_GIT_COMMIT_SHA": "a" * 40}):
            with patch.object(app_module, "_load_supabase_status", return_value=HEALTHY):
                body = b"".join(app_module.app({"REQUEST_METHOD": "GET"}, start_response))

        page = body.decode()
        self.assertEqual(captured["status"], "200 OK")
        self.assertEqual(
            captured["headers"]["Cache-Control"],  # type: ignore[index]
            "public, max-age=60, s-maxage=300",
        )
        self.assertIn("Supabase database probe", page)
        self.assertIn("Active and recent", page)
        self.assertIn("a" * 40, page)
        self.assertNotIn("SUPABASE_SERVICE_ROLE_KEY", page)

    def test_unavailable_probe_is_explicitly_unverified(self) -> None:
        page = app_module._render_status(None)
        self.assertIn("Live Supabase check unavailable", page)
        self.assertNotIn("healthy", page.lower())


if __name__ == "__main__":
    unittest.main()
