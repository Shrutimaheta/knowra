import json
import re
from pathlib import Path

from app.rag import retrieve, stream_answer
from app.security import digest
from app.store import db, initialize
from app.worker import run_once
from fastapi import HTTPException
from test_workflows import register, upload


def token_from_outbox(monkeypatch, kind):
    files = list(Path(__import__("os").environ["MAIL_OUTBOX"]).glob("*.eml"))
    from email import policy
    from email.parser import Parser

    message = Parser(policy=policy.default).parsestr(files[-1].read_text())
    return re.search(r"#" + kind + r"=([A-Za-z0-9_-]+)", message.get_content()).group(1)


def test_immutable_versions_and_originals(client):
    register(client)
    document = upload(client, "Vacation allowance is 20 days.")
    first = client.get(f"/api/v1/documents/{document}/versions").json()[0]
    chat = client.post("/api/v1/conversations").json()["id"]
    old = client.post(
        f"/api/v1/conversations/{chat}/messages", json={"content": "vacation allowance"}
    ).json()
    assert old["citations"][0]["version_id"] == first["id"]
    result = client.post(
        f"/api/v1/documents/{document}/versions",
        files={"file": ("new.txt", b"Vacation allowance is 24 days.", "text/plain")},
    )
    assert result.status_code == 201
    second = result.json()["version_id"]
    assert (
        client.get(
            f"/api/v1/documents/{document}/versions/{first['id']}/original"
        ).content
        == b"Vacation allowance is 20 days."
    )
    assert (
        client.get(f"/api/v1/documents/{document}/versions/{second}/original").content
        == b"Vacation allowance is 24 days."
    )
    found = client.post("/api/v1/search", json={"content": "vacation allowance"}).json()
    assert all(r["version_id"] == second for r in found)
    saved = client.get(f"/api/v1/conversations/{chat}/messages").json()[1]
    assert saved["citations"][0]["version_id"] == first["id"]
    assert len(client.get(f"/api/v1/documents/{document}/versions").json()) == 2


def test_version_routes_do_not_leak_between_tenants(client):
    register(client)
    document = upload(client)
    version = client.get(f"/api/v1/documents/{document}/versions").json()[0]["id"]
    client.post("/api/v1/auth/logout")
    register(client, "other@example.test")
    for suffix in ["versions", f"versions/{version}", f"versions/{version}/original"]:
        assert client.get(f"/api/v1/documents/{document}/{suffix}").status_code == 404
    assert (
        client.post(
            f"/api/v1/documents/{document}/versions",
            files={"file": ("test.txt", b"new content")},
        ).status_code
        == 404
    )


def test_durable_job_recovers_after_worker_crash(client, monkeypatch):
    register(client)
    monkeypatch.setenv("EAGER_INGESTION", "false")
    document = upload(client)
    with db() as c:
        job = c.execute("SELECT * FROM ingestion_jobs").fetchone()
        c.execute(
            "UPDATE ingestion_jobs SET status='running',attempts=1,lease_token='dead-worker',lease_until=0 WHERE id=?",
            (job["id"],),
        )
    initialize()
    assert run_once()
    assert not run_once()
    assert client.get("/api/v1/documents/" + document).json()["status"] == "ready"
    with db() as c:
        assert c.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"] == 1
        assert (
            c.execute("SELECT attempts FROM ingestion_jobs").fetchone()["attempts"] == 2
        )


def test_bounded_retry_and_manual_retry(client, monkeypatch):
    register(client)
    monkeypatch.setenv("EAGER_INGESTION", "false")
    document = upload(client)

    def unavailable(texts):
        raise RuntimeError("Model unavailable")

    monkeypatch.setattr("app.worker.encode", unavailable)
    for _ in range(3):
        with db() as c:
            c.execute("UPDATE ingestion_jobs SET available=0")
        assert run_once()
    assert not run_once()
    assert client.get("/api/v1/documents/" + document).json()["status"] == "failed"
    assert client.post(f"/api/v1/documents/{document}/retry").status_code == 200
    monkeypatch.setattr("app.worker.encode", lambda texts: [None] * len(texts))
    assert run_once()
    assert client.get("/api/v1/documents/" + document).json()["status"] == "ready"


