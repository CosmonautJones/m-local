"""Operator-enabled, additive test catalog. Never imports local email fixtures."""
import json;
import os;
import time;
import from services.places { Place, import_places, LocatedAt }
import from services.models { Restaurant, Location, Offer, HasLocation, Publishes }
import from services.catalog_events { catalog_changed }

node HostedDatasetLoaded {
    has count: int, anchor_ts: float = 0.0;
    def __jac_access__ -> AccessLevel { return AccessLevel.READ; }
}

def promo_title(category: str) -> str {
    return {"restaurant": "Student lunch special", "fast_food": "Quick bite combo",
        "cafe": "Coffee and a study break", "bakery": "Fresh pastry and coffee",
        "ice_cream": "Afternoon scoop", "bar": "Kitchen happy hour",
        "pub": "Early evening food special"}.get(category, "Local lunch special");
}

def hosted_dataset_enabled() -> bool {
    return os.environ.get("MLOCAL_HOSTED_DATASET", "") == "1";
}

def promo_timeline(index: int, now: float) -> tuple[float, float, float] {
    # A month-old catalog with ended, current and upcoming promotions.
    day = 86400.0;
    windows: list[tuple[float, float]] = [(-30.0, -21.0), (-20.0, -7.0),
        (-14.0, 0.25), (-7.0, 1.0), (-3.0, 3.0), (-1.0, 7.0),
        (-10.0, 14.0), (-2.0, 30.0), (1.0, 4.0), (7.0, 14.0)];
    (start, end) = windows[index % len(windows)];
    return (now + start * day, now + end * day, now - 30.0 * day);
}

def _add_hosted_dataset(records: list[dict[str, any]]) -> int {
    # Validation/upsert retains unrelated places; queries compute proximity on demand.
    import_places(records, materialize_nearby=False);
    catalog = {p.place_id: p for p in [root.shared -->[?:Place]]};
    existing = {r.slug for r in [root.shared -->[?:Restaurant]]};
    now = time.time();
    added = 0;
    for (i, rec) in enumerate(records) {
        category = str(rec["category"]);
        if category not in ["restaurant", "fast_food", "cafe", "bakery", "ice_cream", "bar", "pub"] { continue; }
        if "restricted_access_tag" in rec.get("quality_flags", []) { continue; }
        slug = "dataset-test-" + str(rec["id"]).replace(":", "-");
        # Never change existing inventories, claim snapshots, ownership or expiry.
        if slug in existing { continue; }
        price = 3 + i % 13;
        (starts, ends, created) = promo_timeline(i, now);
        addr = rec.get("address", {}) as dict[str, any];
        address = " ".join([str(addr.get(k) or "") for k in ["housenumber", "street", "city"]]).strip();
        r = Restaurant(slug=slug, name=str(rec["name"]),
            cuisine=str(rec.get("cuisine") or category).replace("_", " "),
            blurb="Discover a local favorite in Ann Arbor.",
            is_demo=True, source="dataset-test:" + str(rec["source_url"]));
        root.shared ++> r;
        loc = Location(address=address or "Address unknown", neighborhood="Ann Arbor");
        r +>:HasLocation():+> loc;
        loc +>:LocatedAt():+> catalog[str(rec["id"])];
        r +>:Publishes():+> Offer(
            title=promo_title(category),
            description="Make time for a local favorite at a student-friendly price.",
            price=float(price), regular_price=float(price + 5), price_cents=price * 100,
            regular_price_cents=(price + 5) * 100,
            start_ts=starts,
            end_ts=ends, quantity=0 if i % 17 == 0 else 25,
            dietary=["vegetarian"] if i % 3 == 0 else [],
            eligibility="Students with a valid university ID", is_demo=True, qr_ready=True,
            terms="One per student. While supplies last. Price excludes tax.",
            created_ts=created);
        existing.add(slug);
        added += 1;
    }
    return added;
}

def ensure_hosted_dataset {
    if not hosted_dataset_enabled() or [root.shared -->[?:HostedDatasetLoaded]] { return; }
    with open("data/simulation/places.json") as stream {
        records = json.load(stream) as list[dict[str, any]];
    }
    _add_hosted_dataset(records);
    root.shared ++> HostedDatasetLoaded(count=len(records), anchor_ts=time.time());
    catalog_changed();
}
