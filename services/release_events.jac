"""Opt-in server-only fixed-category events; never accept request or error content."""
import json;
import os;
import sys;
import time;


def _write_event(operation: str, code: str, hourly: int = -1, daily: int = -1) {
    try {
        if os.environ.get("MLOCAL_DOMAIN_EVENT_LOG", "") != "stderr" { return; }
        fields: dict[str, str | int | float] = {
            "kind": "mlocal_domain_event", "time": time.time(),
            "operation": operation, "code": code
        };
        if hourly >= 0 and daily >= 0 {
            fields["hourly_attempts"] = hourly;
            fields["hourly_limit"] = 60;
            fields["daily_attempts"] = daily;
            fields["daily_limit"] = 300;
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
    code = "MAIL_QUOTA_REACHED" if hourly >= 60 or daily >= 300 else "MAIL_QUOTA_NEAR";
    if hourly >= 48 or daily >= 240 {
        _write_event("email_request", code, min(hourly, 60), min(daily, 300));
    }
}
