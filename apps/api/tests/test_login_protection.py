from app import security
from app.routes.common import client_ip
from app.store import db
from fastapi import Request
from test_workflows import register

EMAIL = "owner@example.test"
GOOD = "strong-test-password"


def attempt(client, password, email=EMAIL):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def test_account_locks_after_repeated_failures_even_with_right_password(client):
    register(client)
    client.post("/api/v1/auth/logout")
    for _ in range(security.LOGIN_MAX_FAILURES - 1):
        assert attempt(client, "wrong-password").status_code == 401
    locked = attempt(client, "wrong-password")
    assert locked.status_code == 429
    assert locked.headers["Retry-After"] == "900"
    # While locked, even the correct password is refused.
    assert attempt(client, GOOD).status_code == 429


def test_lock_expires(client, monkeypatch):
    register(client)
    client.post("/api/v1/auth/logout")
    for _ in range(security.LOGIN_MAX_FAILURES):
        attempt(client, "wrong-password")
    later = security.time.time() + security.LOGIN_LOCK_SECONDS + 1
    monkeypatch.setattr(security.time, "time", lambda: later)
    assert attempt(client, GOOD).status_code == 200


def test_success_resets_the_failure_count(client):
    register(client)
    client.post("/api/v1/auth/logout")
    for _ in range(security.LOGIN_MAX_FAILURES - 1):
        attempt(client, "wrong-password")
    assert attempt(client, GOOD).status_code == 200
    client.post("/api/v1/auth/logout")
    # A fresh count: four more misses are still below the limit.
    for _ in range(security.LOGIN_MAX_FAILURES - 1):
        assert attempt(client, "wrong-password").status_code == 401


def test_lockout_is_per_account(client):
    register(client)
    register(client, "second@example.test")
    client.post("/api/v1/auth/logout")
    for _ in range(security.LOGIN_MAX_FAILURES):
        attempt(client, "wrong-password")
    assert attempt(client, GOOD, "second@example.test").status_code == 200


def test_unknown_emails_lock_the_same_way(client):
    # Identical behaviour for unregistered emails reveals nothing about accounts.
    for _ in range(security.LOGIN_MAX_FAILURES - 1):
        assert attempt(client, "wrong-password", "nobody@example.test").status_code == 401
    assert attempt(client, "wrong-password", "nobody@example.test").status_code == 429


def test_password_reset_unlocks_and_stores_no_addresses(client):
    register(client)
    client.post("/api/v1/auth/logout")
    for _ in range(security.LOGIN_MAX_FAILURES):
        attempt(client, "wrong-password")
    with db() as c:
        accounts = [r["account"] for r in c.execute("SELECT account FROM login_failures")]
        assert accounts == [security.digest(EMAIL)]
        user_id = c.execute("SELECT id FROM users WHERE email=?", (EMAIL,)).fetchone()["id"]
        token = security.issue_token(c, "reset", user_id=user_id)
    reset = client.post(
        "/api/v1/auth/reset-password", json={"token": token, "password": "a-new-strong-password"}
    )
    assert reset.status_code == 200
    assert attempt(client, "a-new-strong-password").status_code == 200


def request_from(ip, headers=()):
    return Request({
        "type": "http", "method": "GET", "path": "/", "scheme": "https",
        "headers": [(k.encode(), v.encode()) for k, v in headers],
        "server": ("localhost", 443), "client": (ip, 1234), "query_string": b"",
    })


def test_client_ip_uses_vercel_header_only_on_vercel(monkeypatch):
    forwarded = [("x-vercel-forwarded-for", "203.0.113.7, 10.0.0.1")]
    monkeypatch.delenv("VERCEL", raising=False)
    # Off Vercel the header is client-controlled, so it must be ignored.
    assert client_ip(request_from("10.1.1.1", forwarded)) == "10.1.1.1"
    monkeypatch.setenv("VERCEL", "1")
    assert client_ip(request_from("10.1.1.1", forwarded)) == "203.0.113.7"
    assert client_ip(request_from("10.1.1.1")) == "10.1.1.1"
