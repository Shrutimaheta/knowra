"""Run a versioned deterministic retrieval evaluation; optionally use the real local model."""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))
from app.embeddings import encode, model_name
from app.rag import retrieve


def evaluate(dataset):
    rows = [
        {
            "id": item["expected"],
            "document": item["expected"],
            "page": 1,
            "content": item["text"],
        }
        for item in dataset
        if "text" in item
    ]
    if model_name():
        vectors = encode([row["content"] for row in rows])
        for row, vector in zip(rows, vectors, strict=True):
            row.update(embedding=json.dumps(vector), embedding_model=model_name())
    records = []
    for item in dataset:
        started = time.monotonic()
        found = retrieve(rows, item["query"], limit=3)
        ranks = [r["id"] for r in found]
        records.append(
            {
                "id": item["id"],
                "expected": item["expected"],
                "top": ranks,
                "recall_at_3": int(item["expected"] in ranks),
                "top_1": int(bool(ranks) and ranks[0] == item["expected"]),
                "latency_ms": round((time.monotonic() - started) * 1000, 2),
            }
        )
    return {
        "dataset": "retrieval-v1",
        "model": model_name() or "keyword-only",
        "questions": len(records),
        "recall_at_3": sum(r["recall_at_3"] for r in records) / len(records),
        "top_1_accuracy": sum(r["top_1"] for r in records) / len(records),
        "results": records,
        "scope": "Small fictional regression set; this does not measure LLM groundedness or production accuracy.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="evals/retrieval-report.json")
    parser.add_argument("--minimum-recall", type=float, default=0)
    args = parser.parse_args()
    data = json.loads(
        (Path(__file__).resolve().parents[1] / "evals/retrieval.json").read_text(
            encoding="utf-8-sig"
        )
    )
    report = evaluate(data)
    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps({k: v for k, v in report.items() if k != "results"}, indent=2),
        flush=True,
    )
    if report["recall_at_3"] < args.minimum_recall:
        raise SystemExit("Retrieval regression threshold failed")
