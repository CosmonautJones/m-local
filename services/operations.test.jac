"""Operator backup endpoint: secret-gated, rate-limited, complete and self-checking."""
import os;
import json;
import hashlib;
import tempfile;
import from unittest.mock { patch }
import from services.email_codes { store }
import from services.qr_catalog { _ensure_seed }
import from services.hosted_backup { _state }

glob TOKEN: str = "fixture-backup-token-0123456789abcdefghijklmnop";


test "backups are off without a long host token and refuse a wrong one" {
    _ensure_seed();
    with patch.dict(os.environ, {"MLOCAL_BACKUP_TOKEN": ""}) {
        assert not download_backup(TOKEN).ok;
    }
    with patch.dict(os.environ, {"MLOCAL_BACKUP_TOKEN": "short-token"}) {
        assert not download_backup("short-token").ok;
    }
    with patch.dict(os.environ, {"MLOCAL_BACKUP_TOKEN": TOKEN}) {
        refused = download_backup(TOKEN + "x");
        assert not refused.ok and refused.backup == "";
    }
}


test "a backup holds every table, the private store and checks itself" {
    _ensure_seed();
    with tempfile.TemporaryDirectory() as directory {
        with patch.dict(os.environ, {"MLOCAL_BACKUP_TOKEN": TOKEN, "MLOCAL_ONBOARDING_DIR": directory}) {
            store().remember_account("3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e3e", "backup@fixture.test", "business", "Owner");
            _state["last"] = 0.0;
            result = download_backup(TOKEN);
            assert result.ok, result.message;
            outer = json.loads(result.backup);
            body = outer["backup"];
            text = json.dumps(body, separators=(",", ":"), sort_keys=True);
            assert outer["sha256"] == hashlib.sha256(text.encode()).hexdigest();
            assert body["format"] == "m-local-hosted-backup-v1";
            tables = body["graph"]["tables"];
            assert tables and all([t["row_count"] == len(t["rows"]) for t in tables]);
            assert all([t["sha256"] == hashlib.sha256("\n".join(t["rows"]).encode()).hexdigest() for t in tables]);
            assert sum([t["row_count"] for t in tables]) > 0;
            assert any([t["constraints"] for t in tables]), "primary keys are recorded for restore";
            names = {f["name"]: f for f in body["private"]};
            assert names["code.key"]["bytes"] == 32 and "onboarding.sqlite3" in names;
            assert "backup@fixture.test".encode() in __import__("base64").b64decode(names["onboarding.sqlite3"]["base64"]);
            again = download_backup(TOKEN);
            assert not again.ok and "five minutes" in again.message;
        }
    }
}
