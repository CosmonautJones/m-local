"""Pure, private-input to aggregate-output business analytics.

The graph adapter is responsible for authorization. This module receives only
canonical claim snapshots, never simulation events or editable offer prices.
Calendar boundaries are Ann Arbor local midnights, including DST transitions.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo


TIMEZONE = "America/Detroit"
ALLOWED_DAYS = frozenset((7, 30, 90, 365))
METRICS = (
    "claims", "redemptions", "unique_customers", "returning_customers",
    "value_cents", "savings_cents", "savings_known", "cohort_redeemed",
    "cancelled", "expired", "pending", "unknown_outcomes",
)


TIME_BLOCKS = (
    ("morning", "Morning", "6 AM to 11 AM", 6, 11),
    ("lunch", "Lunch", "11 AM to 4 PM", 11, 16),
    ("dinner", "Dinner", "4 PM to 9 PM", 16, 21),
    ("late", "Late night", "9 PM to 6 AM", 21, 30),
)


@dataclass(frozen=True)
class _Claim:
    identity: str
    actor: str
    offer: str
    title: str
    claimed: float
    redeemed: float
    outcome: str
    resolved: float
    price: int | None
    regular: int | None
    starts: float = 0.0
    ends: float = 0.0


def _timestamp(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    if not math.isfinite(value) or value <= 0:
        return 0.0
    # Reject epochs outside datetime's useful range before later conversions.
    try:
        datetime.fromtimestamp(value, ZoneInfo(TIMEZONE))
    except (ValueError, OverflowError, OSError):
        return 0.0
    return float(value)


def _cents(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _blank() -> dict[str, int]:
    return dict.fromkeys(METRICS, 0)


def _local_date(timestamp: float, zone: ZoneInfo) -> date:
    return datetime.fromtimestamp(timestamp, zone).date()


def _occurred(timestamp: float, cutoff: float, now: float) -> bool:
    return timestamp > 0 and timestamp < cutoff and timestamp <= now


def _normalize(records: list[dict[str, Any]], is_demo: bool, now: float) -> tuple[list[_Claim], list[str]]:
    rows: list[_Claim] = []
    seen: set[str] = set()
    gaps: Counter[str] = Counter()
    for raw in records:
        if raw.get("is_demo", False) and not is_demo:
            continue
        identity = str(raw.get("claim_id", ""))
        if not identity or identity in seen:
            continue
        seen.add(identity)
        claimed = _timestamp(raw.get("claimed_ts"))
        redeemed = _timestamp(raw.get("redeemed_ts"))
        cancelled = _timestamp(raw.get("cancelled_ts"))
        expires = _timestamp(raw.get("expires_ts"))
        # Do not project uncommitted/future-dated activity into the current view.
        if claimed > now:
            continue
        if not claimed:
            gaps["claim timestamps"] += 1
        state = raw.get("status", "")
        outcome, resolved = "unknown_outcomes", 0.0
        if state == "redeemed":
            if redeemed and (not claimed or redeemed >= claimed):
                outcome, resolved = "cohort_redeemed", redeemed
            else:
                gaps["redemption timestamps"] += 1
                redeemed = 0.0
        elif state == "cancelled":
            redeemed = 0.0
            if cancelled and (not claimed or cancelled >= claimed):
                outcome, resolved = "cancelled", cancelled
            else:
                gaps["cancellation timestamps"] += 1
        elif state in ("claimed", "expired"):
            redeemed = 0.0
            if expires and (not claimed or expires >= claimed):
                outcome, resolved = "expired", expires
            else:
                gaps["expiry timestamps"] += 1
        else:
            redeemed = 0.0
            gaps["claim outcome evidence"] += 1
        price = _cents(raw.get("price_cents"))
        regular = _cents(raw.get("regular_price_cents"))
        actor = str(raw.get("actor_id", ""))
        if redeemed and redeemed <= now:
            if price is None:
                gaps["immutable claim prices"] += 1
            if regular is None or price is None or regular < price:
                gaps["regular-price snapshots"] += 1
            if not actor:
                gaps["authenticated account identifiers"] += 1
        rows.append(_Claim(identity, actor, str(raw.get("offer_id", "")),
                           str(raw.get("offer_title", "")) or "Untitled claimed offer",
                           claimed, redeemed, outcome, resolved, price, regular,
                           _timestamp(raw.get("offer_start_ts")), _timestamp(raw.get("offer_end_ts"))))
    warnings = [f"{count} recorded claim(s) have missing or invalid {kind}; affected metrics show only known evidence."
                for kind, count in sorted(gaps.items())]
    return rows, warnings


def _block_of(timestamp: float, zone: ZoneInfo) -> str:
    hour = datetime.fromtimestamp(timestamp, zone).hour
    for key, _label, _hours, first, last in TIME_BLOCKS:
        if first <= hour < last or first <= hour + 24 < last:
            return key
    return "late"


def _clock(moment: datetime) -> str:
    return moment.strftime("%I:%M %p").lstrip("0").replace(":00", "")


def _schedule(starts: float, ends: float, zone: ZoneInfo) -> str:
    if not starts or not ends or ends <= starts:
        return ""
    first, last = datetime.fromtimestamp(starts, zone), datetime.fromtimestamp(ends, zone)
    day = lambda moment: moment.strftime("%b ") + str(moment.day)
    if first.date() == last.date():
        return f"{day(first)}, {_clock(first)} to {_clock(last)}"
    return f"{day(first)}, {_clock(first)} to {day(last)}, {_clock(last)}"


def _sales(rows: list[_Claim], start_date: date, days: int, start_ts: float, now: float, zone: ZoneInfo) -> dict[str, Any]:
    """Redeemed offer value for every day of the period, split by time of day.

    A redemption counts on the local date and in the time block it was redeemed.
    Claims count in the block they were claimed. The schedule is the offer's
    current one, which the business can edit, so it is context and never used
    to count anything.
    """
    keys = [key for key, *_rest in TIME_BLOCKS]
    cell = lambda: {"redemptions": 0, "value_cents": 0, "discount_cents": 0, "discount_known": 0}
    calendar = [{"date": (start_date + timedelta(days=index)).isoformat(), "total": cell(), **{key: cell() for key in keys}}
                for index in range(days)]
    offers: dict[str, dict[str, Any]] = {}

    def offer_for(row: _Claim) -> dict[str, Any]:
        found = offers.setdefault(row.offer, {
            "id": row.offer, "title": row.title, "starts": 0.0, "ends": 0.0, "claims": 0, "redemptions": 0,
            "value_cents": 0, "blocks": {key: {"claims": 0, "redemptions": 0, "value_cents": 0} for key in keys},
        })
        found["title"] = row.title
        if row.starts and row.ends:
            found["starts"], found["ends"] = row.starts, row.ends
        return found

    for row in rows:
        if start_ts <= row.claimed <= now:
            mine = offer_for(row)
            mine["claims"] += 1
            mine["blocks"][_block_of(row.claimed, zone)]["claims"] += 1
        if start_ts <= row.redeemed <= now:
            index = (_local_date(row.redeemed, zone) - start_date).days
            if not 0 <= index < days:
                continue
            key = _block_of(row.redeemed, zone)
            worth = row.price if row.price is not None else 0
            priced = row.price is not None and row.regular is not None and row.regular >= row.price
            for target in (calendar[index]["total"], calendar[index][key]):
                target["redemptions"] += 1
                target["value_cents"] += worth
                if priced:
                    target["discount_known"] += 1
                    target["discount_cents"] += row.regular - row.price
            mine = offer_for(row)
            mine["redemptions"] += 1
            mine["value_cents"] += worth
            mine["blocks"][key]["redemptions"] += 1
            mine["blocks"][key]["value_cents"] += worth

    labels = {key: label for key, label, *_rest in TIME_BLOCKS}
    listed = []
    for item in sorted(offers.values(), key=lambda item: (-item["redemptions"], -item["claims"], item["id"])):
        best = max(TIME_BLOCKS, key=lambda block: (item["blocks"][block[0]]["redemptions"], item["blocks"][block[0]]["claims"]))
        busiest = item["blocks"][best[0]]
        listed.append({
            "title": item["title"], "schedule": _schedule(item["starts"], item["ends"], zone),
            "claims": item["claims"], "redemptions": item["redemptions"], "value_cents": item["value_cents"],
            "busiest": labels[best[0]] if busiest["redemptions"] or busiest["claims"] else "",
            "blocks": [{"key": key, "label": labels[key], **item["blocks"][key]} for key in keys],
        })
    return {
        "blocks": [{"key": key, "label": label, "hours": hours} for key, label, hours, *_rest in TIME_BLOCKS],
        "days": calendar, "offers": listed,
    }


def build_insights(records: list[dict[str, Any]], business_name: str,
                   is_demo: bool, days: int, now: float) -> dict[str, Any]:
    """Build a chronological, aggregate-only response from authorized claims.

    Period claims form the conversion cohort; period redemptions include carry-in
    claims. Returning accounts have a redemption on an earlier local date,
    including dates before the selected period. Daily pending/unknown counts
    describe that day's claim cohort, not a possibly negative inventory delta.
    """
    if type(days) is not int or days not in ALLOWED_DAYS:
        raise ValueError("Choose a 7, 30, 90, or 365 day period.")
    if not _timestamp(now):
        raise ValueError("A valid server timestamp is required.")
    zone = ZoneInfo(TIMEZONE)  # Fail rather than silently apply the host timezone.
    end_date = _local_date(now, zone)
    start_date = end_date - timedelta(days=days - 1)
    start_ts = datetime.combine(start_date, time.min, zone).timestamp()
    rows, warnings = _normalize(records, is_demo, now)
    coverage = [ts for row in rows for ts in (row.claimed, row.redeemed) if 0 < ts <= now]
    first_redemption: dict[str, date] = {}
    for row in rows:
        if row.actor and 0 < row.redeemed <= now:
            redeemed_date = _local_date(row.redeemed, zone)
            first_redemption[row.actor] = min(first_redemption.get(row.actor, redeemed_date), redeemed_date)

    frames: list[dict[str, Any]] = [{
        "day": 0, "date": (start_date - timedelta(days=1)).isoformat(),
        "daily": _blank(), "totals": _blank(), "offers": [],
    }]
    cohort = [row for row in rows if start_ts <= row.claimed <= now]
    cohort_changes = [_blank() for _ in range(days)]
    cohort_daily = [_blank() for _ in range(days)]
    for row in cohort:
        claimed_day = (_local_date(row.claimed, zone) - start_date).days
        initial = "unknown_outcomes" if row.outcome == "unknown_outcomes" else "pending"
        cohort_changes[claimed_day]["claims"] += 1
        cohort_changes[claimed_day][initial] += 1
        cohort_daily[claimed_day]["claims"] += 1
        if initial == "unknown_outcomes":
            cohort_daily[claimed_day][initial] += 1
        elif 0 < row.resolved <= now:
            resolved_day = (_local_date(row.resolved, zone) - start_date).days
            cohort_changes[resolved_day]["pending"] -= 1
            cohort_changes[resolved_day][row.outcome] += 1
            cohort_daily[resolved_day][row.outcome] += 1
            if resolved_day != claimed_day:
                cohort_daily[claimed_day]["pending"] += 1
        else:
            cohort_daily[claimed_day]["pending"] += 1
    redemptions = sorted((row for row in rows if start_ts <= row.redeemed <= now),
                         key=lambda row: (row.redeemed, row.identity))
    cumulative = _blank()
    customers: set[str] = set()
    returners: set[str] = set()
    offer_totals: dict[str, dict[str, Any]] = {}
    redemption_index = 0
    for index in range(days):
        calendar_date = start_date + timedelta(days=index)
        cutoff = datetime.combine(calendar_date + timedelta(days=1), time.min, zone).timestamp()
        daily = _blank()
        day_customers: set[str] = set()
        day_returners: set[str] = set()
        for key in ("claims", "cohort_redeemed", "cancelled", "expired", "pending", "unknown_outcomes"):
            cumulative[key] += cohort_changes[index][key]
            daily[key] = cohort_daily[index][key]
        while redemption_index < len(redemptions):
            row = redemptions[redemption_index]
            if not _occurred(row.redeemed, cutoff, now):
                break
            redemption_index += 1
            daily["redemptions"] += 1
            daily["value_cents"] += row.price if row.price is not None else 0
            if row.price is not None and row.regular is not None and row.regular >= row.price:
                daily["savings_known"] += 1
                daily["savings_cents"] += row.regular - row.price
            if row.actor:
                customers.add(row.actor)
                day_customers.add(row.actor)
                if first_redemption[row.actor] < calendar_date:
                    returners.add(row.actor)
                    day_returners.add(row.actor)
            offer = offer_totals.setdefault(row.offer, {"id": row.offer, "title": row.title, "redemptions": 0, "value_cents": 0})
            offer["title"] = row.title
            offer["redemptions"] += 1
            offer["value_cents"] += row.price if row.price is not None else 0
        daily["unique_customers"] = len(day_customers)
        daily["returning_customers"] = len(day_returners)
        cumulative["unique_customers"] = len(customers)
        cumulative["returning_customers"] = len(returners)
        for key in ("redemptions", "value_cents", "savings_cents", "savings_known"):
            cumulative[key] += daily[key]
        offers = sorted((dict(item) for item in offer_totals.values()),
                        key=lambda item: (-item["redemptions"], -item["value_cents"], item["id"]))
        frames.append({"day": index + 1, "date": calendar_date.isoformat(),
                       "daily": daily, "totals": dict(cumulative), "offers": offers})
    return {
        "ok": True, "message": "", "business_name": business_name, "is_demo": is_demo,
        "period_days": days, "timezone": TIMEZONE, "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(), "as_of": now,
        "coverage_start_date": _local_date(min(coverage), zone).isoformat() if coverage else "",
        "warnings": warnings, "engagement_available": False, "frames": frames,
        "totals": frames[-1]["totals"], "offers": frames[-1]["offers"],
        "sales": _sales(rows, start_date, days, start_ts, now, zone),
    }
