def register(client, email="owner@example.test"):
    r = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "strong-test-password",
            "name": "Alex",
            "workspace": "Test studio",
        },
    )
    assert r.status_code == 201, r.text
    return client.get("/api/v1/users/me").json()


def upload(client, text="Annual leave allowance is 24 days.", visibility="workspace"):
    r = client.post(
        "/api/v1/documents",
        files={"file": ("policy.txt", text.encode(), "text/plain")},
        data={"visibility": visibility, "category": "People"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_authentication_and_logout(client):
    assert client.get("/api/v1/documents").status_code == 401
    register(client)
    assert "password" not in client.get("/api/v1/users/me").json()
    assert client.cookies.get("knowra_session")
    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/users/me").status_code == 401
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": "owner@example.test", "password": "wrong-password"},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": "owner@example.test", "password": "strong-test-password"},
        ).status_code
        == 200
    )


def test_upload_retrieve_chat_citation_feedback_delete(client):
    register(client)
    doc = upload(client)
    assert client.get("/api/v1/documents").json()[0]["status"] == "ready"
    results = client.post("/api/v1/search", json={"content": "annual leave"}).json()
    assert results[0]["document"] == doc
    conversation = client.post("/api/v1/conversations").json()["id"]
    answer = client.post(
        f"/api/v1/conversations/{conversation}/messages",
        json={"content": "annual leave allowance"},
    ).json()
    assert "24 days" in answer["content"]
    assert answer["citations"][0]["page"] == 1
    assert answer["mode"] == "extractive"
    assert (
        client.post(
            f"/api/v1/messages/{answer['id']}/feedback", json={"value": 1}
        ).status_code
        == 200
    )
    assert len(client.get(f"/api/v1/conversations/{conversation}/messages").json()) == 2
    assert client.get("/api/v1/analytics").json()["questions"] == 1
    assert client.delete("/api/v1/documents/" + doc).status_code == 200
    assert client.post("/api/v1/search", json={"content": "annual leave"}).json() == []
    assert (
        client.get(f"/api/v1/conversations/{conversation}/messages").json()[1][
            "citations"
        ]
        == []
    )


def test_cross_tenant_isolation(client):
    register(client)
    doc = upload(client)
    conversation = client.post("/api/v1/conversations").json()["id"]
    client.post("/api/v1/auth/logout")
    register(client, "other@example.test")
    assert client.get("/api/v1/documents").json() == []
    assert client.get("/api/v1/documents/" + doc).status_code == 404
    assert client.delete("/api/v1/documents/" + doc).status_code == 404
    assert client.post("/api/v1/search", json={"content": "annual leave"}).json() == []
    assert (
        client.get(f"/api/v1/conversations/{conversation}/messages").status_code == 404
    )
    assert (
        client.post(
            f"/api/v1/conversations/{conversation}/messages", json={"content": "leave"}
        ).status_code
        == 404
    )


def test_private_document_and_viewer_permissions(client):
    register(client)
    private = upload(client, visibility="private")
    shared = upload(client)
    assert (
        client.post(
            "/api/v1/members",
            json={
                "email": "viewer@example.test",
                "password": "viewer-test-password",
                "name": "Viewer",
                "role": "viewer",
            },
        ).status_code
        == 201
    )
    client.post("/api/v1/auth/logout")
    client.post(
        "/api/v1/auth/login",
        json={"email": "viewer@example.test", "password": "viewer-test-password"},
    )
    assert client.get("/api/v1/documents/" + private).status_code == 404
    assert len(client.get("/api/v1/documents").json()) == 1
    assert (
        client.post(
            "/api/v1/documents", files={"file": ("test.txt", b"data")}
        ).status_code
        == 403
    )
    assert client.delete("/api/v1/documents/" + shared).status_code == 403
    assert client.get("/api/v1/audit").status_code == 403
    assert client.post("/api/v1/demo/seed").status_code == 403


def test_file_validation_and_origin(client):
    register(client)
    for name, body in [
        ("test.exe", b"binary"),
        ("test.pdf", b"not pdf"),
        ("test.txt", b"\x00abc"),
        ("empty.txt", b""),
    ]:
        assert (
            client.post("/api/v1/documents", files={"file": (name, body)}).status_code
            == 400
        )
    assert (
        client.post(
            "/api/v1/conversations", headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )


def test_seed_and_no_evidence(client):
    register(client)
    assert client.post("/api/v1/demo/seed").json()["created"] == 11
    assert client.post("/api/v1/demo/seed").json()["created"] == 0
    conversation = client.post("/api/v1/conversations").json()["id"]
    answer = client.post(
        f"/api/v1/conversations/{conversation}/messages",
        json={"content": "galactic penguin quantum xyz"},
    ).json()
    assert not answer["citations"]
    assert "could not find" in answer["content"]
