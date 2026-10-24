import importlib.util
import os
import zipfile
from pathlib import Path

import pytest
from app.config import validate_demo
from app.demo import bootstrap, identity
from app.store import db


def prepare(client, monkeypatch):
    monkeypatch.setenv("DEMO_PASSWORD", "private-test-demo-password")
    bootstrap()
    monkeypatch.setenv("APP_ENV", "demo")
    response = client.post("/api/v1/auth/login", json={"email": "demo@knowra.example", "password": "private-test-demo-password"})
    assert response.status_code == 200


def test_demo_bootstrap_is_idempotent_and_contains_only_curated_sources(client, monkeypatch):
    prepare(client, monkeypatch)
    bootstrap()
    documents = client.get("/api/v1/documents").json()
    assert len(documents) == 11
    assert all(doc["status"] == "ready" for doc in documents)
    policy = identity("Workplace policy.pdf")
    versions = client.get(f"/api/v1/documents/{policy}/versions").json()
    assert len(versions) == 2
    compared = client.get(f"/api/v1/documents/{policy}/compare", params={"from_version": versions[-1]["id"], "to_version": versions[0]["id"]})
    assert compared.status_code == 200 and compared.json()["changes"]
    assert client.post("/api/v1/search", json={"content": "annual leave"}).json()
    scan = client.post("/api/v1/conflicts/scan", json={"documents": [identity("Handbook 2025.pdf"), identity("Handbook 2026.pdf")]})
    assert scan.status_code == 200
    assert client.get("/api/v1/knowledge-map").status_code == 200
    assert client.get("/api/v1/app-config").json()["demo"]


def test_demo_rejects_mutations_before_parsers_and_preserves_sources(client, monkeypatch):
    prepare(client, monkeypatch)
    for path in ("/auth/register", "/documents", "/invitations", "/demo/seed", "/members"):
        assert client.post("/api/v1" + path, json={}).status_code == 403
    assert client.delete("/api/v1/documents/" + identity("Handbook 2025.pdf")).status_code == 403
    chat = client.post("/api/v1/conversations").json()["id"]
    response = client.post(f"/api/v1/conversations/{chat}/messages", json={"content": "annual leave"})
    assert response.status_code == 200 and response.json()["citations"]
    assert client.delete(f"/api/v1/conversations/{chat}").status_code == 200


def test_demo_does_not_enable_ocr_for_receipt_highlighting(client, monkeypatch):
    prepare(client, monkeypatch)
    document = identity("Fictional expense receipt.png")
    version = client.get(f"/api/v1/documents/{document}/versions").json()[0]["id"]

    def unexpected():
        raise AssertionError("The lightweight demo must not load the OCR runtime")

    monkeypatch.setattr("app.evidence.ocr_engine", unexpected)
    result = client.post(f"/api/v1/documents/{document}/versions/{version}/evidence", json={"page": 1, "text": "Total: INR 4130"})
    assert result.status_code == 200 and result.json()["ranges"]
    assert "live image OCR is disabled" in result.json()["notice"]
    assert client.get(f"/api/v1/documents/{document}/versions/{version}/pages/1/image").status_code == 200


def test_demo_refuses_existing_private_workspace(client, monkeypatch):
    from test_workflows import register

    register(client)
    monkeypatch.setenv("DEMO_PASSWORD", "private-test-demo-password")
    with pytest.raises(RuntimeError, match="dedicated"):
        bootstrap()


def test_demo_password_rotation_revokes_previous_sessions(client, monkeypatch):
    prepare(client, monkeypatch)
    monkeypatch.setenv("DEMO_PASSWORD", "new-private-demo-password")
    bootstrap()
    assert client.get("/api/v1/users/me").status_code == 401
    with db() as c:
        assert c.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] == 1


def test_demo_config_requires_secure_persistent_storage(monkeypatch):
    settings = {"PUBLIC_URL": "https://demo.onrender.com", "COOKIE_SECURE": "true", "DATABASE_URL": "postgresql://u:password@db/neondb?sslmode=require", "DEMO_PASSWORD": "private-demo-password", "EMBEDDED_WORKER": "false", "EMBEDDING_MODEL": ""}
    for key, value in settings.items():
        monkeypatch.setenv(key, value)
    validate_demo()
    monkeypatch.setenv("DATABASE_URL", "sqlite:///temporary.db")
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        validate_demo()
    assert "private-demo-password" in os.environ["DEMO_PASSWORD"]


def test_render_bundle_has_no_private_database_or_environment(tmp_path):
    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location("render_package", root / "scripts/package_render_demo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target = tmp_path / "demo.zip"
    module.package(target)
    with zipfile.ZipFile(target) as archive:
        names = archive.namelist()
        assert "render.yaml" in names
        assert "apps/api/Dockerfile.demo" in names
        assert not any(".env" in Path(name).name or "/data/" in name or name.endswith((".db", ".gz")) for name in names)
        assert sum(name.endswith(".pdf") for name in names) == 10
