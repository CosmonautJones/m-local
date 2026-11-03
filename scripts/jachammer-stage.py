#!/usr/bin/env python3
"""Stage a JacHammer-deployable copy of the committed source.

The repository's jac.toml stays in the shape the pinned Jac 0.37.23 runtime,
the release package launcher and CI expect. JacHammer needs a few differences,
so they are written only into a staged copy:

* `[project] entry-point`/`kind` move to an explicit `[apps.m-local]` app, which
  is what lets jac-scale read the per-app scale settings below.
* One app replica, no autoscaler, and a rollout that stops the old pod before
  starting the new one. The pinned runtime is unsafe with competing writers
  (docs/review/stock-topology), and a ReadWriteOnce volume cannot attach to two
  pods anyway.
* One request thread per process, so mutations are not interleaved.
* Persistent volumes for private onboarding state (MLOCAL_ONBOARDING_DIR lives
  under /srv/m-local) and uploaded photos (assets/photos).
* Jac's native `/user/register` is throttled to one attempt an hour behind a
  proof-of-work challenge (`[serve.auth]`). M-Local never uses it: accounts are
  made by the email-code flow inside the server. JacHammer's gateway cannot
  refuse the route outright, so this is the closest available closure (#40).
  `--open-native-registration` leaves it open for QA provisioning only.
* PyPI pins move to `[dependencies.pypi]`, which JacHammer's staging requires.
  Pinned 0.37.23 ignores that table; Pillow still arrives with the runtime and
  psycopg is only imported by the opt-in SQL modes, which a hosted test never
  selects.

docs/ and tests/ are omitted: they are not needed at runtime and the demo video
alone pushes the upload past JacHammer's ~10MB cap.

The staged copy contains only files tracked at HEAD, so local stores, keys and
other ignored private state are never uploaded.
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

APP = "m-local"
OMIT_TOP = {"docs", "tests"}
APP_BLOCK = [
    f"[apps.{APP}]",
    'kind = "web-app"',
    'entry-point = "main"',
    "",
    f"[apps.{APP}.scale]",
    "replicas = 1",
    "workers = 1",
    "threads = 1",
    "",
    f"[apps.{APP}.scale.hpa]",
    "enabled = false",
    "",
    f"[apps.{APP}.scale.deployment_overlay.spec.strategy.rollingUpdate]",
    "maxSurge = 0",
    "maxUnavailable = 1",
    "",
    f"[apps.{APP}.scale.deployment_overlay.spec.template.spec]",
    "terminationGracePeriodSeconds = 8",
    "",
    "[[scale.gateway.shared_volumes]]",
    'name = "mlocal-state"',
    'mount_path = "/srv/m-local"',
    f'apps = ["{APP}"]',
    'size = "5Gi"',
    'access_mode = "ReadWriteOnce"',
    "",
    "[[scale.gateway.shared_volumes]]",
    'name = "mlocal-photos"',
    'mount_path = "/app/assets/photos"',
    f'apps = ["{APP}"]',
    'size = "2Gi"',
    'access_mode = "ReadWriteOnce"',
    "",
]
AUTH_BLOCK = [
    "[serve.auth]",
    "registration_challenge = true",
    "registration_attempts_per_hour = 1",
    "registration_challenges_per_10_minutes = 2",
    "",
]


class StageError(Exception):
    pass


def _table(line: str) -> str | None:
    text = line.strip()
    if text.startswith("[") and text.endswith("]"):
        return text.strip("[]").strip()
    return None


def transform(text: str, open_registration: bool = False) -> str:
    """Return the JacHammer variant of jac.toml, preserving each line's ending."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    section = ""
    seen = {"entry": False, "kind": False, "pypi": False, "inserted": False}
    for line in lines:
        name = _table(line)
        if name is not None:
            section = name
            if name.startswith("apps.") or name in ("dependencies.pypi", "serve.auth"):
                raise StageError(f"jac.toml already declares [{name}]; refusing to stage over it.")
            if name == "scale.admin" and not seen["inserted"]:
                out.extend(entry + "\n" for entry in APP_BLOCK + ([] if open_registration else AUTH_BLOCK))
                seen["inserted"] = True
            if name == "dependencies":
                out.append(line.replace("[dependencies]", "[dependencies.pypi]", 1))
                seen["pypi"] = True
                continue
        stripped = line.strip()
        if section == "project" and stripped.replace(" ", "") == 'entry-point="main"':
            seen["entry"] = True
            continue
        if section == "project" and stripped.replace(" ", "") == 'kind="web-app"':
            seen["kind"] = True
            continue
        if section == "dependencies" and stripped and not stripped.startswith("#") and "=" in stripped:
            value = stripped.split("=", 1)[1].strip()
            if not value.startswith('"'):
                raise StageError(f"Unexpected [dependencies] entry: {stripped!r}")
        out.append(line)
    missing = [key for key, ok in seen.items() if not ok]
    if missing:
        raise StageError("jac.toml no longer has the expected layout (" + ", ".join(missing) + "); update scripts/jachammer-stage.py.")
    return "".join(out)


def tracked_files(source: Path) -> list[str]:
    result = subprocess.run(["git", "-C", str(source), "ls-files", "-z"], capture_output=True, check=True)
    return [p for p in result.stdout.decode().split("\0") if p]


def stage(source: Path, target: Path, open_registration: bool = False) -> int:
    if target.exists() and any(target.iterdir()):
        raise StageError(f"{target} is not empty; choose a fresh directory.")
    dirty = subprocess.run(["git", "-C", str(source), "status", "--porcelain", "--untracked-files=no"],
                           capture_output=True, text=True, check=True).stdout.strip()
    if dirty:
        raise StageError("Tracked files have uncommitted changes; commit them so the staged copy matches a revision.")
    target.mkdir(parents=True, exist_ok=True)
    count = 0
    for rel in tracked_files(source):
        if rel.split("/", 1)[0] in OMIT_TOP:
            continue
        src = source / rel
        if not src.is_file() or src.is_symlink():
            continue
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        count += 1
    toml = target / "jac.toml"
    toml.write_bytes(transform(toml.read_bytes().decode("utf-8"), open_registration).encode("utf-8"))
    revision = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    (target / ".jachammer-source-revision").write_text(revision + "\n")
    return count


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("target", type=Path, help="new or empty directory for the staged copy")
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--open-native-registration", action="store_true",
                        help="leave Jac's /user/register unthrottled (QA provisioning on a preview only)")
    args = parser.parse_args(argv)
    try:
        count = stage(args.source.resolve(), args.target.resolve(), args.open_native_registration)
    except (StageError, subprocess.CalledProcessError, OSError) as error:
        print(f"jachammer-stage: {error}", file=sys.stderr)
        return 1
    print(f"Staged {count} files in {args.target}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
