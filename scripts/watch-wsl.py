"""Bridge Windows saves into Linux inotify without changing source contents."""
import hashlib
import os
from pathlib import Path
import sys
import time

IGNORED = {".git", ".jac", "node_modules", ".venv", "venv", "__pycache__"}


def snapshot(root: Path) -> dict[Path, str]:
    files = {}
    for directory, names, filenames in os.walk(root):
        names[:] = [name for name in names if name not in IGNORED]
        for name in filenames:
            if not (name.endswith(".jac") or name == "jac.toml"):
                continue
            path = Path(directory) / name
            try:
                files[path] = hashlib.sha256(path.read_bytes()).hexdigest()
            except (FileNotFoundError, PermissionError):
                pass  # Editors may replace a file while saving.
    return files


if __name__ == "__main__":
    root = Path(sys.argv[1]).resolve()
    previous = snapshot(root)
    print("Windows-save bridge active (content hashes, 1 second polling).", flush=True)
    try:
        while True:
            time.sleep(1)
            current = snapshot(root)
            for path, digest in current.items():
                if previous.get(path) != digest:
                    try:
                        os.utime(path, None)
                        print(f"Source changed: {path.relative_to(root)}", flush=True)
                    except FileNotFoundError:
                        pass
            previous = current
    except KeyboardInterrupt:
        pass
