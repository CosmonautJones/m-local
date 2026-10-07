"""Private email-code, account and business-owner state for onboarding.

SQLite transactions serialize OTP consumption across threads/processes. All
replicas must share this directory on one host; do not deploy independent copies.
"""

import from contextlib { contextmanager }
import from email.message { EmailMessage }
import fcntl;
import hashlib;
import hmac;
import json;
import os;
import from pathlib { Path }
import re;
import secrets;
import smtplib;
import sqlite3;
import ssl;
import tempfile;
import time;
import from uuid { UUID }
import from services.release_events { record_mail_failure, record_mail_quota }

def mutation_lock_path() -> str {
    directory = Path(os.environ.get("MLOCAL_ONBOARDING_DIR", ".jac/onboarding")).resolve();
    directory.mkdir(mode=0o700, parents=True, exist_ok=True);
    return str(directory / "mutations.lock");
}

@contextmanager
def identity_review_lock(directory: Path) -> any {
    fd = os.open(directory / "mutations.lock", os.O_CREAT | os.O_RDWR, 0o600);
    try {
        fcntl.flock(fd, fcntl.LOCK_EX);
        yield;
    } finally {
        fcntl.flock(fd, fcntl.LOCK_UN);
        os.close(fd);
    }
}


def account_email(value: str, kind: str) -> str {
    value = value.strip().lower();
    if kind == "student" {
        if not re.fullmatch(r"[a-z][a-z0-9]{1,31}", value) {
            raise ValueError("Enter only your U-M uniqname, before @umich.edu.");
        }
        return value + "@umich.edu";
    }
    if kind != "business" or len(value) > 254 or not re.fullmatch(r"[a-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}", value) {
        raise ValueError("Enter a valid work email address.");
    }
    return value;
}


def validated_name(value: str) -> str {
    value = value.strip();
    if not (1 <= len(value) <= 80) or `any([ord(c) < 32 or 127 <= ord(c) < 160 for c in value]) {
        raise ValueError("Enter your name (up to 80 characters, without control characters).");
    }
    return value;
}

def business_revision(body: dict[str, any]) -> str {
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest();
}

def private_profile(value: any) -> dict[str, any] {
    try {
        body = json.loads(value);
        return body if isinstance(body, dict) else {};
    } except (ValueError, TypeError) { return {}; }
}

def complete_business_identity(body: dict[str, any]) -> bool {
    return all([isinstance(body.get(key), str) and body[key] == body[key].strip() and 0 < len(body[key]) <= limit
        and not `any([(ord(char) < 32 and char not in "\t\r\n") or 127 <= ord(char) < 160 for char in body[key]])
        for (key, limit) in [("name", 120), ("address", 240)]]);
}

def _approved_business_owner(db: any, slug: str) -> str {
    row = db.execute("SELECT b.actor,p.body FROM business_owners b JOIN accounts a ON a.actor=b.actor JOIN business_approvals p ON p.actor=b.actor WHERE b.slug=? AND b.active=1 AND a.kind=?", (slug, "business")).fetchone();
    if row {
        approved = private_profile(row["body"]);
        if not complete_business_identity(approved) { return ""; }
    }
    return row["actor"] if row else "";
}


