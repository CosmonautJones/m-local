# Access-context source ledger

This ledger distinguishes information about a publisher from a verified notice
about one specific storefront. Source reachability is not proof of a business
association, menu, offer, pedestrian entrance, or alternate route.

## City of Ann Arbor road and lane closures (research only)

- Publisher: City of Ann Arbor, Engineering / Traffic.
- Direct source: <https://www.a2gov.org/engineering/traffic/road-and-lane-closures/>
- Recorded retrieval: 2026-09-26T20:28:11.527778+00:00 (HTTP 200; reproducibility
details and content hash are in `docs/research/source-checks.json`).
- Independent page review: 2026-09-27T00:21:39Z. The page publishes dated closures
and distinguishes traffic impacts. The later review did not reproduce the
historical content hash.
- Supported statement: the City publishes road and lane closure information at
this link. This source may support a minimal dated factual closure summary only
after that specific record is reviewed and linked.
- Not established: this page review does not establish a current closure, its
relation to a merchant, a blocked pedestrian entrance, or an alternate route.
No live City notice is attached to an M-Local restaurant, demo or otherwise.
- Freshness/reuse: recheck before displaying and daily while shown. No blanket
content license was verified; retain attribution, link, and minimal factual
summaries rather than republishing source text.

## Synthetic offers, menus, and access fixture

Every seeded restaurant is explicitly named `(Demo)`, carries `is_demo=true`,
and uses fictional example addresses. Its offers and menu entries are synthetic
illustrations, not merchant-confirmed prices, availability, ingredients, or
participation. They have no supporting external menu or offer source and must not
be presented as real merchant facts.

`data/demo/access-notices.json` is a schema fixture only. It is explicitly
simulated, linked only to a fictional demo location, has no source URL and provides
no entrance instruction. It is not evidence of actual access conditions. The app
must label it synthetic and state that missing access information is not an
all-clear.

## Source-check outcomes

See [`docs/research/source-checks.json`](../research/source-checks.json) for
recorded request outcomes and timestamps. In particular, the documented U-M event
JSON request returned HTTP 403; do not describe it as an available verified feed.
The checked City page supports only the limited publisher-level fact above. A
source link must be displayed alongside the specific reviewed real information;
a URL alone does not make an unverified claim verified.
