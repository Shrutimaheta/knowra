import json

import httpx
import pytest
from app.providers import generation_provider
from app.rag import stream_answer
from fastapi import HTTPException


@pytest.fixture(autouse=True)
def isolated_provider(monkeypatch):
    for key in [
        "GEMINI_API_KEY",
        "GEMINI_MODEL",
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "LLM_PROVIDER",
    ]:
        monkeypatch.delenv(key, raising=False)


SOURCE = [
    {"title": "Fictional policy", "page": 1, "content": "Annual leave is 24 days."}
]


def test_gemini_uses_correct_endpoint_and_secret_stays_server_side(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-test-key")
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def raise_for_status(self):
            pass

        def iter_lines(self):
            yield "data: " + json.dumps(
                {
                    "choices": [
                        {"delta": {"content": "24 days [1]."}, "finish_reason": None}
                    ]
                }
            )
            yield "data: " + json.dumps(
                {
                    "choices": [{"delta": {}, "finish_reason": "stop"}],
                    "usage": {"total_tokens": 55},
                }
            )
            yield "data: [DONE]"

    def request(method, url, **kwargs):
        captured.update(url=url, **kwargs)
        return Response()

    monkeypatch.setattr("app.rag.httpx.stream", request)
    events = list(stream_answer("How much annual leave?", SOURCE, []))
    assert (
        captured["url"]
        == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    )
    assert captured["headers"]["Authorization"] == "Bearer fake-gemini-test-key"
    assert captured["json"]["model"] == "gemini-3.5-flash"
    assert captured["json"]["reasoning_effort"] == "low"
    assert "max_completion_tokens" not in captured["json"]
    assert events[-1]["tokens"] == 55
    assert "fake-gemini-test-key" not in json.dumps(events)
    assert "fake-gemini-test-key" not in repr(generation_provider())


def test_explicit_gemini_never_uses_openai_fallback(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-key")
    assert generation_provider() is None
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
    assert generation_provider().name == "gemini"
    monkeypatch.setenv("LLM_PROVIDER", "evidence")
    assert generation_provider() is None


@pytest.mark.parametrize(
    "status,word", [(401, "API key"), (403, "API key"), (404, "model"), (429, "quota")]
)
def test_provider_errors_are_actionable_without_leaking_credentials(
    monkeypatch, status, word
):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-secret")
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def raise_for_status(self):
            request = httpx.Request(
                "POST",
                "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
            )
            raise httpx.HTTPStatusError(
                "deliberately private upstream details",
                request=request,
                response=httpx.Response(status, request=request),
            )

    monkeypatch.setattr(
        "app.rag.httpx.stream",
        lambda *args, **kwargs: calls.append(args[1]) or Response(),
    )
    with pytest.raises(HTTPException) as caught:
        list(stream_answer("leave", SOURCE, []))
    assert word in caught.value.detail
    assert "fake-secret" not in caught.value.detail
    assert len(calls) == 1


def test_truncated_generation_is_not_treated_as_complete(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def raise_for_status(self):
            pass

        def iter_lines(self):
            yield "data: " + json.dumps(
                {
                    "choices": [
                        {"delta": {"content": "Incomplete"}, "finish_reason": "length"}
                    ]
                }
            )
            yield "data: [DONE]"

    monkeypatch.setattr("app.rag.httpx.stream", lambda *args, **kwargs: Response())
    with pytest.raises(HTTPException):
        list(stream_answer("leave", SOURCE, []))
