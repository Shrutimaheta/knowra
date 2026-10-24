import io

import pytest
from app.rag import parse_file
from fastapi import HTTPException
from PIL import Image, ImageDraw, ImageFont
from test_workflows import register


def picture(format="PNG", text=True):
    image = Image.new("RGB", (1200, 300), "white")
    if text:
        ImageDraw.Draw(image).text(
            (30, 70),
            "ICMP reports network errors and supports ping.",
            fill="black",
            font=ImageFont.load_default(size=32),
        )
    buffer = io.BytesIO()
    image.save(buffer, format=format)
    return buffer.getvalue()


@pytest.mark.parametrize(
    "name,format",
    [
        ("photo.jpg", "JPEG"),
        ("photo.jpeg", "JPEG"),
        ("diagram.webp", "WEBP"),
        ("screen.PNG", "PNG"),
    ],
)
def test_supported_image_formats_validate(name, format):
    assert parse_file(name, picture(format)) == [""]


def test_images_reject_fake_or_excessive_dimensions():
    with pytest.raises(HTTPException) as caught:
        parse_file("fake.png", b"<svg><script>bad</script></svg>")
    assert caught.value.status_code == 400
    image = Image.new("1", (12001, 2))
    data = io.BytesIO()
    image.save(data, format="PNG")
    with pytest.raises(HTTPException) as caught:
        parse_file("wide.png", data.getvalue())
    assert "12,000" in caught.value.detail


def test_image_upload_ocr_search_preview_visual_and_permissions(client, monkeypatch):
    register(client)
    data = picture()
    response = client.post(
        "/api/v1/documents", files={"file": ("icmp.png", data, "image/png")}
    )
    assert response.status_code == 201, response.text
    created = response.json()
    path = f"/api/v1/documents/{created['id']}/versions/{created['version_id']}"
    version = client.get(path).json()
    assert version["status"] == "ready"
    assert "ICMP" in version["pages"][0]
    assert client.get(path + "/original").content == data
    assert client.get(path + "/original").headers["content-type"] == "image/png"
    assert client.get(path + "/pages/1/image").content.startswith(b"\x89PNG")
    assert client.get(path + "/pages/2/image").status_code == 404
    assert (
        client.post("/api/v1/search", json={"content": "ICMP"}).json()[0]["document"]
        == created["id"]
    )
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    captured = []

    def visual_answer(query, sources, history, images=None):
        captured.extend(images or [])
        yield {"type": "delta", "text": "ICMP reports network errors [1]."}
        yield {"type": "usage", "model": "test-vision", "tokens": 1}

    monkeypatch.setattr("app.main.stream_answer", visual_answer)
    chat = client.post("/api/v1/conversations").json()["id"]
    response = client.post(
        f"/api/v1/conversations/{chat}/messages",
        json={
            "content": "Explain the screenshot",
            "visual_document_id": created["id"],
            "visual_page": 1,
        },
    )
    assert response.status_code == 200, response.text
    assert captured[0].startswith("data:image/png;base64,")
    client.post("/api/v1/auth/logout")
    register(client, "another@example.test")
    assert client.get(path + "/original").status_code == 404
    assert client.get(path + "/pages/1/image").status_code == 404


def test_image_without_text_remains_available_for_visual_questions(client, monkeypatch):
    register(client)

    def no_embeddings(texts):
        raise AssertionError("An image without text has no passages to embed")

    monkeypatch.setattr("app.worker.encode", no_embeddings)
    created = client.post(
        "/api/v1/documents",
        files={"file": ("blank.png", picture(text=False), "image/png")},
    ).json()
    path = f"/api/v1/documents/{created['id']}/versions/{created['version_id']}"
    version = client.get(path).json()
    assert version["status"] == "ready"
    assert version["pages"] == [""]
    assert any(
        "No readable text" in warning
        for warning in version["layout_meta"][0]["warnings"]
    )
    assert client.get(path + "/pages/1/image").status_code == 200
