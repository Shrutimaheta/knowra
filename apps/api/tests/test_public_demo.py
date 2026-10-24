import time

import pytest
from app.demo import bootstrap, consume_question, identity
from app.main import app, request_count
from app.store import db
from fastapi import HTTPException
from fastapi.testclient import TestClient


def prepare(monkeypatch):
    monkeypatch.setenv("DEMO_PASSWORD", "private-test-demo-password")
    bootstrap()
    monkeypatch.setenv("APP_ENV", "demo")


def enter(client):
    response = client.post("/api/v1/auth/demo")
    assert response.status_code == 200
    assert "httponly" in response.headers.get("set-cookie", "").lower()
    return client.get("/api/v1/users/me").json()


def test_direct_dashboard_is_demo_only_and_has_no_login_flash(client, monkeypatch):
    assert client.post("/api/v1/auth/demo").status_code == 404
    assert client.get("/api/v1/users/me").status_code == 401
    assert 'id="auth" class="auth-layout"' in client.get("/").text
    prepare(monkeypatch)
    assert client.get("/api/v1/app-config").json()["public_dashboard"]
    html = client.get("/").text
    assert 'id="auth" class="auth-layout hidden"' in html
    assert 'id="demo-loading" class="loading"' in html
    monkeypatch.setenv("DEMO_PUBLIC_DASHBOARD", "false")
    assert client.post("/api/v1/auth/demo").status_code == 404


def test_visitor_reload_is_stable_and_reviewer_session_is_not_reused(client, monkeypatch):
    prepare(monkeypatch)
    client.post("/api/v1/auth/login", json={"email": "demo@knowra.example", "password": "private-test-demo-password"})
    user = enter(client)
    assert user["id"] != identity("reviewer") and user["role"] == "viewer"
    assert client.post("/api/v1/auth/demo").status_code == 200
    assert client.get("/api/v1/users/me").json()["id"] == user["id"]
    bootstrap()  # A restart must allow only explicitly registered visitor identities.
    with db() as c:
        assert c.execute("SELECT COUNT(*) AS n FROM demo_visitors").fetchone()["n"] == 1
        assert c.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] == 2


def test_visitors_cannot_read_edit_or_count_each_others_conversations(client, monkeypatch):
    prepare(monkeypatch)
    first = enter(client)
    conversation = client.post("/api/v1/conversations").json()["id"]
    answer = client.post(f"/api/v1/conversations/{conversation}/messages", json={"content": "annual leave"}).json()
    assert answer["citations"]
    other = TestClient(app)
    try:
        second = enter(other)
        assert first["id"] != second["id"] and first["org"] == second["org"]
        assert len(other.get("/api/v1/documents").json()) == 11
        assert other.get("/api/v1/conversations").json() == []
        assert other.get(f"/api/v1/conversations/{conversation}/messages").status_code == 404
        assert other.delete(f"/api/v1/conversations/{conversation}").status_code == 404
        assert other.post(f"/api/v1/messages/{answer['id']}/feedback", json={"value": 1}).status_code == 404
        assert other.get("/api/v1/analytics").json()["questions"] == 0
        assert other.get("/api/v1/knowledge-map").json()["stats"]["answers"] == 0
        documents = [identity("Handbook 2025.pdf"), identity("Handbook 2026.pdf")]
        finding = client.post("/api/v1/conflicts/scan", json={"documents": documents}).json()["findings"][0]
        sources = finding["sources"]
        assert client.post("/api/v1/conflicts/review", json={
            "left_version": sources[0]["version_id"], "right_version": sources[1]["version_id"],
            "fingerprint": finding["id"], "status": "dismissed", "note": "Only the first visitor sees this review.",
        }).status_code == 200
        rescanned = other.post("/api/v1/conflicts/scan", json={"documents": documents}).json()
        personal = next(row for row in rescanned["findings"] if row["id"] == finding["id"])["review"]
        assert personal["status"] == "open" and personal["note"] == ""
        assert other.get("/api/v1/members").status_code == 403
        assert other.post("/api/v1/documents", json={}).status_code == 403
    finally:
        other.close()


def test_expired_visitors_are_cleaned_without_removing_sources_or_reviewer(client, monkeypatch):
    prepare(monkeypatch)
    visitor = enter(client)
    conversation = client.post("/api/v1/conversations").json()["id"]
    with db() as c:
        c.execute("UPDATE demo_visitors SET expires=? WHERE user_id=?", (time.time() - 1, visitor["id"]))
    assert client.post("/api/v1/auth/demo").status_code == 200
    replacement = client.get("/api/v1/users/me").json()
    assert replacement["id"] != visitor["id"]
    with db() as c:
        assert not c.execute("SELECT id FROM users WHERE id=?", (visitor["id"],)).fetchone()
        assert not c.execute("SELECT id FROM conversations WHERE id=?", (conversation,)).fetchone()
        assert c.execute("SELECT id FROM users WHERE id=?", (identity("reviewer"),)).fetchone()
        assert c.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"] == 11


def test_daily_budget_persists_and_rate_cleanup_cannot_erase_it(client, monkeypatch):
    prepare(monkeypatch)
    visitor = enter(client)
    now = [time.time()]
    monkeypatch.setattr("app.demo.time.time", lambda: now[0])
    for _ in range(8):
        consume_question(visitor)
        now[0] += 61
    request_count("unrelated-api", int(now[0] // 60))
    with pytest.raises(HTTPException) as caught:
        consume_question(visitor)
    assert caught.value.status_code == 429 and "daily" in caught.value.detail
    with db() as c:
        assert c.execute("SELECT count FROM demo_usage WHERE bucket='all-visitors'").fetchone()["count"] == 8


def test_shared_budget_cannot_be_reset_with_a_new_cookie(client, monkeypatch):
    prepare(monkeypatch)
    monkeypatch.setattr("app.demo.DAILY_QUESTIONS", 1)
    consume_question(enter(client))
    client.cookies.clear()
    other = enter(client)
    with pytest.raises(HTTPException) as caught:
        consume_question(other)
    assert caught.value.status_code == 429 and "shared" in caught.value.detail
    with db() as c:
        # Failed admission must roll back the new visitor's reservation as well.
        assert not c.execute("SELECT count FROM demo_usage WHERE bucket=?", ("visitor:" + other["id"],)).fetchone()


def test_budget_refuses_generation_before_provider_call_and_keeps_search(client, monkeypatch):
    prepare(monkeypatch)
    enter(client)
    conversation = client.post("/api/v1/conversations").json()["id"]
    monkeypatch.setattr("app.demo.VISITOR_QUESTIONS", 1)
    monkeypatch.setattr("app.demo.DAILY_QUESTIONS", 1)
    assert client.post(f"/api/v1/conversations/{conversation}/messages", json={"content": "annual leave"}).status_code == 200
    def forbidden(*args, **kwargs):
        raise AssertionError("No provider call is allowed after budget exhaustion")
    monkeypatch.setattr("app.main.stream_answer", forbidden)
    response = client.post(f"/api/v1/conversations/{conversation}/messages", json={"content": "annual leave"})
    assert response.status_code == 429
    assert client.post("/api/v1/search", json={"content": "annual leave"}).json()
    assert len(client.get(f"/api/v1/conversations/{conversation}/messages").json()) == 2


def test_visitor_capacity_is_bounded(client, monkeypatch):
    prepare(monkeypatch)
    enter(client)
    monkeypatch.setattr("app.demo.MAX_VISITORS", 1)
    client.cookies.clear()
    assert client.post("/api/v1/auth/demo").status_code == 503
