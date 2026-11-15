import contextlib
import copy
import importlib.util
import io
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("hosted_alpha", ROOT / "scripts" / "check-hosted-alpha.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)
REVISION = "a" * 40
SECURITY = {
    "Strict-Transport-Security": "max-age=31536000",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(self), microphone=(), geolocation=()",
    "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; connect-src 'self'",
}


def response(value, status=200, headers=None):
    return (status, {"Content-Type": "application/json", **(headers or {})}, json.dumps(value).encode())


def rpc(value):
    return response({"ok": True, "data": {"result": value}})


class HostedAlphaTests(unittest.TestCase):
    def setUp(self):
        self.routes = {
            ("GET", "/"): (200, {"Content-Type": "text/html", **SECURITY}, b"<!doctype html><html><body>App</body></html>"),
            ("GET", "/healthz"): response({"ready": True}),
            ("GET", "/static/assets/mlocal-build.json"): response({"source_revision": REVISION, "runtime_version": "0.37.23", "project_version": "0.1.0"}),
            ("POST", "/function/current_session"): rpc({"role": "guest", "authenticated": False}),
            ("POST", "/function/home_feed"): rpc({"items": [], "total_deals": 0, "matching_deals": 0, "show_samples": False, "signed_in": False}),
            ("POST", "/user/register"): response({"ok": False}, 403),
            ("POST", "/user/login"): response({"ok": False}, 404),
            ("GET", "/docs"): response({"ok": False}, 404),
            ("GET", "/graph/data"): response({"ok": False}, 403),
        }
        self.seen = []
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def handle_request(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                fixture.seen.append((self.command, self.path, body))
                status, headers, data = fixture.routes.get((self.command, self.path), response({}, 404))
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = handle_request
            do_POST = handle_request

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:" + str(self.server.server_port)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.thread.join, 2)
        self.addCleanup(self.server.shutdown)

    def results(self, allow_samples=False):
        return {name: (passed, message) for name, passed, message in probe.check_host(self.url, REVISION, allow_samples)}

    def test_accepts_protected_host_with_valid_empty_catalog(self):
        results = self.results()
        self.assertTrue(all(passed for passed, _ in results.values()), results)
        self.assertEqual(len(results), 15)
        sent = {(method, path): body for method, path, body in self.seen}
        self.assertEqual(sent[("POST", "/user/register")], b"{}")
        self.assertEqual(sent[("POST", "/user/login")], b"{}")
        self.assertEqual(json.loads(sent[("POST", "/function/home_feed")]), {"limit": 40})

    def test_accepts_provider_health_with_healthy_application(self):
        self.routes[("GET", "/healthz")] = response({"status": "healthy", "services": {"m-local": {"status": "healthy"}}})
        self.assertTrue(self.results()["health"][0])

    def test_rejects_unhealthy_200_and_string_true(self):
        for value in ({"ready": False}, {"ready": "true"}, {"status": "healthy", "services": {"m-local": {"status": "unhealthy"}}}):
            with self.subTest(value=value):
                self.routes[("GET", "/healthz")] = response(value)
                self.assertFalse(self.results()["health"][0])

    def test_spa_fallback_is_not_json_health_or_build_evidence(self):
        for path, check in (("/healthz", "health"), ("/static/assets/mlocal-build.json", "build")):
            self.routes[("GET", path)] = self.routes[("GET", "/")]
            self.assertFalse(self.results()[check][0])

    def test_rejects_wrong_revision_and_runtime(self):
        for values in ({"source_revision": "b" * 40, "runtime_version": "0.37.23"}, {"source_revision": REVISION, "runtime_version": "0.36.1"}):
            self.routes[("GET", "/static/assets/mlocal-build.json")] = response({**values, "project_version": "0.1.0"})
            self.assertFalse(self.results()["build"][0])

    def test_rejects_authenticated_guest_probe(self):
        self.routes[("POST", "/function/current_session")] = rpc({"role": "student", "authenticated": True})
        self.assertFalse(self.results()["guest_session"][0])

    def test_rejects_samples_unless_explicitly_allowed(self):
        self.routes[("POST", "/function/home_feed")] = rpc({"items": [], "total_deals": 0, "matching_deals": 0, "show_samples": True, "signed_in": False})
        self.assertFalse(self.results()["guest_feed"][0])
        self.assertTrue(self.results(allow_samples=True)["guest_feed"][0])

    def test_rejects_malformed_feed_or_application_failure(self):
        for payload in ({"ok": False, "data": {"result": {}}}, {"ok": True, "data": {"result": {"items": "not a list"}}}):
            self.routes[("POST", "/function/home_feed")] = response(payload)
            self.assertFalse(self.results()["guest_feed"][0])

    def test_throttled_registration_is_not_closed(self):
        for status in (200, 400, 401, 403, 429):
            with self.subTest(status=status):
                self.routes[("POST", "/user/register")] = response({"ok": False, "error": {"code": "CHALLENGE_REQUIRED"}}, status)
                self.assertFalse(self.results()["native_registration"][0])

    def test_spa_docs_response_does_not_prove_route_denial(self):
        self.routes[("GET", "/docs")] = self.routes[("GET", "/")]
        passed, message = self.results()["docs_denied"]
        self.assertFalse(passed)
        self.assertIn("denial", message)
        self.assertNotIn("exposed", message)

    def test_rejects_missing_or_weak_security_headers(self):
        status, headers, body = self.routes[("GET", "/")]
        broken = copy.copy(headers)
        broken["Strict-Transport-Security"] = "max-age=0"
        broken["X-Frame-Options"] = "SAMEORIGIN"
        broken["X-Content-Type-Options"] = ""
        broken["Referrer-Policy"] = "unsafe-url"
        broken["Content-Security-Policy"] = "default-src *; frame-ancestors *"
        broken["Permissions-Policy"] = "camera=*"
        self.routes[("GET", "/")] = (status, broken, body)
        results = self.results()
        for name in ("hsts", "nosniff", "frame_denial", "referrer_policy", "content_security_policy", "permissions_policy"):
            self.assertFalse(results[name][0], name)

    def test_does_not_follow_redirects(self):
        self.routes[("GET", "/static/assets/mlocal-build.json")] = response({}, 302, {"Location": "/private"})
        self.assertFalse(self.results()["build"][0])
        self.assertFalse(any(path == "/private" for _, path, _ in self.seen))

    def test_outputs_only_named_checks_without_remote_payload(self):
        marker = "SECRET_fixture_token_and_email@example.test"
        self.routes[("GET", "/healthz")] = (500, {"Content-Type": "text/plain"}, marker.encode())
        with contextlib.redirect_stdout(io.StringIO()) as out:
            result = probe.main(["--url", self.url, "--expected-revision", REVISION])
        self.assertEqual(result, 1)
        self.assertIn("FAIL health:", out.getvalue())
        self.assertNotIn(marker, out.getvalue())

    def test_validates_destination_and_preview_scope_before_request(self):
        for url in ("http://public.example.test", "https://user:password@example.test", "https://example.test/path", "https://example.test/?token=x"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                probe.check_host(url, REVISION)
        with self.assertRaises(ValueError):
            probe.check_host("https://production.example.test", REVISION, True)
        with self.assertRaises(ValueError):
            probe.check_host(self.url, "main")


if __name__ == "__main__":
    unittest.main()
