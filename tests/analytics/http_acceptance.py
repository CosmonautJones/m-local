"""Live Insights acceptance against an isolated local app with provisioned accounts.

Creates fictional offers and claims. Never use a shared demo or production store.
Run with --api and --accounts as in tests/integration/qr_http.py.
No passwords, tokens, account IDs or claim credentials are printed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import importlib.util
import json
from pathlib import Path
import secrets
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("qr_http", ROOT / "tests/integration/qr_http.py")
http = importlib.util.module_from_spec(spec)
spec.loader.exec_module(http)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", type=http.provision.local_api, required=True)
    parser.add_argument("--accounts", type=Path, required=True)
    args = parser.parse_args()
    accounts = json.loads(args.accounts.read_text())
    clients = {}
    for role, account in accounts.items():
        login = http.provision.post(args.api, "/user/login", {
            "identity": {"type": "email", "value": account["email"]},
            "credential": {"type": "password", "password": account["password"]},
        })
        clients[role] = http.Api(args.api, login["token"])
    merchant, other = clients["merchant_leaf"], clients["merchant_noodle"]
    student, second = clients["student_a"], clients["student_b"]
    require = http.require
    require(not http.Api(args.api).call("merchant_insights")["ok"], "guest analytics denied")
    denied = student.call("merchant_insights")
    require(not denied["ok"] and not denied.get("frames"), "student receives no merchant analytics")
    require(not merchant.call("merchant_insights", days=999)["ok"], "unsupported period rejected")
    baseline = merchant.call("merchant_insights", days=7)
    other_before = other.call("merchant_insights", days=7)
    require(baseline["ok"] and baseline["is_demo"], "demo merchant clearly labeled")
    for days in (7, 30, 90, 365):
        data = merchant.call("merchant_insights", days=days)
        require(data["ok"] and len(data["frames"]) == days + 1,
                f"{days}-day period includes zero baseline and local daily frames")
    now = datetime.now(ZoneInfo("America/Detroit"))
    run = secrets.token_hex(5)
    offer = dict(offer_id="", create_key=secrets.token_hex(16), title="Insights acceptance " + run,
                 description="Fictional local acceptance offer", price="3.00", regular_price="5.00",
                 start_local=(now-timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M"),
                 end_local=(now+timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"), quantity="2",
                 eligibility="Demo students", terms="Local test only", dietary="", menu_item="")
    saved = merchant.call("save_offer", **offer)
    require(saved["ok"], "created isolated test offer")
    offer_id = saved["code"]
    claim = student.call("claim_offer", offer_id=offer_id)
    require(claim["ok"], "real claim request succeeds")
    retry = student.call("claim_offer", offer_id=offer_id)
    require(retry["claim_id"] == claim["claim_id"], "claim retry preserves canonical record")
    claimed = merchant.call("merchant_insights", days=7)
    require(claimed["totals"]["claims"] == baseline["totals"]["claims"] + 1,
            "claim appears exactly once in live metrics")
    offer.update(offer_id=offer_id, title="Edited acceptance " + run, price="9.00", regular_price="12.00")
    require(merchant.call("save_offer", **offer)["ok"], "future offer terms edited")
    require(not other.call("redeem_claim", qr_payload=claim["qr_payload"])["ok"], "other merchant cannot redeem")
    require(merchant.call("redeem_claim", qr_payload=claim["qr_payload"])["ok"], "real redemption succeeds")
    require(not merchant.call("redeem_claim", qr_payload=claim["qr_payload"])["ok"], "redemption retry rejected")
    redeemed = merchant.call("merchant_insights", days=7)
    for key, delta in (("redemptions", 1), ("value_cents", 300), ("savings_cents", 200), ("savings_known", 1)):
        require(redeemed["totals"][key] == baseline["totals"][key] + delta,
                f"live {key} uses original claim snapshot and counts once")
    title = next(o["title"] for o in redeemed["offers"] if o["id"] == offer_id)
    require(title == "Insights acceptance " + run, "replay offer title retains original snapshot")
    cancelled = second.call("claim_offer", offer_id=offer_id)
    require(cancelled["ok"], "second account claims")
    require(second.call("cancel_claim", offer_id=offer_id)["ok"], "real cancellation succeeds")
    require(second.call("cancel_claim", offer_id=offer_id)["ok"], "cancellation retry safe")
    after = merchant.call("merchant_insights", days=7)
    require(after["totals"]["cancelled"] == baseline["totals"]["cancelled"] + 1,
            "cancellation appears once with recorded timestamp")
    require(other.call("merchant_insights", days=7)["totals"] == other_before["totals"],
            "other business totals remain unchanged")
    require(after["frames"][-1]["totals"] == after["totals"], "latest replay frame matches live summary")
    encoded = json.dumps(after)
    forbidden_values = [claim["claim_id"], claim["qr_payload"], cancelled["claim_id"], cancelled["qr_payload"]]
    forbidden_values += [a[key] for a in accounts.values() for key in ("root_id", "email", "password")]
    forbidden_values += [a["root_id"].replace("-", "") for a in accounts.values()]
    require(all(value not in encoded for value in forbidden_values), "response contains no private customer identifiers or credentials")
    require(not after["engagement_available"], "untracked engagement is explicitly unavailable")
    print("Live Insights HTTP acceptance passed using an isolated local store.")


if __name__ == "__main__":
    main()
