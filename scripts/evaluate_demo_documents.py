"""Check native PDF extraction and keyword retrieval against explicit source pages."""

import json
import re
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api"))


def normalize(text):
    return re.sub(r"\s+", " ", text).casefold()


def evaluate():
    from app.demo_catalog import DIRECTORY, PDF_NAMES
    from app.rag import chunk_pages, retrieve

    dataset = json.loads((ROOT / "evals/demo-corpus.json").read_text(encoding="utf-8"))
    pages, rows = {}, []
    # Only the current baseline enters retrieval. The older one remains for comparison.
    for name in sorted(PDF_NAMES):
        with pymupdf.open(DIRECTORY / name) as pdf:
            assert len(pdf) == 3, f"Unexpected pagination: {name}"
            texts = [page.get_text(sort=True) for page in pdf]
        pages[name] = texts
        if name == "atlas-requirements-v1.pdf":
            continue
        for index, (page_number, text) in enumerate(chunk_pages(texts)):
            rows.append({"id": f"{name}:{index}", "document": name, "title": name, "page": page_number, "content": text})
    results = []
    for case in dataset["cases"]:
        evidence = normalize(pages[case["file"]][case["page"] - 1])
        extraction = all(normalize(phrase) in evidence for phrase in case["evidence"])
        matches = retrieve(rows, case["question"], limit=5)
        rank = next((i + 1 for i, row in enumerate(matches) if row["document"] == case["file"] and row["page"] == case["page"]), None)
        results.append({"id": case["id"], "extraction": extraction, "source_page_rank": rank})
    return {
        "dataset": dataset["dataset"], "pdfs": len(pages), "pages": sum(len(x) for x in pages.values()),
        "questions": len(results), "extraction_passed": sum(x["extraction"] for x in results),
        "source_page_recall_at_5": sum(x["source_page_rank"] is not None for x in results) / len(results),
        "results": results,
        "scope": "Native text and exact source-page keyword retrieval on fictional fixtures; no live AI correctness claim.",
    }


if __name__ == "__main__":
    report = evaluate()
    target = ROOT / "evals/demo-corpus-report.json"
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if report["extraction_passed"] != report["questions"] or report["source_page_recall_at_5"] < .9:
        sys.exit(1)
