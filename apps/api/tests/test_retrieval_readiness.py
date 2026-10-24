import io
import json

from app.rag import retrieve
from app.worker import run_once
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from test_workflows import register, upload


def networking_pdf():
    writer = PdfWriter()
    for text in [
        "Networking lab: ICMP and IP experiments.",
        "ICMP (Internet Control Message Protocol) reports IP errors and supports network diagnostics such as ping.",
    ]:
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        contents = DecodedStreamObject()
        escaped = text.replace("(", "\\(").replace(")", "\\)")
        contents.set_data(("BT /F1 12 Tf 40 740 Td (" + escaped + ") Tj ET").encode())
        page[NameObject("/Contents")] = contents
    data = io.BytesIO()
    writer.write(data)
    return data.getvalue()


def test_pending_pdf_returns_indexing_notice_then_answers_with_page_citations(
    client, monkeypatch
):
    register(client)
    monkeypatch.setenv("EAGER_INGESTION", "false")
    result = client.post(
        "/api/v1/documents",
        files={"file": ("networking.pdf", networking_pdf(), "application/pdf")},
    )
    assert result.status_code == 201
    chat = client.post("/api/v1/conversations").json()["id"]

    def no_neural_wait(*args):
        raise AssertionError("An exact ICMP match must not initialize the neural model")

    monkeypatch.setattr("app.embeddings.semantic_rank", no_neural_wait)
    response = client.post(
        f"/api/v1/conversations/{chat}/stream", json={"content": "what is ICMP?"}
    )
    events = [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert events[-1]["type"] == "error"
    assert "still being indexed" in events[-1]["message"]
    assert client.get(f"/api/v1/conversations/{chat}/messages").json() == []
    assert run_once()
    result = client.post(
        f"/api/v1/conversations/{chat}/messages", json={"content": "what is ICMP?"}
    )
    assert result.status_code == 200
    answer = result.json()
    assert "Internet Control Message Protocol" in answer["content"]
    assert any(
        source["page"] == 2 and source["title"] == "networking.pdf"
        for source in answer["citations"]
    )


def test_private_indexing_does_not_block_another_workspace_member(client, monkeypatch):
    register(client)
    upload(client, "ICMP reports network errors.")
    monkeypatch.setenv("EAGER_INGESTION", "false")
    upload(client, "Private unfinished material.", visibility="private")
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
    assert (
        client.post("/api/v1/search", json={"content": "what is ICMP?"}).status_code
        == 200
    )


def test_standalone_topic_does_not_inherit_unrelated_chat_history(client, monkeypatch):
    register(client)
    queries = []

    def capture(body, user):
        queries.append(body.content)
        return []

    monkeypatch.setattr("app.main.search", capture)
    chat = client.post("/api/v1/conversations").json()["id"]
    client.post(
        f"/api/v1/conversations/{chat}/messages",
        json={"content": "How many annual leave days?"},
    )
    client.post(
        f"/api/v1/conversations/{chat}/messages", json={"content": "what is ICMP?"}
    )
    assert queries[-1] == "what is ICMP?"
    client.post(
        f"/api/v1/conversations/{chat}/messages", json={"content": "What are its uses?"}
    )
    assert "what is ICMP?" in queries[-1]


def test_unknown_single_topic_still_uses_semantic_search(monkeypatch):
    rows = [
        {
            "id": "icmp",
            "document": "networking",
            "content": "Internet Control Message Protocol reports errors.",
        }
    ]
    calls = []

    def semantic(rows, query):
        calls.append(query)
        return [(0.8, rows[0])]

    monkeypatch.setattr("app.embeddings.semantic_rank", semantic)
    assert retrieve(rows, "ICMP")[0]["id"] == "icmp"
    assert calls == ["ICMP"]


def test_definition_outranks_repeated_mentions_in_lab_questions(monkeypatch):
    rows = [
        {
            "id": "questions",
            "document": "lab",
            "page": 6,
            "content": "ICMP ICMP ICMP ICMP ICMP ICMP: answer these lab questions.",
        },
        {
            "id": "definition",
            "document": "lab",
            "page": 1,
            "content": "The Internet Control Message Protocol (ICMP) reports network errors.",
        },
    ]

    def unexpected(*args):
        raise AssertionError("Exact topic lookup should not wait for embeddings")

    monkeypatch.setattr("app.embeddings.semantic_rank", unexpected)
    assert retrieve(rows, "what is ICMP?")[0]["id"] == "definition"


def test_provider_outage_returns_labeled_evidence_instead_of_no_evidence(
    client, monkeypatch
):
    from fastapi import HTTPException

    register(client)
    upload(client, "Internet Control Message Protocol (ICMP) reports IP errors.")

    def unavailable(*args):
        raise HTTPException(503, "Provider temporarily unavailable")

    monkeypatch.setattr("app.main.stream_answer", unavailable)
    chat = client.post("/api/v1/conversations").json()["id"]
    response = client.post(
        f"/api/v1/conversations/{chat}/messages", json={"content": "what is ICMP?"}
    )
    assert response.status_code == 200
    answer = response.json()
    assert "not an AI-generated answer" in answer["content"]
    assert "Internet Control Message Protocol" in answer["content"]
    assert answer["mode"] == "extractive" and answer["citations"]
    assert "could not find supporting evidence" not in answer["content"]


def test_partial_model_output_is_not_replaced_by_excerpt_fallback(client, monkeypatch):
    from fastapi import HTTPException

    register(client)
    upload(client, "Internet Control Message Protocol (ICMP) reports IP errors.")

    def partial(*args):
        yield {"type": "delta", "text": "Partial generated answer"}
        raise HTTPException(503, "Provider interrupted")

    monkeypatch.setattr("app.main.stream_answer", partial)
    chat = client.post("/api/v1/conversations").json()["id"]
    assert (
        client.post(
            f"/api/v1/conversations/{chat}/messages", json={"content": "what is ICMP?"}
        ).status_code
        == 503
    )
    assert client.get(f"/api/v1/conversations/{chat}/messages").json() == []