obj CodeStore {
    has directory: Path,
        clock: any = time.time,
        key: bytes postinit,
        path: Path postinit;

    def postinit {
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True);
        key_path = self.directory / "code.key";
        if not key_path.exists() {
            (fd, temporary_key) = tempfile.mkstemp(prefix=".code-key-", dir=self.directory);
            try {
                with os.fdopen(fd, "wb") as stream {
                    stream.write(secrets.token_bytes(32));
                    stream.flush();
                    os.fsync(stream.fileno());
                }
                # Publish a complete file once; another cold starter may win.
                try { os.link(temporary_key, key_path); }
                except FileExistsError {}
            } finally {
                os.unlink(temporary_key);
            }
        }
        self.key = key_path.read_bytes();
        if len(self.key) != 32 {
            raise RuntimeError("Onboarding key is unavailable.");
        }
        self.path = self.directory / "onboarding.sqlite3";
        with self.transaction() as db {
            db.execute("CREATE TABLE IF NOT EXISTS codes (challenge TEXT PRIMARY KEY, email TEXT, kind TEXT, name TEXT, digest TEXT, expires REAL, attempts INTEGER, delivered INTEGER)");
            db.execute("CREATE TABLE IF NOT EXISTS sends (email TEXT, at REAL)");
            db.execute("CREATE INDEX IF NOT EXISTS sends_email_at ON sends(email, at)");
            db.execute("CREATE TABLE IF NOT EXISTS accounts (actor TEXT PRIMARY KEY, email TEXT UNIQUE, kind TEXT, name TEXT)");
            db.execute("CREATE TABLE IF NOT EXISTS display_names (actor TEXT PRIMARY KEY, name TEXT)");
            db.execute("CREATE TABLE IF NOT EXISTS provisioning (email TEXT PRIMARY KEY, marker TEXT, kind TEXT, name TEXT)");
            db.execute("CREATE TABLE IF NOT EXISTS drafts (actor TEXT PRIMARY KEY, body TEXT, updated REAL)");
            db.execute("CREATE TABLE IF NOT EXISTS imports (actor TEXT, at REAL)");
            db.execute("CREATE TABLE IF NOT EXISTS business_owners (actor TEXT PRIMARY KEY, slug TEXT UNIQUE NOT NULL, active INTEGER NOT NULL DEFAULT 0)");
            db.execute("CREATE TABLE IF NOT EXISTS business_approvals (actor TEXT PRIMARY KEY, reviewer TEXT NOT NULL, note TEXT NOT NULL, approved REAL NOT NULL)");
            if "body" not in [column["name"] for column in db.execute("PRAGMA table_info(business_approvals)").fetchall()] {
                db.execute("ALTER TABLE business_approvals ADD COLUMN body TEXT NOT NULL DEFAULT '{}'");
            }
            db.execute("CREATE TABLE IF NOT EXISTS business_reviews (id INTEGER PRIMARY KEY, actor TEXT NOT NULL, reviewer TEXT NOT NULL, note TEXT NOT NULL, approved REAL NOT NULL, body TEXT NOT NULL)");
        }
        os.chmod(self.path, 0o600);
    }

    @contextmanager
    def transaction() -> any {
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None);
        db.row_factory = sqlite3.Row;
        try {
            db.execute("BEGIN IMMEDIATE");
            yield db;
            db.commit();
        } except Exception as error {
            db.rollback();
            raise error;
        } finally {
            db.close();
        }
    }

    def digest(challenge: str, code: str) -> str {
        return hmac.new(self.key, (challenge + ":" + code).encode(), hashlib.sha256).hexdigest();
    }

    def request(value: str, kind: str, name: str, send: any) -> dict[str, any] {
        email = account_email(value, kind);
        # Blank means returning sign-in; account existence is checked only after
        # inbox proof. Named requests keep the existing create-or-resume flow.
        name = validated_name(name) if name else "";
        now = self.clock();
        challenge = secrets.token_urlsafe(32);
        code = f"{secrets.randbelow(1000000):06d}";
        with self.transaction() as db {
            db.execute("DELETE FROM sends WHERE at < ?", (now - 86400,));
            db.execute("DELETE FROM codes WHERE expires < ?", (now,));
            recent = db.execute("SELECT at FROM sends WHERE email=? AND at>?", (email, now - 3600)).fetchall();
            waiting = db.execute("SELECT 1 FROM codes WHERE email=?", (email,)).fetchone();
            if waiting and recent and now - max([r["at"] for r in recent]) < 60 {
                raise ValueError("Please wait 60 seconds before requesting another code.");
            }
            if len(recent) >= 5 {
                raise ValueError("Too many code requests. Please try again in an hour.");
            }
            hourly = db.execute("SELECT COUNT(*) FROM sends WHERE at>?", (now - 3600,)).fetchone()[0];
            daily = db.execute("SELECT COUNT(*) FROM sends").fetchone()[0];
            if hourly >= 60 or daily >= 300 {
                record_mail_quota(hourly, daily);
                raise ValueError("Email sign-in is busy. Please try again later.");
            }
            db.execute("INSERT INTO sends VALUES (?,?)", (email, now));
            db.execute("DELETE FROM codes WHERE email=?", (email,));
            db.execute("INSERT INTO codes VALUES (?,?,?,?,?,?,0,0)", (challenge, email, kind, name, self.digest(challenge, code), now + 600));
        }
        record_mail_quota(hourly + 1, daily + 1);
        try {
            send(email, code);
        } except Exception {
            record_mail_failure();
            with self.transaction() as db {
                db.execute("DELETE FROM codes WHERE challenge=?", (challenge,));
            }
            raise ValueError("We could not send the email. Please try again later.") from None;
        }
        with self.transaction() as db {
            db.execute("UPDATE codes SET delivered=1 WHERE challenge=?", (challenge,));
        }
        return {
            "ok": True,
            "challenge": challenge,
            "email": email,
            "retry_after": 60,
            "message": "Check your inbox for a six-digit code. It expires in 10 minutes."
        };
    }

    def consume(challenge: str, code: str) -> dict[str, any] {
        result: dict[str, any] | None = None;
        if len(challenge) > 128 or len(code) > 20 {
            raise ValueError("That code is invalid or expired. Request a new code.");
        }
        with self.transaction() as db {
            row = db.execute("SELECT * FROM codes WHERE challenge=?", (challenge,)).fetchone();
            if row and row["delivered"] and row["expires"] > self.clock() and row["attempts"] < 5 {
                db.execute("UPDATE codes SET attempts=attempts+1 WHERE challenge=?", (challenge,));
                if hmac.compare_digest(self.digest(challenge, code.strip()), row["digest"]) {
                    result = {key: row[key] for key in ("email", "kind", "name")};
                    db.execute("DELETE FROM codes WHERE challenge=?", (challenge,));
                }
            }
        }
        if result is None {
            raise ValueError("That code is invalid or expired. Request a new code after five attempts.");
        }
        return result;
    }

    def pending_count() -> int {
        with self.transaction() as db {
            return db.execute("SELECT COUNT(*) FROM codes WHERE delivered=1").fetchone()[0];
        }
    }

    def remember_account(actor: str, email: str, kind: str, name: str) -> None {
        with self.transaction() as db {
            db.execute("INSERT OR IGNORE INTO accounts VALUES (?,?,?,?)", (actor, email, kind, name));
            db.execute("DELETE FROM provisioning WHERE email=?", (email,));
        }
    }

    def provisioning(email: str, kind: str | None = None, name: str | None = None) -> dict[str, any] {
        with self.transaction() as db {
            if kind is not None {
                db.execute("INSERT OR IGNORE INTO provisioning VALUES (?,?,?,?)", (email, secrets.token_urlsafe(32), kind, name));
            }
            row = db.execute("SELECT * FROM provisioning WHERE email=?", (email,)).fetchone();
            return dict(row) if row else {};
        }
    }

    def account(actor: str) -> dict[str, any] {
        with self.transaction() as db {
            row = db.execute("SELECT email,kind,name FROM accounts WHERE actor=?", (actor,)).fetchone();
            return dict(row) if row else {};
        }
    }

    def display_name(actor: str, fallback: str = "") -> str {
        with self.transaction() as db {
            row = db.execute("SELECT name FROM accounts WHERE actor=?", (actor,)).fetchone();
            if row is None {
                row = db.execute("SELECT name FROM display_names WHERE actor=?", (actor,)).fetchone();
            }
            return row["name"] if row else fallback;
        }
    }

    def save_display_name(actor: str, name: str) -> str {
        if not actor {
            raise ValueError("Sign in before editing your profile.");
        }
        name = validated_name(name);
        with self.transaction() as db {
            changed = db.execute("UPDATE accounts SET name=? WHERE actor=?", (name, actor)).rowcount;
            if not changed {
                # Demo and other runtime accounts may have preferences without
                # gaining a verified email record or application authority.
                db.execute("INSERT INTO display_names VALUES (?,?) ON CONFLICT(actor) DO UPDATE SET name=excluded.name", (actor, name));
            }
        }
        return name;
    }

    def reserve_import(actor: str) -> None {
        now = self.clock();
        with self.transaction() as db {
            db.execute("DELETE FROM imports WHERE at<?", (now - 3600,));
            recent = db.execute("SELECT at FROM imports WHERE actor=?", (actor,)).fetchall();
            count = db.execute("SELECT COUNT(*) FROM imports").fetchone()[0];
            if len(recent) >= 5 or count >= 30 or (recent and now - max([r["at"] for r in recent]) < 30) {
                raise ValueError("Please wait before importing again. Each account can import five sites per hour.");
            }
            db.execute("INSERT INTO imports VALUES (?,?)", (actor, now));
        }
    }

    def save_draft(actor: str, body: dict[str, any]) -> None {
        with self.transaction() as db {
            db.execute("INSERT INTO drafts VALUES (?,?,?) ON CONFLICT(actor) DO UPDATE SET body=excluded.body,updated=excluded.updated", (actor, json.dumps(body), self.clock()));
        }
    }

    def draft(actor: str) -> dict[str, any] {
        with self.transaction() as db {
            row = db.execute("SELECT body FROM drafts WHERE actor=?", (actor,)).fetchone();
            return private_profile(row["body"]) if row else {};
        }
    }

    def update_business_details(actor: str, cuisine: str, description: str, image_url: str | None = None) -> None {
        with self.transaction() as db {
            row = db.execute("SELECT d.body FROM drafts d JOIN accounts a ON a.actor=d.actor WHERE d.actor=? AND a.kind='business'", (actor,)).fetchone();
            if row {
                body = private_profile(row["body"]);
                if not complete_business_identity(body) {
                    raise ValueError("Your saved business profile needs recovery. Contact the host.");
                }
                body["cuisine"] = cuisine;
                body["description"] = description;
                if image_url is not None { body["image_url"] = image_url; }
                db.execute("UPDATE drafts SET body=?,updated=? WHERE actor=?", (json.dumps(body), self.clock(), actor));
            }
        }
    }

    def pending_businesses() -> list[dict[str, any]] {
        with self.transaction() as db {
            rows = db.execute("SELECT a.actor,a.email,d.body,b.slug,p.body AS approved_body FROM accounts a LEFT JOIN drafts d ON d.actor=a.actor LEFT JOIN business_owners b ON b.actor=a.actor LEFT JOIN business_approvals p ON p.actor=a.actor WHERE a.kind='business' AND (d.actor IS NOT NULL OR b.active=1) ORDER BY d.updated").fetchall();
            result: list[dict[str, any]] = [];
            for row in rows {
                profile = private_profile(row["body"]) if row["body"] else {};
                approved = private_profile(row["approved_body"]) if row["approved_body"] else {};
                if not complete_business_identity(approved) or approved.get("name") != profile.get("name") or approved.get("address") != profile.get("address") {
                    result.append({"actor": row["actor"], "email": row["email"], "slug": row["slug"] or "", "profile": profile, "submission": business_revision(profile), "needs_submission": not complete_business_identity(profile)});
                }
            }
            orphaned = db.execute("SELECT b.actor,b.slug FROM business_owners b LEFT JOIN accounts a ON a.actor=b.actor WHERE b.active=1 AND (a.actor IS NULL OR a.kind!='business')").fetchall();
            for row in orphaned {
                result.append({"actor": row["actor"], "email": "", "slug": row["slug"], "profile": {}, "submission": "", "needs_submission": True});
            }
            return result;
        }
    }

    def business_approved(actor: str) -> bool {
        return bool(self.approved_profile(actor));
    }

    def approved_profile(actor: str) -> dict[str, any] {
        with self.transaction() as db {
            row = db.execute("SELECT p.body FROM business_approvals p JOIN accounts a ON a.actor=p.actor WHERE p.actor=? AND a.kind='business'", (actor,)).fetchone();
            body = private_profile(row["body"]) if row else {};
            return body if complete_business_identity(body) else {};
        }
    }

    def approval_covers(actor: str, body: dict[str, any]) -> bool {
        approved = self.approved_profile(actor);
        return bool(approved) and approved.get("name") == body.get("name") and approved.get("address") == body.get("address");
    }

    # Host-only operation. There is deliberately no browser RPC for approval.
    def approve_business(actor: str, reviewer: str, note: str, submission: str) -> None {
        try { actor = UUID(actor).hex; }
        except (ValueError, TypeError, AttributeError) {
            raise ValueError("Choose a verified business account.") from None;
        }
        reviewer = validated_name(reviewer);
        note = note.strip();
        if not note or len(note) > 500 or `any([ord(c) < 32 or 127 <= ord(c) < 160 for c in note]) {
            raise ValueError("Record how business authority was checked (up to 500 characters).");
        }
        # Share the app mutation lock without importing or booting a CLI graph.
        # A review cannot change identity while its public activation commits.
        with identity_review_lock(self.directory) {
            with self.transaction() as db {
                account = db.execute("SELECT kind FROM accounts WHERE actor=?", (actor,)).fetchone();
                draft = db.execute("SELECT body FROM drafts WHERE actor=?", (actor,)).fetchone();
                if account is None or account["kind"] != "business" or draft is None {
                    raise ValueError("Choose a verified business with a submitted profile.");
                }
                body = private_profile(draft["body"]);
                if not body { raise ValueError("Review a complete business submission before approving."); }
                if not hmac.compare_digest(business_revision(body), submission) {
                    raise ValueError("This submission changed. Read the latest profile before approving it.");
                }
                if not complete_business_identity(body) {
                    raise ValueError("Review a complete business name and address.");
                }
                existing = db.execute("SELECT body FROM business_approvals WHERE actor=?", (actor,)).fetchone();
                previous = private_profile(existing["body"]) if existing else {};
                if previous.get("name") == body["name"] and previous.get("address") == body["address"] { return; }
                at = self.clock();
                db.execute("INSERT INTO business_reviews (actor,reviewer,note,approved,body) VALUES (?,?,?,?,?)", (actor, reviewer, note, at, draft["body"]));
                db.execute("INSERT INTO business_approvals (actor,reviewer,note,approved,body) VALUES (?,?,?,?,?) ON CONFLICT(actor) DO UPDATE SET reviewer=excluded.reviewer,note=excluded.note,approved=excluded.approved,body=excluded.body", (actor, reviewer, note, at, draft["body"]));
            }
        }
    }

    """Reserve a stable server-derived identity without granting authority."""
    def reserve_business(actor: str) -> str {
        try {
            actor = UUID(actor).hex;
        } except (ValueError, TypeError, AttributeError) {
            raise ValueError("Sign in with a verified business account to save a business profile.") from None;
        }
        slug = "business-" + actor;
        with self.transaction() as db {
            account = db.execute("SELECT kind FROM accounts WHERE actor=?", (actor,)).fetchone();
            if account is None or account["kind"] != "business" {
                raise ValueError("Sign in with a verified business account to save a business profile.");
            }
            db.execute("INSERT OR IGNORE INTO business_owners (actor,slug) VALUES (?,?)", (actor, slug));
            row = db.execute("SELECT slug FROM business_owners WHERE actor=?", (actor,)).fetchone();
            if row is None or row["slug"] != slug {
                raise ValueError("Could not reserve this business profile. Please retry.");
            }
        }
        return slug;
    }

    """Finalize only after the caller has committed the restaurant graph."""
    def activate_business(actor: str, body: dict[str, str]) -> dict[str, str] {
        try {
            actor = UUID(actor).hex;
        } except (ValueError, TypeError, AttributeError) {
            raise ValueError("Sign in with a verified business account to save a business profile.") from None;
        }
        result = {**body, "status": "active"};
        with self.transaction() as db {
            account = db.execute("SELECT kind FROM accounts WHERE actor=?", (actor,)).fetchone();
            if account is None or account["kind"] != "business" {
                raise ValueError("Sign in with a verified business account to save a business profile.");
            }
            approval = db.execute("SELECT body FROM business_approvals WHERE actor=?", (actor,)).fetchone();
            approved = private_profile(approval["body"]) if approval else {};
            if not complete_business_identity(approved) or approved.get("name") != body.get("name") or approved.get("address") != body.get("address") {
                raise ValueError("Your business needs host approval before publishing.");
            }
            changed = db.execute("UPDATE business_owners SET active=1 WHERE actor=? AND slug=?", (actor, "business-" + actor)).rowcount;
            if not changed {
                raise ValueError("Save your business profile again to finish setting it up.");
            }
            db.execute("INSERT INTO drafts VALUES (?,?,?) ON CONFLICT(actor) DO UPDATE SET body=excluded.body,updated=excluded.updated", (actor, json.dumps(result), self.clock()));
        }
        return result;
    }

    def business_owner(slug: str) -> str {
        with self.transaction() as db {
            return _approved_business_owner(db, slug);
        }
    }
}


def store() -> CodeStore {
    return CodeStore(Path(os.environ.get("MLOCAL_ONBOARDING_DIR", ".jac/onboarding")).resolve());
}


def existing_store() -> CodeStore {
    directory = Path(os.environ.get("MLOCAL_ONBOARDING_DIR", ".jac/onboarding"));
    try {
        directory = directory.resolve();
        if len((directory / "code.key").read_bytes()) != 32 { raise ValueError("Onboarding key is unavailable."); }
        db = sqlite3.connect((directory / "onboarding.sqlite3").as_uri() + "?mode=ro", uri=True, timeout=15);
        try {
            required = {
                "accounts": {"actor", "email", "kind", "name"},
                "business_owners": {"actor", "slug", "active"},
                "drafts": {"actor", "body", "updated"}
            };
            for (table, columns) in required.items() {
                present = {row[1] for row in db.execute("PRAGMA table_info(" + table + ")")};
                if not columns.issubset(present) { raise ValueError("Onboarding database schema is unavailable."); }
            }
        } finally { db.close(); }
    } except (OSError, sqlite3.Error, RuntimeError, ValueError) {
        raise ValueError("Review requires the existing deployment's onboarding database and original key. Check MLOCAL_ONBOARDING_DIR; no replacement store was created.") from None;
    }
    try { return CodeStore(directory); }
    except (OSError, sqlite3.Error, RuntimeError, ValueError) {
        raise ValueError("Review could not open or migrate the existing onboarding store. Check MLOCAL_ONBOARDING_DIR and filesystem access; do not reset its database or key.") from None;
    }
}


def registered_business_owner(slug: str) -> str {
    if not re.fullmatch(r"business-[0-9a-f]{32}", slug) {
        return "";
    }
    try {
        directory = Path(os.environ.get("MLOCAL_ONBOARDING_DIR", ".jac/onboarding")).resolve();
        if len((directory / "code.key").read_bytes()) != 32 { return ""; }
        db = sqlite3.connect((directory / "onboarding.sqlite3").as_uri() + "?mode=ro", uri=True, timeout=15);
        db.row_factory = sqlite3.Row;
        try { return _approved_business_owner(db, slug); }
        finally { db.close(); }
    } except (OSError, sqlite3.Error, RuntimeError) {
        # Unavailable private state must never confer merchant authority.
        return "";
    }
}


def delivery_ready() -> bool {
    return all([os.environ.get(name, "").strip() for name in ("MLOCAL_SMTP_HOST", "MLOCAL_SMTP_FROM", "MLOCAL_SMTP_USERNAME", "MLOCAL_SMTP_PASSWORD")]);
}


def send_code(email: str, code: str) -> None {
    if not delivery_ready() {
        raise ValueError("Email sign-in is not enabled yet. The host needs to configure an email sender.");
    }
    message = EmailMessage();
    message["From"] = os.environ["MLOCAL_SMTP_FROM"];
    message["To"] = email;
    message["Subject"] = f"{code} is your M-Local verification code";
    message.set_content(f"Your M-Local code is: {code}\n\nIt expires in 10 minutes and works once.\nIf you did not request this code, ignore this email.\nM-Local will never ask for your university password.");
    port = int(os.environ.get("MLOCAL_SMTP_PORT", "587"));
    context = ssl.create_default_context();
    smtp: any = None;
    if port == 465 {
        smtp = smtplib.SMTP_SSL(os.environ["MLOCAL_SMTP_HOST"], port, timeout=10, context=context);
    } else {
        smtp = smtplib.SMTP(os.environ["MLOCAL_SMTP_HOST"], port, timeout=10);
    }
    with smtp {
        if port != 465 {
            smtp.starttls(context=context);
        }
        smtp.login(os.environ["MLOCAL_SMTP_USERNAME"], os.environ["MLOCAL_SMTP_PASSWORD"]);
        refused = smtp.send_message(message);
        if refused {
            raise OSError("Recipient refused");
        }
    }
}
