"""Which kind of host this build was deployed to, read from the deploy stamp.

`scripts/jachammer-stage.py` writes `assets/mlocal-build.json` into every staged
copy, with `"channel": "production"` for `jachammer-deploy.sh --prod` and
`"preview"` otherwise. Local development has no stamp.

A production build ignores the test and demo settings below, whatever the host
environment says. JacHammer project variables are set once for the project, so
the preview's sample deals and QA overrides could otherwise reach the public
site. Ignoring them (instead of refusing to start) keeps a misconfigured
redeploy from taking the live site down: the rollout stops the old pod first.
"""
import json
import os
import sys
from functools import lru_cache
from pathlib import Path

STAMP = Path(__file__).resolve().parent.parent / "assets" / "mlocal-build.json"
PRODUCTION = "production"

# Settings that only make sense on a test host. Each one either shows invented
# deals or lets an account act without a verified U-M inbox or approved business.
TEST_SETTINGS = (
    "MLOCAL_SHOW_SAMPLES",
    "MLOCAL_DEMO_MODE",
    "MLOCAL_DEMO_COMPANIES",
    "MLOCAL_DEMO_STUDENTS",
    "MLOCAL_HOSTED_DATASET",
)
_OFF = {"", "0", "false", "no", "off", "[]", "null", "{}"}


@lru_cache(maxsize=4)
def _read_channel(stamp: Path) -> str:
    try:
        value = json.loads(stamp.read_text()).get("channel", "")
    except (OSError, ValueError, AttributeError):
        return ""
    return value if isinstance(value, str) else ""


def channel(stamp: Path | None = None) -> str:
    """The stamped channel, or "" when there is no readable stamp (local development).

    The stamp never changes while a deployment runs, so each path is read once."""
    return _read_channel(STAMP if stamp is None else stamp)


def forget_channel() -> None:
    """Drop the cached stamp (tests that switch channels)."""
    _read_channel.cache_clear()


def production_build(stamp: Path | None = None) -> bool:
    return channel(stamp) == PRODUCTION


def demo_setting(name: str, default: str = "", stamp: Path | None = None) -> str:
    """Read a test-only setting; a production build always gets the default."""
    if name not in TEST_SETTINGS:
        raise ValueError(f"{name} is not a test-only setting")
    if production_build(stamp):
        return default
    return os.environ.get(name, default)


def ignored_test_settings(env=None, stamp: Path | None = None) -> list[str]:
    """Names (never values) of test settings a production build is ignoring."""
    if not production_build(stamp):
        return []
    source = os.environ if env is None else env
    return [name for name in TEST_SETTINGS if source.get(name, "").strip().lower() not in _OFF]


def announce_ignored_test_settings() -> bool:
    """Log once at startup, so the host logs show why sample deals are missing."""
    names = ignored_test_settings()
    if names:
        print("M-Local production build: ignoring test settings " + ", ".join(names)
              + " (previews still use them).", file=sys.stderr, flush=True)
    return True
