"""Identity and membership checks. Run: jac clean --data --force && jac test services/session.jac

Checks that need the offer rules (guest, student, cross-merchant and
private-claim cases) live in services/promo.test.jac, since promo imports this
module. Token handling itself (401 for guests on authenticated endpoints, one
root per login) is the runtime's job and is checked over HTTP."""

import from uuid { uuid4 }
import from services.seed { seed_demo }


def _slug(slug: str) -> Restaurant {
    for r in _restaurants() {
        if r.slug == slug {
            return r;
        }
    }
    raise Exception("missing " + slug);
}


test "provisioning makes exactly one merchant membership" {
    seed_demo();
    actor = "merchant-" + str(uuid4())[:8];
    assert _provision_owner("diag-dough-co", actor);
    s = _session_for(actor);
    assert s.role == "merchant" and s.restaurant_id == jid(_slug("diag-dough-co"));
    assert s.display_name == _slug("diag-dough-co").name;
    assert _provision_owner("maize-noodle-lab", actor);
    assert _slug("diag-dough-co").owner_actor_id != actor;
    now_owned = _restaurant_for_actor(actor);
    assert now_owned is not None and now_owned.slug == "maize-noodle-lab";
    assert not _provision_owner("no-such-slug", actor);
    assert not _provision_owner("diag-dough-co", "");
}


test "owner pairs parse strictly" {
    pairs = _parse_owner_pairs("a=1, bad, =x, y=, b = 2,c=3=4");
    assert pairs == [["a", "1"], ["b", "2"], ["c", "3=4"]];
    assert _parse_owner_pairs("") == [];
}
