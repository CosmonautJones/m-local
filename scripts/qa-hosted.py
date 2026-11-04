#!/usr/bin/env python3
"""QA accounts and real-world usage simulation for a hosted M-Local test copy.

Only for a test deployment that shows fictional sample offers (see
docs/JACHAMMER-TESTING.md). It never touches email: QA students are allowed to
claim through MLOCAL_DEMO_STUDENTS and QA merchants own the sample restaurants
through MLOCAL_MERCHANT_OWNERS, both set as host environment variables.

    python3 scripts/qa-hosted.py provision --url https://<preview host>
    # set the two printed variables on the host and redeploy, then:
    python3 scripts/qa-hosted.py run --url https://<preview host> --minutes 10

Credentials are written to a private file outside the repository
(default ~/.mlocal-qa/accounts.json, mode 0600) and never printed.
"""
import argparse
import concurrent.futures
import json
import os
import random
import secrets
import statistics
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from uuid import UUID

SAMPLE_RESTAURANTS = ["arbor-leaf-kitchen", "maize-noodle-lab", "diag-dough-co"]
DEFAULT_STATE = Path.home() / ".mlocal-qa" / "accounts.json"
MAX_ACTIVE_HOLDS = 2


class QAError(Exception):
    pass


def checked_url(value: str, allow_any: bool) -> str:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost") and parsed.path in ("", "/"):
        return f"http://{parsed.hostname}:{parsed.port or 80}"  # local rehearsal
    if parsed.scheme != "https" or not parsed.hostname or parsed.path not in ("", "/") or parsed.query:
        raise QAError("Pass the https origin of the test deployment, e.g. https://m-local-preview-xxxx.jachammer.app")
    if "preview" not in parsed.hostname and not allow_any:
        raise QAError("Refusing a non-preview host. This tool writes QA data; pass --allow-host only for a dedicated test deployment.")
    return f"https://{parsed.hostname}"


class Client:
    """Minimal HTTP client for Jac's RPC surface; records latency per call."""

    def __init__(self, base: str, stats: "Stats", token: str = ""):
        self.base, self.stats, self.token = base, stats, token

    def _post(self, path: str, body: dict, timeout: float = 60) -> tuple[int, dict]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(self.base + path, json.dumps(body).encode(), headers, method="POST")
        started = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as error:
            status, raw = error.code, error.read()
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            self.stats.record(path, time.monotonic() - started, 0)
            raise QAError(f"{path}: network error {error}") from None
        self.stats.record(path, time.monotonic() - started, status)
        try:
            return status, json.loads(raw or b"{}")
        except ValueError:
            return status, {"raw": raw[:200].decode("utf-8", "replace")}

    def call(self, name: str, **kwargs) -> dict:
        status, payload = self._post("/function/" + name, kwargs)
        if status != 200 or not payload.get("ok"):
            raise QAError(f"{name}: HTTP {status} {str(payload)[:200]}")
        return payload.get("data", {}).get("result") or {}

    def raw(self, name: str, **kwargs) -> tuple[int, dict]:
        return self._post("/function/" + name, kwargs)

    def register_and_login(self, email: str, password: str) -> dict:
        status, payload = self._post("/user/register", {
            "identities": [{"type": "email", "value": email}],
            "credential": {"type": "password", "password": password}})
        if status not in (200, 201) or not payload.get("ok"):
            raise QAError(f"register: HTTP {status}")
        return self.login(email, password)

    def login(self, email: str, password: str) -> dict:
        status, payload = self._post("/user/login", {
            "identity": {"type": "email", "value": email},
            "credential": {"type": "password", "password": password}})
        if status not in (200, 201) or not payload.get("ok"):
            raise QAError(f"login: HTTP {status}")
        data = payload["data"]
        self.token = data["token"]
        return data


