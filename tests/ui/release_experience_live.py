"""Disposable real-browser acceptance through the restricted serialized gateway.

The fixture sends email only to an allowlisted local TLS SMTP sink, owns every
store/process, and never contacts a hosted app. Screenshots exclude credentials.
Run with the pinned jacpython wrapper; Playwright Chromium must be installed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests/integration"))
from recovery_http import Api, copy_application, input_manifest, private_dir, run_logged, scrub_environment, stable_json, stop_process
from smtp_sink import SmtpSink

GATEWAY_FILES = ("scripts/hosted-gateway.mjs", "scripts/phone-share-proxy.mjs",
                 "scripts/onboarding-ingress.mjs", "scripts/serialized-ingress.mjs")


def post(origin, path, body):
    request = urllib.request.Request(origin + path, json.dumps(body).encode(),
                                    {"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.load(response)
    assert result.get("ok"), "fixture native provisioning failed"
    return result["data"]


def port(number):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", number))
    return number


def stop_private_postgres(workspace):
    """Stop the embedded daemon only after all owned API writers are stopped."""
    workspace = workspace.resolve()
    if workspace.parent != Path("/var/tmp") or not workspace.name.startswith("m-local-release-browser."):
        raise RuntimeError("PostgreSQL cleanup refuses an unrelated workspace")
    data = workspace / "cache/pg/main"
    pid_file = data / "postmaster.pid"
    if not pid_file.exists():
        return
    if data.is_symlink() or not data.resolve().is_relative_to(workspace):
        raise RuntimeError("PostgreSQL cleanup refuses an unrelated data directory")
    pid = int(pid_file.read_text().splitlines()[0])
    process = Path("/proc") / str(pid)
    arguments = (process / "cmdline").read_bytes().split(b"\0")
    location = arguments.index(b"-D") + 1
    if Path(os.fsdecode(arguments[location])).resolve() != data.resolve():
        raise RuntimeError("PostgreSQL cleanup refuses a mismatched process")
    executable = (process / "exe").resolve()
    if executable.name != "postgres":
        raise RuntimeError("PostgreSQL cleanup refuses a different executable")
    controller = executable.with_name("pg_ctl")
    subprocess.run([str(controller), "-D", str(data), "-m", "fast", "-w", "-t", "15", "stop"],
                   check=True, timeout=20, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if pid_file.exists():
        raise RuntimeError("Owned PostgreSQL process remained after cleanup")


def main():
    from playwright.sync_api import sync_playwright, expect
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--source-ref", default="", help="Informational candidate commit; source bytes are independently hashed")
    parser.add_argument("--gateway-repo", type=Path, required=True)
    parser.add_argument("--gateway-ref", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--base-port", type=int, default=18900)
    parser.add_argument("--axe", type=Path, default=Path("/var/tmp/m-local-experience-ui/node_modules/axe-core/axe.min.js"))
    args = parser.parse_args()
    if sys.platform != "linux" or os.geteuid() == 0 or os.environ.get("JAC_DB_URL") or os.environ.get("JAC_DEV_SOURCE"):
        raise RuntimeError("Use an unprivileged Linux fixture without inherited live database/source overrides")
    source = args.source.resolve()
    if not source.is_dir() or not (source / "main.jac").is_file():
        raise RuntimeError("Fixture source must be an application source directory")
    jac = Path(os.environ["JAC_BIN"]).resolve()
    assert subprocess.check_output([str(jac), "--version"], text=True, timeout=30).split()[:2] == ["jac", "0.37.23"]
    os.umask(0o077)
    workspace = Path(tempfile.mkdtemp(prefix="m-local-release-browser.", dir="/var/tmp"))
    workspace.chmod(0o700)
    app, cache = workspace / "app", workspace / "cache"
    private_dir(app); private_dir(cache); private_dir(cache / "tmp")
    copy_application(source, app)
    shutil.copy2(Path(__file__), app / "tests/ui/release_experience_live.py")
    shutil.copy2(Path(__file__).with_name("release_sample_fixture.jac"), app / "tests/ui/release_sample_fixture.jac")
    shutil.copy2(source / "assets/manifest.webmanifest", app / "assets/manifest.webmanifest")
    for relative in GATEWAY_FILES:
        data = subprocess.check_output(["git", "show", args.gateway_ref + ":" + relative], cwd=args.gateway_repo)
        (app / relative).write_bytes(data)
    args.evidence.mkdir(parents=True, exist_ok=True)
    manifest = input_manifest(app)
    manifest["assets/manifest.webmanifest"] = hashlib.sha256((app / "assets/manifest.webmanifest").read_bytes()).hexdigest()
    binding = {"source_sha256": hashlib.sha256(stable_json(manifest)).hexdigest(), "files": manifest,
               "source_ref": args.source_ref, "gateway_ref": args.gateway_ref, "workspace": str(workspace), "jac": "0.37.23"}
    binding["axe_sha256"] = hashlib.sha256(args.axe.read_bytes()).hexdigest()
    (args.evidence / "source-binding.json").write_text(json.dumps(binding, indent=2) + "\n")
    environment = scrub_environment(jac, cache, app / ".jac/onboarding")
    # The browser runner imports Playwright from another private venv. Native
    # installation must resolve every dependency into this app's own venv.
    environment.pop("PYTHONPATH", None)
    environment.update(MLOCAL_ENV="development", MLOCAL_DEMO_MODE="1", MLOCAL_SHOW_SAMPLES="1",
                       MLOCAL_HOSTED_DATASET="0", MLOCAL_DEPLOYMENT_TOPOLOGY="single-instance-serialized",
                       MLOCAL_APP_REPLICAS="1", MLOCAL_BACKEND_PORT=str(port(args.base_port)),
                       PORT=str(port(args.base_port + 1)), MLOCAL_INGRESS="restricted-edge")
    native = "http://127.0.0.1:" + str(args.base_port)
    origin = "http://127.0.0.1:" + str(args.base_port + 1)
    processes, checks = [], []
    def interrupted(signum, _frame):
        raise SystemExit(128 + signum)
    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, interrupted)
    def check(value, label):
        assert value, label
        checks.append(label)
        print("PASS " + label, flush=True)
    def launch(command, label):
        with (workspace / (label + ".log")).open("wb") as log:
            process = subprocess.Popen(command, cwd=app, env=environment, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        processes.append(process)
        return process
    def ready(process, url, predicate):
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Owned fixture process exited: " + url)
            try:
                with urllib.request.urlopen(url, timeout=3) as response:
                    if predicate(json.load(response)):
                        return
            except (OSError, ValueError, urllib.error.URLError):
                pass
            time.sleep(.25)
        raise TimeoutError("Owned fixture readiness deadline")
    phase = "install"
    completed = False
    redemption_transition_ms = None
    started = time.monotonic()
    try:
        run_logged("private fixture dependency install", [str(jac), "install", "--no-npm"], app, environment,
                   workspace / "install.log", 180)
        with SmtpSink(workspace / "smtp") as sink:
            environment.update(MLOCAL_SMTP_HOST="127.0.0.1", MLOCAL_SMTP_PORT=str(sink.port),
                MLOCAL_SMTP_FROM=sink.sender, MLOCAL_SMTP_USERNAME=sink.username,
                MLOCAL_SMTP_PASSWORD=sink.password, SSL_CERT_FILE=str(sink.ca_file))
            phase = "native disposable merchant provisioning"
            backend = launch([str(jac), "run", "--no-dev", "--host", "127.0.0.1", "--port", str(args.base_port)], "native-setup")
            ready(backend, native + "/healthz/ready", lambda row: row.get("ready") is True)
            merchant_email = "browser-merchant-" + secrets.token_hex(4) + "@example.test"
            merchant_password = secrets.token_urlsafe(24)
            post(native, "/user/register", {"identities": [{"type": "email", "value": merchant_email}],
                                           "credential": {"type": "password", "password": merchant_password}})
            merchant = post(native, "/user/login", {"identity": {"type": "email", "value": merchant_email},
                                                     "credential": {"type": "password", "password": merchant_password}})
            stop_process(backend)
            environment["MLOCAL_RELEASE_BROWSER_FIXTURE"] = "1"
            run_logged("private mixed sample graph fixture", [str(jac), "run", "--backend", "python", "--no-serve",
                "tests/ui/release_sample_fixture.jac"], app, environment, workspace / "sample-fixture.log", 180)
            environment.pop("MLOCAL_RELEASE_BROWSER_FIXTURE")
            mixed_samples = json.loads((app / ".jac/release-sample-fixture.json").read_text())
            environment["MLOCAL_MERCHANT_OWNERS"] = json.dumps({"arbor-leaf-kitchen": merchant["root_id"]})
            phase = "native app and restricted gateway readiness"
            backend = launch([str(jac), "run", "--no-dev", "--host", "127.0.0.1", "--port", str(args.base_port)], "native")
            ready(backend, native + "/healthz/ready", lambda row: row.get("ready") is True)
            gateway = launch(["node", "scripts/hosted-gateway.mjs"], "gateway")
            ready(gateway, origin + "/healthz", lambda row: row.get("ready") is True)
            public, owner = Api(origin), Api(origin, merchant["token"])
            feed = public.call("home_feed")
            sample = next(row["offer"] for row in feed["items"] if row["place"] == "arbor-leaf-kitchen" and row["offer"]["state"] == "active")
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
                page = context.new_page()
                errors, csp, rpc_calls = [], [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("console", lambda message: csp.append(message.text) if "Content Security Policy" in message.text else None)
                page.on("request", lambda request: rpc_calls.append(request.url.rsplit("/", 1)[-1]) if "/function/" in request.url else None)
                def accessible(label):
                    page.add_script_tag(content=args.axe.read_text())
                    results = page.evaluate("async()=>await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}})")
                    (args.evidence / (label + "-axe.json")).write_text(json.dumps(results, indent=2) + "\n")
                    check(not results["violations"], label + " has no axe WCAG A/AA violations")
                phase = "anonymous actual browser"
                page.goto(origin)
                accessible("welcome")
                page.get_by_role("button", name="Find local deals", exact=False).click()
                expect(page.get_by_role("button", name="Sign in", exact=True)).to_be_visible()
                expect(page.get_by_text(sample["title"], exact=True)).to_be_visible()
                accessible("guest-feed")
                check(page.locator('[autocomplete="one-time-code"]').count() == 0, "guest browses native offers before signup")
                page.get_by_text(sample["title"], exact=True).click()
                expect(page.get_by_role("button", name="Sign in to claim", exact=True)).to_be_visible()
                check("Sample deal for a local simulation" in page.inner_text("body"), "sample detail is honestly labeled")
                page.get_by_role("button", name="View business profile", exact=True).click()
                expect(page.get_by_text("Sample business", exact=True)).to_be_visible()
                check(page.get_by_text("Sign in to view this business.", exact=True).count() == 0, "anonymous public business profile has a usable sanitized projection")
                page.get_by_role("button", name="Back to offer", exact=True).click()
                for width in (320, 390):
                    page.set_viewport_size({"width": width, "height": 844})
                    check(page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), str(width) + "px detail has no horizontal overflow")
                    page.keyboard.press("Tab")
                    check(page.evaluate("document.activeElement !== document.body"), str(width) + "px keyboard reaches a control")
                page.screenshot(path=str(args.evidence / "guest-detail-390.png"))
                accessible("guest-detail")
                phase = "real local TLS email verification"
                page.get_by_role("button", name="Sign in to claim", exact=True).click()
                accessible("claim-sign-in")
                short_controls = page.locator('button,[role="button"]').evaluate_all("nodes=>nodes.filter(n=>n.getBoundingClientRect().width>0&&n.getBoundingClientRect().height>0&&!n.disabled).map(n=>({text:n.textContent.trim(),height:n.getBoundingClientRect().height})).filter(n=>n.height<44)")
                check(not short_controls, "changed sign-in controls provide44px minimum targets")
                page.get_by_role("button", name="Create an account", exact=True).click()
                page.get_by_label("Your name", exact=True).fill("Disposable browser student")
                uniqname = "browser" + secrets.token_hex(4)
                sink.allow(uniqname + "@umich.edu")
                page.get_by_label("U-M uniqname", exact=True).fill(uniqname)
                page.get_by_role("button", name="Send verification code", exact=True).click()
                expect(page.get_by_label("Verification code", exact=True)).to_be_visible()
                code = sink.take_code(uniqname + "@umich.edu", timeout=10)
                page.get_by_label("Verification code", exact=True).fill(code)
                page.get_by_role("button", name="Verify and continue", exact=True).click()
                expect(page.get_by_role("button", name="Claim this sample", exact=True)).to_be_visible()
                check("claim_offer" not in rpc_calls, "native verification returns to selected offer without automatic claim")
                check(page.evaluate("localStorage.getItem('mlocal_public_offer_intent')") == sample["id"], "only selected public offer ID survives verification")
                page.reload()
                expect(page.get_by_role("button", name="Claim this sample", exact=True)).to_be_visible()
                check("claim_offer" not in rpc_calls, "authenticated real browser reload re-fetches selected offer without automatic claim")
                token = page.evaluate("localStorage.getItem('jac_token')")
                student = Api(origin, token)
                phase = "actual saved claim, QR image preview and confirmation"
                page.get_by_role("button", name="Claim this sample", exact=True).click()
                expect(page.locator('[data-testid="claim-qr"]')).to_be_visible()
                detail = student.call("get_offer", offer_id=sample["id"])
                check(detail["my_status"] == "claimed" and detail["my_terms"], "native claim keeps saved terms and opaque QR snapshot")
                qr_path = workspace / "claim-qr.png"
                page.locator('[data-testid="claim-qr"]').screenshot(path=str(qr_path))
                merchant_context = browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
                merchant_page = merchant_context.new_page()
                merchant_page.goto(origin)
                merchant_page.evaluate("token => {localStorage.setItem('jac_token',token);localStorage.setItem('mlocal_audience','business');localStorage.removeItem('mlocal_public_offer_intent');}", merchant["token"])
                merchant_page.reload()
                merchant_page.get_by_role("button", name="Scan QR", exact=True).click()
                merchant_page.get_by_label("Choose a QR image", exact=True).set_input_files(str(qr_path))
                expect(merchant_page.get_by_role("button", name="Confirm redemption", exact=True)).to_be_visible()
                check(student.call("get_offer", offer_id=sample["id"])["my_status"] == "claimed", "local QR image decoding previews native claim without redeeming")
                redemption_started = time.monotonic()
                merchant_page.get_by_role("button", name="Confirm redemption", exact=True).click()
                expect(merchant_page.get_by_text("Redeemed", exact=False).first).to_be_visible()
                expect(page.get_by_text("Your saved claim was redeemed.", exact=True)).to_be_visible(timeout=5000)
                redemption_transition_ms = round((time.monotonic() - redemption_started) * 1000, 2)
                check(redemption_transition_ms <= 5000, "actual merchant redemption reaches the visible student claim within five seconds")
                check(page.locator('[data-testid="claim-qr"]').count() == 0, "visible held-claim polling observes actual redemption and removes QR")
                phase = "availability changes during native inbox verification"
                for mode in ("sold out", "expired"):
                    now = datetime.now(ZoneInfo("America/Detroit"))
                    ending = now.replace(second=0, microsecond=0) + timedelta(minutes=1 if mode == "expired" else 60)
                    created = owner.call("save_offer", offer_id="", create_key=secrets.token_hex(16), title="Browser " + mode,
                        description="Disposable availability recovery fixture", price="4", regular_price="6",
                        start_local=(now - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M"),
                        end_local=ending.strftime("%Y-%m-%d %H:%M"), quantity="1", eligibility="Student ID",
                        terms="Disposable local fixture", dietary="", menu_item="")
                    check(created.get("ok"), "native merchant creates " + mode + " availability fixture")
                    visitor_context = browser.new_context(viewport={"width": 320, "height": 844}, reduced_motion="reduce")
                    visitor = visitor_context.new_page()
                    visitor.goto(origin)
                    visitor.evaluate("id=>localStorage.setItem('mlocal_public_offer_intent',id)", created["code"])
                    visitor.reload()
                    visitor.get_by_role("button", name="Sign in to claim", exact=True).click()
                    visitor.get_by_role("button", name="Create an account", exact=True).click()
                    visitor.get_by_label("Your name", exact=True).fill("Disposable availability student")
                    uniqname = "browser" + secrets.token_hex(4)
                    sink.allow(uniqname + "@umich.edu")
                    visitor.get_by_label("U-M uniqname", exact=True).fill(uniqname)
                    visitor.get_by_role("button", name="Send verification code", exact=True).click()
                    expect(visitor.get_by_label("Verification code", exact=True)).to_be_visible()
                    code = sink.take_code(uniqname + "@umich.edu", timeout=10)
                    if mode == "sold out":
                        check(student.call("claim_offer", offer_id=created["code"]).get("ok"), "another native actor consumes the last unit during verification")
                    else:
                        while time.time() <= ending.timestamp():
                            time.sleep(.25)
                    visitor.get_by_label("Verification code", exact=True).fill(code)
                    visitor.get_by_role("button", name="Verify and continue", exact=True).click()
                    recovery = "This offer is sold out right now." if mode == "sold out" else "This offer is no longer available."
                    expect(visitor.get_by_text(recovery, exact=True)).to_be_visible()
                    check(visitor.get_by_role("button", name="Claim this sample", exact=True).count() == 0,
                          "real " + mode + " verification rechecks server availability with recoverable result")
                    visitor_context.close()
                phase = "headers, metadata and gateway admission"
                with urllib.request.urlopen(origin) as response:
                    check("default-src 'self'" in response.headers.get("Content-Security-Policy", ""), "actual gateway serves restrictive CSP")
                for relative in ("/static/assets/manifest.webmanifest", "/static/assets/brand/app-icon.svg", "/static/assets/brand/app-icon-192.png", "/static/assets/brand/app-icon-512.png"):
                    with urllib.request.urlopen(origin + relative) as response:
                        check(response.status == 200, "actual gateway serves " + relative)
                check(page.title() == "M-Local", "actual document title identifies M-Local")
                check(not errors and not csp, "changed actual browser journeys have no page or CSP errors")
                browser.close()
            phase = "server-authoritative sample switch over actual HTTP"
            check(student.call("toggle_favorite", slug=mixed_samples["sample_parent"]).get("ok"), "native actor saves a sample favorite while enabled")
            check(student.call("toggle_favorite", slug=mixed_samples["real_parent"]).get("ok"), "native actor saves a legitimate real favorite")
            stop_process(gateway)
            stop_process(backend)
            environment.update(MLOCAL_SHOW_SAMPLES="0", MLOCAL_DEMO_MODE="1", MLOCAL_HOSTED_DATASET="1")
            backend = launch([str(jac), "run", "--no-dev", "--host", "127.0.0.1", "--port", str(args.base_port)], "native-samples-disabled")
            ready(backend, native + "/healthz/ready", lambda row: row.get("ready") is True)
            gateway = launch(["node", "scripts/hosted-gateway.mjs"], "gateway-samples-disabled")
            ready(gateway, origin + "/healthz", lambda row: row.get("ready") is True)
            for endpoint in ("home_feed", "list_offers"):
                result = public.call(endpoint)
                offers = [row["offer"] for row in result["items"]] if endpoint == "home_feed" else result
                check(not any(row["id"] in (sample["id"], mixed_samples["unmarked_offer"], mixed_samples["marked_offer"]) for row in offers),
                      "SHOW0 overrides demo and hosted dataset on native " + endpoint)
            for offer_id in (sample["id"], mixed_samples["unmarked_offer"], mixed_samples["marked_offer"]):
                check(public.call("get_offer", offer_id=offer_id) is None, "native direct sample detail is hidden")
                check(not student.call("claim_offer", offer_id=offer_id).get("ok"), "native direct hidden sample claim is refused")
            check(not public.call("get_business_profile", slug=mixed_samples["sample_parent"]).get("ok"), "native sample business profile is hidden")
            real_profile = public.call("get_business_profile", slug=mixed_samples["real_parent"])
            check(real_profile.get("ok") and not real_profile["offers"], "native real business profile hides its sample child")
            hidden_home = student.call("home_feed")
            check(not any(place["slug"] == mixed_samples["sample_parent"] for place in hidden_home["favorites"]), "native stored sample favorites cannot leak when disabled")
            favorite_responses = [
                student.call("taste_choices"),
                student.call("save_taste", categories="pizza", diets="", price_range=""),
                student.call("toggle_favorite", slug=mixed_samples["sample_parent"]),
            ]
            check(not favorite_responses[-1].get("ok"), "native direct favorite writes cannot bypass disabled samples")
            for endpoint, result in zip(("taste_choices", "save_taste", "toggle_favorite"), favorite_responses):
                check(mixed_samples["sample_parent"] not in result["favorites"] and mixed_samples["real_parent"] in result["favorites"],
                      "native " + endpoint + " hides sample favorites while preserving legitimate favorites")
            for offer_id in (mixed_samples["unmarked_offer"], mixed_samples["marked_offer"]):
                check(not student.call("toggle_favorite", offer_id=offer_id).get("ok"), "native hidden offer lookup cannot mutate favorites")
            check(mixed_samples["real_parent"] in student.call("taste_choices")["favorites"], "native rejected sample lookup preserves the legitimate real favorite")
            stop_process(gateway)
            stop_process(backend)
            environment.update(MLOCAL_SHOW_SAMPLES="1", MLOCAL_DEMO_MODE="0")
            backend = launch([str(jac), "run", "--no-dev", "--host", "127.0.0.1", "--port", str(args.base_port)], "native-samples-restored")
            ready(backend, native + "/healthz/ready", lambda row: row.get("ready") is True)
            gateway = launch(["node", "scripts/hosted-gateway.mjs"], "gateway-samples-restored")
            ready(gateway, origin + "/healthz", lambda row: row.get("ready") is True)
            check(mixed_samples["sample_parent"] in student.call("taste_choices")["favorites"], "native re-enabled samples restore saved sample favorite marks")
            phase = "complete"
            completed = True
    finally:
        for process in reversed(processes):
            stop_process(process)
        stop_private_postgres(workspace)
        receipt = {**binding, "status": "passed" if completed else "failed", "checks": checks, "passed": len(checks), "phase": phase,
                   "seconds": round(time.monotonic() - started, 2), "redemption_transition_ms": redemption_transition_ms,
                   "owned_processes_stopped": True,
                   "private_postgres_stopped": True}
        (args.evidence / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print("Retained private fixture: " + str(workspace), flush=True)


if __name__ == "__main__":
    main()
