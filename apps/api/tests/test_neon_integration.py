import io
import time

import jwt
from app.store import db
from test_workflows import register, upload


class Objects:
    def __init__(self):
        self.values = {}

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.values[(Bucket, Key)] = Body

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.values[(Bucket, Key)])}


def test_object_original_round_trip_and_access_controls(client, monkeypatch):
    register(client)
    objects = Objects()
    monkeypatch.setenv("ORIGINAL_STORAGE", "neon")
    monkeypatch.setattr("app.object_storage.client", lambda: objects)
    document = upload(client, "Fictional annual leave is 24 days.", visibility="private")
    version = client.get(f"/api/v1/documents/{document}/versions").json()[0]["id"]
    path = f"/api/v1/documents/{document}/versions/{version}/original"
    assert client.get(path).content == b"Fictional annual leave is 24 days."
    with db() as connection:
        row = connection.execute("SELECT original,original_key,original_size FROM document_versions WHERE id=?", (version,)).fetchone()
    assert row["original"] is None and row["original_key"] in {key for _, key in objects.values}
    assert row["original_size"] == 34
    client.post("/api/v1/auth/logout")
    register(client, "other@example.test")
    assert client.get(path).status_code == 404


def test_neon_exchange_binds_subject_and_limits_session_lifetime(client, monkeypatch):
    monkeypatch.setenv("AUTH_PROVIDER", "neon")
    expiration = time.time() + 120
    monkeypatch.setattr("app.neon_auth.verify", lambda token: {"sub": "test-managed-subject", "email": "managed@example.test", "name": "Managed user", "exp": expiration})
    response = client.post("/api/v1/auth/neon", json={"token": "a" * 30, "workspace": "Managed workspace"})
    assert response.status_code == 200
    first = client.get("/api/v1/users/me").json()
    assert first["workspace"] == "Managed workspace"
    assert client.post("/api/v1/auth/neon", json={"token": "b" * 30}).status_code == 200
    assert client.get("/api/v1/users/me").json()["id"] == first["id"]
    with db() as connection:
        sessions = connection.execute("SELECT expires FROM sessions").fetchall()
        assert all(row["expires"] <= expiration for row in sessions)
        assert connection.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] == 1
    assert client.post("/api/v1/auth/login", json={"email": first["email"], "password": "not-a-managed-login"}).status_code == 409


def test_neon_identity_cannot_claim_existing_local_email(client, monkeypatch):
    register(client)
    monkeypatch.setenv("AUTH_PROVIDER", "neon")
    monkeypatch.setattr("app.neon_auth.verify", lambda token: {"sub": "unrelated", "email": "owner@example.test", "exp": time.time() + 120})
    assert client.post("/api/v1/auth/neon", json={"token": "x" * 30}).status_code == 409


def test_invalid_managed_token_is_rejected(client, monkeypatch):
    monkeypatch.setenv("AUTH_PROVIDER", "neon")
    monkeypatch.setenv("NEON_AUTH_BASE_URL", "https://auth.example.test/auth")
    monkeypatch.setenv("NEON_AUTH_JWKS_URL", "https://auth.example.test/jwks")

    class Invalid:
        def get_signing_key_from_jwt(self, token):
            raise jwt.InvalidTokenError()

    monkeypatch.setattr("app.neon_auth.jwks", lambda url: Invalid())
    assert client.post("/api/v1/auth/neon", json={"token": "bad-token-" * 4}).status_code == 401


def test_integrity_does_not_call_function_for_inaccessible_source(client, monkeypatch):
    register(client)
    document = upload(client)
    version = client.get(f"/api/v1/documents/{document}/versions").json()[0]["id"]
    calls = []
    monkeypatch.setattr("app.neon_functions.source_integrity", lambda *args: calls.append(args) or {"verified": True})
    assert client.get(f"/api/v1/documents/{document}/versions/{version}/integrity").json()["verified"]
    assert len(calls) == 1
    client.post("/api/v1/auth/logout")
    register(client, "outsider@example.test")
    assert client.get(f"/api/v1/documents/{document}/versions/{version}/integrity").status_code == 404
    assert len(calls) == 1
