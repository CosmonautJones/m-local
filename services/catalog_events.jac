"""Change signals and shared state for the catalog read snapshot.

Kept free of project imports so any writer, including seeding modules that the
catalog itself depends on, can signal a change without an import cycle.
services/catalog.jac reads these and owns the snapshot logic.
"""

import os;
import threading;


glob cache_state: dict[str, any] = {"generation": 0, "snapshot": None, "dirty": set(), "seeded": ""},
     actor_cache: dict[str, any] = {},
     cache_lock: threading.RLock = threading.RLock();


"""MLOCAL_CATALOG_CACHE=off (the test suites) rebuilds and re-checks on every read."""
def cache_reuse_enabled -> bool {
    return os.environ.get("MLOCAL_CATALOG_CACHE", "").strip().lower() not in ["off", "0", "false", "no"];
}


"""Any structural catalog write: rebuild on the next read, and re-check the
seed once, so a write that later rolls back cannot leave a stale verdict."""
def catalog_changed {
    with cache_lock {
        cache_state["generation"] = int(cache_state["generation"]) + 1;
        cache_state["seeded"] = "";
    }
}


"""The catalog seed was found complete for this key (shared root + dataset mode)."""
def seed_verified(key: str) -> bool {
    return cache_reuse_enabled() and cache_state["seeded"] == key;
}


def mark_seeded(key: str) {
    with cache_lock {
        cache_state["seeded"] = key;
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
        cache_state["seeded"] = "";
        dirty: set[str] = cache_state["dirty"];
        dirty.clear();
        actor_cache.clear();
    }
}
