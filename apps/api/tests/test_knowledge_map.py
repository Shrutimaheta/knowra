import json

from app.store import db
from test_workflows import register, upload


def answer(client, question="What is ICMP?"):
    chat = client.post("/api/v1/conversations").json()["id"]
    response = client.post(
        f"/api/v1/conversations/{chat}/messages", json={"content": question}
    )
    assert response.status_code == 200, response.text
    return chat, response.json()


def test_map_authentication_and_empty_state(client):
    assert client.get("/api/v1/knowledge-map").status_code == 401
    register(client)
    data = client.get("/api/v1/knowledge-map").json()
    assert data["nodes"] == [] and data["edges"] == []
    assert data["stats"]["documents"] == 0


def test_map_links_actual_citations_and_retains_cited_older_versions(client):
    register(client)
    document = upload(client, "ICMP reports IP network errors and supports ping.")
    chat, saved = answer(client)
    old = client.get(f"/api/v1/documents/{document}/versions").json()[0]["id"]
    for n in range(2, 6):
        response = client.post(
            f"/api/v1/documents/{document}/versions",
            files={
                "file": (
                    f"new{n}.txt",
                    f"ICMP reports network errors. New policy revision {n}.".encode(),
                    "text/plain",
                )
            },
        )
        assert response.status_code == 201
    data = client.get("/api/v1/knowledge-map").json()
    versions = [node for node in data["nodes"] if node["type"] == "version"]
    assert any(node["version_id"] == old and not node["current"] for node in versions)
    assert any(node["version"] == 5 and node["current"] for node in versions)
    assert data["stats"]["earlier_version_answers"] == 1
    found = next(node for node in data["nodes"] if node["type"] == "answer")
    assert found["conversation"] == chat and found["historical"]
    assert found["message"] == saved["id"]
    citation = next(edge for edge in data["edges"] if edge["type"] == "citation")
    assert citation["version_id"] == old and citation["historical"]
    assert citation["evidence"][0]["page"] == 1
    assert "ICMP" in citation["evidence"][0]["text"]
    assert all(
        edge["source"] in {node["id"] for node in data["nodes"]}
        and edge["target"] in {node["id"] for node in data["nodes"]}
        for edge in data["edges"]
    )
    assert "original" not in json.dumps(data) and "embedding" not in json.dumps(data)


def test_uncited_documents_have_no_invented_answer_links(client):
    register(client)
    document = upload(client, "Annual leave is 24 days.")
    data = client.get("/api/v1/knowledge-map").json()
    assert data["stats"] == {
        "documents": 1,
        "versions": 1,
        "answers": 0,
        "earlier_version_answers": 0,
    }
    assert all(edge["type"] == "version" for edge in data["edges"])
    assert data["nodes"][0]["document"] == document


def test_map_excludes_private_sources_and_other_users_conversations(client):
    register(client)
    shared = upload(client, "ICMP reports network errors.")
    private = upload(
        client, "Secret private allowance is 24 days.", visibility="private"
    )
    _, message = answer(client)
    client.post(
        "/api/v1/members",
        json={
            "name": "Reader",
            "email": "reader@example.test",
            "password": "reader-safe-password",
            "role": "viewer",
        },
    )
    client.post("/api/v1/auth/logout")
    client.post(
        "/api/v1/auth/login",
        json={"email": "reader@example.test", "password": "reader-safe-password"},
    )
    data = client.get("/api/v1/knowledge-map").json()
    assert data["stats"]["documents"] == 1
    assert shared in json.dumps(data) and private not in json.dumps(data)
    assert message["id"] not in json.dumps(data)
    assert data["stats"]["answers"] == 0
    client.post("/api/v1/auth/logout")
    register(client, "outside@example.test")
    assert client.get("/api/v1/knowledge-map").json()["nodes"] == []


def test_deleted_sources_remove_graph_nodes_and_edges(client):
    register(client)
    document = upload(client, "ICMP reports IP errors.")
    answer(client)
    assert client.delete(f"/api/v1/documents/{document}").status_code == 200
    assert client.get("/api/v1/knowledge-map").json()["nodes"] == []


def test_bounded_view_and_parameter_validation_are_explicit(client):
    register(client)
    upload(client, "First document.")
    upload(client, "Second document.")
    response = client.get("/api/v1/knowledge-map?document_limit=1&answer_limit=1")
    assert response.status_code == 200
    data = response.json()
    assert data["stats"]["documents"] == 1 and data["limited"]
    assert client.get("/api/v1/knowledge-map?document_limit=10000").status_code == 422


def test_forged_or_unversioned_citations_do_not_create_graph_edges(client):
    register(client)
    doc_a = upload(client, "ICMP reports IP errors.")
    doc_b = upload(client, "Another independent document.")
    _, saved = answer(client)
    version_b = client.get(f"/api/v1/documents/{doc_b}/versions").json()[0]["id"]
    with db() as c:
        c.execute(
            "UPDATE messages SET citations=? WHERE id=?",
            (
                json.dumps(
                    [
                        {
                            "document": doc_a,
                            "version_id": version_b,
                            "page": 1,
                            "content": "Wrong association",
                        },
                        {"document": doc_a, "page": 1},
                    ]
                ),
                saved["id"],
            ),
        )
    data = client.get("/api/v1/knowledge-map").json()
    assert not any(edge["type"] == "citation" for edge in data["edges"])
    assert data["stats"]["answers"] == 0
