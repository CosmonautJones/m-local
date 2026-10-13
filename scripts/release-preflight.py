"""Entry point for local package/config/state/evidence validation; no network writes."""
import runpy
from pathlib import Path
import sys

sys.argv.insert(1, "preflight")
runpy.run_path(str(Path(__file__).resolve().parents[1] / "deploy/release/package.py"), run_name="__main__")
