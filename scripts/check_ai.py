"""Check the selected AI connection using fictional evidence; never print credentials."""

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api"))


def load_local_settings():
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            match = re.match(r"^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$", line)
            if match:
                os.environ.setdefault(match[1], match[2].strip().strip('"').strip("'"))


def main():
    load_local_settings()
    from app.providers import generation_provider
    from app.rag import stream_answer
    from fastapi import HTTPException

    provider = generation_provider()
    if not provider:
        print("No AI key configured. The application is in evidence-only mode.")
        return 1
    print("Provider:", provider.name, "| Model:", provider.model, flush=True)
    source = {
        "title": "Fictional demo leave policy",
        "page": 1,
        "version": 1,
        "content": "FICTIONAL TEST DATA: Annual leave allowance is 24 days in 2026, compared with 20 days in 2025.",
    }
    try:
        events = list(
            stream_answer(
                "How many days did annual leave increase? Cite the source.",
                [source],
                [],
            )
        )
    except HTTPException as error:
        print("Connection check failed:", error.detail)
        return 1
    text = "".join(event.get("text", "") for event in events)
    usage = next((event for event in events if event["type"] == "usage"), {})
    print(
        "Live streaming check succeeded. Provider-reported tokens:",
        usage.get("tokens", 0),
    )
    print("Answer:", text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
