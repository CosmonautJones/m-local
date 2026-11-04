"""Approve a business from an emailed link.

When a business submits a name and address for review, M-Local emails the
operator (MLOCAL_OPERATOR_EMAIL) the submission and a link to
MLOCAL_PUBLIC_URL/#approve=<token>. The token is signed with a key derived from
the private onboarding key and names one actor and one exact submission hash,
for seven days. Opening the link shows the submission; approving goes through
the same revision-bound CodeStore.approve_business the host command uses, so an
edited submission invalidates older links and approving twice changes nothing.

The link sits in the URL fragment, which browsers never send to a server, and
approval needs a second, deliberate tap, so mail scanners that prefetch links
cannot approve anything. Whoever holds the email can approve: keep the operator
inbox private. Without MLOCAL_OPERATOR_EMAIL and MLOCAL_PUBLIC_URL no email is
sent and the host review command remains the only way to approve.
"""

import base64;
import hashlib;
import hmac;
import json;
import os;
import re;
import tempfile;
import time;
import from email.message { EmailMessage }
import from pathlib { Path }
import from services.email_codes { store, deliver, delivery_ready }
import from services.release_events { record_mail_failure }

glob LINK_TTL_SECONDS: int = 7 * 86400,
     LINK_REVIEWER: str = "Operator (emailed review link)",
     LINK_NOTE: str = "Approved from the emailed review link after checking the business name and address.";

obj ReviewLinkView {
    has ok: bool = False,
        message: str = "",
        approved: bool = False,
        name: str = "",
        address: str = "",
        email: str = "",
        website: str = "",
        cuisine: str = "",
        description: str = "";
}


def _private_dir -> Path {
    return Path(os.environ.get("MLOCAL_ONBOARDING_DIR", ".jac/onboarding")).resolve();
}


def _link_key -> bytes {
    raw = (_private_dir() / "code.key").read_bytes();
    if len(raw) != 32 { raise ValueError("Review links need the original onboarding key."); }
    return hmac.new(raw, b"m-local business review link v1", hashlib.sha256).digest();
}


def make_review_token(actor: str, submission: str, expires: int) -> str {
    if not re.fullmatch(r"[0-9a-f]{32}", actor) or not re.fullmatch(r"[0-9a-f]{64}", submission) {
        raise ValueError("Review links name one business account and one submission.");
    }
    body = bytes.fromhex(actor) + bytes.fromhex(submission) + int(expires).to_bytes(8, "big");
    mac = hmac.new(_link_key(), body, hashlib.sha256).digest();
    return base64.urlsafe_b64encode(body + mac).decode().rstrip("=");
}


"""Return (actor, submission) for a genuine, unexpired token."""
def read_review_token(token: str, now: float) -> tuple[str, str] {
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{100,120}", token) {
        raise ValueError("This review link is not valid.");
    }
    try { raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)); }
    except (ValueError, TypeError) { raise ValueError("This review link is not valid.") from None; }
    if len(raw) != 88 { raise ValueError("This review link is not valid."); }
    (body, mac) = (raw[:56], raw[56:]);
    if not hmac.compare_digest(hmac.new(_link_key(), body, hashlib.sha256).digest(), mac) {
        raise ValueError("This review link is not valid.");
    }
    if int.from_bytes(body[48:56], "big") < now {
        raise ValueError("This review link has expired. Use the newest review email, or the host review command.");
    }
    return (body[:16].hex(), body[16:48].hex());
}


def _notices_path -> Path {
    return _private_dir() / "review-notices.json";
}


def _notified(actor: str) -> str {
    try {
        data = json.loads(_notices_path().read_text());
        return str(data.get(actor, "")) if isinstance(data, dict) else "";
    } except (OSError, ValueError) { return ""; }
}


def _remember_notice(actor: str, submission: str) {
    path = _notices_path();
    try { data = json.loads(path.read_text()); }
    except (OSError, ValueError) { data = {}; }
    if not isinstance(data, dict) { data = {}; }
    data[actor] = submission;
    (fd, temp) = tempfile.mkstemp(dir=str(path.parent), prefix=".review-notices.");
    try {
        with os.fdopen(fd, "w") as stream { json.dump(data, stream); }
        os.chmod(temp, 0o600);
        os.replace(temp, path);
    } except OSError {
        try { os.unlink(temp); } except OSError {}
    }
}


