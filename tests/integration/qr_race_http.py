"""Real-HTTP acceptance for the QR backend on feat/01-runtime-release (+ fixes).

Starts the API-only server itself (Jac 0.37.23, default worker count unless
WORKERS is set), registers fresh accounts per run, provisions two merchants
through MLOCAL_MERCHANT_OWNERS, and exercises identity, private claims,
stable terms, QR preview/redeem, simultaneous claims and restart persistence.
"""
import json, sys, os, time, subprocess, urllib.request, concurrent.futures as cf

HERE = os.path.dirname(os.path.abspath(__file__))
JAC = os.environ.get("JAC", os.path.expanduser("~/jachacks/bin/jac-0.37.23"))
PORT = int(os.environ.get("PORT", "8131"))
B = f"http://127.0.0.1:{PORT}"
RUN = os.urandom(3).hex()
results = []
SERVE = ["run", "--serve", "--no-client", "--port", str(PORT), "main.jac"]
if os.environ.get("WORKERS"):
    SERVE[2:2] = ["--workers", os.environ["WORKERS"]]


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{str(detail)[:220]}]" if detail and not cond else ""))


def stop():
    subprocess.run(["pkill", "-f", f"no-client --port {PORT}"], capture_output=True)
    for _ in range(40):
        try:
            urllib.request.urlopen(B + "/functions", timeout=0.5)
            time.sleep(0.25)
        except Exception:
            return


def start(env_extra=None):
    stop()
    time.sleep(1.5)
    env = dict(os.environ, **(env_extra or {}))
    subprocess.Popen([JAC] + SERVE, cwd=HERE, env=env, stdin=subprocess.DEVNULL,
                     stdout=open(os.path.join(HERE, "server.log"), "a"), stderr=subprocess.STDOUT)
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


def hyphen(h):
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def new_offer(token, qty, price="5", title=None):
    d = call("offer_defaults")
    r = call("save_offer", {"offer_id": "", "create_key": os.urandom(16).hex(), "title": title or f"HTTP test {RUN} q{qty} (Demo)", "description": "", "price": price,
                            "regular_price": "9", "start_local": d[0], "end_local": d[1], "quantity": str(qty),
                            "eligibility": "Students with a valid university ID", "terms": "One per student.", "dietary": "vegan", "menu_item": ""}, token)
    return r


open(os.path.join(HERE, "server.log"), "w").close()
start()
s1, s1_root = user("student-one")
s2, _ = user("student-two")
m1, m1_root = user("merchant-noodle")
m2, m2_root = user("merchant-leaf")
check("guest sees a catalog", len(call("list_offers")) >= 3)
check("signed-in student sees the same catalog", len(call("list_offers", {}, s1)) == len(call("list_offers")))
g = call("current_session")
check("guest session is guest", g.get("role") == "guest" and not g.get("authenticated"))
for fn, body in [("claim_offer", {"offer_id": "x"}), ("redeem_claim", {"qr_payload": "x"}), ("resolve_claim", {"qr_payload": "x"}), ("merchant_portal", {})]:
    check(f"guest {fn} is 401", call(fn, body).get("http") == 401)
check("actor id equals login root id", call("current_session", {}, s1).get("actor_id") == s1_root)
check("unprovisioned merchant account is a student", call("current_session", {}, m1).get("role") == "student")

# Provision exactly the way scripts/provision-demo.py writes the map (hyphenated UUIDs).
owners = json.dumps({"maize-noodle-lab": hyphen(m1_root), "arbor-leaf-kitchen": hyphen(m2_root)})
start({"MLOCAL_MERCHANT_OWNERS": owners})
check("hyphenated owner map: merchant recognized", call("current_session", {}, m1).get("role") == "merchant", call("current_session", {}, m1))
check("merchant portal shows own restaurant", call("merchant_portal", {}, m2).get("name", "").startswith("Arbor Leaf"), call("merchant_portal", {}, m2))
check("merchant cannot claim", call("claim_offer", {"offer_id": call("list_offers")[0]["id"]}, m1).get("ok") is False)

