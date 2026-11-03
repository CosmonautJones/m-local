"""Server-side access-context evaluation. Callers provide only the server clock."""

import from services.context_models {
    ContextNotice,
    Affects,
    AccessNoticeView,
    AccessContextView,
    NoticeSrc
}


glob:pub ACCESS_NOTICE_MAX_AGE_SECONDS: float = 86400.0;


def _notice_state(n: ContextNotice | NoticeSrc, now_ts: float) -> str {
    if n.valid_from <= now_ts and now_ts < n.valid_until and n.checked_at <= now_ts and now_ts - n.checked_at <= ACCESS_NOTICE_MAX_AGE_SECONDS {
        return "current";
    }
    return "needs_recheck";
}


"""Plain copy of one notice node and the locations it affects."""
def notice_src(n: ContextNotice, location_ids: list[str]) -> NoticeSrc {
    return NoticeSrc(id=jid(n), location_ids=location_ids, summary=n.summary,
        publisher=n.publisher, source_url=n.source_url, checked_at=n.checked_at,
        valid_from=n.valid_from, valid_until=n.valid_until, is_demo=n.is_demo,
        entrance_instruction=n.entrance_instruction);
}


"""The one evaluation rule, shared by the live graph path and cached catalog reads.
A notice counts only when it affects exactly this location."""
def access_context_from(notices: list[NoticeSrc], location_id: str, now_ts: float) -> AccessContextView {
    views: list[AccessNoticeView] = [];
    for n in notices {
        if len(n.location_ids) != 1 or n.location_ids[0] != location_id {
            continue;
        }
        state = _notice_state(n, now_ts);
        views.append(AccessNoticeView(
            id=n.id, summary=n.summary, publisher=n.publisher,
            source_url=n.source_url, checked_at=n.checked_at,
            valid_from=n.valid_from, valid_until=n.valid_until, state=state,
            is_demo=n.is_demo,
            entrance_instruction=n.entrance_instruction if state == "current" else ""
        ));
    }
    views.sort(key=lambda (v: AccessNoticeView) -> float { return v.valid_until; }, reverse=True);
    if not views {
        return AccessContextView(state="none", notices=[]);
    }
    overall = "current" if any([v.state == "current" for v in views]) else "needs_recheck";
    return AccessContextView(state=overall, notices=views);
}


def get_access_context(location_id: str, now_ts: float) -> AccessContextView {
    """Return only notices connected to this location.

    ``none`` means no reviewed access information is known; it is never an
    all-clear. Stale or out-of-window notices retain provenance but omit any
    definitive entrance instruction.
    """;
    found: list[NoticeSrc] = [];
    for n in [root.shared -->[?:ContextNotice]] {
        affected = [n ->:Affects:->];
        if len(affected) != 1 or jid(affected[0]) != location_id {
            continue;
        }
        found.append(notice_src(n, [jid(affected[0])]));
    }
    return access_context_from(found, location_id, now_ts);
}
