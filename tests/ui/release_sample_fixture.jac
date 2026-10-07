"""Offline fixture for a private release-browser store; never run on a shared graph."""
import json;
import os;
import time;
import uuid;
import from pathlib { Path }
import from services.models { Restaurant, Offer, Publishes }

with entry {
    base = Path.cwd().resolve();
    if not str(base).startswith("/var/tmp/m-local-release-browser.") or os.environ.get("MLOCAL_RELEASE_BROWSER_FIXTURE", "") != "1" {
        raise RuntimeError("Sample fixture refuses a non-disposable application store.");
    }
    now = time.time();
    suffix = uuid.uuid4().hex;
    sample_parent = Restaurant(slug="sample-parent-" + suffix, name="Disposable sample parent", source="release-fixture", is_demo=True);
    real_parent = Restaurant(slug="real-parent-" + suffix, name="Disposable real parent", source="release-fixture", is_demo=False);
    root.shared ++> sample_parent;
    root.shared ++> real_parent;
    unmarked = Offer(title="Unmarked child of sample parent", price_cents=400, regular_price_cents=600, quantity=1,
        start_ts=now - 60, end_ts=now + 3600, status="active", is_demo=False, qr_ready=True);
    marked = Offer(title="Sample child of real parent", price_cents=400, regular_price_cents=600, quantity=1,
        start_ts=now - 60, end_ts=now + 3600, status="active", is_demo=True, qr_ready=True);
    sample_parent +>:Publishes():+> unmarked;
    real_parent +>:Publishes():+> marked;
    path = base / ".jac/release-sample-fixture.json";
    path.write_text(json.dumps({"sample_parent": sample_parent.slug, "real_parent": real_parent.slug,
        "unmarked_offer": jid(unmarked), "marked_offer": jid(marked)}));
    path.chmod(0o600);
}
