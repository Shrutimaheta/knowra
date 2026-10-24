import asyncio
import threading

import httpx
import pymupdf
from app import embeddings
from app.main import protect
from app.rag import _passage_terms, lexical_rank, parse_file
from fastapi import Request, Response
from test_workflows import register, upload


def test_pdf_upload_defers_extraction_and_worker_still_indexes(client, monkeypatch):
    register(client)
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50, 50), "Internet Control Message Protocol (ICMP) reports errors.")
        data = pdf.tobytes()

    def unexpected(*args, **kwargs):
        raise AssertionError("Upload validation must not extract PDF text")

    monkeypatch.setattr("pypdf._page.PageObject.extract_text", unexpected)
    assert parse_file("network.pdf", data) == [""]
    response = client.post(
        "/api/v1/documents", files={"file": ("network.pdf", data, "application/pdf")}
    )
    assert response.status_code == 201
    result = client.post("/api/v1/search", json={"content": "what is ICMP?"})
    assert result.status_code == 200
    assert "Control Message Protocol" in result.json()[0]["content"]


def test_query_vectors_cache_by_model_and_never_return_mutable_cache(monkeypatch):
    calls = []

    class Encoded:
        def tolist(self):
            return [[1.0, 0.0]]

    class Model:
        def encode(self, texts, **kwargs):
            calls.append(texts)
            return Encoded()

    embeddings._query_vector.cache_clear()
    monkeypatch.setattr(embeddings, "model", lambda name: Model())
    monkeypatch.setenv("EMBEDDING_MODEL", "first-model")
    try:
        first = embeddings.query_vector("vacation entitlement")
        first[0] = 99
        assert embeddings.query_vector("vacation entitlement") == [1.0, 0.0]
        assert len(calls) == 1
        monkeypatch.setenv("EMBEDDING_MODEL", "second-model")
        assert embeddings.query_vector("vacation entitlement") == [1.0, 0.0]
        assert len(calls) == 2
    finally:
        embeddings._query_vector.cache_clear()


def test_cached_terms_follow_current_source_content_and_permissions(client):
    register(client)
    document = upload(client, "Annual leave allowance is 24 days.")
    for _ in range(2):
        assert client.post("/api/v1/search", json={"content": "annual leave"}).json()
    client.delete("/api/v1/documents/" + document).raise_for_status()
    assert client.post("/api/v1/search", json={"content": "annual leave"}).json() == []
    old = [{"id": "v1", "content": "annual leave allowance"}]
    new = [{"id": "v2", "content": "security requirements"}]
    assert lexical_rank(old, "annual leave")
    assert lexical_rank(new, "annual leave") == []
    assert _passage_terms.cache_info().maxsize == 1024


def test_ingestion_embeddings_use_bounded_batches_in_source_order(monkeypatch):
    batches = []

    class Model:
        def encode(self, texts, **kwargs):
            batches.append(len(texts))

            class Result:
                def tolist(self):
                    return [[int(text)] for text in texts]

            return Result()

    monkeypatch.setenv("EMBEDDING_MODEL", "test-batching")
    monkeypatch.setattr(embeddings, "model", lambda name: Model())
    assert embeddings.encode([str(i) for i in range(70)]) == [[i] for i in range(70)]
    assert batches == [32, 32, 6]


def test_slow_request_bookkeeping_does_not_block_event_loop(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    released = []

    def slow_count(*args):
        entered.set()
        released.append(release.wait(timeout=2))
        return 1

    monkeypatch.setattr("app.main.request_count", slow_count)
    request = Request({
        "type": "http", "method": "GET", "path": "/api/v1/documents",
        "scheme": "http", "headers": [], "server": ("localhost", 80),
        "client": ("127.0.0.1", 1234), "query_string": b"",
    })

    async def next_request(request):
        return Response("ok")

    async def check():
        task = asyncio.create_task(protect(request, next_request))
        try:
            while not entered.is_set():
                await asyncio.sleep(0.001)
            assert not task.done()
        finally:
            release.set()
        assert (await task).status_code == 200

    asyncio.run(check())
    assert released == [True]


def test_network_connection_failure_returns_real_source_excerpts(client, monkeypatch):
    register(client)
    upload(client, "Annual leave allowance is 24 days.")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-test-key")

    def unavailable(*args, **kwargs):
        raise httpx.ConnectError("private upstream connection details")

    monkeypatch.setattr("app.rag.httpx.stream", unavailable)
    chat = client.post("/api/v1/conversations").json()["id"]
    answer = client.post(
        f"/api/v1/conversations/{chat}/messages", json={"content": "annual leave"}
    )
    assert answer.status_code == 200
    assert answer.json()["mode"] == "extractive"
    assert "24 days" in answer.json()["content"]
    assert "not an AI-generated answer" in answer.json()["content"]
    assert "private upstream" not in answer.text
