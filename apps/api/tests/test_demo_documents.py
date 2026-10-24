import hashlib
import json
from pathlib import Path

import pymupdf
from app.demo import bootstrap, identity
from app.demo_catalog import DIRECTORY, DOCUMENTS, PDF_NAMES
from test_workflows import register

ROOT = Path(__file__).resolve().parents[3]
CASES = json.loads((ROOT / "evals/demo-corpus.json").read_text(encoding="utf-8"))["cases"]


def test_business_pdfs_are_complete_selectable_and_clearly_fictional():
    for filename in PDF_NAMES:
        with pymupdf.open(DIRECTORY / filename) as pdf:
            assert len(pdf) == 3
            for page in pdf:
                text = page.get_text()
                assert len(text.split()) > 180
                assert "FICTIONAL DEMO COMPANY AND CONTENT" in text
                assert "ASTER VALE" in text
                assert all(0 <= word[0] < word[2] <= page.rect.width for word in page.get_text("words"))


def assert_searches(client):
    current_files = {names[-1]: title for title, _, names in DOCUMENTS}
    for case in CASES:
        response = client.post("/api/v1/search", json={"content": case["question"]})
        assert response.status_code == 200, case["id"]
        matches = response.json()
        assert any(row["title"] == current_files[case["file"]] and row["page"] == case["page"] for row in matches), (case["id"], [(r["title"], r["page"]) for r in matches])
    matches = client.post("/api/v1/search", json={"content": "Atlas operational retention export support response"}).json()
    assert any(row["title"] == "Atlas portal requirements.pdf" for row in matches)
    assert all(row["version"] == 2 for row in matches if row["title"] == "Atlas portal requirements.pdf")


def test_full_app_sample_ingestion_and_retrieval_use_actual_pdfs(client):
    register(client)
    assert client.post("/api/v1/demo/seed").json()["created"] == 11
    assert client.post("/api/v1/demo/seed").json()["created"] == 0
    documents = client.get("/api/v1/documents").json()
    assert len(documents) == 11
    assert all(row["status"] == "ready" for row in documents)
    assert_searches(client)


def test_cloud_demo_preserves_requirement_versions_and_originals(client, monkeypatch):
    monkeypatch.setenv("DEMO_PASSWORD", "fictional-demo-password")
    bootstrap()
    monkeypatch.setenv("APP_ENV", "demo")
    assert client.post("/api/v1/auth/login", json={"email": "demo@knowra.example", "password": "fictional-demo-password"}).status_code == 200
    assert_searches(client)
    document = identity("Atlas portal requirements.pdf")
    versions = client.get(f"/api/v1/documents/{document}/versions").json()
    by_number = {row["number"]: row for row in versions}
    assert set(by_number) == {1, 2}
    original = client.get(f"/api/v1/documents/{document}/versions/{by_number[2]['id']}/original")
    assert original.status_code == 200
    assert hashlib.sha256(original.content).digest() == hashlib.sha256((DIRECTORY / "atlas-requirements-v2.pdf").read_bytes()).digest()
    compared = client.get(f"/api/v1/documents/{document}/compare", params={"from_version": by_number[1]["id"], "to_version": by_number[2]["id"]})
    assert compared.status_code == 200
    changes = json.dumps(compared.json()["changes"])
    assert "180 days" in changes and "90 days" in changes
    assert "1 hour" in changes and "4 hours" in changes
