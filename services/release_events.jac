"""Opt-in server-only fixed-category events; never accept request or error content."""
import json;
import os;
import sys;
import time;


"""Site-wide sign-in email limits. Set them below the mail provider's own
quota (Resend's free plan stops at 100 a day) so a code is refused with a clear
message instead of silently not arriving. Invalid values keep the default."""
def mail_cap(name: str, fallback: int) -> int {
    text = os.environ.get(name, "").strip();
    return int(text) if text.isdigit() and 0 < int(text) <= 1000000 else fallback;
}


def mail_caps -> tuple[int, int] {
    return (mail_cap("MLOCAL_MAIL_HOURLY_CAP", 60), mail_cap("MLOCAL_MAIL_DAILY_CAP", 300));
}


def _write_event(operation: str, code: str, hourly: int = -1, daily: int = -1) {
    try {
        if os.environ.get("MLOCAL_DOMAIN_EVENT_LOG", "") != "stderr" { return; }
        fields: dict[str, str | int | float] = {
            "kind": "mlocal_domain_event", "time": time.time(),
            "operation": operation, "code": code
        };
        if hourly >= 0 and daily >= 0 {
            (hourly_cap, daily_cap) = mail_caps();
            fields["hourly_attempts"] = hourly;
            fields["hourly_limit"] = hourly_cap;
            fields["daily_attempts"] = daily;
            fields["daily_limit"] = daily_cap;
        }
        print(json.dumps(fields), file=sys.stderr, flush=True);
    } except Exception {
        # Event output is optional; sink failure never changes the operation.
    }
}


def record_outcome(operation: str, ok: bool) {
    if operation in ("email_request", "claim", "redeem") and isinstance(ok, bool) and not ok {
        _write_event(operation, "OPERATION_FAILED");
    }
}


def record_mail_failure {
    _write_event("email_delivery", "SMTP_DELIVERY_FAILED");
}


def record_mail_quota(hourly: int, daily: int) {
    if not isinstance(hourly, int) or not isinstance(daily, int)
        or isinstance(hourly, bool) or isinstance(daily, bool)
        or hourly < 0 or daily < 0 { return; }
    (hourly_cap, daily_cap) = mail_caps();
    code = "MAIL_QUOTA_REACHED" if hourly >= hourly_cap or daily >= daily_cap else "MAIL_QUOTA_NEAR";
    # Warn from 80% of either limit.
    if hourly * 5 >= hourly_cap * 4 or daily * 5 >= daily_cap * 4 {
        _write_event("email_request", code, min(hourly, hourly_cap), min(daily, daily_cap));
    }
}
