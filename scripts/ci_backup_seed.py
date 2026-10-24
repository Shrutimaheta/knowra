"""Fictional restore fixture; used only by the disposable container CI job."""

from app.main import app
from fastapi.testclient import TestClient

with TestClient(app) as client:
    client.post("/api/v1/auth/register", json={
        "email": "backup-ci@example.test", "name": "CI fixture",
        "workspace": "Disposable CI", "password": "ci-only-example-password",
    }).raise_for_status()
    client.post("/api/v1/documents", files={
        "file": ("probe.txt", b"CI restore probe", "text/plain"),
    }).raise_for_status()
print("Fictional account and immutable original created for restore drill")
