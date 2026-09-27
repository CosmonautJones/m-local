"""PromoPusher graph schema.

Restaurant -HasLocation-> Location
Restaurant -Serves-> MenuItem
Restaurant -Publishes-> Offer -Features-> MenuItem
Offer -ClaimedAs-> Redemption

Times are epoch seconds (float); display is converted to Ann Arbor local time.
"""

import from services.qr_auth { merchant_owner }

# Public catalog nodes are app-owned. HTTP mutations enforce ownership in promo.
node Restaurant {
    def __jac_access__ -> AccessLevel { return AccessLevel.WRITE; }
    has slug: str,
        name: str,
        cuisine: str = "",
        blurb: str = "",
        merchant_key: str = "",  # Legacy import compatibility; never authorization.
        owner_actor_id: str = "",
        is_demo: bool = False,
        source: str = "manual",
        archived: bool = False;
}

node Location {
    def __jac_access__ -> AccessLevel { return AccessLevel.WRITE; }
    has address: str,
        neighborhood: str = "",
        entrance_note: str = "",
        note_date: str = "";
}

node MenuItem {
    def __jac_access__ -> AccessLevel { return AccessLevel.WRITE; }
    has name: str,
        price: float = 0.0,
        price_cents: int = -1,
        dietary: list[str] = [];
}

node Offer {
    def __jac_access__ -> AccessLevel { return AccessLevel.WRITE; }
    has title: str,
        description: str = "",
        price: float = 0.0,
        price_cents: int = -1,
        regular_price: float = 0.0,
        regular_price_cents: int = -1,
        start_ts: float = 0.0,
        end_ts: float = 0.0,
        quantity: int = 0,
        qr_ready: bool = False,  # Old claims require trusted stock reconciliation.
        eligibility: str = "Any student with a valid student ID",
        terms: str = "",
        dietary: list[str] = [],
        status: str = "active",
        is_demo: bool = False,
        archived: bool = False,
        menu_item: str = "",
        created_ts: float = 0.0;
}

# Credentials and actor IDs never receive public read access.
node Redemption {
    has student_id: str = "",  # Legacy data only, not an authentication input.
        code: str = "",        # Legacy data only, never accepted for redemption.
        actor_id: str = "",
        restaurant_slug: str = "",
        qr_payload: str = "",
        offer_title_snapshot: str = "",
        price_cents_snapshot: int = 0,
        regular_price_cents_snapshot: int = -1,
        terms_snapshot: str = "",
        eligibility_snapshot: str = "",
        status: str = "claimed",
        claimed_ts: float = 0.0,
        expires_ts: float = 0.0,
        redeemed_ts: float = 0.0,
        cancelled_ts: float = 0.0;

    # Jac's optional graph visualizer renders repr(node). Never emit private
    # fields there, even if the operator accidentally enables that route.
    def __repr__ -> str { return "Redemption(private)"; }

    def __jac_access__ -> AccessLevel {
        actor = jid(root);
        if actor == self.actor_id or (merchant_owner(self.restaurant_slug) == actor) {
            return AccessLevel.WRITE;
        }
        return AccessLevel.NO_ACCESS;
    }
}

# Public stock accounting reveals no credential, actor or claim ID. Private
# Redemption nodes cannot be counted by other students because graph grants filter.
node Reservation {
    has status: str = "claimed", expires_ts: float = 0.0;
    def __jac_access__ -> AccessLevel { return AccessLevel.WRITE; }
}

edge Reserves: Offer --> Reservation {
    def __jac_access__ -> AccessLevel { return AccessLevel.WRITE; }
}

edge UsesReservation: Redemption --> Reservation {
    def __jac_access__ -> AccessLevel { return AccessLevel.WRITE; }
}

edge HasLocation: Restaurant --> Location {
    def __jac_access__ -> AccessLevel { return AccessLevel.WRITE; }
}

edge Serves: Restaurant --> MenuItem {
    def __jac_access__ -> AccessLevel { return AccessLevel.WRITE; }
}

edge Publishes: Restaurant --> Offer {
    def __jac_access__ -> AccessLevel { return AccessLevel.WRITE; }
}

edge Features: Offer --> MenuItem {
    def __jac_access__ -> AccessLevel { return AccessLevel.WRITE; }
}

edge ClaimedAs: Offer --> Redemption {
    def __jac_access__ -> AccessLevel { return AccessLevel.WRITE; }
}

"""Minutes a claim holds a unit before it is released back to availability."""
glob:pub CLAIM_HOLD_MINUTES: int = 20;

glob:pub DIET_TAGS: list[str] = ["vegetarian", "vegan", "gluten-free", "halal"];
