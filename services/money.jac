"""Exact money handling.

Prices are authoritative as integer cents. Dollar strings from forms and
records go through money_to_cents; floats are display-only.
"""

import re;


glob MONEY_PATTERN: str = r"^\$?(\d+)(?:\.(\d{1,2}))?$";


"""Convert a nonnegative dollar amount like "8", "8.5" or "$8.05" to cents.
Raises ValueError for anything else: empty text, negatives, NaN, infinity,
exponents, or more than two fractional digits."""
def money_to_cents(text: str) -> int {
    m = re.match(MONEY_PATTERN, text.strip());
    if m is None {
        raise ValueError(f"not a valid dollar amount: {text!r}");
    }
    dollars = int(m.group(1));
    frac = m.group(2) or "";
    cents = int((frac + "00")[:2]);
    return dollars * 100 + cents;
}


"""Like money_to_cents, but returns None instead of raising."""
def try_money_to_cents(text: str) -> int | None {
    try {
        return money_to_cents(text);
    } except ValueError {
        return None;
    }
}


"""Cents to a float dollar amount, for display fields only."""
def cents_to_dollars(cents: int) -> float {
    return cents / 100;
}


"""Cents to a display label like "$8.05"."""
def money_label(cents: int) -> str {
    return f"${cents // 100}.{cents % 100:02d}";
}
