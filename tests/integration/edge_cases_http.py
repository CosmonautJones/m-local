"""Real-HTTP edge cases for claim/redemption: last available offer, double
redemption, expired claim, wrong merchant. Starts its own API-only server,
registers fresh accounts per run, provisions two merchants by environment.
The expired-claim case really waits for an offer to end (about 1-2 minutes).
"""
import datetime, json, os, subprocess, sys, time, urllib.request, concurrent.futures as cf
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
JAC = os.environ.get("JAC", os.path.expanduser("~/jachacks/bin/jac-0.37.23"))
PORT = int(os.environ.get("PORT", "8151"))
B = f"http://127.0.0.1:{PORT}"
RUN = os.urandom(3).hex()
TZ = ZoneInfo("America/Detroit")
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:240]}]" if detail and not cond else ""), flush=True)


def stop():
    subprocess.run(["pkill", "-f", f"no-client --port {PORT}"], capture_output=True)
    time.sleep(1.5)


def start(env_extra=None):
    stop()
    subprocess.Popen([JAC, "run", "--serve", "--no-client", "--port", str(PORT), "main.jac"], cwd=HERE,
                     env=dict(os.environ, **(env_extra or {})), stdin=subprocess.DEVNULL,
                     stdout=open(os.path.join(HERE, "edge-server.log"), "a"), stderr=subprocess.STDOUT)
    for _ in range(120):
        try:
            urllib.request.urlopen(B + "/functions", timeout=1)
            return
        except Exception:
            time.sleep(0.5)
    raise SystemExit("server did not start")


def call(fn, body=None, token=None):
    req = urllib.request.Request(B + "/function/" + fn, data=json.dumps(body or {}).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())["data"]["result"]
    except urllib.error.HTTPError as e:
        return {"http": e.code}


def user(name):
    name = f"{name}-{RUN}"
    cred = {"type": "password", "password": f"pw-{name}-1234567"}
    post = lambda p, b: json.loads(urllib.request.urlopen(urllib.request.Request(B + p, data=json.dumps(b).encode(), method="POST", headers={"Content-Type": "application/json"})).read())
    try:
        post("/user/register", {"identities": [{"type": "username", "value": name}], "credential": cred})
    except urllib.error.HTTPError:
        pass
    d = post("/user/login", {"identity": {"type": "username", "value": name}, "credential": cred})["data"]
    return d["token"], d["root_id"]


def fmt(ts):
    return datetime.datetime.fromtimestamp(ts, TZ).strftime("%Y-%m-%d %H:%M")


def offer(token, title, qty, start_ts, end_ts, price="6"):
    return call("save_offer", {"offer_id": "", "create_key": os.urandom(16).hex(), "title": f"{title} {RUN} (Demo)", "description": "", "price": price,
                               "regular_price": "10", "start_local": fmt(start_ts), "end_local": fmt(end_ts),
                               "quantity": str(qty), "eligibility": "Students with a valid university ID",
                               "terms": "One per student.", "dietary": "", "menu_item": ""}, token)


def remaining(oid, token=None):
    v = call("get_offer", {"offer_id": oid}, token)
    return (v or {}).get("remaining"), (v or {}).get("state")


start()
s1, _ = user("stu-a")
s2, _ = user("stu-b")
s3, _ = user("stu-c")
leaf, leaf_root = user("m-leaf")
noodle, noodle_root = user("m-noodle")
start({"MLOCAL_MERCHANT_OWNERS": json.dumps({"arbor-leaf-kitchen": leaf_root, "maize-noodle-lab": noodle_root})})
check("setup: both merchants recognized", call("current_session", {}, leaf).get("role") == "merchant" and call("current_session", {}, noodle).get("role") == "merchant")
now = time.time()

