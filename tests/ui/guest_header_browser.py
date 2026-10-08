"""Compiled M-Local header proof with isolated synthetic RPCs; no live server.

Playwright 1.56.x must already be installed, with the selected browser available.
Observation mode retains failures and screenshots and never claims a pass.
The caller supplies the source commit and independently binds this copied build
to its Git tree. This script binds the actual source/build/asset bytes instead.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import mimetypes
from pathlib import Path
import platform
import re
import sys
from urllib.parse import unquote, urlsplit


ORIGIN = "http://header.test"
WIDTHS = (320, 390, 430, 1280)
THEMES = ("light", "dark")
GUEST_ACTIONS = ("theme-toggle", "Sign in", "Choose account type")
SOURCE_INPUTS = ("main.jac", "theme.jac", "jac.toml", ".jac-version")

# Read-only DTOs copied from tests/ui/browser/harness.mjs; no private claims.
OFFER = {
    "id": "fixture-offer", "title": "Current bowl",
    "description": "Fictional UI test meal", "restaurant": "Fixture Kitchen",
    "price": 9, "regular_price": 12, "address": "Fictional test address",
    "neighborhood": "Test area", "state": "active", "remaining": 4,
    "quantity": 5, "eligibility": "Student ID", "terms": "Current offer terms",
    "menu_item": "", "dietary": [], "reasons": [], "is_demo": False,
    "time_label": "Until tonight", "my_status": "", "my_claim_id": "",
    "my_qr_payload": "", "my_title": "", "my_price_cents": 0,
    "my_terms": "", "my_eligibility": "", "my_expires": "",
    "my_expires_ts": 0, "entrance_note": "", "note_date": "",
    "image_url": "", "offer_image_url": "",
    "access_context": {"state": "none", "notices": []},
    "start_input": "2026-09-26 17:00", "end_input": "2026-09-26 23:00",
}

# Range fragments, rather than textContent alone, detect cut-off label text.
GEOMETRY = r"""(el, options) => {
  const eps = .75;
  const rect = r => ({left:r.left,top:r.top,right:r.right,bottom:r.bottom,
    width:r.width,height:r.height});
  const fits = (r,b,x=true,y=true) => (!x || (r.left>=b.left-eps && r.right<=b.right+eps))
    && (!y || (r.top>=b.top-eps && r.bottom<=b.bottom+eps));
  const viewport = {left:0,top:0,right:innerWidth,bottom:innerHeight};
  const box = rect(el.getBoundingClientRect());
  const style = getComputedStyle(el);
  const issues = [];
  const clips = [];
  for(let a=el.parentElement; a; a=a.parentElement) {
    const s=getComputedStyle(a), r=a.getBoundingClientRect();
    const paint=/(^|\s)(paint|strict|content)(\s|$)/.test(s.contain);
    const x=paint || /^(hidden|clip|scroll|auto)$/.test(s.overflowX);
    const y=paint || /^(hidden|clip|scroll|auto)$/.test(s.overflowY);
    if(x || y) clips.push({tag:a.tagName,testid:a.dataset.testid||null,x,y,
      rect:{left:r.left+a.clientLeft,top:r.top+a.clientTop,
        right:r.left+a.clientLeft+a.clientWidth,
        bottom:r.top+a.clientTop+a.clientHeight}});
    if(s.visibility==='hidden' || s.display==='none' || Number(s.opacity)===0)
      issues.push('hidden ancestor');
    if(s.clipPath!=='none' || s.clip!=='auto') issues.push('unsupported ancestor clipping');
  }
  const checkRect=(r, what, control=false) => {
    if(!fits(r,viewport)) issues.push(what+' outside viewport');
    if(control && !fits(r,box)) issues.push(what+' outside control');
    for(const c of clips) if(!fits(r,c.rect,c.x,c.y))
      issues.push(what+' clipped by '+c.tag+(c.testid?':'+c.testid:''));
  };
  if(box.width<=0 || box.height<=0 || style.visibility==='hidden' ||
     style.display==='none' || Number(style.opacity)===0) issues.push('not visible');
  checkRect(box,'element');
  if(options.target && (box.width<44-eps || box.height<44-eps)) issues.push('target smaller than 44px');
  const textRects=[];
  const labelClips=[];
  const walker=document.createTreeWalker(el,NodeFilter.SHOW_TEXT);
  while(walker.nextNode()) {
    const node=walker.currentNode;
    if(!node.textContent.trim()) continue;
    const range=document.createRange();range.selectNodeContents(node);
    const fragments=[...range.getClientRects()].filter(r=>r.width>0 && r.height>0);
    if(!fragments.length) issues.push('nonempty label text has no rendered range');
    const innerClips=[];
    for(let a=node.parentElement; a && a!==el.parentElement; a=a.parentElement) {
      const s=getComputedStyle(a),r=a.getBoundingClientRect();
      const paint=/(^|\s)(paint|strict|content)(\s|$)/.test(s.contain);
      const x=paint || /^(hidden|clip|scroll|auto)$/.test(s.overflowX);
      const y=paint || /^(hidden|clip|scroll|auto)$/.test(s.overflowY);
      if(s.visibility==='hidden' || s.display==='none' || Number(s.opacity)===0)
        issues.push('hidden label text');
      if(s.clipPath!=='none' || s.clip!=='auto') issues.push('unsupported label clipping');
      if(x || y) {
        const clip={tag:a.tagName,x,y,rect:{left:r.left+a.clientLeft,top:r.top+a.clientTop,
          right:r.left+a.clientLeft+a.clientWidth,bottom:r.top+a.clientTop+a.clientHeight}};
        innerClips.push(clip);labelClips.push(clip);
      }
    }
    for(const r of fragments) {
      const fragment=rect(r);textRects.push(fragment);checkRect(fragment,'label',true);
      for(const c of innerClips) if(!fits(fragment,c.rect,c.x,c.y))
        issues.push('label clipped inside control by '+c.tag);
      const inset=Math.min(1,r.width/4,r.height/4);
      for(const [x,y] of [[(r.left+r.right)/2,(r.top+r.bottom)/2],
        [r.left+inset,r.top+inset],[r.right-inset,r.top+inset],
        [r.left+inset,r.bottom-inset],[r.right-inset,r.bottom-inset]]) {
        const hit=document.elementFromPoint(x,y);
        if(!hit || !(hit===el || el.contains(hit))) issues.push('label sample occluded');
      }
    }
  }
  const text=(el.textContent||'').replace(/\s+/g,' ').trim();
  if(options.text && text!==options.text) issues.push('visible label differs');
  if(options.text && !textRects.length) issues.push('label has no rendered text range');
  const center={x:(box.left+box.right)/2,y:(box.top+box.bottom)/2};
  const hit=document.elementFromPoint(center.x,center.y);
  if(!hit || !(hit===el || el.contains(hit))) issues.push('element center occluded');
  let outline=null;
  if(options.focus) {
    if(document.activeElement!==el || !el.matches(':focus-visible')) issues.push('keyboard focus not visible');
    const width=parseFloat(style.outlineWidth)||0,offset=parseFloat(style.outlineOffset)||0;
    const visible=style.outlineStyle!=='none' && width>=2 &&
      style.outlineColor!=='transparent' && style.outlineColor!=='rgba(0, 0, 0, 0)';
    if(!visible) issues.push('focus outline missing');
    const margin=Math.max(0,width+offset);
    outline={style:style.outlineStyle,width,offset,color:style.outlineColor,
      rect:{left:box.left-margin,top:box.top-margin,right:box.right+margin,bottom:box.bottom+margin}};
    checkRect(outline.rect,'focus outline');
  }
  return {rect:box,text,textRects,clips,labelClips,outline,issues:[...new Set(issues)],
    accessibleLabel:el.getAttribute('aria-label'),tag:el.tagName};
}"""

ACTIVE = r"""() => {
  const e=document.activeElement;
  if(!e) return {key:null,tag:null};
  const header=e.closest('[data-testid="app-masthead"]');
  const key=header ? (e.dataset.testid==='theme-toggle' ? 'theme-toggle' :
    (e.getAttribute('aria-label') || e.textContent || '').replace(/\s+/g,' ').trim()) : null;
  return {key,tag:e.tagName,text:(e.textContent||'').replace(/\s+/g,' ').trim(),
    label:e.getAttribute('aria-label')};
}"""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inventory(directory: Path) -> dict:
    root = directory.resolve(strict=True)
    files = {}
    for candidate in sorted(directory.rglob("*")):
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(root):
            raise ValueError(f"Input escapes its root: {candidate}")
        if candidate.is_file():
            raw = candidate.read_bytes()
            files[candidate.relative_to(directory).as_posix()] = {
                "sha256": digest(raw), "bytes": len(raw)
            }
    if not files:
        raise ValueError(f"Empty input directory: {directory}")
    encoded = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return {"root": str(root), "files": files, "manifest_sha256": digest(encoded)}


def bindings(app_root: Path) -> dict:
    source = {}
    for name in SOURCE_INPUTS:
        path = (app_root / name).resolve(strict=True)
        if not path.is_relative_to(app_root):
            raise ValueError(f"Source input escapes app root: {name}")
        raw = path.read_bytes()
        source[name] = {"sha256": digest(raw), "bytes": len(raw)}
    return {"source_inputs": source,
            "compiled": inventory(app_root / ".jac" / "client" / "dist"),
            "assets": inventory(app_root / "assets")}


class Proof:
    def __init__(self, args, before):
        self.args = args
        self.before = before
        self.checks = []
        self.scenarios = []
        self.case_runs = []
        self.network = []
        self.errors = []
        self.screenshots = []
        self.cleanup = []
        self.browser_version = None
        self.pw_version = None

    def check(self, ok, name, details=None):
        self.checks.append({"name": name, "passed": bool(ok), "details": details})

    def shot(self, page, name):
        path = self.args.evidence / (name + ".png")
        page.screenshot(path=str(path), full_page=True, animations="disabled")
        self.screenshots.append({"path": path.name, "sha256": digest(path.read_bytes())})

    def fixture(self, role, name):
        signed = role == "student"
        session = {"authenticated": signed, "role": role,
                   "actor_id": "fixture-student" if signed else "",
                   "restaurant_id": "", "display_name": "Fixture student" if signed else "",
                   "is_demo": False, "email_verified": signed,
                   "business_account": False, "catalog_activity": False}
        feed = {"signed_in": signed, "personalized": False, "completed": True,
                "price_range": "", "favorites": [], "show_samples": False,
                "items": [{"offer": OFFER, "place": "fixture-kitchen",
                           "place_labels": [], "categories": [], "price_cents": 900,
                           "regular_cents": 1200, "price_range": "", "reasons": [],
                           "slot": "more", "is_favorite": False}],
                "total_deals": 1, "note": ""}
        return {"current_session": session, "home_feed": feed, "get_offer": OFFER}[name]

    def route(self, route, role, case):
        request = route.request
        parsed = urlsplit(request.url)
        event = {"case": case, "method": request.method,
                 "url": f"{parsed.scheme}://{parsed.netloc}{parsed.path}"}
        try:
            if parsed.scheme != "http" or parsed.netloc != "header.test":
                raise ValueError("External/non-fixture request blocked")
            path = unquote(parsed.path)
            if "\\" in path or "\x00" in path or ".." in path.split("/"):
                raise ValueError("Invalid asset path")
            if path.startswith("/function/"):
                name = path.removeprefix("/function/")
                if name not in ("current_session", "home_feed", "get_offer"):
                    raise ValueError("Unexpected RPC blocked: " + name)
                if request.method != "POST":
                    raise ValueError("Unexpected RPC method")
                body = request.post_data_json
                if name == "get_offer" and (not isinstance(body, dict) or body.get("offer_id") != OFFER["id"]):
                    raise ValueError("Unexpected offer ID")
                route.fulfill(json={"ok": True, "type": "response",
                    "data": {"result": self.fixture(role, name), "reports": []}, "error": None})
                event.update(kind="synthetic-read-only-rpc", name=name)
            elif path == "/" and request.method == "GET":
                entries = [name for name in self.before["compiled"]["files"]
                           if re.fullmatch(r"client\.[^/]+\.js", name)]
                if len(entries) != 1:
                    raise ValueError("Expected one actual compiled client entry")
                stylesheet = '<link rel="stylesheet" href="/styles.css">' if "styles.css" in self.before["compiled"]["files"] else ""
                shell = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                    '<meta name="viewport" content="width=device-width,initial-scale=1">'
                    '<title>app</title>' + stylesheet + '</head><body><div id="root"></div>'
                    '<script id="__jac_init__" type="application/json">'
                    '{"module":"main","function":"app","endpointEffects":{}}</script>'
                    '<script type="module" src="/'
                    + entries[0] + '"></script></body></html>')
                route.fulfill(content_type="text/html", body=shell)
                event.update(kind="synthetic-compiled-client-html-shell", sha256=digest(shell.encode()),
                             basis="coordinator-verified Jac 0.37.23 root/viewport/init metadata; contained compiled entry URL")
            elif request.method == "GET":
                if path.startswith("/static/assets/"):
                    group, relative = "assets", path.removeprefix("/static/assets/")
                else:
                    group, relative = "compiled", path.lstrip("/")
                manifest = self.before[group]
                if relative not in manifest["files"]:
                    raise ValueError("Unknown asset blocked: " + path)
                root = Path(manifest["root"])
                asset = (root / relative).resolve(strict=True)
                if not asset.is_relative_to(root) or not asset.is_file():
                    raise ValueError("Asset escaped contained root")
                raw = asset.read_bytes()
                if digest(raw) != manifest["files"][relative]["sha256"]:
                    raise ValueError("Asset changed during proof")
                content_type = {".js": "application/javascript", ".mjs": "application/javascript",
                    ".ttf": "font/ttf", ".woff2": "font/woff2", ".svg": "image/svg+xml"}.get(
                        asset.suffix.lower(), mimetypes.guess_type(asset.name)[0] or "application/octet-stream")
                route.fulfill(body=raw, content_type=content_type)
                event.update(kind="contained-unmodified-asset", input_group=group, path=relative,
                             sha256=digest(raw))
            else:
                raise ValueError("Unexpected request blocked")
        except Exception as error:
            event.update(kind="blocked", error=str(error))
            self.check(False, case + ": request rejected", event.copy())
            route.abort("blockedbyclient")
        self.network.append(event)

    def open(self, browser, width, theme, role, case):
        context = browser.new_context(viewport={"width": width, "height": 844},
            service_workers="block", reduced_motion="reduce", color_scheme=theme)
        try:
            context.set_default_timeout(8000)
            context.route("**/*", lambda route: self.route(route, role, case))
            def deny_socket(socket):
                self.check(False, case + ": websocket rejected", {"url": socket.url})
                socket.close(code=1008, reason="Synthetic header proof forbids sockets")
            context.route_web_socket("**/*", deny_socket)
            seed = {"theme": theme, "role": role}
            context.add_init_script("const seed=" + json.dumps(seed) + ";"
                "localStorage.clear();localStorage.setItem('mlocal_theme',seed.theme);"
                "if(seed.role==='student')localStorage.setItem('jac_token','synthetic-ui-token');")
            page = context.new_page()
            page.on("pageerror", lambda error: self.errors.append({"case": case, "error": str(error)}))
            page.goto(ORIGIN + "/", wait_until="load")
            if role == "guest":
                page.get_by_role("button", name=re.compile(r"^Find local deals(?:\s|$)")).click()
            page.get_by_text("Current bowl", exact=True).first.wait_for()
            page.get_by_text("Current bowl", exact=True).first.click()
            page.get_by_role("button", name="Sign in to claim" if role == "guest" else "Claim this offer", exact=True).wait_for()
            page.get_by_test_id("app-masthead").wait_for()
            page.evaluate("document.fonts.ready")
            self.check(page.locator("html").get_attribute("data-theme") == theme,
                       case + ": selected theme")
            self.check(page.get_by_test_id("theme-toggle").count() == 1,
                       case + ": one appearance control")
            self.check(page.evaluate("""()=>document.fonts.check('13px Figtree') && [...document.fonts].some(f=>f.family.replace(/[\"']/g,'')==='Figtree' && f.status==='loaded')"""),
                       case + ": Figtree available")
            self.check(page.evaluate("""async()=>{const i=new Image();i.src='/static/assets/brand/logo-master.png';await i.decode();return i.naturalWidth>0;}"""),
                       case + ": actual logo asset decoded")
            return context, page
        except Exception:
            try:
                context.close()
                self.cleanup.append({"case": case, "context_closed": True})
            except Exception as error:
                self.cleanup.append({"case": case, "context_closed": False, "error": str(error)})
                self.check(False, case + ": context cleanup", str(error))
            raise

    def control(self, page, key):
        masthead = page.get_by_test_id("app-masthead")
        return masthead.get_by_test_id(key) if key == "theme-toggle" else masthead.get_by_role("button", name=key, exact=True)

    def measure(self, page, key, case, focus=False):
        options = {"target": True, "focus": focus,
                   "text": None if key == "theme-toggle" else key}
        measured = self.control(page, key).evaluate(GEOMETRY, options)
        self.check(not measured["issues"], case + ": " + key + (" focused" if focus else " geometry"), measured)
        if key == "theme-toggle":
            self.check(measured["accessibleLabel"] in ("Switch to light mode", "Switch to dark mode"),
                       case + ": theme accessible name", measured["accessibleLabel"])
        return measured

    def geometry(self, page, role, case):
        keys = GUEST_ACTIONS if role == "guest" else ("theme-toggle", "Log out")
        boxes = [(key, self.measure(page, key, case)["rect"]) for key in keys]
        logo = page.get_by_test_id("app-masthead").get_by_role("img", name="M Local", exact=True)
        measured = logo.evaluate(GEOMETRY, {"target": False, "focus": False, "text": None})
        self.check(not measured["issues"], case + ": logo geometry", measured)
        boxes.append(("logo", measured["rect"]))
        for i, (first, a) in enumerate(boxes):
            for second, b in boxes[i + 1:]:
                overlap = min(a["right"], b["right"]) - max(a["left"], b["left"]) > .75 and min(a["bottom"], b["bottom"]) - max(a["top"], b["top"]) > .75
                self.check(not overlap, case + ": no overlap " + first + "/" + second,
                           {"first": a, "second": b})
        self.check(page.evaluate("document.documentElement.scrollWidth<=innerWidth"),
                   case + ": document does not overflow")

    def tab_to(self, page, key, case):
        trace = []
        for _ in range(64):
            page.keyboard.press("Tab")
            active = page.evaluate(ACTIVE)
            trace.append(active)
            if active["key"] == key:
                self.measure(page, key, case, focus=True)
                return trace
        raise AssertionError("Keyboard could not reach " + key + ": " + json.dumps(trace))

    def traversal(self, page, case):
        # Reach the first action by actual Tab, then check DOM order both ways.
        trace = self.tab_to(page, "theme-toggle", case)
        for key in GUEST_ACTIONS[1:]:
            page.keyboard.press("Tab")
            active = page.evaluate(ACTIVE)
            trace.append(active)
            self.check(active["key"] == key, case + ": forward Tab reaches " + key, active)
            if active["key"] == key:
                self.measure(page, key, case, focus=True)
        self.shot(page, case + "-keyboard-choose")
        for key in reversed(GUEST_ACTIONS[:-1]):
            page.keyboard.press("Shift+Tab")
            active = page.evaluate(ACTIVE)
            trace.append(active)
            self.check(active["key"] == key, case + ": reverse Tab reaches " + key, active)
            if active["key"] == key:
                self.measure(page, key, case, focus=True)
        self.scenarios.append({"case": case, "keyboard_trace": trace})

    def activation(self, page, key, press, theme, case):
        trace = self.tab_to(page, key, case)
        self.shot(page, case + "-focus")
        page.keyboard.press(press)
        if key == "theme-toggle":
            other = "dark" if theme == "light" else "light"
            page.wait_for_function("value=>document.documentElement.dataset.theme===value", arg=other)
            self.check(page.evaluate("localStorage.getItem('mlocal_theme')") == other,
                       case + ": theme activation persisted")
            self.measure(page, key, case, focus=True)
        elif key == "Sign in":
            field = page.get_by_role("textbox", name="U-M uniqname", exact=True)
            field.wait_for()
            page.wait_for_function("document.activeElement?.getAttribute('aria-label')==='U-M uniqname'")
            self.check(page.get_by_test_id("app-masthead").count() == 0,
                       case + ": sign-in screen opened")
            # Reach Back with keyboard from the app's naturally focused input.
            trace.extend(self.tab_to_unscoped(page, "Back"))
            page.keyboard.press(press)
            page.get_by_role("button", name="Sign in to claim", exact=True).wait_for()
            page.get_by_test_id("app-masthead").wait_for()
            self.check(page.get_by_text("Current bowl", exact=True).count() > 0,
                       case + ": Back restored selected public offer")
        elif key in ("Choose account type", "Log out"):
            page.get_by_role("button", name=re.compile(r"^Find local deals(?:\s|$)")).wait_for()
            self.check(page.get_by_test_id("app-masthead").count() == 0,
                       case + ": welcome opened")
            if key == "Log out":
                self.check(page.evaluate("localStorage.getItem('jac_token')") is None,
                           case + ": synthetic token removed by actual jacLogout")
        self.scenarios.append({"case": case, "activation": {"key": key, "press": press},
                               "keyboard_trace": trace})

    def tab_to_unscoped(self, page, name):
        trace = []
        for _ in range(64):
            page.keyboard.press("Tab")
            active = page.evaluate("""()=>{const e=document.activeElement;return {text:(e?.textContent||'').replace(/\s+/g,' ').trim(),label:e?.getAttribute('aria-label'),role:e?.getAttribute('role'),tag:e?.tagName};}""")
            trace.append(active)
            if active["text"] == name and (active["tag"] == "BUTTON" or active["role"] == "button"):
                return trace
        raise AssertionError("Keyboard could not reach " + name + ": " + json.dumps(trace))

    def case(self, browser, width, theme, role, action=None, press=None):
        suffix = "detail" if action is None else action.lower().replace(" ", "-") + "-" + press.lower()
        name = f"{width}-{theme}-{role}-{suffix}"
        context = page = None
        initial_checks = len(self.checks)
        completed = False
        try:
            context, page = self.open(browser, width, theme, role, name)
            self.geometry(page, role, name)
            if action is None:
                self.shot(page, name)
                if role == "guest":
                    self.traversal(page, name)
            else:
                self.activation(page, action, press, theme, name)
            completed = True
        except Exception as error:
            self.check(False, name + ": scenario exception", str(error))
            if page is not None and not page.is_closed():
                try:
                    self.shot(page, name + "-failure")
                except Exception as shot_error:
                    self.errors.append({"case": name, "error": "Failure screenshot: " + str(shot_error)})
        finally:
            if context is not None:
                try:
                    context.close()
                    self.cleanup.append({"case": name, "context_closed": True})
                except Exception as error:
                    self.cleanup.append({"case": name, "context_closed": False, "error": str(error)})
                    self.check(False, name + ": context cleanup", str(error))
            self.case_runs.append({"case": name, "width": width, "theme": theme,
                "role": role, "action": action, "press": press,
                "completed_without_exception": completed,
                "check_count": len(self.checks) - initial_checks,
                "failure_count": sum(not check["passed"] for check in self.checks[initial_checks:])})

    def run(self):
        browser = None
        try:
            self.pw_version = version("playwright")
            if not self.pw_version.startswith("1.56."):
                raise RuntimeError("Playwright 1.56.x required; found " + self.pw_version)
            from playwright.sync_api import sync_playwright
            with sync_playwright() as playwright:
                try:
                    launch = {"headless": True}
                    if self.args.channel:
                        launch["channel"] = self.args.channel
                    browser = playwright.chromium.launch(**launch)
                    self.browser_version = browser.version
                    for width in WIDTHS:
                        for theme in THEMES:
                            self.case(browser, width, theme, "guest")
                            self.case(browser, width, theme, "student")
                            if not self.args.geometry_only:
                                for press in ("Enter", "Space"):
                                    for action in GUEST_ACTIONS:
                                        self.case(browser, width, theme, "guest", action, press)
                                    self.case(browser, width, theme, "student", "Log out", press)
                finally:
                    if browser is not None:
                        browser.close()
                        self.cleanup.append({"browser_closed": True})
        except Exception as error:
            self.check(False, "harness/runtime exception", str(error))
        self.check(not self.errors, "no browser page errors", self.errors)
        try:
            after = bindings(self.args.app_root)
            self.check(after == self.before, "source/build/asset bytes unchanged")
        except Exception as error:
            after = {"error": str(error)}
            self.check(False, "after-run byte binding", str(error))
        failures = [check for check in self.checks if not check["passed"]]
        source_binding = {
            "schema": "mlocal-copied-header-input-binding-v1",
            "source_commit": self.args.source_commit,
            "commit_basis": "caller-declared; separate original Git HEAD/tree and full input manifest required",
            "before": self.before, "after": after, "unchanged": after == self.before,
            "harness_sha256": digest(Path(__file__).read_bytes()),
        }
        binding_path = self.args.evidence / "source-binding.json"
        binding_path.write_text(json.dumps(source_binding, indent=2) + "\n", encoding="utf-8")
        result = {
            "schema": "mlocal-guest-header-browser-v1", "created_at": datetime.now(timezone.utc).isoformat(),
            "mode": "observe" if self.args.observe else "verify",
            "status": ("observed_failures" if failures else "observed_no_failures") if self.args.observe else ("failed" if failures else "passed"),
            "passing_claim": not self.args.observe and not failures,
            "source_commit": self.args.source_commit,
            "source_commit_basis": "caller-declared copied-build identity; verify against separate original Git HEAD/tree and input manifest",
            "app_root": str(self.args.app_root), "before": self.before, "after": after,
            "source_binding": {"path": binding_path.name, "sha256": digest(binding_path.read_bytes())},
            "environment": {"os": platform.system(), "release": platform.release(),
                "machine": platform.machine(), "python": platform.python_version(),
                "playwright": self.pw_version, "browser_version": self.browser_version,
                "browser_channel": self.args.channel or "bundled-chromium"},
            "synthetic_mode": True, "rpc_allowlist": ["current_session", "home_feed", "get_offer"],
            "limits": ["Compiled client and real browser geometry/keyboard with synthetic DTOs only",
                "No backend, DB, email, account creation, credential validation, provider or physical-device proof",
                "Native browser selected independently of any canonical rollout/browser acceptance",
                "Source SHA is supplied by caller; raw copied inputs and unmodified compiled graph are bound here"],
            "widths": list(WIDTHS), "height": 844, "themes": list(THEMES),
            "coverage": {"detail_geometry_and_screenshots": True,
                "guest_forward_and_reverse_tab_traversal": True,
                "guest_enter_and_space_activation": not self.args.geometry_only,
                "signed_in_enter_and_space_logout": not self.args.geometry_only,
                "geometry_only_diagnostic": self.args.geometry_only,
                "expected_fresh_contexts": 16 if self.args.geometry_only else 80,
                "actual_case_count": len(self.case_runs),
                "completed_case_count": sum(case["completed_without_exception"] for case in self.case_runs)},
            "checks": self.checks, "failure_count": len(failures), "failures": failures,
            "case_runs": self.case_runs, "scenarios": self.scenarios, "network": self.network,
            "screenshots": self.screenshots, "cleanup": self.cleanup,
        }
        (self.args.evidence / "receipt.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": result["status"], "passing_claim": result["passing_claim"],
            "failure_count": len(failures), "receipt": str(self.args.evidence / "receipt.json")}, sort_keys=True))
        return 0 if self.args.observe or not failures else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--channel", choices=("chrome",), default=None)
    parser.add_argument("--observe", action="store_true")
    parser.add_argument("--geometry-only", action="store_true",
                        help="Diagnostic observation: omit activation cases, retain geometry/screenshots/Tab checks")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_commit):
        parser.error("--source-commit must be the exact lowercase 40-character SHA")
    if args.geometry_only and not args.observe:
        parser.error("--geometry-only requires --observe; full verification exercises every activation")
    args.app_root = args.app_root.resolve(strict=True)
    args.evidence = args.evidence.resolve()
    if args.evidence.is_relative_to(args.app_root) or args.app_root.is_relative_to(args.evidence):
        parser.error("--evidence must be separate from the input app root")
    before = bindings(args.app_root)
    # New evidence only: never overwrite an original receipt or screenshot.
    args.evidence.mkdir(parents=True, exist_ok=False)
    return Proof(args, before).run()


if __name__ == "__main__":
    sys.exit(main())
