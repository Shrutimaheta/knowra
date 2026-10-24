"""Cross-platform launcher; reads ignored local settings without printing them."""

import argparse
import os
import sys
from pathlib import Path

from check_ai import load_local_settings

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    load_local_settings()
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    args = parser.parse_args()
    os.chdir(ROOT / "apps/api")
    os.execv(sys.executable, [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(args.port)])