# The expiring offer is created first so its clock runs while the other cases execute.
end_minute = (int(now) // 60 + 2) * 60
short = offer(leaf, "Expiring", 2, now - 600, end_minute)
check("setup: short-lived offer created", short.get("ok"), short)
short_id = short.get("code")
held = call("claim_offer", {"offer_id": short_id}, s3)
check("expired: claim accepted while offer is live", held.get("ok"), held)
view = call("get_offer", {"offer_id": short_id}, s3)
check("expired: hold deadline is capped at the offer end", abs(view.get("my_expires_ts", 0) - end_minute) < 1, (view.get("my_expires_ts"), end_minute))

print("--- last available offer")
one = offer(noodle, "Last unit", 1, now - 600, now + 7200)
oid = one.get("code")
check("last: one unit shown", remaining(oid) == (1, "active"), remaining(oid))
a = call("claim_offer", {"offer_id": oid}, s1)
check("last: first student gets it", a.get("ok"), a)
check("last: shows sold out afterwards", remaining(oid) == (0, "sold out"), remaining(oid))
b = call("claim_offer", {"offer_id": oid}, s2)
check("last: second student is refused with a sold-out message", b.get("ok") is False and "sold out" in b.get("message", "").lower() and not b.get("qr_payload"), b)
check("last: holder retry keeps the same QR and unit", call("claim_offer", {"offer_id": oid}, s1).get("qr_payload") == a["qr_payload"] and remaining(oid)[0] == 0)
check("last: cancel returns the unit", call("cancel_claim", {"offer_id": oid}, s1).get("ok") and remaining(oid) == (1, "active"), remaining(oid))
check("last: cancelled QR can no longer be redeemed", call("redeem_claim", {"qr_payload": a["qr_payload"]}, noodle).get("ok") is False)
b2 = call("claim_offer", {"offer_id": oid}, s2)
check("last: released unit goes to the next student", b2.get("ok") and b2.get("qr_payload") != a["qr_payload"], b2)
race = offer(noodle, "Last unit race", 1, now - 600, now + 7200).get("code")
racers = [user(f"racer-{i}")[0] for i in range(12)]
with cf.ThreadPoolExecutor(12) as ex:
    outs = list(ex.map(lambda t: call("claim_offer", {"offer_id": race}, t), racers))
wins = [o for o in outs if isinstance(o, dict) and o.get("ok")]
check("last: 12 simultaneous students, exactly one winner", len(wins) == 1, f"{len(wins)} winners")
check("last: no loser received a QR", all(not o.get("qr_payload") for o in outs if not o.get("ok")))
check("last: merchant cannot drop quantity below held units", offer and call("save_offer", {"offer_id": race, "title": f"Last unit race {RUN} (Demo)", "description": "", "price": "6", "regular_price": "10", "start_local": fmt(now - 600), "end_local": fmt(now + 7200), "quantity": "0", "eligibility": "Students", "terms": "One.", "dietary": "", "menu_item": ""}, noodle).get("ok") is False)

print("--- wrong merchant")
w = offer(leaf, "Ownership", 3, now - 600, now + 7200, price="7")
wid = w.get("code")
wc = call("claim_offer", {"offer_id": wid}, s1)
check("wrong merchant: setup claim", wc.get("ok"), wc)
pv = call("resolve_claim", {"qr_payload": wc["qr_payload"]}, noodle)
check("wrong merchant: preview refused and reveals no terms", pv.get("ok") is False and not pv.get("title_snapshot") and not pv.get("price_cents"), pv)
rd = call("redeem_claim", {"qr_payload": wc["qr_payload"]}, noodle)
check("wrong merchant: redemption refused", rd.get("ok") is False, rd)
check("wrong merchant: claim is untouched", call("get_offer", {"offer_id": wid}, s1).get("my_status") == "claimed" and remaining(wid)[0] == 2)
check("wrong merchant: cannot pause the other restaurant's offer", call("set_offer_status", {"offer_id": wid, "status": "paused"}, noodle).get("ok") is False and remaining(wid)[1] == "active")
check("wrong merchant: claim absent from the other merchant's history", wc["claim_id"] not in [c.get("claim_id") for c in call("merchant_portal", {}, noodle).get("claims", [])])
check("wrong merchant: a student account cannot redeem", call("redeem_claim", {"qr_payload": wc["qr_payload"]}, s2).get("ok") is False)
check("wrong merchant: guest gets 401", call("redeem_claim", {"qr_payload": wc["qr_payload"]}).get("http") == 401)

print("--- double redemption")
first = call("redeem_claim", {"qr_payload": wc["qr_payload"]}, leaf)
check("double: owner redeems once at the claimed price", first.get("ok") and "$7.00" in first.get("message", ""), first)
second = call("redeem_claim", {"qr_payload": wc["qr_payload"]}, leaf)
check("double: second redemption refused", second.get("ok") is False and "already" in second.get("message", "").lower(), second)
check("double: preview reports already redeemed", call("resolve_claim", {"qr_payload": wc["qr_payload"]}, leaf).get("status") == "redeemed")
check("double: stock counted once", remaining(wid)[0] == 2, remaining(wid))
check("double: redeemed claim cannot be cancelled", call("cancel_claim", {"offer_id": wid}, s1).get("ok") is False)
check("double: same student cannot claim the offer again", call("claim_offer", {"offer_id": wid}, s1).get("ok") is False)
dc = call("claim_offer", {"offer_id": wid}, s2)
with cf.ThreadPoolExecutor(8) as ex:
    scans = list(ex.map(lambda _: call("redeem_claim", {"qr_payload": dc["qr_payload"]}, leaf), range(8)))
check("double: 8 simultaneous scans redeem exactly once", sum(1 for x in scans if x.get("ok")) == 1, [x.get("message") for x in scans])
check("double: stock after simultaneous scans is exact", remaining(wid)[0] == 1, remaining(wid))
hist = [c for c in call("merchant_portal", {}, leaf).get("claims", []) if c.get("claim_id") in (wc["claim_id"], dc["claim_id"])]
check("double: history shows each claim redeemed once", len(hist) == 2 and all(c.get("status") == "redeemed" for c in hist), hist)

print("--- expired claim")
wait = end_minute - time.time() + 3
if wait > 0:
    print(f"(waiting {wait:.0f}s for the short-lived offer to end)", flush=True)
    time.sleep(wait)
pv = call("resolve_claim", {"qr_payload": held["qr_payload"]}, leaf)
check("expired: preview reports expired", pv.get("ok") is False and pv.get("status") == "expired", pv)
ex_red = call("redeem_claim", {"qr_payload": held["qr_payload"]}, leaf)
check("expired: redemption refused", ex_red.get("ok") is False, ex_red)
check("expired: second attempt still refused", call("redeem_claim", {"qr_payload": held["qr_payload"]}, leaf).get("ok") is False)
v = call("get_offer", {"offer_id": short_id}, s3)
check("expired: student no longer shown a live claim", (v or {}).get("my_status") in ("expired", ""), (v or {}).get("my_status"))
check("expired: ended offer refuses new claims", call("claim_offer", {"offer_id": short_id}, s1).get("ok") is False)
check("expired: ended offer is hidden from discovery", short_id not in [o["id"] for o in call("list_offers")])
hist = [c for c in call("merchant_portal", {}, leaf).get("claims", []) if c.get("claim_id") == held["claim_id"]]
check("expired: merchant history shows it as expired, not redeemed", len(hist) == 1 and hist[0].get("status") == "expired", hist)

start({"MLOCAL_MERCHANT_OWNERS": json.dumps({"arbor-leaf-kitchen": leaf_root, "maize-noodle-lab": noodle_root})})
check("restart: redeemed stays redeemed", call("resolve_claim", {"qr_payload": wc["qr_payload"]}, leaf).get("status") == "redeemed")
check("restart: expired stays unredeemable", call("redeem_claim", {"qr_payload": held["qr_payload"]}, leaf).get("ok") is False)
check("restart: last-unit offer still sold out", remaining(race) == (0, "sold out"), remaining(race))
stop()
passed = sum(1 for _, ok in results if ok)
print(f"\n{passed}/{len(results)} edge-case checks passed (jac {JAC.rsplit('-', 1)[-1]})")
sys.exit(0 if passed == len(results) else 1)
