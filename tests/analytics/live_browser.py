"""Real app browser acceptance; requires an isolated local server and demo accounts.

Windows Python with Playwright + installed Chrome. Screenshots/export go to the
ignored .jac/insights-evidence directory. No credentials are printed or captured.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re
import secrets

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("qr_http", ROOT / "tests/integration/qr_http.py")
http = importlib.util.module_from_spec(spec)
spec.loader.exec_module(http)


def main():
    from playwright.sync_api import sync_playwright, expect

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ui", type=http.provision.local_api, required=True)
    parser.add_argument("--api", type=http.provision.local_api, required=True)
    parser.add_argument("--accounts", type=Path, required=True)
    args = parser.parse_args()
    accounts = json.loads(args.accounts.read_text())
    evidence = ROOT / ".jac/insights-evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    clients = {}
    for role in ("merchant_leaf", "student_a"):
        account = accounts[role]
        login = http.provision.post(args.api, "/user/login", {
            "identity": {"type": "email", "value": account["email"]},
            "credential": {"type": "password", "password": account["password"]},
        })
        clients[role] = http.Api(args.api, login["token"])

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 1000}, reduced_motion="reduce")
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def sign_in(role):
            # Public UI uses verified email. Provisioned fixture accounts authenticate
            # directly against this explicitly isolated API, never a shared host.
            account = accounts[role]
            login = http.provision.post(args.api, "/user/login", {
                "identity": {"type": "email", "value": account["email"]},
                "credential": {"type": "password", "password": account["password"]},
            })
            page.evaluate("token => { localStorage.setItem('jac_token', token); localStorage.setItem('mlocal_audience', 'business'); }", login["token"])
            page.reload()
            expect(page.get_by_role("button", name="Log out", exact=True)).to_be_visible(timeout=20000)
            expect(page.locator(".bi-metrics")).to_be_visible(timeout=20000)

        def metric(label):
            return page.locator(".bi-metric").filter(has=page.get_by_role("heading", name=label, exact=True)).locator("strong")

        page.goto(args.ui)
        sign_in("merchant_leaf")
        baseline = clients["merchant_leaf"].call("merchant_insights", days=30)
        expect(metric("Redemptions")).to_have_text(str(baseline["totals"]["redemptions"]))
        page.get_by_role("button", name="Year", exact=True).click()
        expect(page.get_by_role("heading", name="Your year in review")).to_be_visible()
        expect(page.locator(".bi-progress")).to_have_text("Day 365 / 365", timeout=20000)
        page.get_by_role("button", name="Reset", exact=True).click()
        expect(metric("Redemptions")).to_have_text("0")
        expect(page.locator(".bi-offers")).to_have_count(0)
        page.get_by_role("button", name="Play", exact=True).click()
        expect(page.locator("#bi-replay-date")).not_to_have_value("0")
        page.get_by_role("button", name="Pause replay", exact=True).click()
        page.get_by_label("Replay date", exact=True).fill("365")
        expect(metric("Redemptions")).to_have_text(str(baseline["totals"]["redemptions"]))
        page.get_by_role("button", name="Return to latest", exact=True).click()
        expect(page.get_by_role("button", name="Refresh", exact=True)).to_be_enabled()
        http.require(True, "real authenticated app: year filter, seek, play, pause and reset")

        # A separate API client commits a transaction while the real dashboard is open.
        merchant, student = clients["merchant_leaf"], clients["student_a"]
        start, end = merchant.call("offer_defaults")
        offer = merchant.call("save_offer", offer_id="", create_key=secrets.token_hex(16), title="Browser acceptance " + secrets.token_hex(4),
                              description="Isolated browser test", price="4", regular_price="6", start_local=start,
                              end_local=end, quantity="1", eligibility="Demo", terms="Local test", dietary="", menu_item="")
        assert offer["ok"]
        claim = student.call("claim_offer", offer_id=offer["code"])
        assert claim["ok"]
        assert merchant.call("redeem_claim", qr_payload=claim["qr_payload"])["ok"]
        expect(metric("Redemptions")).to_have_text(str(baseline["totals"]["redemptions"] + 1), timeout=40000)
        http.require(True, "30-second visible refresh displays a committed real redemption")
        page.locator(".bi-header").scroll_into_view_if_needed()
        page.screenshot(path=str(evidence / "insights-desktop.png"))
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        assert page.locator(".bi").evaluate("node => node.scrollWidth <= node.clientWidth + 1")
        page.locator(".bi-header").scroll_into_view_if_needed()
        page.screenshot(path=str(evidence / "insights-mobile.png"))
        http.require(True, "390px merchant layout has no horizontal overflow")

        with page.expect_download() as download:
            page.get_by_role("button", name="Download recap", exact=True).click()
        artifact = evidence / "merchant-recap.html"
        download.value.save_as(artifact)
        exported = artifact.read_text(encoding="utf-8")
        for account in accounts.values():
            for key in ("email", "password", "root_id"):
                assert account[key] not in exported
            assert account["root_id"].replace("-", "") not in exported
        assert claim["claim_id"] not in exported and claim["qr_payload"] not in exported
        offline = browser.new_page(viewport={"width":390,"height":844})
        offline.route("http://**/*", lambda route: route.abort())
        offline.route("https://**/*", lambda route: route.abort())
        offline.goto(artifact.as_uri())
        expect(offline.locator("#redemptions")).to_have_text(str(baseline["totals"]["redemptions"] + 1))
        offline.get_by_role("button", name="Reset", exact=True).click()
        expect(offline.locator("#redemptions")).to_have_text("0")
        offline.close()
        http.require(True, "downloaded real recap works offline and contains no customer credentials")

        # Hold an actual old-account request across sign-out; then release it.
        pending = []
        page.route("**/function/merchant_insights", lambda route: pending.append(route))
        page.get_by_role("button", name="Refresh", exact=True).click()
        expect(page.get_by_role("button", name="Refreshing…", exact=True)).to_be_visible()
        page.get_by_role("button", name="Log out", exact=True).click()
        expect(page.locator(".bi")).to_have_count(0)
        for route in pending:
            route.continue_()
        page.unroute("**/function/merchant_insights")
        sign_in("merchant_noodle")
        expect(page.locator(".bi-empty")).to_be_visible()
        expect(metric("Redemptions")).to_have_text("0")
        assert "Arbor Leaf" not in page.locator(".bi").inner_text()
        http.require(True, "late old-account response cannot reappear after sign-out and merchant switch")
        assert not errors, errors
        browser.close()
    print("Live browser acceptance passed. Evidence: .jac/insights-evidence/")


if __name__ == "__main__":
    main()
