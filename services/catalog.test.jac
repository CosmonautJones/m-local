"""Catalog snapshot cache rules. Comparisons with live promo views and claim
flows live in promo.test.jac (importing promo here would be circular)."""

import os;
import time;
import from unittest.mock { patch }
import from services.qr_catalog { _ensure_seed }


def _reuse -> dict[str, str] {
    return {"MLOCAL_CATALOG_CACHE": "on", "MLOCAL_SHOW_SAMPLES": "1"};
}


def _best_id(claims: list[ClaimSrc], now: float) -> str {
    chosen = best_claim(claims, now);
    return chosen.id if chosen is not None else "";
}


test "batched and per-place builds agree" {
    _ensure_seed();
    now = time.time();
    batched = _build_batched(0, now);
    walked = _build_walk(0, now);
    assert [p.slug for p in batched.places] == [p.slug for p in walked.places];
    for (a, b) in zip(batched.places, walked.places) {
        assert [s.id for s in a.offers] == [s.id for s in b.offers], a.slug;
        assert (a.loc_id, a.address, a.labels, a.categories) == (b.loc_id, b.address, b.labels, b.categories), a.slug;
        for (x, y) in zip(a.offers, b.offers) {
            assert (x.redeemed, sorted(x.held), x.categories) == (y.redeemed, sorted(y.held), y.categories), x.title;
        }
    }
    assert sorted([(n.id, n.location_ids) for n in batched.notices]) == sorted([(n.id, n.location_ids) for n in walked.notices]);
}


test "a catalog write rebuilds the snapshot and old snapshots expire" {
    _ensure_seed();
    with patch.dict(os.environ, _reuse()) {
        reset_catalog_cache();
        first = catalog_snapshot();
        assert catalog_snapshot() is first;
        catalog_changed();
        second = catalog_snapshot();
        assert second is not first and second.generation > first.generation;
        second.built_at = time.time() - CATALOG_MAX_AGE_SECONDS - 1;
        assert catalog_snapshot() is not second;
    }
}


test "with reuse off every read rebuilds" {
    _ensure_seed();
    with patch.dict(os.environ, {"MLOCAL_CATALOG_CACHE": "off"}) {
        assert catalog_snapshot() is not catalog_snapshot();
    }
}


test "best claim prefers live or redeemed QR claims, then the newest" {
    old = ClaimSrc(id="a", status="cancelled", claimed_ts=50.0, expires_ts=60.0, qr_payload="q1");
    live = ClaimSrc(id="b", status="claimed", claimed_ts=10.0, expires_ts=1000.0, qr_payload="q2");
    legacy = ClaimSrc(id="c", status="claimed", claimed_ts=99.0, expires_ts=1000.0, qr_payload="");
    assert _best_id([old, live, legacy], 100.0) == "b";
    assert _best_id([old], 100.0) == "a";
    assert best_claim([legacy], 100.0) is None;
    expired = ClaimSrc(id="d", status="claimed", claimed_ts=90.0, expires_ts=95.0, qr_payload="q3");
    assert claim_status_of(expired, 100.0) == "expired";
    assert _best_id([expired, old], 100.0) == "d";
}
