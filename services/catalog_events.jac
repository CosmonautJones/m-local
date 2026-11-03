"""Change signals and shared state for the catalog read snapshot.

Kept free of project imports so any writer, including seeding modules that the
catalog itself depends on, can signal a change without an import cycle.
services/catalog.jac reads these and owns the snapshot logic.
"""

import threading;


glob cache_state: dict[str, any] = {"generation": 0, "snapshot": None, "dirty": set()},
     actor_cache: dict[str, any] = {},
     cache_lock: threading.RLock = threading.RLock();


"""Any structural catalog write: rebuild on the next read."""
def catalog_changed {
    with cache_lock {
        cache_state["generation"] = int(cache_state["generation"]) + 1;
    }
}


"""A claim, cancellation or redemption changed this offer's public stock."""
def offer_stock_changed(offer_id: str) {
    with cache_lock {
        dirty: set[str] = cache_state["dirty"];
        dirty.add(offer_id);
    }
}


"""This account's own claims changed (claimed, cancelled or redeemed)."""
def actor_claims_changed(actor: str) {
    with cache_lock {
        actor_cache.pop(actor, None);
    }
}


"""Test and operator hook: drop everything."""
def reset_catalog_cache {
    with cache_lock {
        cache_state["generation"] = int(cache_state["generation"]) + 1;
        cache_state["snapshot"] = None;
        dirty: set[str] = cache_state["dirty"];
        dirty.clear();
        actor_cache.clear();
    }
}
