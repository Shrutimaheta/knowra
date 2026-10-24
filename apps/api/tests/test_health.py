from app.main import app
from fastapi.testclient import TestClient


def test_health(tmp_path, monkeypatch):
    monkeypatch.setenv("KNOWRA_DB", str(tmp_path / "health.db"))
    monkeypatch.setenv("EMBEDDED_WORKER", "false")
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "service": "knowra-api"}
