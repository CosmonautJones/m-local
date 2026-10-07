"""Passwordless onboarding; verified inbox ownership, never enrollment or merchant authority."""
import from services.onboarding_support { request_code, verify_code, account_details, may_claim, demo_student }
import from services.production_guard { exit_unless_production_ready }

# Opt-in (MLOCAL_ENV=production): exit before serving with unsafe private-state config.
glob _production_config_checked: bool = exit_unless_production_ready();

obj EmailCodeResult {
    has ok: bool = False, message: str = "", challenge: str = "",
        email: str = "", retry_after: int = 0, token: str = "";
}

def _code_result(raw: dict[str, any]) -> EmailCodeResult {
    return EmailCodeResult(ok=bool(raw.get("ok", False)),
        message=str(raw.get("message", "")), challenge=str(raw.get("challenge", "")),
        email=str(raw.get("email", "")), retry_after=int(raw.get("retry_after", 0)),
        token=str(raw.get("token", "")));
}

def:pub request_email_code(value: str, kind: str, name: str) -> EmailCodeResult {
    return _code_result(request_code(value, kind, name));
}

def:pub verify_email_code(challenge: str, code: str) -> EmailCodeResult {
    return _code_result(verify_code(challenge, code));
}

def verified_account(actor: str) -> dict[str, any] {
    return account_details(actor);
}

def student_can_claim(actor: str) -> bool { return may_claim(actor); }
def is_demo_student(actor: str) -> bool { return demo_student(actor); }
