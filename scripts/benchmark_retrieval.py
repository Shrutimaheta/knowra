"""Repeatable in-process keyword timing on synthetic, permission-free passages."""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))
from app.rag import lexical_rank


def benchmark():
    rows = [
        {
            "id": str(i),
            "content": f"Department {i} annual leave security policy. "
            + "Employees receive annual leave and report security incidents. " * 20,
        }
        for i in range(1000)
    ]
    durations = []
    for i in range(21):
        started = time.perf_counter()
        result = lexical_rank(rows, "annual leave" if i % 2 else "security incidents")
        assert len(result) == 30
        durations.append((time.perf_counter() - started) * 1000)
    return {
        "passages": len(rows),
        "cold_ms": round(durations[0], 2),
        "warm_median_ms": round(statistics.median(durations[1:]), 2),
        "scope": "Synthetic in-process keyword ranking; excludes database, model and network latency.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = benchmark()
    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