made = new_offer(m2, 8, price="8")
check("owner creates an offer", made.get("ok"), made)
oid = made.get("code")
v0 = call("get_offer", {"offer_id": oid})
check("new offer is claimable (qr_ready)", v0 and v0.get("remaining") == 8 and v0.get("state") == "active", v0)
c1 = call("claim_offer", {"offer_id": oid}, s1)
check("student claims and gets a v1 QR (53 chars)", c1.get("ok") and c1.get("qr_payload", "").startswith("mlocal:v1:") and len(c1["qr_payload"]) == 53, c1)
retry = call("claim_offer", {"offer_id": oid}, s1)
check("retry returns same claim and QR", retry.get("ok") and retry.get("qr_payload") == c1["qr_payload"] and retry.get("claim_id") == c1["claim_id"], retry)
check("retry used no extra unit", call("get_offer", {"offer_id": oid}).get("remaining") == 7)
other = call("get_offer", {"offer_id": oid}, s2)
check("other student sees no credential", other.get("my_qr_payload") == "" and other.get("my_claim_id") == "")
check("guest sees no credential", call("get_offer", {"offer_id": oid}).get("my_qr_payload") == "")
mine = call("get_offer", {"offer_id": oid}, s1)
check("claimant sees own QR and locked price", mine.get("my_qr_payload") == c1["qr_payload"] and mine.get("my_price_cents") == 800, mine)
check("wrong merchant cannot resolve", call("resolve_claim", {"qr_payload": c1["qr_payload"]}, m1).get("ok") is False)
check("wrong merchant cannot redeem", call("redeem_claim", {"qr_payload": c1["qr_payload"]}, m1).get("ok") is False)
check("student cannot redeem", call("redeem_claim", {"qr_payload": c1["qr_payload"]}, s2).get("ok") is False)
check("URL payload rejected", call("resolve_claim", {"qr_payload": "https://example.invalid/x"}, m2).get("ok") is False)
d = call("offer_defaults")
up = call("save_offer", {"offer_id": oid, "title": f"HTTP test {RUN} q8 (Demo)", "description": "", "price": "12", "regular_price": "20",
                         "start_local": d[0], "end_local": d[1], "quantity": "8", "eligibility": "Anyone", "terms": "Changed.", "dietary": "", "menu_item": ""}, m2)
check("owner edits price after the claim", up.get("ok"), up)
pv = call("resolve_claim", {"qr_payload": c1["qr_payload"]}, m2)
check("owner preview shows locked $8 and does not redeem", pv.get("ok") and pv.get("price_cents") == 800 and pv.get("status") == "claimed", pv)
red = call("redeem_claim", {"qr_payload": c1["qr_payload"]}, m2)
check("redemption charges the claimed $8.00", red.get("ok") and "$8.00" in red.get("message", ""), red)
check("second redemption rejected", call("redeem_claim", {"qr_payload": c1["qr_payload"]}, m2).get("ok") is False)
check("merchant history hides actor ids", all(not k.startswith("student") and k != "actor_id" for c in call("merchant_portal", {}, m2)["claims"] for k in c.keys()))

# Double scan: 5 simultaneous redeems of one QR.
c2 = call("claim_offer", {"offer_id": oid}, s2)
with cf.ThreadPoolExecutor(5) as ex:
    scans = list(ex.map(lambda _: call("redeem_claim", {"qr_payload": c2["qr_payload"]}, m2), range(5)))
check("5 simultaneous scans redeem exactly once", sum(1 for x in scans if isinstance(x, dict) and x.get("ok")) == 1, [x.get("message") for x in scans])

# Last unit race.
race = new_offer(m1, 1)["code"]
racers = [user(f"racer-{i}")[0] for i in range(20)]
with cf.ThreadPoolExecutor(20) as ex:
    outs = list(ex.map(lambda t: call("claim_offer", {"offer_id": race}, t), racers))
wins = [o for o in outs if isinstance(o, dict) and o.get("ok")]
check("20 simultaneous students: exactly one gets the last unit", len(wins) == 1, f"{len(wins)} winners")
v = call("get_offer", {"offer_id": race})
check("last unit shows sold out", v and v.get("remaining") == 0 and v.get("state") == "sold out", v and v.get("state"))
five = new_offer(m1, 5)["code"]
with cf.ThreadPoolExecutor(10) as ex:
    outs = list(ex.map(lambda _: call("claim_offer", {"offer_id": five}, s2), range(10)))
codes = {o.get("qr_payload") for o in outs if isinstance(o, dict)}
check("10 simultaneous retries by one student use one unit", len(codes) == 1 and call("get_offer", {"offer_id": five}).get("remaining") == 4, (len(codes), call("get_offer", {"offer_id": five}).get("remaining")))
cancel = call("cancel_claim", {"offer_id": five}, s2)
check("cancel releases the unit", cancel.get("ok") and call("get_offer", {"offer_id": five}).get("remaining") == 5, cancel)

start({"MLOCAL_MERCHANT_OWNERS": owners})
check("after restart: redemption persisted", call("get_offer", {"offer_id": oid}, s1).get("my_status") == "redeemed")
check("after restart: sold-out persisted", call("get_offer", {"offer_id": race}).get("remaining") == 0)
check("after restart: merchant still merchant", call("current_session", {}, m1).get("role") == "merchant")
stop()
passed = sum(1 for _, ok in results if ok)
print(f"\n{passed}/{len(results)} HTTP checks passed (jac {JAC.rsplit('-', 1)[-1]}, workers {os.environ.get('WORKERS', 'default')})")
sys.exit(0 if passed == len(results) else 1)
