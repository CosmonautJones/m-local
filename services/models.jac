"""PromoPusher graph schema.

Restaurant -HasLocation-> Location
Restaurant -Serves-> MenuItem
Restaurant -Publishes-> Offer -Features-> MenuItem
Offer -ClaimedAs-> Redemption

The catalog hangs off root.shared so every visitor sees the same offers.
Identity is the caller's root id (jid(root)); ownership is enforced in
services/promo.jac, never by the client.

Money is authoritative in integer cents (price_cents, regular_price_cents,
price_cents_snapshot). The float price fields are display copies kept for
existing callers. Times are epoch seconds (float); display is converted to
Ann Arbor local time.
"""

node Restaurant {
    has slug: str,
        name: str,
        cuisine: str = "",
        blurb: str = "",
        merchant_key: str = "",
        owner_actor_id: str = "",
        is_demo: bool = False,
        source: str = "manual";
}

node Location {
    has address: str,
        neighborhood: str = "",
        entrance_note: str = "",
        note_date: str = "";
}

node MenuItem {
    has name: str,
        price: float = 0.0,
        price_cents: int = 0,
        dietary: list[str] = [];
}

node Offer {
    has title: str,
        description: str = "",
        price: float = 0.0,
        regular_price: float = 0.0,
        price_cents: int = 0,
        regular_price_cents: int = 0,
        start_ts: float = 0.0,
        end_ts: float = 0.0,
        quantity: int = 0,
        eligibility: str = "Any student with a valid student ID",
        terms: str = "",
        dietary: list[str] = [],
        status: str = "active",
        is_demo: bool = False,
        menu_item: str = "",
        created_ts: float = 0.0;
}

"""One student's claim on one offer. student_id holds the claimant's actor id.
status: claimed, redeemed, expired or cancelled. The snapshot fields freeze the
terms the student accepted; later offer edits never change them. expires_ts is
the immutable claim deadline."""
node Redemption {
    has student_id: str,
        code: str,
        status: str = "claimed",
        claimed_ts: float = 0.0,
        expires_ts: float = 0.0,
        redeemed_ts: float = 0.0,
        cancelled_ts: float = 0.0,
        offer_title_snapshot: str = "",
        price_cents_snapshot: int = 0,
        terms_snapshot: str = "",
        eligibility_snapshot: str = "";
}

edge HasLocation: Restaurant --> Location {}

edge Serves: Restaurant --> MenuItem {}

edge Publishes: Restaurant --> Offer {}

edge Features: Offer --> MenuItem {}

edge ClaimedAs: Offer --> Redemption {}

"""Minutes a claim holds a unit before it is released back to availability."""
glob:pub CLAIM_HOLD_MINUTES: int = 20;

glob:pub DIET_TAGS: list[str] = ["vegetarian", "vegan", "gluten-free", "halal"];
