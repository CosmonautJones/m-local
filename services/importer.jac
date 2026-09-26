"""Data import boundary.

Every restaurant enters the graph through f"import_restaurant(record)". The demo
seed uses it today; a future community-source adapter (CSV, partner feed) only
has to produce the same record shape. Offer times in a record are given as
hour offsets from import time so demo data is always fresh.
"""

import time;
import from services.models {
    Restaurant,
    Location,
    MenuItem,
    Offer,
    HasLocation,
    Serves,
    Publishes,
    Features
}


"""Create one restaurant (with location, menu and offers) from a plain record.

Record keys: slug, name, cuisine, blurb, merchant_key, is_demo, source,
location{address, neighborhood, entrance_note, note_date},
menu[{name, price, dietary}], offers[{title, description, price, regular_price,
start_in_h, end_in_h, quantity, eligibility, terms, dietary, menu_item, status}].
Returns the restaurant, or the existing one if the slug is already present.
"""
def import_restaurant(record: dict[str, any]) -> Restaurant {
    existing = [root-->[?:Restaurant, slug == record["slug"]]];
    if existing {
        return existing[0];
    }
    now = time.time();
    r = Restaurant(
        slug=record["slug"],
        name=record["name"],
        cuisine=record.get("cuisine", ""),
        blurb=record.get("blurb", ""),
        merchant_key=record.get("merchant_key", ""),
        is_demo=record.get("is_demo", False),
        source=record.get("source", "manual")
    );
    root ++> r;
    loc: dict[str, str] = record.get("location", {});
    r +>:HasLocation():+> Location(
        address=loc.get("address", ""),
        neighborhood=loc.get("neighborhood", ""),
        entrance_note=loc.get("entrance_note", ""),
        note_date=loc.get("note_date", "")
    );
    items: dict[str, MenuItem] = {};
    menu: list[dict[str, any]] = record.get("menu", []);
    offers: list[dict[str, any]] = record.get("offers", []);
    for m in menu {
        item = MenuItem(
            name=m["name"], price=float(m.get("price", 0)), dietary=m.get("dietary", [])
        );
        r +>:Serves():+> item;
        items[m["name"]] = item;
    }
    for o in offers {
        offer = Offer(
            title=o["title"],
            description=o.get("description", ""),
            price=float(o.get("price", 0)),
            regular_price=float(o.get("regular_price", 0)),
            start_ts=now + float(o.get("start_in_h", 0)) * 3600,
            end_ts=now + float(o.get("end_in_h", 4)) * 3600,
            quantity=int(o.get("quantity", 10)),
            eligibility=o.get("eligibility", "Any student with a valid student ID"),
            terms=o.get("terms", ""),
            dietary=o.get("dietary", []),
            status=o.get("status", "active"),
            is_demo=record.get("is_demo", False),
            menu_item=o.get("menu_item", ""),
            created_ts=now
        );
        r +>:Publishes():+> offer;
        name = o.get("menu_item", "");
        if name and name in items {
            offer +>:Features():+> items[name];
        }
    }
    return r;
}