def test_password_change_revokes_other_sessions(client):
    register(client)
    previous = client.cookies.get("knowra_session")
    client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.test", "password": "strong-test-password"},
    )
    assert len(client.get("/api/v1/auth/sessions").json()) == 2
    assert (
        client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "incorrect",
                "new_password": "new-strong-password",
            },
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "strong-test-password",
                "new_password": "new-strong-password",
            },
        ).status_code
        == 200
    )
    assert len(client.get("/api/v1/auth/sessions").json()) == 1
    current = client.cookies.get("knowra_session")
    client.cookies.set("knowra_session", previous)
    assert client.get("/api/v1/users/me").status_code == 401
    client.cookies.clear()
    client.cookies.set("knowra_session", current)
    assert client.get("/api/v1/users/me").status_code == 200


def test_password_reset_is_single_use_and_revokes_sessions(client, monkeypatch):
    register(client)
    assert (
        client.post(
            "/api/v1/auth/forgot-password", json={"email": "nobody@example.test"}
        ).json()
        == client.post(
            "/api/v1/auth/forgot-password", json={"email": "owner@example.test"}
        ).json()
    )
    token = token_from_outbox(monkeypatch, "reset")
    with db() as c:
        stored = c.execute("SELECT token FROM account_tokens").fetchone()["token"]
        assert stored == digest(token) and stored != token
    result = client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "password": "replacement-password"},
    )
    assert result.status_code == 200
    assert client.get("/api/v1/users/me").status_code == 401
    assert (
        client.post(
            "/api/v1/auth/reset-password",
            json={"token": token, "password": "replacement-password"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": "owner@example.test", "password": "replacement-password"},
        ).status_code
        == 200
    )


def test_invitation_expiry_and_role(client, monkeypatch):
    original = register(client)
    assert (
        client.post(
            "/api/v1/invitations",
            json={"email": "invited@example.test", "role": "viewer"},
        ).status_code
        == 201
    )
    token = token_from_outbox(monkeypatch, "invite")
    client.post("/api/v1/auth/logout")
    accepted = client.post(
        "/api/v1/invitations/accept",
        json={"token": token, "name": "Invited", "password": "invited-password"},
    )
    assert accepted.status_code == 201
    user = client.get("/api/v1/users/me").json()
    assert user["org"] == original["org"] and user["role"] == "viewer"
    assert client.get("/api/v1/audit").status_code == 403
    assert (
        client.post(
            "/api/v1/invitations/accept",
            json={"token": token, "name": "Again", "password": "invited-password"},
        ).status_code
        == 400
    )


def test_expired_reset_link(client, monkeypatch):
    register(client)
    client.post("/api/v1/auth/forgot-password", json={"email": "owner@example.test"})
    token = token_from_outbox(monkeypatch, "reset")
    with db() as c:
        c.execute("UPDATE account_tokens SET expires=0")
    assert (
        client.post(
            "/api/v1/auth/reset-password",
            json={"token": token, "password": "replacement-password"},
        ).status_code
        == 400
    )


def test_revoke_session_is_user_scoped(client):
    register(client)
    session = client.get("/api/v1/auth/sessions").json()[0]
    assert session["current"]
    assert client.delete("/api/v1/auth/sessions/" + session["id"]).status_code == 200
    assert client.get("/api/v1/users/me").status_code == 401


def test_stream_saves_only_complete_answer(client):
    register(client)
    upload(client)
    conversation = client.post("/api/v1/conversations").json()["id"]
    response = client.post(
        f"/api/v1/conversations/{conversation}/stream", json={"content": "annual leave"}
    )
    assert response.headers["content-type"].startswith("text/event-stream")
    events = [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert events[0]["type"] == "citations"
    assert any(event["type"] == "delta" for event in events)
    assert events[-1]["type"] == "done"
    assert len(client.get(f"/api/v1/conversations/{conversation}/messages").json()) == 2


def test_interrupted_stream_does_not_save_partial_answer(client, monkeypatch):
    register(client)
    upload(client)
    conversation = client.post("/api/v1/conversations").json()["id"]

    def interrupted(*args):
        yield {"type": "delta", "text": "Partial output"}
        raise HTTPException(502, "Provider interrupted")

    monkeypatch.setattr("app.main.stream_answer", interrupted)
    response = client.post(
        f"/api/v1/conversations/{conversation}/stream", json={"content": "leave"}
    )
    assert "Provider interrupted" in response.text
    assert client.get(f"/api/v1/conversations/{conversation}/messages").json() == []
    with db() as c:
        assert not c.execute("SELECT * FROM chat_runs").fetchall()


def test_hybrid_semantic_candidates_without_keyword_overlap(monkeypatch):
    rows = [
        {
            "id": "vacation",
            "content": "Employees receive 24 days of annual leave.",
            "document": "one",
        },
        {
            "id": "security",
            "content": "Enable multifactor authentication.",
            "document": "two",
        },
    ]
    monkeypatch.setattr(
        "app.embeddings.semantic_rank", lambda rows, query: [(0.8, rows[0])]
    )
    result = retrieve(rows, "vacation entitlement")
    assert result[0]["id"] == "vacation"
    assert result[0]["matched_by"] == ["semantic"]


def test_limits_are_shared_and_quota_is_enforced(client, monkeypatch):
    register(client)
    monkeypatch.setenv("WORKSPACE_STORAGE_MB", "0")
    assert (
        client.post(
            "/api/v1/documents", files={"file": ("test.txt", b"hello")}
        ).status_code
        == 413
    )
    with db() as c:
        c.execute("UPDATE request_limits SET count=10000")
    assert client.get("/api/v1/documents").status_code == 429


def test_health_migration_and_conversation_delete(client):
    register(client)
    assert client.get("/api/v1/health/ready").json()["revision"] == "0006"
    conversation = client.post("/api/v1/conversations").json()["id"]
    assert client.delete("/api/v1/conversations/" + conversation).status_code == 200
    assert (
        client.get(f"/api/v1/conversations/{conversation}/messages").status_code == 404
    )


def test_provider_stream_protocol(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key-for-protocol-test")

    class Provider:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def raise_for_status(self):
            pass

        def iter_lines(self):
            yield "data: " + json.dumps(
                {"choices": [{"delta": {"content": "24 days [1]."}}]}
            )
            yield "data: " + json.dumps({"choices": [], "usage": {"total_tokens": 42}})
            yield "data: [DONE]"

    monkeypatch.setattr("app.rag.httpx.stream", lambda *args, **kwargs: Provider())
    events = list(
        stream_answer(
            "leave", [{"title": "Policy", "page": 1, "content": "24 days"}], []
        )
    )
    assert events[0]["text"] == "24 days [1]."
    assert events[-1]["tokens"] == 42


def test_semantic_search_preserves_private_document_boundary(client, monkeypatch):
    register(client)
    monkeypatch.setenv("EMBEDDING_MODEL", "test-384")

    def vectors(texts):
        return [
            [1.0, 0.0] + [0.0] * 382
            if "acquisition" in text.lower()
            else [0.0, 1.0] + [0.0] * 382
            for text in texts
        ]

    monkeypatch.setattr("app.worker.encode", vectors)
    monkeypatch.setattr("app.main.query_vector", lambda query: vectors([query])[0])
    monkeypatch.setattr("app.embeddings.query_vector", lambda query: vectors([query])[0])
    private = upload(client, "Confidential acquisition strategy.", visibility="private")
    upload(client, "Travel reimbursement policy.")
    result = client.post("/api/v1/search", json={"content": "acquisition"}).json()
    assert any(row["document"] == private for row in result)
    client.post(
        "/api/v1/members",
        json={
            "name": "Viewer",
            "email": "semantic-viewer@example.test",
            "password": "viewer-safe-password",
            "role": "viewer",
        },
    )
    client.post("/api/v1/auth/logout")
    client.post(
        "/api/v1/auth/login",
        json={
            "email": "semantic-viewer@example.test",
            "password": "viewer-safe-password",
        },
    )
    assert client.post("/api/v1/search", json={"content": "acquisition"}).json() == []


def test_recovery_mail_failure_does_not_enumerate_or_issue_token(client, monkeypatch):
    register(client)

    def fail(*args):
        raise RuntimeError("SMTP unavailable")

    monkeypatch.setattr("app.security.deliver", fail)
    known = client.post(
        "/api/v1/auth/forgot-password", json={"email": "owner@example.test"}
    )
    unknown = client.post(
        "/api/v1/auth/forgot-password", json={"email": "missing@example.test"}
    )
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()
    with db() as c:
        assert c.execute("SELECT * FROM account_tokens").fetchall() == []
