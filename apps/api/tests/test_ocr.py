import io
import json
from pathlib import Path

import pymupdf
import pytest
from app.extraction import ExtractionError, extract_pdf
from app.rag import stream_answer
from PIL import Image, ImageDraw, ImageFont
from test_workflows import register


def scanned_pdf():
    image = Image.new("RGB", (1500, 1000), "white")
    draw = ImageDraw.Draw(image)
    fonts = [
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    font = ImageFont.truetype(next(f for f in fonts if Path(f).exists()), 36)
    draw.text(
        (60, 40),
        "ICMP stands for Internet Control Message Protocol.",
        font=font,
        fill="black",
    )
    draw.text(
        (60, 100),
        "ICMP reports network errors and supports ping.",
        font=font,
        fill="black",
    )
    for x in [60, 650, 1400]:
        draw.line((x, 220, x, 520), fill="black", width=3)
    for y in [220, 320, 420, 520]:
        draw.line((60, y, 1400, y), fill="black", width=3)
    for y, cells in [
        (250, ["Protocol", "Number"]),
        (350, ["ICMP", "1"]),
        (450, ["TCP", "6"]),
    ]:
        for x, value in zip([85, 680], cells, strict=True):
            draw.text((x, y), value, font=font, fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=750, height=500)
        page.insert_text((40, 40), "Networking laboratory introduction", fontsize=16)
        page = pdf.new_page(width=750, height=500)
        page.insert_image(page.rect, stream=buffer.getvalue())
        page = pdf.new_page(width=750, height=650)
        page.insert_text(
            (40, 40),
            "Native explanation: retain this selectable paragraph alongside the scanned protocol table.",
        )
        page.insert_image(pymupdf.Rect(40, 120, 710, 620), stream=buffer.getvalue())
        return pdf.tobytes()


def test_real_scan_ocr_table_search_citation_and_original_permissions(
    client, monkeypatch
):
    register(client)
    original = scanned_pdf()
    created = client.post(
        "/api/v1/documents",
        files={"file": ("network.pdf", original, "application/pdf")},
    ).json()
    path = f"/api/v1/documents/{created['id']}/versions/{created['version_id']}"
    version = client.get(path).json()
    assert version["status"] == "ready", client.get("/api/v1/documents").text
    assert version["layout_meta"][0]["method"] == "text"
    assert version["layout_meta"][1]["method"] == "ocr"
    assert version["layout_meta"][2]["method"] == "text + OCR"
    assert "retain this selectable paragraph" in version["pages"][2]
    assert "Protocol: TCP; Number: 6" in version["pages"][2]
    assert "Internet Control Message Protocol" in version["pages"][1]
    assert ["TCP", "6"] in version["layout_meta"][1]["tables"][0]
    assert "Protocol: ICMP; Number: 1" in version["pages"][1]
    assert client.get(path + "/original").content == original
    assert client.get(path + "/pages/2/image").content.startswith(b"\x89PNG")
    assert client.get(path + "/pages/4/image").status_code == 404
    chat = client.post("/api/v1/conversations").json()["id"]
    answer = client.post(
        f"/api/v1/conversations/{chat}/messages", json={"content": "what is ICMP?"}
    ).json()
    assert "Internet Control Message Protocol" in answer["content"]
    assert answer["citations"][0]["page"] == 2
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    captured = []

    def visual_answer(query, sources, history, images=None):
        captured.append(images)
        yield {"type": "delta", "text": "The ICMP protocol number is 1 [1]."}
        yield {"type": "usage", "model": "test-vision", "tokens": 1}

    monkeypatch.setattr("app.main.stream_answer", visual_answer)
    response = client.post(
        f"/api/v1/conversations/{chat}/messages",
        json={
            "content": "Read this table",
            "visual_document_id": created["id"],
            "visual_page": 2,
        },
    )
    assert response.status_code == 200, response.text
    assert captured[0][0].startswith("data:image/png;base64,")
    assert "base64" not in client.get(f"/api/v1/conversations/{chat}/messages").text
    client.post("/api/v1/auth/logout")
    register(client, "different@example.test")
    assert client.get(path + "/pages/2/image").status_code == 404
    other_chat = client.post("/api/v1/conversations").json()["id"]
    assert (
        client.post(
            f"/api/v1/conversations/{other_chat}/messages",
            json={
                "content": "Read this table",
                "visual_document_id": created["id"],
                "visual_page": 2,
            },
        ).status_code
        == 404
    )


def test_native_table_preserves_column_relationships():
    with pymupdf.open() as pdf:
        p = pdf.new_page()
        for x in [40, 240, 440]:
            p.draw_line((x, 40), (x, 160))
        for y in [40, 80, 120, 160]:
            p.draw_line((40, y), (440, y))
        for y, cells in [
            (65, ["Protocol", "Number"]),
            (105, ["ICMP", "1"]),
            (145, ["TCP", "6"]),
        ]:
            for x, cell in zip([50, 250], cells, strict=True):
                p.insert_text((x, y), cell)
        pages, layout = extract_pdf(pdf.tobytes())
    assert "Protocol: TCP; Number: 6" in pages[0]
    assert layout[0]["tables"][0][1] == ["ICMP", "1"]


def test_unreadable_pdf_reports_failure():
    with pymupdf.open() as pdf:
        pdf.new_page()
        with pytest.raises(ExtractionError, match="No readable text"):
            extract_pdf(pdf.tobytes())


def test_visual_payload_uses_selected_image_only_when_requested(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    captured = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def raise_for_status(self):
            pass

        def iter_lines(self):
            yield "data: " + json.dumps(
                {"choices": [{"delta": {"content": "ICMP [1]"}}]}
            )
            yield "data: [DONE]"

    def request(*args, **kwargs):
        captured.append(kwargs["json"])
        return Response()

    monkeypatch.setattr("app.rag.httpx.stream", request)
    sources = [{"title": "Network", "content": "ICMP", "page": 1}]
    list(stream_answer("Explain", sources, []))
    assert isinstance(captured[-1]["messages"][-1]["content"], str)
    list(stream_answer("Explain", sources, [], ["data:image/png;base64,test"]))
    assert (
        captured[-1]["messages"][-1]["content"][1]["image_url"]["url"]
        == "data:image/png;base64,test"
    )