class Stats:
    def __init__(self):
        self.lock = threading.Lock()
        self.calls: dict[str, list[float]] = {}
        self.errors: dict[str, int] = {}

    def record(self, path: str, seconds: float, status: int):
        name = path.rsplit("/", 1)[-1]
        with self.lock:
            self.calls.setdefault(name, []).append(seconds)
            if status == 0 or status >= 500:
                self.errors[name] = self.errors.get(name, 0) + 1

    def summary(self) -> dict:
        out = {}
        for name, values in sorted(self.calls.items()):
            ordered = sorted(values)
            out[name] = {
                "calls": len(values),
                "p50_ms": round(statistics.median(ordered) * 1000),
                "p95_ms": round(ordered[max(0, int(len(ordered) * 0.95) - 1)] * 1000),
                "max_ms": round(ordered[-1] * 1000),
                "server_or_network_errors": self.errors.get(name, 0),
            }
        return out


# ------------------------------------------------------------------ provision

def provision(args) -> int:
    base = checked_url(args.url, args.allow_host)
    state_path: Path = args.state
    if state_path.exists():
        raise QAError(f"{state_path} already exists; reuse it (this command never overwrites credentials).")
    stats = Stats()
    suffix = secrets.token_hex(4)
    accounts = {"url": base, "students": [], "merchants": []}
    for i in range(args.students):
        email = f"mlocal-qa-student{i + 1}-{suffix}@example.test"
        password = secrets.token_urlsafe(24)
        data = Client(base, stats).register_and_login(email, password)
        accounts["students"].append({"email": email, "password": password, "root_id": UUID(data["root_id"]).hex})
    for slug in SAMPLE_RESTAURANTS[:args.merchants]:
        email = f"mlocal-qa-{slug}-{suffix}@example.test"
        password = secrets.token_urlsafe(24)
        data = Client(base, stats).register_and_login(email, password)
        accounts["merchants"].append({"email": email, "password": password, "root_id": UUID(data["root_id"]).hex, "slug": slug})
    if args.merge_into:
        base_accounts = json.loads(args.merge_into.read_text())
        if base_accounts["url"] != base:
            raise QAError("--merge-into was created for a different host.")
        if accounts["merchants"]:
            raise QAError("--merge-into adds students only; pass --merchants 0.")
        accounts = {"url": base, "students": base_accounts["students"] + accounts["students"],
                    "merchants": base_accounts["merchants"]}
    state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(state_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(accounts, stream, indent=2)
    students = json.dumps([a["root_id"] for a in accounts["students"]], separators=(",", ":"))
    owners = json.dumps({a["slug"]: a["root_id"] for a in accounts["merchants"]}, separators=(",", ":"))
    print(f"Created {len(accounts['students'])} QA students and {len(accounts['merchants'])} QA merchants; credentials in {state_path}.")
    print("Set on the host, then redeploy:")
    print(f"MLOCAL_DEMO_STUDENTS={students}")
    print(f"MLOCAL_MERCHANT_OWNERS={owners}")
    return 0


# ------------------------------------------------------------------ scenarios

class Run:
    def __init__(self, base: str, accounts: dict):
        self.base = base
        self.stats = Stats()
        self.results: list[dict] = []
        self.findings: list[str] = []
        self.guest = Client(base, self.stats)
        self.students = [self._login(a) for a in accounts["students"]]
        self.merchants = {a["slug"]: self._login(a) for a in accounts["merchants"]}

    def _login(self, account: dict) -> Client:
        client = Client(self.base, self.stats)
        client.login(account["email"], account["password"])
        return client

    def check(self, scenario: str, name: str, ok: bool, detail: str = ""):
        self.results.append({"scenario": scenario, "check": name, "ok": bool(ok), "detail": detail[:300]})
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {name}" + (f" -- {detail[:160]}" if detail and not ok else ""), flush=True)

    def scenario(self, title: str, fn):
        print(f"\n== {title}", flush=True)
        try:
            fn(title)
        except QAError as error:
            self.check(title, "scenario completed without an unexpected error", False, str(error))

    # helpers
    def claimable_offers(self, slug: str | None = None, viewer: "Client | None" = None) -> list[dict]:
        """Open offers; with a viewer, only ones that account has never claimed."""
        offers = (viewer or self.guest).call("list_offers")
        out = []
        for o in offers if isinstance(offers, list) else []:
            if o.get("state") != "active" or o.get("remaining", 0) < 1:
                continue
            if viewer is not None and (o.get("my_status") or o.get("my_claim_id")):
                continue
            if slug is not None and o.get("restaurant") != self.restaurant_name(slug):
                continue
            out.append(o)
        return out

    _names: dict[str, str] = {}

    def restaurant_name(self, slug: str) -> str:
        if slug not in self._names:
            self._names[slug] = self.merchants[slug].call("merchant_portal").get("name", "").replace(" (Demo)", "")
        return self._names[slug]

    def clear_holds(self, student: Client):
        for o in student.call("list_offers"):
            if o.get("my_status") == "claimed":
                student.call("cancel_claim", offer_id=o["id"])

    def publish(self, slug: str, title: str, quantity: int, create_key: str | None = None) -> str:
        merchant = self.merchants[slug]
        start, end = self.guest.call("offer_defaults")
        key = create_key or secrets.token_urlsafe(24)
        result = merchant.call("save_offer", offer_id="", title=title, description="QA test offer.",
            price="5", regular_price="9", start_local=start, end_local=end, quantity=str(quantity),
            eligibility="U-M students", terms="QA test.", dietary="", menu_item="", create_key=key)
        if not result.get("ok"):
            raise QAError("publish failed: " + result.get("message", ""))
        return result.get("code") or ""

    def offer_by_title(self, title: str) -> dict | None:
        for o in self.guest.call("list_offers"):
            if o.get("title") == title:
                return o
        return None

    # scenarios
    def s_roles(self, s):
        guest = self.guest.call("current_session")
        self.check(s, "guest session is unauthenticated", not guest.get("authenticated"))
        for i, student in enumerate(self.students):
            v = student.call("current_session")
            self.check(s, f"QA student {i + 1} is a student", v.get("role") == "student", json.dumps(v)[:200])
        for slug, merchant in self.merchants.items():
            v = merchant.call("current_session")
            self.check(s, f"QA merchant owns {slug}", v.get("role") == "merchant" and bool(v.get("restaurant_id")), json.dumps(v)[:200])

    def s_browse(self, s):
        feed = self.guest.call("home_feed")
        items = feed.get("items", [])
        self.check(s, "guest feed lists offers", len(items) > 0, f"{len(items)} items")
        offers = self.guest.call("list_offers")
        cheap = self.guest.call("list_offers", max_price="5")
        self.check(s, "price filter only returns offers at or under $5",
                   all(o["price"] <= 5 for o in cheap if o.get("my_status") != "claimed"), f"{len(cheap)} of {len(offers)}")
        now = self.guest.call("list_offers", window="now")
        self.check(s, "'now' filter only returns offers that have started", all(o.get("state") != "scheduled" for o in now))
        diets = sorted({d for o in offers for d in o.get("dietary", [])})
        if diets:
            tag = diets[0]
            tagged = self.guest.call("list_offers", diets=tag)
            self.check(s, f"diet filter '{tag}' only returns tagged offers", all(tag in o.get("dietary", []) for o in tagged), f"{len(tagged)}")
        if offers:
            detail = self.guest.call("get_offer", offer_id=offers[0]["id"])
            self.check(s, "offer detail opens for a guest", detail.get("id") == offers[0]["id"])
            self.check(s, "guest sees no QR credential", not any(o.get("my_qr_payload") for o in offers))
            nearby = self.guest.call("nearby_after", offer_id=offers[0]["id"])
            self.check(s, "'what's nearby' answers", isinstance(nearby, dict))
        biz = self.guest.call("get_business_profile", slug=SAMPLE_RESTAURANTS[0])
        self.check(s, "sample business profile opens", bool(biz), json.dumps(biz)[:120])

    def s_claim_redeem(self, s):
        student = self.students[0]
        self.clear_holds(student)
        slug = SAMPLE_RESTAURANTS[0]
        offers = self.claimable_offers(slug, student)
        if not offers:
            self.publish(slug, f"QA claim test {secrets.token_hex(3)}", 5)
            offers = self.claimable_offers(slug, student)
        offer = offers[0]
        before = offer["remaining"]
        first = student.call("claim_offer", offer_id=offer["id"])
        self.check(s, "student claims an offer and gets a QR", first.get("ok") and bool(first.get("qr_payload")), first.get("message", ""))
        again = student.call("claim_offer", offer_id=offer["id"])
        self.check(s, "claiming again returns the same QR (no second hold)", again.get("qr_payload") == first.get("qr_payload"))
        mine = student.call("get_offer", offer_id=offer["id"])
        self.check(s, "reloaded offer shows the saved claim", mine.get("my_status") == "claimed" and mine.get("my_qr_payload") == first.get("qr_payload"))
        after = self.guest.call("get_offer", offer_id=offer["id"])
        self.check(s, "remaining count drops by one", after.get("remaining") == before - 1, f"{before} -> {after.get('remaining')}")
        qr = first["qr_payload"]
        other = next((m for k, m in self.merchants.items() if k != slug), None)
        if other:
            wrong = other.call("resolve_claim", qr_payload=qr)
            self.check(s, "another restaurant cannot preview this QR", not wrong.get("ok"), wrong.get("message", ""))
            wrong_redeem = other.call("redeem_claim", qr_payload=qr)
            self.check(s, "another restaurant cannot redeem this QR", not wrong_redeem.get("ok"), wrong_redeem.get("message", ""))
        not_merchant = self.students[1].call("redeem_claim", qr_payload=qr)
        self.check(s, "a student cannot redeem a QR", not not_merchant.get("ok"))
        merchant = self.merchants[slug]
        preview = merchant.call("resolve_claim", qr_payload=qr)
        self.check(s, "owning merchant previews the claim with saved terms",
                   preview.get("ok") and preview.get("title_snapshot") == offer["title"], preview.get("message", ""))
        redeemed = merchant.call("redeem_claim", qr_payload=qr)
        self.check(s, "merchant confirms one-time redemption", redeemed.get("ok"), redeemed.get("message", ""))
        twice = merchant.call("redeem_claim", qr_payload=qr)
        self.check(s, "second scan of the same QR is refused", not twice.get("ok"), twice.get("message", ""))
        view = student.call("get_offer", offer_id=offer["id"])
        self.check(s, "student sees the claim as redeemed", (view or {}).get("my_status") in ("redeemed", ""), str((view or {}).get("my_status")))
        reclaim = student.call("claim_offer", offer_id=offer["id"])
        self.check(s, "student cannot claim the same offer again after redeeming", not reclaim.get("ok"), reclaim.get("message", ""))
        forged = merchant.call("redeem_claim", qr_payload="mlocal:v1:" + secrets.token_urlsafe(32))
        self.check(s, "a forged QR is refused", not forged.get("ok"))

    def s_hold_limit(self, s):
        student = self.students[1]
        self.clear_holds(student)
        offers = self.claimable_offers(viewer=student)
        for _ in range(MAX_ACTIVE_HOLDS + 1 - len(offers)):
            self.publish(SAMPLE_RESTAURANTS[0], f"QA hold test {secrets.token_hex(3)}", 5)
        offers = self.claimable_offers(viewer=student)
        if len(offers) < MAX_ACTIVE_HOLDS + 1:
            self.check(s, "enough open offers to test the limit", False, f"{len(offers)} available")
            return
        held = []
        for o in offers[:MAX_ACTIVE_HOLDS]:
            r = student.call("claim_offer", offer_id=o["id"])
            held.append(o)
            self.check(s, f"hold {len(held)} accepted", r.get("ok"), r.get("message", ""))
        extra = student.call("claim_offer", offer_id=offers[MAX_ACTIVE_HOLDS]["id"])
        self.check(s, f"hold {MAX_ACTIVE_HOLDS + 1} is refused by the limit", not extra.get("ok"), extra.get("message", ""))
        cancel = student.call("cancel_claim", offer_id=held[0]["id"])
        self.check(s, "student cancels a hold", cancel.get("ok"), cancel.get("message", ""))
        retry = student.call("claim_offer", offer_id=offers[MAX_ACTIVE_HOLDS]["id"])
        self.check(s, "a freed slot can be used", retry.get("ok"), retry.get("message", ""))
        self.clear_holds(student)

    def s_last_unit_race(self, s):
        slug = SAMPLE_RESTAURANTS[1]
        title = f"QA last unit {secrets.token_hex(3)}"
        key = secrets.token_urlsafe(24)
        self.publish(slug, title, 1, create_key=key)
        offer = self.offer_by_title(title)
        self.check(s, "merchant publishes a one-unit offer", offer is not None)
        if offer is None:
            return
        try:
            self.publish(slug, title, 1, create_key=key)
        except QAError:
            pass
        dupes = [o for o in self.guest.call("list_offers") if o.get("title") == title]
        self.check(s, "retrying the same publish does not create a duplicate", len(dupes) == 1, f"{len(dupes)} copies")
        racers = self.students[2:2 + 6] or self.students
        for r in racers:
            self.clear_holds(r)
        with concurrent.futures.ThreadPoolExecutor(len(racers)) as pool:
            outcomes = list(pool.map(lambda c: c.call("claim_offer", offer_id=offer["id"]), racers))
        winners = [o for o in outcomes if o.get("ok")]
        self.check(s, f"{len(racers)} students race for the last unit: exactly one wins", len(winners) == 1, f"{len(winners)} winners")
        self.check(s, "losers are told it is sold out", all("sold out" in o.get("message", "").lower() for o in outcomes if not o.get("ok")),
                   "; ".join(sorted({o.get('message', '') for o in outcomes if not o.get('ok')})))
        final = self.guest.call("get_offer", offer_id=offer["id"])
        self.check(s, "offer shows sold out", (final or {}).get("state") == "sold out" or (final or {}).get("remaining") == 0, str((final or {}).get("state")))
        if winners:
            r = self.merchants[slug].call("redeem_claim", qr_payload=winners[0]["qr_payload"])
            self.check(s, "winner's QR redeems", r.get("ok"), r.get("message", ""))

    def s_pause(self, s):
        slug = SAMPLE_RESTAURANTS[2] if len(SAMPLE_RESTAURANTS) > 2 and SAMPLE_RESTAURANTS[2] in self.merchants else SAMPLE_RESTAURANTS[0]
        title = f"QA pause {secrets.token_hex(3)}"
        self.publish(slug, title, 3)
        offer = self.offer_by_title(title)
        if offer is None:
            self.check(s, "published offer is listed", False)
            return
        merchant = self.merchants[slug]
        paused = merchant.call("set_offer_status", offer_id=offer["id"], status="paused")
        self.check(s, "merchant pauses an offer", paused.get("ok"), paused.get("message", ""))
        self.check(s, "paused offer is hidden from guests", self.offer_by_title(title) is None)
        student = self.students[0]
        self.clear_holds(student)
        claim = student.call("claim_offer", offer_id=offer["id"])
        self.check(s, "paused offer cannot be claimed", not claim.get("ok"), claim.get("message", ""))
        resumed = merchant.call("set_offer_status", offer_id=offer["id"], status="active")
        self.check(s, "merchant resumes it", resumed.get("ok") and self.offer_by_title(title) is not None)
        other = self.merchants[next(k for k in self.merchants if k != slug)] if len(self.merchants) > 1 else None
        if other:
            hijack = other.call("set_offer_status", offer_id=offer["id"], status="paused")
            self.check(s, "another merchant cannot pause it", not hijack.get("ok"), hijack.get("message", ""))

    def s_access(self, s):
        status, _ = self.guest.raw("claim_offer", offer_id="x")
        self.check(s, "anonymous claim is rejected", status in (401, 403), f"HTTP {status}")
        status, _ = self.guest.raw("merchant_portal")
        self.check(s, "anonymous merchant portal is rejected", status in (401, 403), f"HTTP {status}")
        portal = self.students[0].call("merchant_portal")
        self.check(s, "a student has no merchant portal", not portal.get("offers") and not portal.get("name"))
        publish = self.students[0].raw("save_offer", offer_id="", title="x", description="", price="1", regular_price="2",
            start_local="", end_local="", quantity="1", eligibility="", terms="", dietary="", menu_item="", create_key=secrets.token_urlsafe(24))
        self.check(s, "a student cannot publish", publish[0] != 200 or not (publish[1].get("data", {}).get("result") or {}).get("ok"))
        fresh = Client(self.base, self.stats)
        email = f"mlocal-qa-unlisted-{secrets.token_hex(4)}@example.test"
        password = secrets.token_urlsafe(24)
        status, payload = fresh._post("/user/register", {
            "identities": [{"type": "email", "value": email}],
            "credential": {"type": "password", "password": password}})
        code = (payload.get("error") or {}).get("code", "") if isinstance(payload, dict) else ""
        if status in (400, 429) and code in ("CHALLENGE_REQUIRED", "RATE_LIMITED"):
            # Deploy staging throttles native registration (docs/JACHAMMER-TESTING.md).
            self.check(s, "native registration is throttled", True, code)
            return
        if status not in (200, 201) or not payload.get("ok"):
            raise QAError(f"register: HTTP {status} {code}")
        fresh.login(email, password)
        role = fresh.call("current_session").get("role")
        self.check(s, "a native account outside the QA list is unverified", role == "unverified", str(role))
        offers = self.claimable_offers()
        if offers:
            r = fresh.call("claim_offer", offer_id=offers[0]["id"])
            self.check(s, "an unverified account cannot claim", not r.get("ok"), r.get("message", ""))

    def s_tastes(self, s):
        student = self.students[3 % len(self.students)]
        choices = self.guest.call("taste_choices")
        cats = [c.get("key") for c in choices.get("all_categories", [])][:2] if isinstance(choices, dict) else []
        saved = student.call("save_taste", categories=",".join(c for c in cats if c), diets="", price_range="$")
        self.check(s, "student saves taste preferences", isinstance(saved, dict))
        slug = SAMPLE_RESTAURANTS[0]
        def is_favorite() -> bool:
            return any(f.get("slug") == slug for f in student.call("home_feed").get("favorites", []))
        was = is_favorite()
        student.call("toggle_favorite", slug=slug)
        self.check(s, "toggling a favorite changes the student's feed", is_favorite() != was)
        student.call("toggle_favorite", slug=slug)
        self.check(s, "toggling back restores it", is_favorite() == was)
        feed = student.call("home_feed")
        self.check(s, "feed is personalized for a signed-in student", feed.get("signed_in") is True)

    # realistic traffic
    def soak(self, minutes: float, seed: int, users: int = 0):
        active = self.students[:users] if users > 0 else self.students
        print(f"\n== Mixed real-world traffic for {minutes:g} minutes, {len(active)} students", flush=True)
        rng = random.Random(seed)
        stop = time.monotonic() + minutes * 60
        counters = {"browse": 0, "detail": 0, "favorite": 0, "claim_ok": 0, "claim_refused": 0, "cancel": 0,
                    "redeem_ok": 0, "redeem_refused": 0, "errors": 0}
        pending: list[tuple[str, str]] = []  # (restaurant name, qr)
        lock = threading.Lock()
        names = {self.restaurant_name(slug): slug for slug in self.merchants}

        def student_loop(student: Client, local_seed: int):
            r = random.Random(local_seed)
            while time.monotonic() < stop:
                try:
                    roll = r.random()
                    # The feed screen calls home_feed (and refreshes it every 30 s while open).
                    feed = student.call("home_feed", price_range=r.choice(["", "", "$", "$$"]),
                                        window=r.choice(["any", "now", "today"]), diets="")
                    offers = [item["offer"] for item in feed.get("items", []) if isinstance(item.get("offer"), dict)]
                    with lock: counters["browse"] += 1
                    open_offers = [o for o in offers if o.get("state") == "active"]
                    if open_offers and roll < 0.6:
                        o = r.choice(open_offers)
                        student.call("get_offer", offer_id=o["id"])
                        with lock: counters["detail"] += 1
                        if r.random() < 0.15:
                            student.call("toggle_favorite", offer_id=o["id"])
                            with lock: counters["favorite"] += 1
                        if r.random() < 0.35:
                            res = student.call("claim_offer", offer_id=o["id"])
                            with lock:
                                if res.get("ok"):
                                    counters["claim_ok"] += 1
                                    # Only QA-merchant restaurants can scan; other holds expire or are cancelled.
                                    if o.get("restaurant") in names and r.random() < 0.8:
                                        pending.append((o["restaurant"], res["qr_payload"]))
                                else:
                                    counters["claim_refused"] += 1
                    held = [o for o in offers if o.get("my_status") == "claimed"]
                    if held and r.random() < 0.1:
                        student.call("cancel_claim", offer_id=r.choice(held)["id"])
                        with lock: counters["cancel"] += 1
                except QAError as error:
                    with lock:
                        counters["errors"] += 1
                    print(f"  soak error: {error}", flush=True)
                time.sleep(r.uniform(2, 8))

        def merchant_loop():
            while time.monotonic() < stop + 15:
                with lock:
                    job = pending.pop(0) if pending else None
                if job is None:
                    time.sleep(2)
                    continue
                name, qr = job
                merchant = self.merchants[names[name]]
                try:
                    time.sleep(rng.uniform(1, 4))
                    merchant.call("resolve_claim", qr_payload=qr)
                    res = merchant.call("redeem_claim", qr_payload=qr)
                    with lock:
                        counters["redeem_ok" if res.get("ok") else "redeem_refused"] += 1
                except QAError as error:
                    with lock:
                        counters["errors"] += 1
                    print(f"  soak error: {error}", flush=True)

        with concurrent.futures.ThreadPoolExecutor(len(active) + 1) as pool:
            futures = [pool.submit(student_loop, s, seed + i) for i, s in enumerate(active)]
            futures.append(pool.submit(merchant_loop))
            for f in futures:
                f.result()
        print("  " + json.dumps(counters), flush=True)
        self.results.append({"scenario": "soak", "check": "mixed traffic counters", "ok": counters["errors"] == 0, "detail": json.dumps(counters)})
        for s in self.students:
            self.clear_holds(s)
        return counters


def run(args) -> int:
    accounts = json.loads(args.state.read_text())
    base = checked_url(args.url or accounts["url"], args.allow_host)
    if base != accounts["url"]:
        raise QAError("The QA accounts were created on a different host.")
    qa = Run(base, accounts)
    started = time.time()
    for title, fn in [] if args.skip_scenarios else [
        ("Roles: QA accounts resolve to students and merchants", qa.s_roles),
        ("Guest browsing and filters", qa.s_browse),
        ("Claim, merchant preview and one-time redemption", qa.s_claim_redeem),
        ("Two active holds per student", qa.s_hold_limit),
        ("Last-unit race and duplicate publish", qa.s_last_unit_race),
        ("Merchant pause and resume", qa.s_pause),
        ("Access control", qa.s_access),
        ("Tastes and favorites", qa.s_tastes),
    ]:
        qa.scenario(title, fn)
    counters = qa.soak(args.minutes, args.seed, args.users) if args.minutes > 0 else {}
    failures = [r for r in qa.results if not r["ok"]]
    report = {"url": base, "started": started, "finished": time.time(), "checks": len(qa.results),
              "failures": failures, "results": qa.results, "soak": counters, "latency": qa.stats.summary()}
    out = args.report or (args.state.parent / f"qa-report-{int(started)}.json")
    out.write_text(json.dumps(report, indent=2))
    print(f"\n{len(qa.results) - len(failures)}/{len(qa.results)} checks passed. Report: {out}")
    print(json.dumps(qa.stats.summary(), indent=1))
    return 1 if failures else 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("provision", help="create QA accounts on the test host")
    p.add_argument("--url", required=True)
    p.add_argument("--students", type=int, default=8)
    p.add_argument("--merchants", type=int, default=3, choices=range(0, len(SAMPLE_RESTAURANTS) + 1))
    p.add_argument("--merge-into", type=Path, help="existing accounts file to extend with the new students")
    p.add_argument("--state", type=Path, default=DEFAULT_STATE)
    p.add_argument("--allow-host", action="store_true")
    r = sub.add_parser("run", help="run QA scenarios and mixed traffic")
    r.add_argument("--url")
    r.add_argument("--minutes", type=float, default=5)
    r.add_argument("--seed", type=int, default=7)
    r.add_argument("--users", type=int, default=0, help="students in the traffic phase (default: all)")
    r.add_argument("--skip-scenarios", action="store_true", help="only run the traffic phase")
    r.add_argument("--state", type=Path, default=DEFAULT_STATE)
    r.add_argument("--report", type=Path)
    r.add_argument("--allow-host", action="store_true")
    args = parser.parse_args(argv)
    try:
        return provision(args) if args.command == "provision" else run(args)
    except QAError as error:
        print(f"qa-hosted: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
