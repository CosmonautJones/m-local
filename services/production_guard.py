"""Refuse to serve a production deployment that cannot keep its private state.

Opt-in: nothing here runs unless MLOCAL_ENV=production. This cannot prove the
onboarding directory is durable (a writable path can still be an ephemeral
container layer); it rejects the configurations that are certainly wrong.
Messages name a setting, never its value.
"""
import os
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path

ENV_NAME = "MLOCAL_ENV"
ONBOARDING_DIR = "MLOCAL_ONBOARDING_DIR"
EXIT_CODE = 78  # EX_CONFIG
SMTP_SETTINGS = ("MLOCAL_SMTP_HOST", "MLOCAL_SMTP_FROM", "MLOCAL_SMTP_USERNAME", "MLOCAL_SMTP_PASSWORD")
_TRUE = {"1", "true", "yes", "on"}


class ProductionConfigError(RuntimeError):
    """Raised at startup with every problem found, so one deploy fixes all of them."""


def is_production(env: Mapping[str, str]) -> bool:
    return env.get(ENV_NAME, "").strip().lower() == "production"


def _inside(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def _writable(directory: Path) -> bool:
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".mlocal-write-check-"):
            return True
    except OSError:
        return False


def _demo_enabled(env: Mapping[str, str]) -> list[str]:
    enabled = []
    if env.get("MLOCAL_DEMO_MODE", "").strip().lower() in _TRUE:
        enabled.append("MLOCAL_DEMO_MODE")
    if env.get("MLOCAL_DEMO_COMPANIES", "").strip() not in ("", "0"):
        enabled.append("MLOCAL_DEMO_COMPANIES")
    students = env.get("MLOCAL_DEMO_STUDENTS", "").strip()
    if students and students not in ("[]", "null"):
        enabled.append("MLOCAL_DEMO_STUDENTS")
    return enabled


def validate_production_config(env: Mapping[str, str], app_root: Path) -> list[str]:
    """Return a list of human-readable problems; empty means ready (or not production)."""
    if not is_production(env):
        return []
    problems: list[str] = []

    raw_dir = env.get(ONBOARDING_DIR, "").strip()
    if not raw_dir:
        problems.append(f"{ONBOARDING_DIR} is not set. Point it at a persistent volume outside the app source.")
    elif not os.path.isabs(raw_dir):
        problems.append(f"{ONBOARDING_DIR} must be an absolute path.")
    else:
        directory = Path(os.path.realpath(raw_dir))
        root = Path(os.path.realpath(app_root))
        if _inside(directory, root):
            problems.append(f"{ONBOARDING_DIR} must be outside the application source directory.")
        elif not directory.is_dir():
            problems.append(f"{ONBOARDING_DIR} must be an existing directory (mount the volume first).")
        elif not _writable(directory):
            problems.append(f"{ONBOARDING_DIR} is not writable by the app.")

    for name in SMTP_SETTINGS:
        if not env.get(name, "").strip():
            problems.append(f"{name} is not set (email delivery is required in production).")

    for name in _demo_enabled(env):
        problems.append(f"{name} must be off in production.")
    return problems


def enforce_production_config(env: Mapping[str, str] | None = None, app_root: Path | None = None) -> bool:
    """Raise ProductionConfigError listing every problem; returns True when startup may proceed."""
    source = os.environ if env is None else env
    root = Path(__file__).resolve().parent.parent if app_root is None else app_root
    problems = validate_production_config(source, root)
    if problems:
        raise ProductionConfigError(
            "M-Local refuses to start: production configuration is incomplete.\n- " + "\n- ".join(problems)
        )
    return True
