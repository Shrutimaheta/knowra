"""Exercise a real internal parser container without database credentials."""

import base64
import os
import time

import httpx
import pymupdf

origin = os.getenv("PARSER_ORIGIN", "http://parser:8001")
deadline = time.monotonic() + 60
while True:
    try:
        httpx.get(origin + "/health", timeout=2).raise_for_status()
        break
    except httpx.HTTPError:
        if time.monotonic() >= deadline:
            raise
        time.sleep(1)
with pymupdf.open() as pdf:
    page = pdf.new_page()
    page.insert_text((50, 50), "Fictional annual leave allowance is 24 days.")
    data = pdf.tobytes()
for operation in ("validate", "extract", "image", "highlight"):
    response = httpx.post(origin + "/process", timeout=310, json={
        "operation": operation, "filename": "policy.pdf",
        "data": base64.b64encode(data).decode(), "number": 1,
        "pages": ["Fictional annual leave allowance is 24 days."],
        "quote": "Fictional annual leave allowance is 24 days.",
    })
    response.raise_for_status()
    result = response.json()
    if operation == "extract":
        assert "24 days" in result["pages"][0]
    if operation == "highlight":
        assert result["ranges"] and result["image"]
print("Restricted parser validation, extraction, preview and evidence passed")