def review_link_settings -> tuple[str, str] {
    operator = os.environ.get("MLOCAL_OPERATOR_EMAIL", "").strip();
    public = os.environ.get("MLOCAL_PUBLIC_URL", "").strip().rstrip("/");
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,63}", operator) { operator = ""; }
    if not re.fullmatch(r"https://[A-Za-z0-9.-]+(:[0-9]{1,5})?", public) and not re.fullmatch(r"http://(127\.0\.0\.1|localhost)(:[0-9]{1,5})?", public) {
        public = "";
    }
    return (operator, public);
}


def _pending(actor: str) -> dict[str, any] {
    for pending in store().pending_businesses() {
        if pending.get("actor") == actor { return pending; }
    }
    return {};
}


def _line(value: any) -> str {
    return " ".join(str(value or "").split())[:240];
}


"""Email the operator once per new submission. Never fails the caller's save."""
def notify_business_review(actor: str, now: float | None = None) -> bool {
    (operator, public) = review_link_settings();
    if not operator or not public or not delivery_ready() { return False; }
    try {
        pending = _pending(actor);
        if not pending or pending.get("needs_submission") { return False; }
        submission = str(pending["submission"]);
        if _notified(actor) == submission { return False; }
        profile = pending.get("profile", {});
        token = make_review_token(actor, submission, int((now or time.time()) + LINK_TTL_SECONDS));
        message = EmailMessage();
        message["From"] = os.environ["MLOCAL_SMTP_FROM"];
        message["To"] = operator;
        message["Subject"] = "Review business: " + _line(profile.get("name"));
        message.set_content("\n".join([
            "A business asked to be listed on M-Local.",
            "",
            "Name: " + _line(profile.get("name")),
            "Address: " + _line(profile.get("address")),
            "Account email: " + _line(pending.get("email")),
            "Website: " + (_line(profile.get("website")) or "(none)"),
            "",
            "Check that this person can speak for the business at this address",
            "(for example, call the business or match the website's contact email).",
            "",
            "Review and approve:",
            public + "/#approve=" + token,
            "",
            "The link works for this exact submission for 7 days. If the business",
            "changes its name or address you will get a new email. Anyone with this",
            "email can approve, so do not forward it."
        ]));
        deliver(message);
        _remember_notice(actor, submission);
        return True;
    } except (OSError, ValueError, KeyError) {
        record_mail_failure();
        return False;
    }
}


def _owner_notice(email: str, name: str) {
    if not email or not delivery_ready() { return; }
    try {
        message = EmailMessage();
        message["From"] = os.environ["MLOCAL_SMTP_FROM"];
        message["To"] = email;
        message["Subject"] = "Your business is approved on M-Local";
        message.set_content(_line(name) + " is approved. Open M-Local and tap Continue to offers to publish your first deal.");
        deliver(message);
    } except (OSError, ValueError) { record_mail_failure(); }
}


def _view(actor: str, submission: str) -> ReviewLinkView {
    pending = _pending(actor);
    if not pending {
        approved = store().approved_profile(actor);
        if approved {
            return ReviewLinkView(ok=True, approved=True, name=str(approved.get("name", "")),
                address=str(approved.get("address", "")), message="This business is already approved.");
        }
        return ReviewLinkView(message="This business has no submission waiting for review.");
    }
    if pending.get("submission") != submission {
        return ReviewLinkView(message="This business changed its details after this email. Use the newest review email.");
    }
    profile = pending.get("profile", {});
    return ReviewLinkView(ok=True, name=str(profile.get("name", "")), address=str(profile.get("address", "")),
        email=str(pending.get("email", "")), website=str(profile.get("website", "")),
        cuisine=str(profile.get("cuisine", "")), description=str(profile.get("description", ""))[:600]);
}


"""What the emailed link would approve. The signed token is the authorization."""
def:pub review_link_details(token: str) -> ReviewLinkView {
    try {
        (actor, submission) = read_review_token(token, time.time());
        return _view(actor, submission);
    } except ValueError as error { return ReviewLinkView(message=str(error)); }
    except OSError { return ReviewLinkView(message="Business review is unavailable right now. Try again shortly."); }
}


"""Approve the exact submission the emailed link names."""
def:pub approve_from_review_link(token: str, note: str = "") -> ReviewLinkView {
    try {
        (actor, submission) = read_review_token(token, time.time());
        current = _view(actor, submission);
        if not current.ok or current.approved { return current; }
        store().approve_business(actor, LINK_REVIEWER, note.strip()[:500] or LINK_NOTE, submission);
        _owner_notice(current.email, current.name);
        return ReviewLinkView(ok=True, approved=True, name=current.name, address=current.address, email=current.email,
            message="Approved. The owner can now publish offers.");
    } except ValueError as error { return ReviewLinkView(message=str(error)); }
    except OSError { return ReviewLinkView(message="Business review is unavailable right now. Try again shortly."); }
}
