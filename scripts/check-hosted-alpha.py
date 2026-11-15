#!/usr/bin/env python3
"""Check a hosted M-Local build without credentials, mail, or application writes.

Use --allow-samples only for an invited preview. A passing result checks HTTP
acceptance; it does not certify inbox delivery, phones, backups or capacity.
"""
import argparse
import http.client
import json
import re
import urllib.error
import urllib.parse
import urllib.request

RUNTIME = "0.37.23"
TIMEOUT = 10
MAX_RESPONSE = 2 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def destination(url, revision, allow_samples):
    parsed = urllib.parse.urlsplit(url)
    local = parsed.hostname in ("localhost", "127.0.0.1", "::1")
    if (not parsed.hostname or parsed.username is not None or parsed.password is not None
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment
            or (parsed.scheme != "https" and not (local and parsed.scheme == "http"))):
        raise ValueError("Use an HTTPS origin without credentials, path, query or fragment.")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Expected revision must be a full lowercase Git commit SHA.")
    if allow_samples and not local and not re.search(r"(^|[.-])preview([.-]|$)", parsed.hostname):
        raise ValueError("Allowing samples requires a preview hostname.")
    return url.rstrip("/")


def request(opener, origin, path, body=None):
    data = None if body is None else json.dumps(body, separators=(",", ":")).encode()
    req = urllib.request.Request(origin + path, data=data, headers={
        "Content-Type": "application/json", "Accept-Encoding": "identity",
        "User-Agent": "M-Local-alpha-check",
    })
    try:
        try:
            response = opener.open(req, timeout=TIMEOUT)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                return None, {}, b""
            return response.status, response.headers, raw
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, http.client.HTTPException):
        # Remote exceptions can contain host details or supplied response text.
        return None, {}, b""


def document(reply):
    status, headers, raw = reply
    if status != 200 or headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
        return None
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        return None
    return value if isinstance(value, dict) else None


def result(reply):
    value = document(reply)
    if value is None or value.get("ok") is not True or not isinstance(value.get("data"), dict):
        return None
    value = value["data"].get("result")
    return value if isinstance(value, dict) else None


def healthy(value):
    if not isinstance(value, dict):
        return False
    if "ready" in value:
        return value["ready"] is True and value.get("status", "healthy") in ("healthy", "ready")
    services = value.get("services")
    return (value.get("status") == "healthy" and isinstance(services, dict) and "m-local" in services
            and all(isinstance(service, dict) and service.get("status") == "healthy" for service in services.values()))


def valid_feed(value, allow_samples):
    if not isinstance(value, dict) or not isinstance(value.get("items"), list):
        return False
    total, matching = value.get("total_deals"), value.get("matching_deals")
    return (type(total) is int and type(matching) is int and total >= matching >= len(value["items"])
            and len(value["items"]) <= 40 and all(isinstance(item, dict) for item in value["items"])
            and value.get("signed_in") is False and type(value.get("show_samples")) is bool
            and (allow_samples or value["show_samples"] is False))


def protected_csp(text):
    directives = {}
    for entry in text.split(";"):
        parts = entry.split()
        if parts:
            directives.setdefault(parts[0].lower(), parts[1:])
    required = {"default-src": ["'self'"], "object-src": ["'none'"], "base-uri": ["'none'"],
                "form-action": ["'self'"], "frame-ancestors": ["'none'"], "connect-src": ["'self'"]}
    scripts = directives.get("script-src", [])
    return (all(directives.get(key) == value for key, value in required.items()) and "'self'" in scripts
            and all(source in ("'self'", "'unsafe-inline'") for source in scripts))


def denied(reply):
    status, _, raw = reply
    if status not in (403, 404):
        return False
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        return True
    error = value.get("error") if isinstance(value, dict) else None
    return not (isinstance(error, dict) and error.get("code") in ("CHALLENGE_REQUIRED", "RATE_LIMITED"))


def check_host(url, revision, allow_samples=False):
    origin = destination(url, revision, allow_samples)
    opener = urllib.request.build_opener(NoRedirect())
    results = []

    def check(name, passed, failure):
        results.append((name, bool(passed), "verified" if passed else failure))

    root = request(opener, origin, "/")
    status, headers, raw = root
    check("root", status == 200 and headers.get("Content-Type", "").split(";", 1)[0].strip().lower() == "text/html"
          and b"<html" in raw.lower(), "expected HTTP 200 HTML application shell")
    check("health", healthy(document(request(opener, origin, "/healthz"))), "healthy JSON response not verified")
    build = document(request(opener, origin, "/static/assets/mlocal-build.json")) or {}
    check("build", build.get("source_revision") == revision and build.get("runtime_version") == RUNTIME
          and isinstance(build.get("project_version"), str) and bool(build["project_version"].strip()),
          "expected source/runtime identity not verified")
    session = result(request(opener, origin, "/function/current_session", {})) or {}
    check("guest_session", session.get("role") == "guest" and session.get("authenticated") is False,
          "anonymous guest session not verified")
    check("guest_feed", valid_feed(result(request(opener, origin, "/function/home_feed", {"limit": 40})), allow_samples),
          "valid anonymous paged feed and sample policy not verified")

    hsts = re.search(r"(?:^|;)\s*max-age\s*=\s*(\d+)\s*(?:;|$)", headers.get("Strict-Transport-Security", ""), re.I)
    check("hsts", hsts is not None and int(hsts.group(1)) >= 31536000, "HSTS of at least one year missing")
    check("nosniff", headers.get("X-Content-Type-Options", "").strip().lower() == "nosniff", "nosniff header missing")
    check("frame_denial", headers.get("X-Frame-Options", "").strip().upper() == "DENY", "frame denial missing")
    check("referrer_policy", headers.get("Referrer-Policy", "").strip().lower() in
          ("no-referrer", "same-origin", "strict-origin", "strict-origin-when-cross-origin"), "restrictive referrer policy missing")
    check("content_security_policy", protected_csp(headers.get("Content-Security-Policy", "")), "required content security policy missing or weaker")
    permissions = re.sub(r"\s+", "", headers.get("Permissions-Policy", "").lower()).split(",")
    check("permissions_policy", all(policy in permissions for policy in ("camera=(self)", "microphone=()", "geolocation=()")),
          "self-only camera and disabled microphone/geolocation policy missing")

    for name, path, body in (("native_registration", "/user/register", {}), ("native_login", "/user/login", {}),
                              ("docs_denied", "/docs", None), ("graph_denied", "/graph/data", None)):
        check(name, denied(request(opener, origin, path, body)), "explicit HTTP 403/404 route denial not verified")
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--allow-samples", action="store_true", help="invited preview only")
    args = parser.parse_args(argv)
    try:
        results = check_host(args.url, args.expected_revision, args.allow_samples)
    except ValueError as error:
        print("FAIL configuration: " + str(error))
        return 2
    for name, passed, message in results:
        print(("PASS" if passed else "FAIL") + f" {name}: {message}")
    passed = sum(ok for _, ok, _ in results)
    print(f"{passed}/{len(results)} HTTP acceptance checks passed.")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
